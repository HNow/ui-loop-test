"""
Unit tests for Phase 1: UI Grouping Chain

Tests cover:
  - ComponentGrouping tree construction (orphan resolution, cycle breaking,
    deep chain flattening, geometric fallback)
  - UIDivision region segmentation
  - SemanticExtraction element validation
"""

import json
import pytest
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from storage.component import Component, ComponentTree, Element, Region
from phases.phase1_grouping.grouping import ComponentGrouping
from phases.phase1_grouping.semantic import SemanticExtraction


# ---------------------------------------------------------------------------
# Helpers: reusable fixtures
# ---------------------------------------------------------------------------


def make_element(
    elem_id: str,
    elem_type: str = "container",
    bbox: tuple = (0, 0, 100, 100),
    content_description: str = "test element",
    children_ids: list | None = None,
    parent_id: str | None = None,
) -> Element:
    """Create an Element with sensible defaults."""
    return Element(
        id=elem_id,
        type=elem_type,
        bbox=bbox,
        content_description=content_description,
        children_ids=children_ids if children_ids is not None else [],
        parent_id=parent_id,
    )


def make_config() -> MagicMock:
    """Create a mock Config with sensible defaults."""
    cfg = MagicMock()
    cfg.target_regions_min = 3
    cfg.target_regions_max = 10
    cfg.max_elements_per_region = 40
    cfg.per_component_threshold = 0.9
    return cfg


def make_client() -> AsyncMock:
    """Create a mock DualProviderClient."""
    client = AsyncMock()
    client.code_complete = AsyncMock()
    client.vision_analyze = AsyncMock()
    return client


# ---------------------------------------------------------------------------
# ComponentGrouping tests
# ---------------------------------------------------------------------------


