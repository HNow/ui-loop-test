"""
Unit tests for utils/metrics.py

Tests cover:
  - TreeNode height-1 subtree extraction
  - TreeBLEU computation
  - ContainerMatch computation
  - Tree Edit Distance (approximate fallback when zss not installed)
  - dom_to_tree_node and component_tree_to_tree_node conversion
"""

import pytest

from utils.metrics import (
    TreeNode,
    compute_treebleu,
    compute_container_match,
    compute_tree_edit_distance,
    compute_all_metrics,
    dom_to_tree_node,
    component_tree_to_tree_node,
)
from utils.dom import DOMNode
from storage.component import ComponentTree, Element


class TestTreeNode:
    def test_leaf_has_no_subtrees(self):
        node = TreeNode(label="button")
        assert node.get_height1_subtrees() == set()

    def test_single_level_subtrees(self):
        child_a = TreeNode(label="text")
        child_b = TreeNode(label="image")
        parent = TreeNode(label="div", children=[child_a, child_b])

        subtrees = parent.get_height1_subtrees()
        assert ("div", ("text", "image")) in subtrees

    def test_nested_subtrees(self):
        leaf = TreeNode(label="span")
        mid = TreeNode(label="p", children=[leaf])
        root = TreeNode(label="div", children=[mid])

        subtrees = root.get_height1_subtrees()
        assert ("div", ("p",)) in subtrees
        assert ("p", ("span",)) in subtrees

    def test_containers_only(self):
        leaf = TreeNode(label="span")
        mid = TreeNode(label="p", children=[leaf])
        root = TreeNode(label="div", children=[mid])

        containers = root.get_containers()
        labels = [c.label for c in containers]
        assert "div" in labels
        assert "p" in labels
        assert "span" not in labels

    def test_empty_tree_containers(self):
        node = TreeNode(label="img")
        assert node.get_containers() == []


class TestTreeBLEU:
    def test_identical_trees(self):
        tree = TreeNode(
            label="div",
            children=[
                TreeNode(label="p"),
                TreeNode(label="button"),
            ],
        )
        assert compute_treebleu(tree, tree) == 1.0

    def test_completely_different(self):
        ref = TreeNode(label="nav", children=[TreeNode(label="a")])
        gen = TreeNode(label="footer", children=[TreeNode(label="span")])
        assert compute_treebleu(gen, ref) == 0.0

    def test_partial_overlap(self):
        ref = TreeNode(
            label="div",
            children=[
                TreeNode(label="h1", children=[TreeNode(label="span")]),
                TreeNode(label="p", children=[TreeNode(label="a")]),
            ],
        )
        gen = TreeNode(
            label="div",
            children=[
                TreeNode(label="h1", children=[TreeNode(label="span")]),
                TreeNode(label="p", children=[TreeNode(label="button")]),
            ],
        )
        score = compute_treebleu(gen, ref)
        assert 0.0 < score < 1.0

    def test_empty_reference(self):
        gen = TreeNode(label="div", children=[TreeNode(label="p")])
        ref = TreeNode(label="div")
        assert compute_treebleu(gen, ref) == 0.0

    def test_both_empty(self):
        a = TreeNode(label="div")
        b = TreeNode(label="div")
        assert compute_treebleu(a, b) == 1.0


class TestContainerMatch:
    def test_identical(self):
        tree = TreeNode(
            label="div",
            children=[
                TreeNode(label="p"),
                TreeNode(label="button"),
            ],
        )
        assert compute_container_match(tree, tree) == 1.0

    def test_no_match(self):
        ref = TreeNode(label="nav", children=[TreeNode(label="a")])
        gen = TreeNode(label="main", children=[TreeNode(label="img")])
        assert compute_container_match(gen, ref) == 0.0

    def test_partial_match(self):
        ref = TreeNode(
            label="div",
            children=[
                TreeNode(label="p"),
                TreeNode(label="h1", children=[TreeNode(label="span")]),
            ],
        )
        gen = TreeNode(
            label="div",
            children=[
                TreeNode(label="p"),
                TreeNode(label="h1", children=[TreeNode(label="a")]),
            ],
        )
        score = compute_container_match(gen, ref)
        assert 0.0 < score <= 1.0

    def test_empty_reference(self):
        gen = TreeNode(label="div", children=[TreeNode(label="p")])
        ref = TreeNode(label="div")
        assert compute_container_match(gen, ref) == 1.0


