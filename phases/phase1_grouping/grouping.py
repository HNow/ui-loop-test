"""
Phase 1.3: Component Grouping

Organize flat element list into hierarchical component tree.
This is the critical step where parent-child relationships are determined.

The key insight from DesignCoder: containment is determined by bounding box
enclosure. Element B is a CHILD of element A iff B is visually enclosed
within A's boundaries. If B is adjacent but not enclosed, B is a SIBLING.

This phase is the highest-leverage intervention in the entire pipeline.
The DesignCoder paper showed that removing hierarchy extraction caused:
- SSIM to drop from 0.88 to 0.79
- TreeBLEU to drop from 0.65 to 0.43
- Container Match to drop from 0.50 to 0.29

Algorithm:
1. Send region crop + flat element list to vision model
2. Prompt specifically for containment reasoning
3. Parse nested tree structure from response
4. Post-process:
   - Ensure no orphan leaves (every element needs a parent)
   - Resolve overlapping container claims (tightest enclosure wins)
   - Flatten chains of single-child containers (>5-6 levels is suspicious)
   - Detect and break cycles to prevent infinite recursion
5. Assemble sub-trees into full page tree

If vision model fails, we fall back to geometric grouping based purely on
bbox enclosure (less accurate but deterministic).
"""

import copy
import json
import re
from typing import List, Dict, Optional, Tuple, Set
from collections import defaultdict
from storage.component import Component, Region, Element, ComponentTree
from llm_client import DualProviderClient
from config import Config