class TestComponentGrouping:
    """Tests for Phase 1.3: Component Grouping."""

    @pytest.fixture
    def grouping(self):
        client = make_client()
        config = make_config()
        return ComponentGrouping(client, config)

    # -- Geometric fallback grouping --

    def test_geometric_grouping_basic(self, grouping):
        """
        Geometric grouping should assign parent-child relationships
        based on bounding-box enclosure.
        """
        region_id = "r1"
        # A large container and a smaller element inside it
        container = make_element("c1", "container", (0, 0, 200, 200))
        button = make_element("b1", "button", (10, 10, 80, 30))

        tree = grouping._geometric_grouping(region_id, [container, button])

        # Button should be a child of the container
        assert button.parent_id == container.id
        assert button.id in container.children_ids

    def test_geometric_grouping_nested(self, grouping):
        """
        Three levels of nesting: outer > middle > inner.
        """
        region_id = "r1"
        outer = make_element("outer", "container", (0, 0, 300, 300))
        middle = make_element("mid", "card", (10, 10, 280, 280))
        inner = make_element("inner", "button", (20, 20, 60, 30))

        tree = grouping._geometric_grouping(region_id, [outer, middle, inner])

        # inner should be inside middle, middle inside outer
        assert inner.parent_id == middle.id
        assert middle.parent_id == outer.id

    def test_geometric_grouping_sibling(self, grouping):
        """
        Two buttons side by side — neither encloses the other,
        so they should be siblings under a shared container.
        """
        region_id = "r1"
        container = make_element("c1", "container", (0, 0, 400, 100))
        btn1 = make_element("b1", "button", (10, 10, 80, 30))
        btn2 = make_element("b2", "button", (110, 10, 80, 30))

        tree = grouping._geometric_grouping(region_id, [container, btn1, btn2])

        # Both buttons should be children of the container
        assert btn1.parent_id == container.id
        assert btn2.parent_id == container.id
        assert btn1.id in container.children_ids
        assert btn2.id in container.children_ids

    # -- Post-processing: orphan resolution --

    def test_ensure_no_orphans(self, grouping):
        """
        Elements with no parent should be attached to the root.
        """
        root = make_element("root", "container", (0, 0, 500, 500))
        orphan = make_element("orphan", "text", (10, 10, 50, 20))
        # orphan has no parent_id set

        tree = ComponentTree(root_id="root", elements={"root": root, "orphan": orphan})
        grouping._ensure_no_orphans(tree)

        assert orphan.parent_id == "root"
        assert orphan.id in root.children_ids

    # -- Post-processing: cycle breaking --

    def test_break_cycles(self, grouping):
        """
        A cycle A→B→A should be detected and the back-edge removed.
        """
        a = make_element("a", "container", (0, 0, 100, 100), children_ids=["b"])
        b = make_element(
            "b", "container", (10, 10, 80, 80), children_ids=["a"], parent_id="a"
        )

        # Create the cycle: a→b→a
        tree = ComponentTree(root_id="a", elements={"a": a, "b": b})
        grouping._break_cycles(tree)

        # The back-edge should be removed: b should no longer list a as a child
        assert "a" not in b.children_ids

    # -- Post-processing: deep chain flattening --

    def test_flatten_deep_chains(self, grouping):
        """
        A→B→C→D (3 single-child nodes) should flatten to A→D.
        """
        a = make_element("a", "container", (0, 0, 100, 100), children_ids=["b"])
        b = make_element(
            "b", "container", (0, 0, 80, 80), children_ids=["c"], parent_id="a"
        )
        c = make_element(
            "c", "container", (0, 0, 60, 60), children_ids=["d"], parent_id="b"
        )
        d = make_element("d", "button", (0, 0, 40, 40), parent_id="c")

        tree = ComponentTree(root_id="a", elements={"a": a, "b": b, "c": c, "d": d})
        grouping._flatten_deep_chains(tree)

        # A should now point directly to D
        assert d.id in a.children_ids
        assert d.parent_id == "a"

        # B and C should be removed
        assert "b" not in tree.elements
        assert "c" not in tree.elements

    # -- Container conflict resolution --

    def test_resolve_container_conflicts(self, grouping):
        """
        If two parents claim the same child, the tighter enclosure wins.
        """
        parent_big = make_element("big", "container", (0, 0, 300, 300))
        parent_small = make_element("small", "container", (50, 50, 100, 100))
        child = make_element(
            "child",
            "button",
            (60, 60, 40, 40),
            parent_id="big",  # Initially claimed by big
        )
        # Both parents claim the child
        parent_big.children_ids = ["child"]
        parent_small.children_ids = ["child"]

        tree = ComponentTree(
            root_id="big",
            elements={"big": parent_big, "small": parent_small, "child": child},
        )
        grouping._resolve_container_conflicts(tree)

        # Child should now be claimed only by the tighter parent (small)
        assert child.parent_id == "small"
        assert "child" not in parent_big.children_ids
        assert "child" in parent_small.children_ids

    # -- Bbox computation from children --

    def test_compute_container_bboxes(self, grouping):
        """
        Container bbox should be recomputed as the union of children.
        """
        parent = make_element("p", "container", (0, 0, 1, 1), children_ids=["c1", "c2"])
        child1 = make_element("c1", "button", (10, 20, 50, 30), parent_id="p")
        child2 = make_element("c2", "text", (70, 20, 40, 30), parent_id="p")

        tree = ComponentTree(
            root_id="p", elements={"p": parent, "c1": child1, "c2": child2}
        )
        grouping._compute_container_bboxes(tree)

        # Parent bbox should be union of children: x=10, y=20, w=100, h=30
        assert parent.bbox == (10, 20, 100, 30)

    # -- Full tree assembly --

    def test_assemble_full_tree_single_region(self, grouping):
        """
        Single region should be returned as-is.
        """
        root = make_element("r1_root", "container", (0, 0, 500, 500))
        tree = ComponentTree(root_id="r1_root", elements={"r1_root": root})
        region = Region(id="r1", name="test", bbox=(0, 0, 500, 500))

        result = grouping._assemble_full_tree([tree], [region])
        assert result.root_id == "r1_root"

    def test_assemble_full_tree_multi_region(self, grouping):
        """
        Multiple regions should be ordered top-to-bottom and placed
        under a synthetic page_root.
        """
        r1_root = make_element("r1_root", "container", (0, 0, 500, 200))
        r2_root = make_element("r2_root", "container", (0, 200, 500, 200))

        tree1 = ComponentTree(root_id="r1_root", elements={"r1_root": r1_root})
        tree2 = ComponentTree(root_id="r2_root", elements={"r2_root": r2_root})

        region1 = Region(id="r1", name="header", bbox=(0, 0, 500, 200))
        region2 = Region(id="r2", name="content", bbox=(0, 200, 500, 200))

        result = grouping._assemble_full_tree([tree1, tree2], [region1, region2])

        # Should have a synthetic page_root
        assert result.root_id == "page_root"
        page_root = result.elements["page_root"]
        assert "r1_root" in page_root.children_ids
        assert "r2_root" in page_root.children_ids
        # Regions should be ordered top-to-bottom (r1 first, r2 second)
        assert page_root.children_ids[0] == "r1_root"
        assert page_root.children_ids[1] == "r2_root"

    # -- Geometry helpers --

    def test_is_enclosed(self, grouping):
        """Test bbox enclosure check."""
        assert grouping._is_enclosed((10, 10, 50, 50), (0, 0, 100, 100))
        assert not grouping._is_enclosed((10, 10, 50, 50), (20, 20, 100, 100))
        assert not grouping._is_enclosed((0, 0, 50, 50), (10, 10, 50, 50))

    def test_overlap_ratio(self, grouping):
        """Test IoU computation."""
        # Two identical boxes: IoU = 1.0
        assert (
            grouping._compute_overlap_ratio((0, 0, 100, 100), (0, 0, 100, 100)) == 1.0
        )

        # Non-overlapping boxes: IoU = 0.0
        assert (
            grouping._compute_overlap_ratio((0, 0, 50, 50), (100, 100, 50, 50)) == 0.0
        )
        # Partially overlapping
        iou = grouping._compute_overlap_ratio((0, 0, 100, 100), (50, 0, 100, 100))
        assert 0.0 < iou < 1.0

    # -- JSON fixing --

    def test_fix_json_issues(self, grouping):
        """Test common JSON fixes from LLM output."""
        assert grouping._fix_json_issues("{'key': 'value'}") == '{"key": "value"}'
        assert grouping._fix_json_issues('{"a": 1,}') == '{"a": 1}'
        assert grouping._fix_json_issues('{"a": [1,]}') == '{"a": [1]}'

    # -- Vision grouping with mock client --

    @pytest.mark.asyncio
    async def test_group_with_vision(self, grouping):
        """
        Test the full grouping flow with a mocked vision model response.
        """
        # Mock the vision model to return a hierarchy
        mock_response = MagicMock()
        mock_response.content = json.dumps(
            {
                "hierarchy": {
                    "id": "root",
                    "type": "container",
                    "children": [
                        {
                            "id": "0",
                            "type": "card",
                            "children": [
                                {"id": "1", "type": "image"},
                                {"id": "2", "type": "heading"},
                            ],
                        },
                        {"id": "3", "type": "button"},
                    ],
                }
            }
        )
        grouping.client.vision_analyze = AsyncMock(return_value=mock_response)

        # Create test component and regions
        component = MagicMock()
        component.tree = None
        component.output_dir = Path("/tmp/test")

        region = Region(id="r1", name="test-region", bbox=(0, 0, 500, 500))
        region.crop_path = None

        elements = [
            make_element("e1", "card", (10, 10, 200, 200), "product card"),
            make_element("e2", "image", (20, 20, 180, 120), "product photo"),
            make_element("e3", "heading", (20, 150, 180, 30), "Product Name"),
            make_element("e4", "button", (20, 190, 120, 36), "Buy Now"),
        ]

        tree = await grouping.group(component, [region], {"r1": elements})

        # Should have a root with children
        assert tree.root_id is not None
        assert len(tree.elements) > 0


