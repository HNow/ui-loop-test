"""
Unit tests for Phase 2: Code Generation

Tests cover:
  - HTMLGenerator tag mapping, class name generation, recursive HTML fallback
  - HTMLGenerator VLLM single-shot codegen (prompt building, sanitization)
  - StyleGenerator layout computation, CSS generation, document assembly
  - StyleGenerator ensure_document_structure for VLLM output
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from pathlib import Path

from storage.component import Component, ComponentTree, Element, Region, DetectedElement
from phases.phase2_codegen.html_gen import HTMLGenerator
from phases.phase2_codegen.style_gen import StyleGenerator


def make_element(
    elem_id: str,
    elem_type: str = "container",
    bbox: tuple = (0, 0, 100, 100),
    content_description: str = "test element",
    children_ids: list | None = None,
    parent_id: str | None = None,
) -> Element:
    return Element(
        id=elem_id,
        type=elem_type,
        bbox=bbox,
        content_description=content_description,
        children_ids=children_ids if children_ids is not None else [],
        parent_id=parent_id,
    )


def make_config() -> MagicMock:
    cfg = MagicMock()
    cfg.target_regions_min = 3
    cfg.target_regions_max = 10
    cfg.max_elements_per_region = 40
    cfg.per_component_threshold = 0.9
    cfg.use_tailwind = False
    return cfg


def make_client() -> AsyncMock:
    client = AsyncMock()
    client.code_complete = AsyncMock()
    client.vision_analyze = AsyncMock()
    return client


class TestHTMLGeneratorTagMapping:
    def test_known_types(self):
        gen = HTMLGenerator(make_client(), make_config())
        assert gen._map_type_to_tag("button") == "button"
        assert gen._map_type_to_tag("heading") == "h2"
        assert gen._map_type_to_tag("image") == "img"
        assert gen._map_type_to_tag("navigation") == "nav"
        assert gen._map_type_to_tag("card") == "article"
        assert gen._map_type_to_tag("text") == "p"
        assert gen._map_type_to_tag("input") == "input"
        assert gen._map_type_to_tag("link") == "a"

    def test_unknown_type_defaults_to_div(self):
        gen = HTMLGenerator(make_client(), make_config())
        assert gen._map_type_to_tag("foobar") == "div"

    def test_case_insensitive(self):
        gen = HTMLGenerator(make_client(), make_config())
        assert gen._map_type_to_tag("Button") == "button"
        assert gen._map_type_to_tag("HEADING") == "h2"


class TestHTMLGeneratorClassName:
    def test_root_class(self):
        gen = HTMLGenerator(make_client(), make_config())
        elem = make_element("e1", "card")
        name = gen._generate_class_name(elem, [])
        assert name == "card"

    def test_hierarchical_class(self):
        gen = HTMLGenerator(make_client(), make_config())
        elem = make_element("e1", "button")
        name = gen._generate_class_name(elem, ["hero", "card"])
        assert name == "hero-card-button"

    def test_index_suffix(self):
        gen = HTMLGenerator(make_client(), make_config())
        elem = make_element("e1", "text")
        name = gen._generate_class_name(elem, [], index=2)
        assert name == "text-2"


class TestHTMLGeneratorRecursive:
    def test_leaf_element(self):
        gen = HTMLGenerator(make_client(), make_config())
        tree = ComponentTree(
            root_id="btn1",
            elements={
                "btn1": make_element("btn1", "button", (10, 10, 80, 30), "Click Me")
            },
        )
        html = gen._tree_to_html_recursive("btn1", tree)
        assert "<button" in html
        assert "Click Me" in html
        assert "</button>" in html

    def test_nested_elements(self):
        gen = HTMLGenerator(make_client(), make_config())
        parent = make_element(
            "p1", "container", (0, 0, 200, 200), "", children_ids=["c1"]
        )
        child = make_element("c1", "text", (10, 10, 180, 30), "Hello", parent_id="p1")

        tree = ComponentTree(root_id="p1", elements={"p1": parent, "c1": child})
        html = gen._tree_to_html_recursive("p1", tree)

        assert "<div" in html
        assert "<p" in html
        assert "Hello" in html

    def test_img_self_closing(self):
        gen = HTMLGenerator(make_client(), make_config())
        tree = ComponentTree(
            root_id="img1",
            elements={
                "img1": make_element("img1", "image", (0, 0, 100, 100), "A photo")
            },
        )
        html = gen._tree_to_html_recursive("img1", tree)
        assert "<img" in html
        assert "/>" in html
        assert 'alt="A photo"' in html

    def test_cycle_guard(self):
        gen = HTMLGenerator(make_client(), make_config())
        a = make_element("a", "container", (0, 0, 100, 100), "", children_ids=["b"])
        b = make_element(
            "b", "container", (0, 0, 80, 80), "", parent_id="a", children_ids=["a"]
        )

        tree = ComponentTree(root_id="a", elements={"a": a, "b": b})
        html = gen._tree_to_html_recursive("a", tree)
        assert "<div" in html

    def test_extract_subtree(self):
        gen = HTMLGenerator(make_client(), make_config())
        root = make_element(
            "root", "container", (0, 0, 500, 500), "", children_ids=["r1", "r2"]
        )
        r1 = make_element(
            "r1", "section", (0, 0, 500, 250), "", parent_id="root", children_ids=["c1"]
        )
        r2 = make_element("r2", "section", (0, 250, 500, 250), "", parent_id="root")
        c1 = make_element("c1", "button", (10, 10, 80, 30), "Click", parent_id="r1")

        tree = ComponentTree(
            root_id="root", elements={"root": root, "r1": r1, "r2": r2, "c1": c1}
        )

        sub = gen._extract_subtree(tree, "r1")
        assert "r1" in sub.elements
        assert "c1" in sub.elements
        assert "root" not in sub.elements
        assert "r2" not in sub.elements
        assert sub.root_id == "r1"


class TestHTMLGeneratorExtractHtml:
    def test_code_fence_html(self):
        gen = HTMLGenerator(make_client(), make_config())
        content = '```html\n<div class="foo">bar</div>\n```'
        assert '<div class="foo">bar</div>' == gen._extract_html(content)

    def test_code_fence_generic(self):
        gen = HTMLGenerator(make_client(), make_config())
        content = "```\n<p>text</p>\n```"
        assert "<p>text</p>" == gen._extract_html(content)

    def test_bare_html(self):
        gen = HTMLGenerator(make_client(), make_config())
        content = "<span>hello</span>"
        assert "<span>hello</span>" == gen._extract_html(content)


class TestStyleGeneratorLayout:
    def test_leaf_node(self):
        gen = StyleGenerator(make_client(), make_config())
        elem = make_element("e1", "button", (10, 20, 80, 30))
        tree = ComponentTree(root_id="e1", elements={"e1": elem})

        styles = gen._compute_layout_styles("e1", tree)
        assert styles["width"] == 80
        assert styles["height"] == 30
        assert styles["display"] == "block"

    def test_horizontal_children(self):
        gen = StyleGenerator(make_client(), make_config())
        parent = make_element(
            "p", "container", (0, 0, 400, 50), "", children_ids=["c1", "c2"]
        )
        c1 = make_element("c1", "button", (10, 10, 80, 30), "Btn1", parent_id="p")
        c2 = make_element("c2", "button", (110, 10, 80, 30), "Btn2", parent_id="p")
        tree = ComponentTree(root_id="p", elements={"p": parent, "c1": c1, "c2": c2})

        styles = gen._compute_layout_styles("p", tree)
        assert styles["display"] == "flex"
        assert styles["flex_direction"] == "row"

    def test_vertical_children(self):
        gen = StyleGenerator(make_client(), make_config())
        parent = make_element(
            "p", "container", (0, 0, 200, 300), "", children_ids=["c1", "c2"]
        )
        c1 = make_element("c1", "text", (10, 10, 180, 30), "Line 1", parent_id="p")
        c2 = make_element("c2", "text", (10, 60, 180, 30), "Line 2", parent_id="p")
        tree = ComponentTree(root_id="p", elements={"p": parent, "c1": c1, "c2": c2})

        styles = gen._compute_layout_styles("p", tree)
        assert styles["display"] == "flex"
        assert styles["flex_direction"] == "column"

    def test_gap_computation(self):
        gen = StyleGenerator(make_client(), make_config())
        parent = make_element(
            "p", "container", (0, 0, 200, 300), "", children_ids=["c1", "c2"]
        )
        c1 = make_element("c1", "text", (10, 10, 180, 30), "", parent_id="p")
        c2 = make_element("c2", "text", (10, 50, 180, 30), "", parent_id="p")
        tree = ComponentTree(root_id="p", elements={"p": parent, "c1": c1, "c2": c2})

        styles = gen._compute_layout_styles("p", tree)
        assert styles["gap"] == 10


class TestStyleGeneratorCss:
    def test_generates_css_rules(self):
        gen = StyleGenerator(make_client(), make_config())
        parent = make_element(
            "p", "container", (0, 0, 200, 200), "", children_ids=["c1"]
        )
        child = make_element("c1", "button", (10, 10, 80, 30), "", parent_id="p")

        tree = ComponentTree(root_id="p", elements={"p": parent, "c1": child})
        layout = {
            "p": {
                "display": "flex",
                "flex_direction": "column",
                "gap": 10,
                "padding": 8,
                "width": 200,
                "height": 200,
            }
        }

        css = gen._generate_custom_css(tree, layout, [])
        assert '[data-elem-id="p"]' in css
        assert "display: flex" in css
        assert "flex-direction: column" in css

    def test_flex_containers_get_selectors(self):
        gen = StyleGenerator(make_client(), make_config())
        parent = make_element(
            "p", "container", (0, 0, 200, 200), "", children_ids=["e1", "e2"]
        )
        e1 = make_element("e1", "button", (10, 10, 80, 30), "", parent_id="p")
        e2 = make_element("e2", "button", (100, 10, 80, 30), "", parent_id="p")

        tree = ComponentTree(
            root_id="p", elements={"p": parent, "e1": e1, "e2": e2}
        )
        layout = {
            "p": {"display": "flex", "flex_direction": "row", "gap": 10,
                  "padding": 0, "width": 200, "height": 200},
            "e1": {"display": "block", "width": 80, "height": 30},
            "e2": {"display": "block", "width": 80, "height": 30},
        }

        css = gen._generate_custom_css(tree, layout, [])
        # Container with flex gets a rule
        assert '[data-elem-id="p"]' in css
        assert "display: flex" in css
        # Leaf elements with no flex/gap/padding get no rule
        assert '[data-elem-id="e1"]' not in css
        assert '[data-elem-id="e2"]' not in css


class TestStyleGeneratorDocument:
    def test_assemble_document(self):
        gen = StyleGenerator(make_client(), make_config())
        colors = [{"hex": "#ff0000", "coverage_pct": 50.0}]
        html = gen._assemble_document("<p>Hello</p>", "p { color: red; }", colors)

        assert "<!DOCTYPE html>" in html
        assert "<p>Hello</p>" in html
        assert "p { color: red; }" in html
        assert "--color-primary: #ff0000" in html
        assert "box-sizing: border-box" in html
        assert "tailwind" not in html.lower()

    def test_no_tailwind_cdn(self):
        gen = StyleGenerator(make_client(), make_config())
        html = gen._assemble_document("<div>test</div>", "", [])
        assert "cdn.tailwindcss" not in html
        assert "tailwind" not in html.lower()

    def test_body_uses_color_primary_var(self):
        gen = StyleGenerator(make_client(), make_config())
        html = gen._assemble_document("<div>test</div>", "", [])
        assert "var(--color-primary" in html


class TestStyleGeneratorPageRoot:
    """BUG-009 FIX-D: page_root positioning and region absolute layout."""

    def test_page_root_returns_is_page_root(self):
        gen = StyleGenerator(make_client(), make_config())
        page = make_element("page_root", "page", (0, 0, 1, 1), "", children_ids=["r1"])
        r1 = make_element("r1", "section", (50, 100, 400, 300), "", parent_id="page_root")
        tree = ComponentTree(root_id="page_root", elements={"page_root": page, "r1": r1})

        styles = gen._compute_layout_styles("page_root", tree)
        assert styles["is_page_root"] is True
        assert styles["type"] == "page"

    def test_page_root_css_position_relative(self):
        gen = StyleGenerator(make_client(), make_config())
        page = make_element("page_root", "page", (0, 0, 1, 1), "", children_ids=["r1"])
        r1 = make_element("r1", "section", (50, 100, 400, 300), "", parent_id="page_root")
        tree = ComponentTree(root_id="page_root", elements={"page_root": page, "r1": r1})

        layout = {
            "page_root": {"is_page_root": True, "type": "page",
                          "display": "block", "flex_direction": None,
                          "gap": 0, "padding": 0,
                          "x": 0, "y": 0, "width": 1, "height": 1},
            "r1": {"display": "flex", "flex_direction": "column",
                   "gap": 0, "padding": 0,
                   "x": 50, "y": 100, "width": 400, "height": 300},
        }

        css = gen._generate_custom_css(tree, layout, [], ref_width=1200, ref_height=1500)
        assert "position: relative" in css
        assert "width: 1200px" in css
        assert "height: 1500px" in css

    def test_region_roots_get_absolute_position(self):
        gen = StyleGenerator(make_client(), make_config())
        page = make_element("page_root", "page", (0, 0, 1, 1), "",
                            children_ids=["nav", "hero"])
        nav = make_element("nav", "navigation", (0, 0, 1200, 80), "",
                           parent_id="page_root")
        hero = make_element("hero", "section", (0, 80, 1200, 400), "",
                            parent_id="page_root")
        tree = ComponentTree(
            root_id="page_root",
            elements={"page_root": page, "nav": nav, "hero": hero},
        )

        layout = {
            "page_root": {"is_page_root": True, "type": "page",
                          "display": "block", "flex_direction": None,
                          "gap": 0, "padding": 0,
                          "x": 0, "y": 0, "width": 1, "height": 1},
            "nav": {"display": "block", "flex_direction": None,
                    "gap": 0, "padding": 0,
                    "x": 0, "y": 0, "width": 1200, "height": 80},
            "hero": {"display": "block", "flex_direction": None,
                     "gap": 0, "padding": 0,
                     "x": 0, "y": 80, "width": 1200, "height": 400},
        }

        css = gen._generate_custom_css(tree, layout, [], ref_width=1200, ref_height=1500)
        assert "position: absolute" in css
        assert "left: 0px" in css
        assert "top: 80px" in css
        assert "width: 1200px" in css
        assert "height: 400px" in css

    def test_non_region_elements_no_absolute(self):
        """Elements that are NOT region roots should not get position: absolute."""
        gen = StyleGenerator(make_client(), make_config())
        page = make_element("page_root", "page", (0, 0, 1, 1), "",
                            children_ids=["r1"])
        r1 = make_element("r1", "section", (0, 0, 500, 300), "",
                           parent_id="page_root", children_ids=["btn"])
        btn = make_element("btn", "button", (10, 10, 80, 30), "Click",
                           parent_id="r1")
        tree = ComponentTree(
            root_id="page_root",
            elements={"page_root": page, "r1": r1, "btn": btn},
        )

        layout = {
            "page_root": {"is_page_root": True, "type": "page",
                          "display": "block", "flex_direction": None,
                          "gap": 0, "padding": 0,
                          "x": 0, "y": 0, "width": 1, "height": 1},
            "r1": {"display": "flex", "flex_direction": "column",
                   "gap": 0, "padding": 10,
                   "x": 0, "y": 0, "width": 500, "height": 300},
            "btn": {"display": "block", "flex_direction": None,
                    "gap": 0, "padding": 0,
                    "x": 10, "y": 10, "width": 80, "height": 30},
        }

        css = gen._generate_custom_css(tree, layout, [], ref_width=1200, ref_height=800)
        # btn should not have position: absolute
        btn_rule_start = css.find('[data-elem-id="btn"]')
        if btn_rule_start != -1:
            btn_rule_end = css.find("}", btn_rule_start)
            btn_rule = css[btn_rule_start:btn_rule_end]
            assert "position: absolute" not in btn_rule


# ---------------------------------------------------------------------------
# VLLM Single-Shot Codegen tests (Part B)
# ---------------------------------------------------------------------------


class TestHTMLGeneratorVLLMPrompt:
    """Tests for VLLM prompt building."""

    def test_build_vllm_prompt_is_simple(self):
        """Prompt should be minimal — no Phase 1 metadata."""
        gen = HTMLGenerator(make_client(), make_config())
        component = MagicMock()
        component.detected_elements = [
            DetectedElement(id="e1", type="button", bbox=(10, 20, 100, 40), text="Click"),
        ]
        component.regions = []
        component.reference_path = None

        prompt = gen._build_vllm_prompt(component, [])

        # Should NOT contain Phase 1 metadata
        assert "DETECTED" not in prompt
        assert "data-elem-id" not in prompt
        assert "e1" not in prompt
        assert "COLOR PALETTE" not in prompt

    def test_build_vllm_prompt_contains_clone_instruction(self):
        gen = HTMLGenerator(make_client(), make_config())
        component = MagicMock()
        component.reference_path = None

        prompt = gen._build_vllm_prompt(component, [])

        assert "Clone" in prompt or "clone" in prompt
        assert "background" in prompt.lower()

    def test_build_vllm_prompt_includes_dimensions(self, tmp_path):
        from PIL import Image
        img_path = tmp_path / "ref.png"
        Image.new("RGB", (800, 600)).save(img_path)

        gen = HTMLGenerator(make_client(), make_config())
        component = MagicMock()
        component.reference_path = img_path

        prompt = gen._build_vllm_prompt(component, [])

        assert "800" in prompt
        assert "600" in prompt

    def test_build_vllm_prompt_no_tailwind(self):
        gen = HTMLGenerator(make_client(), make_config())
        component = MagicMock()
        component.reference_path = None

        prompt = gen._build_vllm_prompt(component, [])

        assert "Tailwind" in prompt
        assert "plain CSS" in prompt.lower() or "Plain CSS" in prompt


class TestHTMLGeneratorVLLMSanitize:
    """Tests for VLLM output sanitization."""

    def test_sanitize_replaces_external_img_src(self):
        gen = HTMLGenerator(make_client(), make_config())
        html = '<img src="https://example.com/photo.jpg" alt="test">'
        result = gen._sanitize_vllm_output(html)

        assert "https://example.com" not in result
        assert "background-color: #e5e7eb" in result

    def test_sanitize_keeps_data_uri_images(self):
        gen = HTMLGenerator(make_client(), make_config())
        html = '<img src="data:image/png;base64,abc123" alt="test">'
        result = gen._sanitize_vllm_output(html)

        assert "data:image/png;base64,abc123" in result

    def test_sanitize_strips_external_css_urls(self):
        gen = HTMLGenerator(make_client(), make_config())
        html = '<div style="background-image: url(https://example.com/bg.png);">text</div>'
        result = gen._sanitize_vllm_output(html)

        assert "https://example.com" not in result

    def test_sanitize_neutralizes_external_hrefs(self):
        gen = HTMLGenerator(make_client(), make_config())
        html = '<a href="https://example.com">Link</a>'
        result = gen._sanitize_vllm_output(html)

        assert 'href="#"' in result

    def test_sanitize_removes_external_link_tags(self):
        gen = HTMLGenerator(make_client(), make_config())
        html = '<link rel="stylesheet" href="https://cdn.example.com/style.css">'
        result = gen._sanitize_vllm_output(html)

        assert "cdn.example.com" not in result


class TestHTMLGeneratorVLLMGenerate:
    """Tests for the full VLLM generation flow."""

    @pytest.mark.asyncio
    async def test_generate_vllm_fullpage(self):
        client = make_client()
        mock_response = MagicMock()
        mock_response.content = '```html\n<div class="hero"><h1>Hello</h1></div>\n```'
        client.codegen_from_vision = AsyncMock(return_value=mock_response)

        gen = HTMLGenerator(client, make_config())

        component = MagicMock()
        component.reference_path = None
        component.detected_elements = []
        component.regions = []

        colors = [{"hex": "#ffffff", "coverage_pct": 80.0}]
        result = await gen.generate_vllm_fullpage(component, colors)

        assert "<div" in result
        assert "Hello" in result
        client.codegen_from_vision.assert_called_once()


class TestStyleGeneratorEnsureDocument:
    """Tests for ensure_document_structure."""

    def test_wraps_fragment_in_document(self):
        gen = StyleGenerator(make_client(), make_config())
        colors = [{"hex": "#ff0000", "coverage_pct": 50.0}]
        html = '<div class="hero"><h1>Hello</h1></div>'

        result = gen.ensure_document_structure(html, colors)

        assert "<!DOCTYPE html>" in result
        assert "<html" in result
        assert "box-sizing: border-box" in result
        assert "--color-primary: #ff0000" in result
        assert "Hello" in result

    def test_keeps_full_document_intact(self):
        gen = StyleGenerator(make_client(), make_config())
        colors = [{"hex": "#ff0000", "coverage_pct": 50.0}]
        html = """<!DOCTYPE html>
<html><head><style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
</style></head><body><h1>Hello</h1></body></html>"""

        result = gen.ensure_document_structure(html, colors)

        assert result == html  # Unchanged

    def test_injects_reset_into_existing_document(self):
        gen = StyleGenerator(make_client(), make_config())
        colors = [{"hex": "#0000ff", "coverage_pct": 40.0}]
        html = """<!DOCTYPE html>
<html><head><style>
body { color: red; }
</style></head><body><p>Test</p></body></html>"""

        result = gen.ensure_document_structure(html, colors)

        assert "box-sizing: border-box" in result
        assert "--color-primary: #0000ff" in result
        assert "body { color: red; }" in result

    def test_no_tailwind_in_output(self):
        gen = StyleGenerator(make_client(), make_config())
        result = gen.ensure_document_structure("<div>test</div>", [])

        assert "tailwind" not in result.lower()
        assert "cdn.tailwindcss" not in result