class ComponentGrouping:
    """
    Builds hierarchical component tree from flat element list.

    This is Phase 1.3 of the DesignCoder pipeline. For each region,
    we ask the vision model to determine parent-child relationships
    based on visual containment, then post-process the tree for quality.
    """

    def __init__(self, client: DualProviderClient, config: Config):
        self.client = client
        self.config = config

    async def group(
        self,
        component: Component,
        regions: List[Region],
        elements_by_region: Dict[str, List[Element]],
    ) -> ComponentTree:
        """
        Build hierarchical component tree from flat elements per region.

        For each region:
        1. Send region crop + element list to vision model
        2. Parse the returned hierarchy into a ComponentTree
        3. Post-process (orphans, conflicts, deep chains, cycles)

        Finally, assemble all region sub-trees into a single page tree.

        Returns:
            ComponentTree with root_id, elements dict, and regions list.
        """
        region_trees = []

        for region in regions:
            print(f"  Grouping elements in: {region.name}...", end=" ")

            elements = elements_by_region.get(region.id, [])
            if not elements:
                print("⚠ No elements to group")
                continue

            try:
                prompt = self._build_grouping_prompt(region.name, elements)

                response = await self.client.vision_analyze(
                    prompt=prompt,
                    images=[region.crop_path] if region.crop_path else [],
                    temperature=0.3,
                )

                tree = self._parse_grouping_response(
                    response.content, region.id, elements
                )

                if len(tree.elements) < len(elements):
                    print(
                        f"⚠ Tree has {len(tree.elements)} nodes, expected {len(elements)}"
                    )

            except Exception as e:
                print(f"⚠ Vision grouping failed ({e}), using geometric fallback")
                tree = self._geometric_grouping(region.id, elements)

            tree = self._post_process_tree(tree, elements)
            region_trees.append(tree)
            print(f"✓ ({len(tree.elements)} nodes)")

        # Stitch all region sub-trees under a single page root
        full_tree = self._assemble_full_tree(region_trees, regions)

        return full_tree

    # ------------------------------------------------------------------
    # Tree construction helpers
    # ------------------------------------------------------------------

    def _create_flat_tree(
        self, region_id: str, elements: List[Element]
    ) -> ComponentTree:
        """
        Create a flat tree where all elements are direct children of a
        synthetic root node. Used when there's nothing to nest.
        """
        root = Element(
            id=f"{region_id}_root",
            type="container",
            bbox=(0, 0, 1, 1),
            content_description="region root",
            children_ids=[e.id for e in elements],
        )

        elements_dict = {root.id: root}
        for e in elements:
            e.parent_id = root.id
            elements_dict[e.id] = e

        return ComponentTree(root_id=root.id, elements=elements_dict, regions=[])

    def _build_grouping_prompt(self, region_name: str, elements: List[Element]) -> str:
        """
        Build the prompt that asks the vision model to organize elements
        into a containment-based hierarchy.

        The prompt emphasizes the critical containment rule: child elements
        must be visually enclosed within their parent's bounding box.
        """
        # Format each element with its index, type, bbox, and description
        element_list = []
        for i, e in enumerate(elements):
            x, y, w, h = e.bbox
            element_list.append(
                f"[{i}] {e.type} at ({x},{y}) size {w}x{h} - '{e.content_description[:40]}'"
            )

        element_text = "\n".join(element_list)

        return f"""Given these elements in the "{region_name}" region, organize them into a hierarchical tree.

CONTAINMENT RULE (CRITICAL):
Element B is a CHILD of element A if and only if B is visually enclosed within A's boundaries.
If B is adjacent to A but not enclosed, B is a SIBLING of A, NOT a child.

Check bounding boxes:
- If element B's bbox is entirely within element A's bbox → B is child of A
- If elements overlap partially or not at all → they are siblings or belong to different parents

Elements:
{element_text}

Output format - JSON only:
{{
  "hierarchy": {{
    "id": "root",
    "type": "container",
    "children": [
      {{
        "id": "0",
        "type": "card",
        "children": [
          {{"id": "2", "type": "image"}},
          {{"id": "3", "type": "heading"}}
        ]
      }},
      {{
        "id": "1",
        "type": "button"
      }}
    ]
  }}
}}

Guidelines:
- Real UIs rarely exceed 5-6 nesting levels
- If a chain of single-child containers is deeper than 3 levels, flatten it
- Every leaf element must have a parent container
- Use ONLY the element index numbers (0, 1, 2, ...) as IDs — NOT "[0]" or "child-0"
- The "root" node is a synthetic container that holds all top-level elements
- SIBLINGS share the same parent, they are NOT nested inside each other
- You MUST include EVERY element in the tree — do not omit any

Respond with valid JSON only."""

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    def _parse_grouping_response(
        self, content: str, region_id: str, elements: List[Element]
    ) -> ComponentTree:
        """
        Parse the LLM's JSON hierarchy into a ComponentTree.

        Extracts JSON from the response, then recursively walks the
        hierarchy to build Element objects with parent/child links.
        """
        # Extract the first JSON object from the response text
        json_match = re.search(r"\{[\s\S]*\}", content)
        if not json_match:
            raise ValueError("No JSON found in response")

        json_str = json_match.group()

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            # Attempt to fix common LLM JSON mistakes (trailing commas, etc.)
            json_str = self._fix_json_issues(json_str)
            try:
                data = json.loads(json_str)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON: {e}")

        element_by_index = {str(i): e for i, e in enumerate(elements)}
        element_by_id = {e.id: e for e in elements}

        hierarchy = data.get("hierarchy", data.get("tree", {}))

        tree_elements: Dict[str, Element] = {}
        visited_ids: Set[str] = set()
        root_elem = self._parse_node_recursive(
            hierarchy,
            None,
            region_id,
            element_by_index,
            element_by_id,
            tree_elements,
            visited_ids,
        )

        for elem in elements:
            if elem.id not in tree_elements:
                root_elem.children_ids.append(elem.id)
                elem_copy = copy.deepcopy(elem)
                elem_copy.parent_id = root_elem.id
                tree_elements[elem_copy.id] = elem_copy

        return ComponentTree(root_id=root_elem.id, elements=tree_elements, regions=[])

    def _parse_node_recursive(
        self,
        node_data: dict,
        parent_id: Optional[str],
        region_id: str,
        element_by_index: Dict[str, Element],
        element_by_id: Dict[str, Element],
        tree_elements: Dict[str, Element],
        visited_ids: Set[str],
    ) -> Element:
        """
        Recursively convert a JSON hierarchy node into an Element.

        Matches node IDs to existing elements when possible; otherwise
        creates synthetic container elements. Tracks visited IDs to
        prevent cycles from malformed LLM output.
        """
        raw_id = node_data.get("id", "")
        node_id = raw_id.strip("[]()")

        original_elem = None
        if node_id in element_by_index:
            original_elem = element_by_index[node_id]
        elif raw_id in element_by_index:
            original_elem = element_by_index[raw_id]
        elif node_id in element_by_id:
            original_elem = element_by_id[node_id]
        elif raw_id in element_by_id:
            original_elem = element_by_id[raw_id]

        if original_elem:
            elem = copy.deepcopy(original_elem)
            elem.parent_id = parent_id
            elem.children_ids = []
        else:
            # No match found — create a synthetic container node
            elem_type = node_data.get("type", "container")
            elem = Element(
                id=f"{region_id}_synthetic_{len(tree_elements)}",
                type=elem_type,
                bbox=(0, 0, 1, 1),  # Will be computed from children later
                content_description=f"{elem_type} container",
                parent_id=parent_id,
                children_ids=[],
            )

        # Cycle guard: skip if we've already processed this element ID
        if elem.id in visited_ids:
            return elem
        visited_ids.add(elem.id)

        # Process child nodes
        children_data = node_data.get("children", [])
        for child_data in children_data:
            child_elem = self._parse_node_recursive(
                child_data if isinstance(child_data, dict) else {"id": str(child_data)},
                elem.id,
                region_id,
                element_by_index,
                element_by_id,
                tree_elements,
                visited_ids,
            )
            # Only add the child if it wasn't a duplicate/cycle
            if child_elem.id not in elem.children_ids:
                elem.children_ids.append(child_elem.id)

        tree_elements[elem.id] = elem
        return elem

    # ------------------------------------------------------------------
    # Geometric fallback
    # ------------------------------------------------------------------

    def _geometric_grouping(
        self, region_id: str, elements: List[Element]
    ) -> ComponentTree:
        """
        Fallback: build hierarchy purely from bbox enclosure.

        Sort elements largest-to-smallest. For each element, find the
        smallest container that fully encloses it — that's its parent.
        Deterministic but less accurate than vision-based grouping.
        """
        # Largest elements first — they're likely containers
        sorted_elements = sorted(
            elements, key=lambda e: e.bbox[2] * e.bbox[3], reverse=True
        )

        element_dict = {e.id: e for e in elements}

        for elem in sorted_elements:
            # Find the tightest-fitting container that encloses this element
            best_parent = None
            best_area = float("inf")

            for candidate in sorted_elements:
                if candidate.id == elem.id:
                    continue
                # Only consider container-like types as potential parents
                if candidate.type not in ("container", "card", "list"):
                    continue

                if self._is_enclosed(elem.bbox, candidate.bbox):
                    candidate_area = candidate.bbox[2] * candidate.bbox[3]
                    if candidate_area < best_area:
                        best_area = candidate_area
                        best_parent = candidate

            if best_parent:
                elem.parent_id = best_parent.id
                if elem.id not in best_parent.children_ids:
                    best_parent.children_ids.append(elem.id)

        # Find the root (element with no parent)
        root = None
        for elem in sorted_elements:
            if elem.parent_id is None:
                root = elem
                break

        if not root:
            # No natural root — create a synthetic one
            root = Element(
                id=f"{region_id}_root",
                type="container",
                bbox=(0, 0, 1, 1),
                content_description="root container",
                children_ids=[e.id for e in elements if e.parent_id is None],
            )
            element_dict[root.id] = root
            for e in elements:
                if e.parent_id is None:
                    e.parent_id = root.id

        return ComponentTree(root_id=root.id, elements=element_dict, regions=[])

    # ------------------------------------------------------------------
    # Post-processing
    # ------------------------------------------------------------------

    def _post_process_tree(
        self, tree: ComponentTree, original_elements: List[Element]
    ) -> ComponentTree:
        """
        Apply quality rules to the parsed tree:
        1. Attach orphan elements to the root
        2. Resolve conflicting parent claims
        3. Flatten overly-deep single-child chains
        4. Break any cycles in the tree
        5. Recompute container bboxes from children (bottom-up)
        """
        self._ensure_no_orphans(tree)
        self._resolve_container_conflicts(tree)
        self._flatten_deep_chains(tree)
        self._break_cycles(tree)
        self._compute_container_bboxes(tree)
        return tree

    def _ensure_no_orphans(self, tree: ComponentTree):
        """
        Every element must belong to the tree. Orphans (elements with
        no parent that aren't the root) get attached to the root node.
        """
        orphans = []
        for elem_id, elem in tree.elements.items():
            if elem.parent_id is None and elem_id != tree.root_id:
                orphans.append(elem)

        if orphans:
            root = tree.elements[tree.root_id]
            for orphan in orphans:
                orphan.parent_id = root.id
                if orphan.id not in root.children_ids:
                    root.children_ids.append(orphan.id)

    def _resolve_container_conflicts(self, tree: ComponentTree):
        """
        If multiple parents claim the same child, keep only the parent
        whose bbox most tightly encloses the child.
        """
        # Build a map: child_id → [parent_ids that list it as a child]
        parent_claims: Dict[str, List[str]] = defaultdict(list)
        for elem_id, elem in tree.elements.items():
            for child_id in elem.children_ids:
                parent_claims[child_id].append(elem_id)

        # Resolve any element claimed by more than one parent
        for child_id, claimed_parents in parent_claims.items():
            if len(claimed_parents) <= 1:
                continue

            child = tree.elements.get(child_id)
            if not child:
                continue

            # Pick the parent with the best overlap ratio
            best_parent = None
            best_overlap = -1

            for parent_id in claimed_parents:
                parent = tree.elements.get(parent_id)
                if not parent:
                    continue
                overlap = self._compute_overlap_ratio(child.bbox, parent.bbox)
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_parent = parent_id

            # Update the child's parent and remove it from losing parents
            child.parent_id = best_parent
            for parent_id in claimed_parents:
                if parent_id != best_parent:
                    parent = tree.elements.get(parent_id)
                    if parent and child_id in parent.children_ids:
                        parent.children_ids.remove(child_id)

    def _flatten_deep_chains(self, tree: ComponentTree):
        """
        Flatten chains where three consecutive nodes each have exactly
        one child. Replace A→B→C→D with A→D, removing B and C.

        This catches pathological LLM output that nests too deeply.
        After flattening, pruned nodes are removed from the tree.
        """
        nodes_to_remove: Set[str] = set()

        for elem_id, elem in list(tree.elements.items()):
            if elem_id in nodes_to_remove:
                continue

            # Check for a chain of 3+ single-child nodes
            if len(elem.children_ids) != 1:
                continue
            child = tree.elements.get(elem.children_ids[0])
            if not child or len(child.children_ids) != 1:
                continue
            grandchild = tree.elements.get(child.children_ids[0])
            if not grandchild or len(grandchild.children_ids) != 1:
                continue

            # A→B→C→D becomes A→D
            great_grandchild_id = grandchild.children_ids[0]
            great_grandchild = tree.elements.get(great_grandchild_id)

            if great_grandchild:
                # Rewire: elem now points directly to great-grandchild
                elem.children_ids = [great_grandchild_id]
                great_grandchild.parent_id = elem.id

                # Mark the two middle nodes for removal
                nodes_to_remove.add(child.id)
                nodes_to_remove.add(grandchild.id)

        # Actually remove pruned nodes from the tree
        for node_id in nodes_to_remove:
            tree.elements.pop(node_id, None)

    def _break_cycles(self, tree: ComponentTree):
        """
        Detect and break cycles in the children_ids graph.

        Uses iterative DFS with a visited/in-stack approach.
        If a back-edge is found (child already on the stack),
        that child reference is removed to break the cycle.
        """
        visited: Set[str] = set()
        in_stack: Set[str] = set()

        def dfs(node_id: str):
            """Iterative DFS to find and break back-edges."""
            stack = [(node_id, False)]  # (id, is_post_visit)

            while stack:
                current_id, is_post = stack.pop()

                if is_post:
                    # Post-visit: remove from recursion stack
                    in_stack.discard(current_id)
                    continue

                if current_id in visited:
                    continue

                visited.add(current_id)
                in_stack.add(current_id)
                # Push a post-visit marker so we pop from in_stack later
                stack.append((current_id, True))

                elem = tree.elements.get(current_id)
                if not elem:
                    in_stack.discard(current_id)
                    continue

                # Check each child — remove back-edges
                safe_children = []
                for child_id in elem.children_ids:
                    if child_id in in_stack:
                        # Back-edge detected → break the cycle
                        continue
                    safe_children.append(child_id)
                    if child_id not in visited:
                        stack.append((child_id, False))

                elem.children_ids = safe_children

        # Start DFS from the root
        dfs(tree.root_id)

        # Also run on any nodes not reachable from root (shouldn't happen
        # after _ensure_no_orphans, but defensive)
        for elem_id in list(tree.elements.keys()):
            if elem_id not in visited:
                dfs(elem_id)

    _ABSOLUTE_DRIFT_CAP = 200

    def _compute_container_bboxes(self, tree: ComponentTree):
        """
        Bottom-up pass: compute bboxes ONLY for synthetic/placeholder
        nodes (those created during grouping, not detected in Phase 1.0).

        Real detected elements keep their accurate Phase 1.0 bboxes.
        Synthetic nodes (ID contains 'synthetic') and placeholders
        (bbox area < 100) get their bbox computed as the union of
        children bboxes.
        """
        visited: Set[str] = set()

        def compute_bbox(elem_id: str) -> Optional[Tuple[int, int, int, int]]:
            if elem_id in visited:
                elem = tree.elements.get(elem_id)
                return elem.bbox if elem else None
            visited.add(elem_id)

            elem = tree.elements.get(elem_id)
            if not elem:
                return None

            if not elem.children_ids:
                return elem.bbox

            # Recurse into children so their bboxes are resolved first
            child_bboxes = []
            for child_id in elem.children_ids:
                cb = compute_bbox(child_id)
                if cb:
                    child_bboxes.append(cb)

            ex, ey, ew, eh = elem.bbox
            is_synthetic = "synthetic" in elem_id
            is_placeholder = (ew * eh) < 100

            # Only overwrite bbox for synthetic/placeholder nodes
            if (is_synthetic or is_placeholder) and child_bboxes:
                min_x = min(b[0] for b in child_bboxes)
                min_y = min(b[1] for b in child_bboxes)
                max_x = max(b[0] + b[2] for b in child_bboxes)
                max_y = max(b[1] + b[3] for b in child_bboxes)
                elem.bbox = (min_x, min_y, max_x - min_x, max_y - min_y)

            return elem.bbox

        compute_bbox(tree.root_id)

    # ------------------------------------------------------------------
    # Tree assembly
    # ------------------------------------------------------------------

    def _assemble_full_tree(
        self, region_trees: List[ComponentTree], regions: List[Region]
    ) -> ComponentTree:
        """
        Stitch per-region sub-trees into a single page tree.

        Creates a page_root node whose children are the region roots,
        ordered top-to-bottom by y-coordinate.
        """
        if not region_trees:
            return ComponentTree(root_id="empty", elements={}, regions=[])

        if len(region_trees) == 1:
            tree = region_trees[0]
            tree.regions = regions
            return tree

        # Merge all elements from every region into one dict
        full_elements: Dict[str, Element] = {}
        root_children = []

        # Sort regions by vertical position (top-to-bottom)
        sorted_pairs = sorted(
            zip(region_trees, regions), key=lambda pair: pair[1].bbox[1]
        )

        for tree, region in sorted_pairs:
            full_elements.update(tree.elements)
            root_children.append(tree.root_id)

        # Create the top-level page root
        page_root = Element(
            id="page_root",
            type="page",
            bbox=(0, 0, 1, 1),
            content_description="full page",
            children_ids=root_children,
        )
        full_elements[page_root.id] = page_root

        # Point each region root's parent to page_root
        for tree, region in sorted_pairs:
            root_elem = tree.elements.get(tree.root_id)
            if root_elem:
                root_elem.parent_id = page_root.id

        return ComponentTree(
            root_id=page_root.id, elements=full_elements, regions=regions
        )

    # ------------------------------------------------------------------
    # Geometry helpers
    # ------------------------------------------------------------------

    def _is_enclosed(
        self,
        inner_bbox: Tuple[int, int, int, int],
        outer_bbox: Tuple[int, int, int, int],
    ) -> bool:
        """Check if inner bbox is fully contained within outer bbox."""
        ix, iy, iw, ih = inner_bbox
        ox, oy, ow, oh = outer_bbox
        return ix >= ox and iy >= oy and ix + iw <= ox + ow and iy + ih <= oy + oh

    def _compute_overlap_ratio(
        self, bbox1: Tuple[int, int, int, int], bbox2: Tuple[int, int, int, int]
    ) -> float:
        """Compute Intersection-over-Union (IoU) of two bboxes."""
        x1, y1, w1, h1 = bbox1
        x2, y2, w2, h2 = bbox2

        xi = max(x1, x2)
        yi = max(y1, y2)
        wi = min(x1 + w1, x2 + w2) - xi
        hi = min(y1 + h1, y2 + h2) - yi

        if wi <= 0 or hi <= 0:
            return 0.0

        intersection = wi * hi
        area1 = w1 * h1
        area2 = w2 * h2
        union = area1 + area2 - intersection

        return intersection / union if union > 0 else 0.0

    def _fix_json_issues(self, json_str: str) -> str:
        """Fix common JSON mistakes from LLM responses."""
        # Remove trailing commas before } or ]
        json_str = re.sub(r",\s*}", "}", json_str)
        json_str = re.sub(r",\s*]", "]", json_str)
        # Convert single quotes to double quotes
        json_str = json_str.replace("'", '"')
        return json_str