class TestTreeEditDistance:
    def test_identical_trees_zero_distance(self):
        tree = TreeNode(
            label="div",
            children=[
                TreeNode(label="p"),
                TreeNode(label="span"),
            ],
        )
        dist = compute_tree_edit_distance(tree, tree)
        assert dist == 0

    def test_different_trees_positive_distance(self):
        ref = TreeNode(
            label="div",
            children=[
                TreeNode(label="p"),
                TreeNode(label="h1"),
                TreeNode(label="img"),
            ],
        )
        gen = TreeNode(
            label="nav",
            children=[
                TreeNode(label="a"),
            ],
        )
        dist = compute_tree_edit_distance(gen, ref)
        assert dist > 0


class TestConversions:
    def test_dom_to_tree_node_simple(self):
        dom = DOMNode(
            tag="div",
            classes=["card"],
            children=[
                DOMNode(tag="p", classes=["text"]),
            ],
        )
        tree = dom_to_tree_node(dom)
        assert tree.label == "div.card"
        assert len(tree.children) == 1
        assert tree.children[0].label == "p.text"

    def test_dom_to_tree_node_no_classes(self):
        dom = DOMNode(tag="main")
        tree = dom_to_tree_node(dom)
        assert tree.label == "main"

    def test_component_tree_to_tree_node(self):
        root = Element(
            id="root",
            type="container",
            bbox=(0, 0, 100, 100),
            content_description="root",
        )
        child = Element(
            id="c1",
            type="button",
            bbox=(10, 10, 50, 30),
            content_description="btn",
            parent_id="root",
        )
        root.children_ids = ["c1"]

        tree = ComponentTree(root_id="root", elements={"root": root, "c1": child})
        node = component_tree_to_tree_node(tree)

        assert node.label == "container.root"
        assert len(node.children) == 1
        assert node.children[0].label == "button.c1"

    def test_component_tree_with_cycle(self):
        a = Element(
            id="a",
            type="container",
            bbox=(0, 0, 100, 100),
            content_description="a",
            children_ids=["b"],
        )
        b = Element(
            id="b",
            type="container",
            bbox=(0, 0, 80, 80),
            content_description="b",
            parent_id="a",
            children_ids=["a"],
        )

        tree = ComponentTree(root_id="a", elements={"a": a, "b": b})
        node = component_tree_to_tree_node(tree)

        assert node.label == "container.a"
        assert len(node.children) == 1
        assert node.children[0].label == "container.b"
        assert node.children[0].children[0].label == "cycle_ref"


class TestComputeAllMetrics:
    def test_no_reference_returns_none(self):
        dom = DOMNode(tag="div", children=[DOMNode(tag="p")])
        result = compute_all_metrics(dom)
        assert result["treebleu"] is None
        assert result["container_match"] is None
        assert result["tree_edit_distance"] is None

    def test_with_reference_dom(self):
        gen = DOMNode(
            tag="div",
            classes=["container"],
            children=[
                DOMNode(tag="p"),
                DOMNode(tag="button"),
            ],
        )
        ref = DOMNode(
            tag="div",
            classes=["container"],
            children=[
                DOMNode(tag="p"),
                DOMNode(tag="button"),
            ],
        )
        result = compute_all_metrics(gen, reference_tree=ref)
        assert result["treebleu"] == 1.0
        assert result["container_match"] == 1.0

    def test_with_component_tree(self):
        gen = DOMNode(tag="div", children=[DOMNode(tag="p")])

        root = Element(
            id="r",
            type="container",
            bbox=(0, 0, 100, 100),
            content_description="r",
            children_ids=["c1"],
        )
        child = Element(
            id="c1",
            type="text",
            bbox=(10, 10, 80, 20),
            content_description="text",
            parent_id="r",
        )
        comp_tree = ComponentTree(root_id="r", elements={"r": root, "c1": child})

        result = compute_all_metrics(gen, reference_component_tree=comp_tree)
        assert isinstance(result["treebleu"], float)
