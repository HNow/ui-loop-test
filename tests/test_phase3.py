"""
Unit tests for Phase 3: Self-Correcting Refinement

Tests cover:
  - ComponentMatcher: expected index building, class/semantic/position matching
  - VisualComparator: SSIM severity, issue categorization, JSON parsing
  - TargetedRepair: HTML extraction, replacement, type-to-tag mapping
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from storage.component import Component, ComponentTree, Element, Region
from phases.phase3_refinement.matcher import ComponentMatcher
from phases.phase3_refinement.comparator import VisualComparator
from phases.phase3_refinement.repair import TargetedRepair
from utils.dom import DOMNode


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
    cfg.per_component_threshold = 0.9
    cfg.max_iterations = 5
    return cfg


def make_client() -> AsyncMock:
    client = AsyncMock()
    client.code_complete = AsyncMock()
    client.vision_analyze = AsyncMock()
    return client


# ---------------------------------------------------------------------------
# ComponentMatcher tests
# ---------------------------------------------------------------------------


class TestComponentMatcherIndex:
    def test_build_expected_index(self):
        client = make_client()
        config = make_config()
        matcher = ComponentMatcher(client, config)

        root = make_element("r", "container", (0, 0, 500, 500))
        btn = make_element("b1", "button", (10, 10, 80, 30), parent_id="r")
        tree = ComponentTree(root_id="r", elements={"r": root, "b1": btn})

        index = matcher._build_expected_index(tree)
        assert "r" in index
        assert "b1" in index
        assert index["b1"]["type"] == "button"
        assert "button" in index["b1"]["class_names"]

    def test_flatten_dom(self):
        matcher = ComponentMatcher(make_client(), make_config())

        leaf = DOMNode(tag="span")
        mid = DOMNode(tag="p", children=[leaf])
        root = DOMNode(tag="div", children=[mid])

        flat = matcher._flatten_dom(root)
        assert len(flat) == 3
        tags = [n.tag for n in flat]
        assert "div" in tags
        assert "p" in tags
        assert "span" in tags


class TestComponentMatcherByClass:
    def test_match_by_class(self):
        matcher = ComponentMatcher(make_client(), make_config())

        btn = make_element("b1", "button", (10, 10, 80, 30))
        tree = ComponentTree(root_id="b1", elements={"b1": btn})
        index = matcher._build_expected_index(tree)

        dom = DOMNode(
            tag="button",
            classes=["button"],
            bbox={"x": 10, "y": 10, "width": 80, "height": 30},
        )

        match = matcher._match_by_class(dom, index, set())
        assert match is not None
        assert match["expected_id"] == "b1"
        assert match["matched_by"] == "class_name"

    def test_no_match_without_classes(self):
        matcher = ComponentMatcher(make_client(), make_config())

        btn = make_element("b1", "button", (10, 10, 80, 30))
        tree = ComponentTree(root_id="b1", elements={"b1": btn})
        index = matcher._build_expected_index(tree)

        dom = DOMNode(tag="div")

        match = matcher._match_by_class(dom, index, set())
        assert match is None


class TestComponentMatcherBySemantic:
    def test_match_button_tag(self):
        matcher = ComponentMatcher(make_client(), make_config())

        btn = make_element("b1", "button", (10, 10, 80, 30))
        candidates = [("b1", {"tag": "button", "type": "button"})]

        dom = DOMNode(tag="button")
        match = matcher._match_by_semantic(dom, candidates)
        assert match is not None
        assert match["expected_id"] == "b1"

    def test_match_heading_variants(self):
        matcher = ComponentMatcher(make_client(), make_config())

        h = make_element("h1", "heading", (10, 10, 200, 30))
        candidates = [("h1", {"tag": "h2", "type": "heading"})]

        for tag in ["h1", "h2", "h3", "h4", "h5", "h6"]:
            dom = DOMNode(tag=tag)
            match = matcher._match_by_semantic(dom, candidates)
            assert match is not None


class TestComponentMatcherByPosition:
    def test_match_nearby(self):
        matcher = ComponentMatcher(make_client(), make_config())

        elem = make_element("e1", "button", (100, 100, 50, 30))
        candidates = [("e1", {"bbox": (100, 100, 50, 30)})]

        dom = DOMNode(tag="div", bbox={"x": 102, "y": 101, "width": 48, "height": 28})
        match = matcher._match_by_position(dom, candidates)
        assert match is not None
        assert match["confidence"] > 0

    def test_no_match_far_away(self):
        matcher = ComponentMatcher(make_client(), make_config())

        elem = make_element("e1", "button", (0, 0, 50, 30))
        candidates = [("e1", {"bbox": (0, 0, 50, 30)})]

        dom = DOMNode(tag="div", bbox={"x": 500, "y": 500, "width": 50, "height": 30})
        match = matcher._match_by_position(dom, candidates)
        assert match is None


# ---------------------------------------------------------------------------
# VisualComparator tests
# ---------------------------------------------------------------------------


class TestVisualComparatorSeverity:
    def test_major(self):
        comp = VisualComparator(make_client(), make_config())
        assert comp._severity_from_ssim(0.3) == "major"
        assert comp._severity_from_ssim(0.6) == "major"

    def test_minor(self):
        comp = VisualComparator(make_client(), make_config())
        assert comp._severity_from_ssim(0.75) == "minor"
        assert comp._severity_from_ssim(0.85) == "minor"

    def test_none(self):
        comp = VisualComparator(make_client(), make_config())
        assert comp._severity_from_ssim(0.95) == "none"


class TestVisualComparatorCategorize:
    def test_misarrangement(self):
        comp = VisualComparator(make_client(), make_config())
        category, severity = comp._categorize_issue(
            "Button is offset from expected position"
        )
        assert category == "misarrangement"
        assert severity == "major"

    def test_style_error(self):
        comp = VisualComparator(make_client(), make_config())
        category, severity = comp._categorize_issue("Background color is wrong")
        assert category == "style_error"
        assert severity == "minor"

    def test_missing_element(self):
        comp = VisualComparator(make_client(), make_config())
        category, severity = comp._categorize_issue("Navigation bar is missing")
        assert category == "missing_element"
        assert severity == "major"

    def test_unknown_defaults_to_style(self):
        comp = VisualComparator(make_client(), make_config())
        category, severity = comp._categorize_issue("Something looks off")
        assert category == "style_error"
        assert severity == "minor"


class TestVisualComparatorParseResponse:
    def test_valid_json(self):
        comp = VisualComparator(make_client(), make_config())
        content = """
        {
            "issues": [
                {
                    "category": "style_error",
                    "severity": "minor",
                    "description": "Font is wrong",
                    "repair": "Change font-family"
                }
            ],
            "overall_assessment": "Mostly good"
        }
        """
        issues = comp._parse_comparison_response(content)
        assert len(issues) == 1
        assert issues[0]["issue_type"] == "style_error"
        assert issues[0]["repair_suggestion"] == "Change font-family"

    def test_trailing_commas(self):
        comp = VisualComparator(make_client(), make_config())
        content = '{"issues": [{"category": "misarrangement", "severity": "major", "description": "test", "repair": "fix",}],}'
        issues = comp._parse_comparison_response(content)
        assert len(issues) == 1

    def test_empty_issues(self):
        comp = VisualComparator(make_client(), make_config())
        content = "No JSON here"
        issues = comp._parse_comparison_response(content)
        assert issues == []


class TestVisualComparatorCompare:
    @pytest.mark.asyncio
    async def test_returns_empty_without_tree(self, tmp_path):
        comp = VisualComparator(make_client(), make_config())
        ref = tmp_path / "ref.png"

        component = MagicMock()
        component.tree = None
        component.reference_path = ref

        issues = await comp.compare([], component)
        assert issues == []

    @pytest.mark.asyncio
    async def test_skips_low_confidence(self, tmp_path):
        comp = VisualComparator(make_client(), make_config())

        from PIL import Image

        ref = tmp_path / "ref.png"
        Image.new("RGB", (100, 100), (255, 255, 255)).save(ref)

        elem = make_element("e1", "button", (10, 10, 80, 30))
        tree = ComponentTree(root_id="e1", elements={"e1": elem})

        component = MagicMock()
        component.tree = tree
        component.reference_path = ref
        component.iterations = []

        dom = DOMNode(tag="button", bbox={"x": 10, "y": 10, "width": 80, "height": 30})
        matches = [{"expected_id": "e1", "dom_node": dom, "confidence": 0.1}]

        issues = await comp.compare(matches, component)
        assert issues == []


# ---------------------------------------------------------------------------
# TargetedRepair tests
# ---------------------------------------------------------------------------


class TestTargetedRepairTypeToTag:
    def test_known_types(self):
        repair = TargetedRepair(make_client(), make_config())
        assert repair._map_type_to_tag("container") == "div"
        assert repair._map_type_to_tag("button") == "button"
        assert repair._map_type_to_tag("heading") == "h2"
        assert repair._map_type_to_tag("image") == "img"
        assert repair._map_type_to_tag("navigation") == "nav"
        assert repair._map_type_to_tag("card") == "article"

    def test_unknown_defaults_to_div(self):
        repair = TargetedRepair(make_client(), make_config())
        assert repair._map_type_to_tag("unknown_widget") == "div"


class TestTargetedRepairExtractHtml:
    def test_html_code_fence(self):
        repair = TargetedRepair(make_client(), make_config())
        content = '```html\n<div class="fixed">Hello</div>\n```'
        result = repair._extract_repaired_html(content)
        assert '<div class="fixed">Hello</div>' == result

    def test_generic_code_fence(self):
        repair = TargetedRepair(make_client(), make_config())
        content = "```\n<button>New</button>\n```"
        result = repair._extract_repaired_html(content)
        assert "<button>New</button>" == result

    def test_bare_html_tags(self):
        repair = TargetedRepair(make_client(), make_config())
        content = 'Here is the fix: <span class="badge">OK</span> done'
        result = repair._extract_repaired_html(content)
        assert '<span class="badge">OK</span>' == result

    def test_returns_none_for_no_html(self):
        repair = TargetedRepair(make_client(), make_config())
        result = repair._extract_repaired_html("no html here")
        assert result is None


class TestTargetedRepairExtractComponent:
    def test_find_by_class(self):
        repair = TargetedRepair(make_client(), make_config())

        elem = make_element("e1", "card", (10, 10, 200, 150))
        tree = ComponentTree(root_id="e1", elements={"e1": elem})

        full_html = '<div class="container"><article class="card"><h2>Title</h2></article></div>'

        html, sel_type, sel_value = repair._extract_component_html(
            full_html, "e1", MagicMock(tree=tree)
        )
        assert html is not None
        assert "<article" in html
        assert sel_type == "class"
        assert sel_value == "card"

    def test_find_by_id(self):
        repair = TargetedRepair(make_client(), make_config())

        elem = make_element("my_card", "card", (10, 10, 200, 150))
        tree = ComponentTree(root_id="my_card", elements={"my_card": elem})

        full_html = '<div><article id="my-card"><p>Content</p></article></div>'

        html, sel_type, sel_value = repair._extract_component_html(
            full_html, "my_card", MagicMock(tree=tree)
        )
        assert html is not None
        assert sel_type == "id"

    def test_find_by_tag_fallback(self):
        repair = TargetedRepair(make_client(), make_config())

        elem = make_element("e1", "navigation", (0, 0, 500, 60))
        tree = ComponentTree(root_id="e1", elements={"e1": elem})

        full_html = '<div><nav><a href="#">Home</a></nav></div>'

        html, sel_type, sel_value = repair._extract_component_html(
            full_html, "e1", MagicMock(tree=tree)
        )
        assert html is not None
        assert "<nav" in html
        assert sel_type == "tag"

    def test_not_found(self):
        repair = TargetedRepair(make_client(), make_config())

        elem = make_element("e1", "button", (10, 10, 80, 30))
        tree = ComponentTree(root_id="e1", elements={"e1": elem})

        full_html = "<div><p>No button here</p></div>"

        html, sel_type, sel_value = repair._extract_component_html(
            full_html, "e1", MagicMock(tree=tree)
        )
        assert html is None


class TestTargetedRepairReplace:
    def test_replace_by_class(self):
        repair = TargetedRepair(make_client(), make_config())

        full_html = '<div><article class="card"><h2>Old</h2></article></div>'
        new_html = '<article class="card"><h2>New</h2></article>'

        result = repair._replace_component_html(full_html, "class", "card", new_html)
        assert "New" in result
        assert "Old" not in result

    def test_replace_by_id(self):
        repair = TargetedRepair(make_client(), make_config())

        full_html = '<div><nav id="my-nav"><a>Old</a></nav></div>'
        new_html = '<nav id="my-nav"><a>New</a></nav>'

        result = repair._replace_component_html(full_html, "id", "my-nav", new_html)
        assert "New" in result
        assert "Old" not in result

    def test_replace_preserves_surroundings(self):
        repair = TargetedRepair(make_client(), make_config())

        full_html = "<header><h1>Title</h1></header><main><p>Content</p></main>"
        new_html = "<h1>New Title</h1>"

        result = repair._replace_component_html(full_html, "tag", "h1", new_html)
        assert "<main>" in result
        assert "<header>" in result


class TestTargetedRepairParseCssPx:
    def test_extract_width(self):
        result = TargetedRepair._parse_css_px("width: 200px; height: 50px;", "width")
        assert result == 200

    def test_extract_height(self):
        result = TargetedRepair._parse_css_px("height: 100px;", "height")
        assert result == 100

    def test_missing_property(self):
        result = TargetedRepair._parse_css_px("color: red;", "width")
        assert result is None

    def test_case_insensitive(self):
        result = TargetedRepair._parse_css_px("Width: 300Px;", "width")
        assert result == 300


class TestTargetedRepairBuildPrompt:
    def test_prompt_contains_issues(self):
        repair = TargetedRepair(make_client(), make_config())
        issues = [
            {"severity": "major", "description": "Button misaligned"},
            {"severity": "minor", "description": "Color wrong"},
        ]
        prompt = repair._build_repair_prompt("<button>OK</button>", issues, "button")
        assert "MAJOR" in prompt
        assert "MINOR" in prompt
        assert "Button misaligned" in prompt
        assert "Color wrong" in prompt
        assert "<button>OK</button>" in prompt
