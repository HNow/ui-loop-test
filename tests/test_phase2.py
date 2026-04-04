"""
Unit tests for Phase 2: Code Generation

Tests cover:
  - HTMLGenerator tag mapping, class name generation, recursive HTML fallback
  - StyleGenerator layout computation, CSS generation, document assembly
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from storage.component import Component, ComponentTree, Element, Region
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