class TestSemanticExtraction:
    """Tests for Phase 1.2: Semantic Extraction."""

    @pytest.fixture
    def semantic(self):
        client = make_client()
        config = make_config()
        return SemanticExtraction(client, config)

    def test_deduplicate_elements(self, semantic):
        """
        Duplicate elements (IoU > 0.8) should be merged.
        """
        elem1 = make_element("e1", "button", (10, 10, 80, 30), "Submit")
        elem2 = make_element(
            "e2", "button", (12, 12, 78, 28), "Submit"
        )  # Nearly identical bbox

        # _deduplicate_elements should detect these are the same element
        result = semantic._deduplicate_elements([elem1, elem2])
        assert len(result) == 1

    def test_validate_element_types_button(self, semantic):
        """
        A button should not be full-width.
        """
        wide_button = make_element("e1", "button", (0, 10, 1200, 30), "wide button")
        normal_button = make_element(
            "e2", "button", (100, 10, 120, 36), "normal button"
        )

        result = semantic._validate_element_types([wide_button, normal_button])
        # The wide button should be reclassified as a container
        assert result[0].type != "button"
        assert result[1].type == "button"

    def test_validate_element_types_icon(self, semantic):
        """
        An icon should be small (< 64x64).
        """
        big_icon = make_element("e1", "icon", (0, 0, 200, 200), "big icon")
        small_icon = make_element("e2", "icon", (10, 10, 24, 24), "small icon")

        result = semantic._validate_element_types([big_icon, small_icon])
        assert result[0].type != "icon"  # Too big, reclassified
        assert result[1].type == "icon"  # Correct size

    def test_normalize_type(self, semantic):
        """Test type normalization mappings."""
        assert semantic._normalize_type("btn") == "button"
        assert semantic._normalize_type("txt") == "text"
        assert semantic._normalize_type("img") == "image"
        assert semantic._normalize_type("nav") == "nav-item"
        assert semantic._normalize_type("navigation") == "nav-item"
        assert semantic._normalize_type("h1") == "heading"
        assert semantic._normalize_type("unknown") == "container"  # Default fallback
