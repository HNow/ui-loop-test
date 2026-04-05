"""
Unit tests for Phase 3: Self-Correcting Refinement

Tests cover:
  - ComponentMatcher: expected index building, class/semantic/position matching
  - VisualComparator: SSIM severity, issue categorization, JSON parsing
  - TargetedRepair: HTML extraction, replacement, type-to-tag mapping
  - ElementCloseupComparator: per-element SSIM, crop saving, VLLM analysis,
    comparison log, issue generation
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from storage.component import Component, ComponentTree, Element, Region, DetectedElement
from phases.phase3_refinement.matcher import ComponentMatcher
from phases.phase3_refinement.comparator import VisualComparator
from phases.phase3_refinement.repair import TargetedRepair, FullPageRepair
from phases.phase3_refinement.element_comparator import ElementCloseupComparator
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

    def test_prompt_includes_closeup_context(self):
        repair = TargetedRepair(make_client(), make_config())
        issues = [{"severity": "minor", "description": "Color off"}]
        closeup_context = [
            {
                "element_id": "e1",
                "element_type": "button",
                "ssim": 0.45,
                "bbox": [10, 20, 80, 30],
            },
        ]
        prompt = repair._build_repair_prompt(
            "<button>OK</button>", issues, "button",
            closeup_context=closeup_context,
        )
        assert "SSIM=0.450" in prompt
        assert "button (e1)" in prompt

    def test_prompt_no_closeup_context(self):
        repair = TargetedRepair(make_client(), make_config())
        issues = [{"severity": "minor", "description": "test"}]
        prompt = repair._build_repair_prompt(
            "<div>hi</div>", issues, "div", closeup_context=None
        )
        assert "Element-level comparison" not in prompt


class TestTargetedRepairGatherImages:
    def test_prefers_closeup_ref_crop(self, tmp_path):
        repair = TargetedRepair(make_client(), make_config())
        crop = tmp_path / "ref.png"
        crop.write_bytes(b"fake")

        issues = [{"ref_crop": str(crop), "severity": "minor"}]
        component = MagicMock()
        component.tree = None

        images = repair._gather_context_images("e1", issues, None, component)
        assert len(images) == 1
        assert images[0] == crop

    def test_falls_back_to_region_crop(self, tmp_path):
        repair = TargetedRepair(make_client(), make_config())

        # No closeup crops in issues
        issues = [{"severity": "minor", "description": "test"}]

        component = MagicMock()
        component.tree = None
        component.regions = None

        images = repair._gather_context_images("e1", issues, None, component)
        assert images == []


# ---------------------------------------------------------------------------
# ElementCloseupComparator tests (Part C)
# ---------------------------------------------------------------------------


class TestElementCloseupCompareElement:
    """Tests for _compare_element — per-element SSIM from bbox crops."""

    def test_identical_crops_high_ssim(self, tmp_path):
        from PIL import Image

        comp = ElementCloseupComparator(make_client(), make_config())

        img = Image.new("RGB", (200, 200), (128, 128, 128))
        elem = DetectedElement(id="e1", type="button", bbox=(10, 10, 80, 40))

        closeup_dir = tmp_path / "closeups"
        closeup_dir.mkdir()

        result = comp._compare_element(elem, img, img, closeup_dir)

        assert result is not None
        assert result["ssim"] > 0.99
        assert result["element_id"] == "e1"
        assert result["element_type"] == "button"
        assert (closeup_dir / "e1_ref.png").exists()
        assert (closeup_dir / "e1_gen.png").exists()

    def test_different_crops_low_ssim(self, tmp_path):
        from PIL import Image

        comp = ElementCloseupComparator(make_client(), make_config())

        ref = Image.new("RGB", (200, 200), (255, 0, 0))
        gen = Image.new("RGB", (200, 200), (0, 0, 255))
        elem = DetectedElement(id="e1", type="text", bbox=(10, 10, 80, 40))

        closeup_dir = tmp_path / "closeups"
        closeup_dir.mkdir()

        result = comp._compare_element(elem, ref, gen, closeup_dir)

        assert result is not None
        assert result["ssim"] < 0.5

    def test_tiny_element_skipped(self, tmp_path):
        from PIL import Image

        comp = ElementCloseupComparator(make_client(), make_config())

        img = Image.new("RGB", (200, 200), (128, 128, 128))
        elem = DetectedElement(id="e1", type="icon", bbox=(10, 10, 5, 5))

        closeup_dir = tmp_path / "closeups"
        closeup_dir.mkdir()

        result = comp._compare_element(elem, img, img, closeup_dir)
        assert result is None

    def test_out_of_bounds_clamped(self, tmp_path):
        from PIL import Image

        comp = ElementCloseupComparator(make_client(), make_config())

        img = Image.new("RGB", (100, 100), (128, 128, 128))
        # Element extends past image bounds
        elem = DetectedElement(id="e1", type="text", bbox=(80, 80, 50, 50))

        closeup_dir = tmp_path / "closeups"
        closeup_dir.mkdir()

        result = comp._compare_element(elem, img, img, closeup_dir)
        assert result is not None
        assert result["ssim"] > 0.99  # Same image, so identical


class TestElementCloseupIssueFromSsim:
    """Tests for _issue_from_ssim fallback issue generation."""

    def test_low_ssim_major_misarrangement(self):
        comp = ElementCloseupComparator(make_client(), make_config())
        entry = {
            "element_id": "e1",
            "element_type": "button",
            "ssim": 0.3,
            "bbox": [10, 20, 80, 30],
            "ref_crop_path": "/tmp/ref.png",
            "gen_crop_path": "/tmp/gen.png",
        }
        issue = comp._issue_from_ssim(entry)
        assert issue["severity"] == "major"
        assert issue["issue_type"] == "misarrangement"
        assert issue["component_id"] == "e1"

    def test_medium_ssim_major_style(self):
        comp = ElementCloseupComparator(make_client(), make_config())
        entry = {
            "element_id": "e2",
            "element_type": "heading",
            "ssim": 0.6,
            "bbox": [0, 0, 200, 40],
            "ref_crop_path": "",
            "gen_crop_path": "",
        }
        issue = comp._issue_from_ssim(entry)
        assert issue["severity"] == "major"
        assert issue["issue_type"] == "style_error"

    def test_high_ssim_minor_style(self):
        comp = ElementCloseupComparator(make_client(), make_config())
        entry = {
            "element_id": "e3",
            "element_type": "text",
            "ssim": 0.8,
            "bbox": [0, 0, 100, 20],
            "ref_crop_path": "",
            "gen_crop_path": "",
        }
        issue = comp._issue_from_ssim(entry)
        assert issue["severity"] == "minor"


class TestElementCloseupParseResponse:
    """Tests for _parse_closeup_response."""

    def test_valid_json(self):
        comp = ElementCloseupComparator(make_client(), make_config())
        content = json.dumps({
            "category": "style_error",
            "severity": "minor",
            "description": "Background color is wrong",
            "repair": "Change background from #fff to #f0f0f0",
        })
        entry = {
            "element_id": "e1",
            "ssim": 0.7,
            "bbox": [10, 20, 80, 30],
            "ref_crop_path": "/tmp/ref.png",
            "gen_crop_path": "/tmp/gen.png",
        }
        result = comp._parse_closeup_response(content, entry)
        assert result is not None
        assert result["component_id"] == "e1"
        assert result["issue_type"] == "style_error"
        assert result["severity"] == "minor"
        assert "background" in result["description"].lower()

    def test_no_json_returns_none(self):
        comp = ElementCloseupComparator(make_client(), make_config())
        result = comp._parse_closeup_response("no json here", {})
        assert result is None

    def test_trailing_commas_handled(self):
        comp = ElementCloseupComparator(make_client(), make_config())
        content = '{"category": "misarrangement", "severity": "major", "description": "offset", "repair": "fix",}'
        entry = {
            "element_id": "e1",
            "ssim": 0.4,
            "bbox": [0, 0, 50, 50],
            "ref_crop_path": "",
            "gen_crop_path": "",
        }
        result = comp._parse_closeup_response(content, entry)
        assert result is not None
        assert result["issue_type"] == "misarrangement"


class TestElementCloseupBuildPrompt:
    """Tests for _build_closeup_prompt."""

    def test_prompt_contains_element_info(self):
        comp = ElementCloseupComparator(make_client(), make_config())
        entry = {
            "element_type": "button",
            "text": "Submit",
            "ssim": 0.65,
            "bbox": [100, 200, 80, 30],
        }
        prompt = comp._build_closeup_prompt(entry)

        assert "button" in prompt
        assert "Submit" in prompt
        assert "0.650" in prompt
        assert "x=100" in prompt


class TestElementCloseupSaveLog:
    """Tests for _save_comparison_log."""

    def test_saves_json_file(self, tmp_path):
        comp = ElementCloseupComparator(make_client(), make_config())

        component = MagicMock()
        component.output_dir = tmp_path

        log = [
            {
                "element_id": "e1",
                "element_type": "button",
                "text": "Go",
                "bbox": [10, 20, 80, 30],
                "ssim": 0.85,
                "ref_crop_path": Path("/tmp/ref.png"),
                "gen_crop_path": Path("/tmp/gen.png"),
            },
        ]

        comp._save_comparison_log(component, 1, log)

        path = tmp_path / "artifacts" / "iter_1_element_comparison.json"
        assert path.exists()

        data = json.loads(path.read_text())
        assert len(data) == 1
        assert data[0]["element_id"] == "e1"
        assert data[0]["ssim"] == 0.85
        # Path objects should be serialized as strings
        assert isinstance(data[0]["ref_crop_path"], str)


class TestElementCloseupFullCompare:
    """Integration test for the full compare() flow."""

    @pytest.mark.asyncio
    async def test_compare_returns_issues_and_log(self, tmp_path):
        from PIL import Image

        comp = ElementCloseupComparator(make_client(), make_config())

        # Create reference and a different generated image
        ref = Image.new("RGB", (200, 200), (255, 255, 255))
        gen = Image.new("RGB", (200, 200), (0, 0, 0))
        ref_path = tmp_path / "ref.png"
        gen_path = tmp_path / "gen.png"
        ref.save(ref_path)
        gen.save(gen_path)

        component = MagicMock()
        component.reference_path = ref_path
        component.output_dir = tmp_path
        component.detected_elements = [
            DetectedElement(id="e1", type="button", bbox=(10, 10, 80, 40), text="Go"),
            DetectedElement(id="e2", type="text", bbox=(10, 60, 100, 20), text="Hello"),
        ]

        # Mock VLLM response for analysis
        mock_response = MagicMock()
        mock_response.content = json.dumps({
            "category": "style_error",
            "severity": "major",
            "description": "Colors completely wrong",
            "repair": "Change all backgrounds to white",
        })
        comp.client.codegen_from_vision = AsyncMock(return_value=mock_response)

        issues, log = await comp.compare(component, gen_path, 1)

        # Both elements should appear in log
        assert len(log) == 2

        # Both should have low SSIM (ref is white, gen is black)
        for entry in log:
            assert entry["ssim"] < 0.5

        # Issues should be generated for elements below threshold
        assert len(issues) > 0
        assert issues[0]["component_id"] in ("e1", "e2")

        # Comparison log should be saved
        log_path = tmp_path / "artifacts" / "iter_1_element_comparison.json"
        assert log_path.exists()

        # Closeup crops should exist
        closeup_dir = tmp_path / "artifacts" / "iter_1_closeups"
        assert closeup_dir.exists()

    @pytest.mark.asyncio
    async def test_compare_no_elements_returns_empty(self, tmp_path):
        from PIL import Image

        comp = ElementCloseupComparator(make_client(), make_config())

        img = Image.new("RGB", (100, 100), (128, 128, 128))
        img_path = tmp_path / "img.png"
        img.save(img_path)

        component = MagicMock()
        component.reference_path = img_path
        component.output_dir = tmp_path
        component.detected_elements = []

        issues, log = await comp.compare(component, img_path, 1)
        assert issues == []
        assert log == []

    @pytest.mark.asyncio
    async def test_compare_identical_no_issues(self, tmp_path):
        from PIL import Image

        cfg = make_config()
        cfg.per_component_threshold = 0.9
        comp = ElementCloseupComparator(make_client(), cfg)

        img = Image.new("RGB", (200, 200), (128, 128, 128))
        img_path = tmp_path / "img.png"
        img.save(img_path)

        component = MagicMock()
        component.reference_path = img_path
        component.output_dir = tmp_path
        component.detected_elements = [
            DetectedElement(id="e1", type="button", bbox=(10, 10, 80, 40)),
        ]

        issues, log = await comp.compare(component, img_path, 1)

        # Identical images → SSIM ≈ 1.0 → no issues
        assert len(log) == 1
        assert log[0]["ssim"] > 0.99
        assert issues == []


# ---------------------------------------------------------------------------
# FullPageRepair tests
# ---------------------------------------------------------------------------


class TestFullPageRepairPrompt:
    """Tests for full-page repair prompt construction."""

    def test_build_repair_prompt_contains_html_and_rules(self):
        repair = FullPageRepair(make_client(), make_config())

        html = "<html><body><div>Hello</div></body></html>"
        summary = "- [MAJOR] elem_0 (button, SSIM=0.05): missing"

        prompt = repair._build_repair_prompt(html, summary)

        assert html in prompt
        assert "MAJOR" in prompt
        assert "elem_0" in prompt
        assert "data-elem-id" in prompt
        assert "No external URLs" in prompt or "no Tailwind" in prompt.lower()
        assert "COMPLETE" in prompt

    def test_build_repair_prompt_no_tailwind(self):
        repair = FullPageRepair(make_client(), make_config())
        prompt = repair._build_repair_prompt("<html></html>", "none")
        assert "Tailwind" in prompt


class TestFullPageRepairIssueSummary:
    """Tests for issue summary formatting."""

    def test_formats_issues_with_severity_and_ssim(self):
        repair = FullPageRepair(make_client(), make_config())

        issues = [
            {
                "component_id": "elem_5",
                "issue_type": "missing_element",
                "severity": "major",
                "description": "Button is missing",
                "ssim": 0.05,
            },
        ]
        comparison_log = []

        summary = repair._build_issue_summary(issues, comparison_log)

        assert "MAJOR" in summary
        assert "elem_5" in summary
        assert "missing_element" in summary
        assert "0.050" in summary

    def test_fills_from_comparison_log(self):
        repair = FullPageRepair(make_client(), make_config())

        issues = []
        comparison_log = [
            {
                "element_id": "elem_3",
                "element_type": "text",
                "ssim": 0.4,
            },
        ]

        summary = repair._build_issue_summary(issues, comparison_log)

        assert "elem_3" in summary
        assert "LOW_SSIM" in summary

    def test_skips_high_ssim_entries(self):
        repair = FullPageRepair(make_client(), make_config())

        issues = []
        comparison_log = [
            {
                "element_id": "elem_ok",
                "element_type": "text",
                "ssim": 0.95,  # Above threshold
            },
        ]

        summary = repair._build_issue_summary(issues, comparison_log)

        assert "elem_ok" not in summary


class TestFullPageRepairValidation:
    """Tests for repair validation."""

    def test_valid_html_passes(self):
        repair = FullPageRepair(make_client(), make_config())

        original = '<html><body><div data-elem-id="e1">x</div></body></html>'
        repaired = '<html><body><div data-elem-id="e1">y</div></body></html>'

        assert repair._validate_repair(original, repaired) is True

    def test_missing_closing_html_fails(self):
        repair = FullPageRepair(make_client(), make_config())
        assert repair._validate_repair("<html></html>", "<html><body>") is False

    def test_too_large_fails(self):
        repair = FullPageRepair(make_client(), make_config())
        original = "<html>x</html>"
        repaired = "<html>" + "x" * 10000 + "</html>"
        assert repair._validate_repair(original, repaired) is False

    def test_too_small_fails(self):
        repair = FullPageRepair(make_client(), make_config())
        original = "<html>" + "x" * 1000 + "</html>"
        repaired = "<html>y</html>"
        assert repair._validate_repair(original, repaired) is False

    def test_lost_data_elem_ids_fails(self):
        repair = FullPageRepair(make_client(), make_config())
        original = (
            '<html><div data-elem-id="a"></div>'
            '<div data-elem-id="b"></div>'
            '<div data-elem-id="c"></div>'
            '<div data-elem-id="d"></div></html>'
        )
        repaired = '<html><div data-elem-id="a"></div></html>'
        assert repair._validate_repair(original, repaired) is False


class TestFullPageRepairExtractHtml:
    """Tests for HTML extraction from model response."""

    def test_extracts_from_html_code_fence(self):
        repair = FullPageRepair(make_client(), make_config())
        content = 'Sure:\n```html\n<html><body>hi</body></html>\n```'
        assert repair._extract_html(content) == "<html><body>hi</body></html>"

    def test_extracts_doctype_document(self):
        repair = FullPageRepair(make_client(), make_config())
        content = "Here is the fix:\n<!DOCTYPE html>\n<html><body>x</body></html>\nDone."
        result = repair._extract_html(content)
        assert result.startswith("<!DOCTYPE html>")
        assert result.endswith("</html>")

    def test_returns_none_for_no_html(self):
        repair = FullPageRepair(make_client(), make_config())
        assert repair._extract_html("I cannot help with that.") is None


class TestFullPageRepairIntegration:
    """Integration test for the full repair flow."""

    @pytest.mark.asyncio
    async def test_repair_returns_valid_html(self, tmp_path):
        repaired_doc = '<!DOCTYPE html><html><head></head><body><div data-elem-id="e1">fixed</div></body></html>'
        client = make_client()
        client.codegen_from_vision = AsyncMock(
            return_value=MagicMock(content=f"```html\n{repaired_doc}\n```")
        )

        config = make_config()
        repair = FullPageRepair(client, config)

        # Write original HTML
        html_path = tmp_path / "index.html"
        html_path.write_text(
            '<html><head></head><body><div data-elem-id="e1">orig</div></body></html>'
        )

        component = MagicMock()
        component.html_path = html_path
        component.reference_path = tmp_path / "ref.png"

        # Create a dummy reference image
        from PIL import Image
        Image.new("RGB", (100, 100), "white").save(component.reference_path)

        screenshot_path = tmp_path / "iter.png"
        Image.new("RGB", (100, 100), "gray").save(screenshot_path)

        issues = [{"component_id": "e1", "severity": "major",
                    "issue_type": "style_error", "description": "wrong color",
                    "ssim": 0.3}]

        result = await repair.repair(component, issues, [], screenshot_path)

        assert "fixed" in result
        assert 'data-elem-id="e1"' in result
        client.codegen_from_vision.assert_called_once()

        # Verify both images were passed
        call_kwargs = client.codegen_from_vision.call_args
        images = call_kwargs.kwargs.get("images") or call_kwargs[1].get("images")
        assert len(images) == 2

    @pytest.mark.asyncio
    async def test_repair_keeps_original_on_failure(self, tmp_path):
        client = make_client()
        client.codegen_from_vision = AsyncMock(
            side_effect=RuntimeError("API error")
        )

        config = make_config()
        repair = FullPageRepair(client, config)

        html_path = tmp_path / "index.html"
        original = "<html><body>original</body></html>"
        html_path.write_text(original)

        component = MagicMock()
        component.html_path = html_path
        component.reference_path = tmp_path / "ref.png"

        from PIL import Image
        Image.new("RGB", (100, 100)).save(component.reference_path)

        screenshot_path = tmp_path / "iter.png"
        Image.new("RGB", (100, 100)).save(screenshot_path)

        result = await repair.repair(component, [], [], screenshot_path)
        assert result == original
