"""
Structural metrics for evaluating hierarchy correctness.
Implements TreeBLEU, Container Match, and Tree Edit Distance.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple
from collections import defaultdict


@dataclass
class TreeNode:
    """Generic tree node for metric computation."""

    label: str
    children: List["TreeNode"] = field(default_factory=list)

    def get_height1_subtrees(self) -> Set[Tuple[str, Tuple]]:
        """
        Get all height-1 subtrees: (parent_label, tuple(child_labels)).
        Used for TreeBLEU computation.
        """
        subtrees = set()
        if self.children:
            child_labels = tuple(c.label for c in self.children)
            subtrees.add((self.label, child_labels))
            for child in self.children:
                subtrees.update(child.get_height1_subtrees())
        return subtrees

    def get_containers(self) -> List["TreeNode"]:
        """Get all container nodes (nodes with children)."""
        containers = []
        if self.children:
            containers.append(self)
            for child in self.children:
                containers.extend(child.get_containers())
        return containers

    def to_zss_tree(self):
        """Convert to zss library format for tree edit distance."""
        try:
            from zss import Node as ZSSNode
        except ImportError:
            # Fallback simple implementation
            class SimpleNode:
                def __init__(self, label):
                    self.label = label
                    self.children = []

                def addkid(self, node):
                    self.children.append(node)

            node = SimpleNode(self.label)
            for child in self.children:
                node.addkid(child.to_zss_tree())
            return node

        node = ZSSNode(self.label)
        for child in self.children:
            node.addkid(child.to_zss_tree())
        return node


def compute_treebleu(generated: TreeNode, reference: TreeNode) -> float:
    """
    Compute TreeBLEU: proportion of matching height-1 subtrees.
    Returns score in [0.0, 1.0].
    """
    gen_subtrees = generated.get_height1_subtrees()
    ref_subtrees = reference.get_height1_subtrees()

    if not ref_subtrees:
        return 1.0 if not gen_subtrees else 0.0

    matches = len(gen_subtrees & ref_subtrees)
    return matches / len(ref_subtrees)


def compute_container_match(generated: TreeNode, reference: TreeNode) -> float:
    """
    Compute Container Match: % of reference containers with structurally
    equivalent containers in generated (same children in same order).
    Returns score in [0.0, 1.0].
    """
    ref_containers = reference.get_containers()
    gen_containers = generated.get_containers()

    if not ref_containers:
        return 1.0

    # Build signature map for generated containers
    gen_sigs = defaultdict(list)
    for container in gen_containers:
        sig = (container.label, tuple(c.label for c in container.children))
        gen_sigs[sig].append(container)

    # Match reference containers
    matched = 0
    for ref_container in ref_containers:
        ref_sig = (ref_container.label, tuple(c.label for c in ref_container.children))
        if gen_sigs[ref_sig]:
            matched += 1
            gen_sigs[ref_sig].pop(0)  # Consume match

    return matched / len(ref_containers)


def compute_tree_edit_distance(generated: TreeNode, reference: TreeNode) -> int:
    """
    Compute tree edit distance (Zhang-Shasha algorithm).
    Returns number of insertions, deletions, and relabelings needed.
    """
    try:
        import zss
        from zss import simple_distance

        gen_zss = generated.to_zss_tree()
        ref_zss = reference.to_zss_tree()

        return simple_distance(ref_zss, gen_zss)
    except ImportError:
        # Fallback: approximate with container match inverse
        # This is not the same but gives a rough estimate
        return int((1 - compute_container_match(generated, reference)) * 100)


# Reverse mapping: HTML tag → semantic type.
# Both dom_to_tree_node and component_tree_to_tree_node must produce
# labels from the SAME vocabulary or TreeBLEU/ContainerMatch will
# always be 0.0.
_TAG_TO_TYPE = {
    "div": "container",
    "main": "page",
    "article": "card",
    "section": "section",
    "nav": "navigation",
    "p": "text",
    "h1": "heading",
    "h2": "heading",
    "h3": "heading",
    "h4": "heading",
    "h5": "heading",
    "h6": "heading",
    "button": "button",
    "img": "image",
    "span": "icon",
    "input": "input",
    "a": "link",
    "hr": "divider",
    "ul": "list",
    "ol": "list",
    "li": "list-item",
    "select": "dropdown",
    "textarea": "textarea",
    "label": "label",
    "dialog": "modal",
    "header": "navigation",
    "footer": "footer",
    "figure": "image",
    "figcaption": "text",
    "table": "container",
    "form": "container",
    "body": "page",
}


def dom_to_tree_node(dom_node) -> TreeNode:
    """
    Convert DOMNode (from utils/dom.py) to TreeNode for metrics.
    Also handles ComponentTree (from storage/component.py) by dispatching
    to component_tree_to_tree_node().

    Labels are mapped to semantic types via _TAG_TO_TYPE so that the
    vocabulary matches component_tree_to_tree_node.
    """
    from storage.component import ComponentTree

    if isinstance(dom_node, ComponentTree):
        return component_tree_to_tree_node(dom_node)

    tag = getattr(dom_node, "tag", "div")
    label = _TAG_TO_TYPE.get(tag, tag)

    children = [
        dom_to_tree_node(c)
        for c in (dom_node.children if hasattr(dom_node, "children") else [])
    ]
    return TreeNode(label=label, children=children)


def component_tree_to_tree_node(component_tree) -> TreeNode:
    """
    Convert ComponentTree (from storage/component.py) to TreeNode.
    Labels use the bare semantic type (e.g. "container", "heading")
    so they share a vocabulary with dom_to_tree_node.
    Uses a visited set to guard against cycles in the tree.
    """
    elements = component_tree.elements
    visited = set()

    def build_node(element_id):
        # Cycle guard — return a leaf if we've already visited this node
        if element_id in visited:
            return TreeNode(label="cycle_ref")
        visited.add(element_id)

        element = elements.get(element_id)
        if not element:
            return TreeNode(label="unknown")

        label = element.type
        children = [build_node(cid) for cid in element.children_ids]
        return TreeNode(label=label, children=children)

    return build_node(component_tree.root_id)


def compute_all_metrics(
    generated_dom,
    reference_tree=None,
    generated_component_tree=None,
    reference_component_tree=None,
) -> Dict[str, float]:
    """
    Compute all structural metrics.
    Returns dict with treebleu, container_match, tree_edit_distance.
    """
    # Convert DOM to tree node
    gen_tree = dom_to_tree_node(generated_dom)

    # If we have reference component tree, use it
    if reference_component_tree:
        ref_tree = component_tree_to_tree_node(reference_component_tree)
    elif reference_tree:
        ref_tree = dom_to_tree_node(reference_tree)
    else:
        # No reference to compare against
        return {"treebleu": None, "container_match": None, "tree_edit_distance": None}

    return {
        "treebleu": compute_treebleu(gen_tree, ref_tree),
        "container_match": compute_container_match(gen_tree, ref_tree),
        "tree_edit_distance": compute_tree_edit_distance(gen_tree, ref_tree),
    }
