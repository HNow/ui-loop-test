"""
Phase 3.2: Component Matching

Match rendered DOM elements back to component tree nodes.
Uses class names/IDs assigned in Phase 2 for matching.
"""

import re
from typing import List, Dict, Optional, Tuple
from storage.component import Component, ComponentTree, Element
from llm_client import DualProviderClient
from config import Config
from utils.dom import DOMNode


class ComponentMatcher:
    """Matches rendered DOM to expected component tree."""
    
    def __init__(self, client: DualProviderClient, config: Config):
        self.client = client
        self.config = config
    
    async def match(
        self,
        dom_tree: DOMNode,
        expected_tree: ComponentTree
    ) -> List[Dict]:
        """
        Match DOM nodes to expected component tree nodes.
        
        Returns list of matches:
        - expected_id: component tree element id
        - dom_node: matched DOMNode
        - confidence: match confidence score (0-1)
        - matched_by: how the match was made (class_name, tag, position)
        
        Matching strategy:
        1. Primary: class name matching
        2. Secondary: semantic tag matching
        3. Tertiary: position-based matching
        """
        matches = []
        
        # Build index of expected elements
        expected_index = self._build_expected_index(expected_tree)
        
        # Flatten DOM tree for matching
        dom_flat = self._flatten_dom(dom_tree)
        
        # Track which expected elements have been matched
        matched_expected = set()
        
        # 1. Match by class name (highest confidence)
        for dom_node in dom_flat:
            match = self._match_by_class(dom_node, expected_index, matched_expected)
            if match:
                match["dom_node"] = dom_node
                matches.append(match)
                matched_expected.add(match["expected_id"])
        
        # 2. Match remaining by semantic tag
        unmatched_dom = [n for n in dom_flat if n not in [m["dom_node"] for m in matches]]
        unmatched_expected = [
            (eid, edata) for eid, edata in expected_index.items()
            if eid not in matched_expected
        ]
        
        for dom_node in unmatched_dom:
            if not unmatched_expected:
                break
            
            match = self._match_by_semantic(dom_node, unmatched_expected)
            if match:
                match["dom_node"] = dom_node
                matches.append(match)
                matched_expected.add(match["expected_id"])
                unmatched_expected = [
                    (eid, edata) for eid, edata in unmatched_expected
                    if eid != match["expected_id"]
                ]
        
        # 3. Match remaining by position (lowest confidence)
        unmatched_dom = [n for n in dom_flat if n not in [m["dom_node"] for m in matches]]
        unmatched_expected = [
            (eid, edata) for eid, edata in expected_index.items()
            if eid not in matched_expected
        ]
        
        for dom_node in unmatched_dom:
            if not unmatched_expected:
                break
            
            match = self._match_by_position(dom_node, unmatched_expected)
            if match:
                match["dom_node"] = dom_node
                matches.append(match)
                matched_expected.add(match["expected_id"])
                unmatched_expected = [
                    (eid, edata) for eid, edata in unmatched_expected
                    if eid != match["expected_id"]
                ]
        
        return matches
    
    def _build_expected_index(self, tree: ComponentTree) -> Dict[str, dict]:
        """Build index of expected elements by their identifiers."""
        index = {}
        
        for elem_id, elem in tree.elements.items():
            # Build class name from element type and position
            class_name = elem.type.lower()
            
            index[elem_id] = {
                "element": elem,
                "class_names": {class_name},
                "tag": self._map_type_to_tag(elem.type),
                "bbox": elem.bbox,
                "type": elem.type
            }
        
        return index
    
    def _flatten_dom(self, node: DOMNode, result: List[DOMNode] = None) -> List[DOMNode]:
        """Flatten DOM tree to list."""
        if result is None:
            result = []
        
        result.append(node)
        for child in node.children:
            self._flatten_dom(child, result)
        
        return result
    
    def _map_type_to_tag(self, element_type: str) -> str:
        """Map element type to HTML tag."""
        mapping = {
            "container": "div",
            "text": "p",
            "heading": "h2",
            "button": "button",
            "image": "img",
            "icon": "span",
            "input": "input",
            "link": "a",
            "divider": "hr",
            "badge": "span",
            "list": "ul",
            "card": "article",
            "nav-item": "a",
            "page": "main",
            "section": "section",
            "navigation": "nav",
        }
        return mapping.get(element_type.lower(), "div")
    
    def _match_by_class(
        self,
        dom_node: DOMNode,
        expected_index: Dict[str, dict],
        already_matched: set
    ) -> Optional[Dict]:
        """Match DOM node by its class names."""
        if not dom_node.classes:
            return None
        
        dom_classes = set(c.lower() for c in dom_node.classes)
        
        best_match = None
        best_score = 0
        
        for expected_id, expected_data in expected_index.items():
            if expected_id in already_matched:
                continue
            
            expected_classes = expected_data["class_names"]
            
            # Check for class overlap
            overlap = dom_classes & expected_classes
            if overlap:
                score = len(overlap) / max(len(dom_classes), len(expected_classes))
                if score > best_score and score > 0.5:
                    best_score = score
                    best_match = {
                        "expected_id": expected_id,
                        "confidence": score,
                        "matched_by": "class_name"
                    }
        
        return best_match
    
    def _match_by_semantic(
        self,
        dom_node: DOMNode,
        candidates: List[Tuple[str, dict]]
    ) -> Optional[Dict]:
        """Match by semantic tag and approximate position."""
        dom_tag = dom_node.tag.lower()
        
        best_match = None
        best_score = 0
        
        for expected_id, expected_data in candidates:
            expected_tag = expected_data["tag"]
            expected_type = expected_data["type"]
            
            # Direct tag match
            if dom_tag == expected_tag:
                score = 0.7  # Good match
            # Related tag match
            elif (dom_tag == "button" and expected_type == "button"):
                score = 0.8
            elif (dom_tag == "a" and expected_type in ("link", "nav-item")):
                score = 0.8
            elif (dom_tag in ("h1", "h2", "h3", "h4", "h5", "h6") and expected_type == "heading"):
                score = 0.8
            elif (dom_tag in ("p", "span") and expected_type == "text"):
                score = 0.6
            else:
                continue
            
            if score > best_score:
                best_score = score
                best_match = {
                    "expected_id": expected_id,
                    "confidence": score,
                    "matched_by": "tag"
                }
        
        return best_match
    
    def _match_by_position(
        self,
        dom_node: DOMNode,
        candidates: List[Tuple[str, dict]]
    ) -> Optional[Dict]:
        """Match by approximate position."""
        if not dom_node.bbox:
            return None
        
        dom_center = (
            dom_node.bbox["x"] + dom_node.bbox["width"] / 2,
            dom_node.bbox["y"] + dom_node.bbox["height"] / 2
        )
        
        best_match = None
        best_distance = float('inf')
        
        for expected_id, expected_data in candidates:
            expected_bbox = expected_data["bbox"]
            if not expected_bbox:
                continue
            
            expected_center = (
                expected_bbox[0] + expected_bbox[2] / 2,
                expected_bbox[1] + expected_bbox[3] / 2
            )
            
            # Compute Euclidean distance
            distance = (
                (dom_center[0] - expected_center[0])**2 +
                (dom_center[1] - expected_center[1])**2
            )**0.5
            
            if distance < best_distance and distance < 100:  # Within 100px
                best_distance = distance
                best_match = {
                    "expected_id": expected_id,
                    "confidence": max(0, 1 - distance / 100),  # Decreasing confidence with distance
                    "matched_by": "position"
                }
        
        return best_match
    
    def _compute_match_confidence(
        self,
        expected: dict,
        actual: DOMNode
    ) -> float:
        """Compute confidence score for a match."""
        scores = []
        
        # Class match
        if expected["class_names"] & set(c.lower() for c in actual.classes):
            scores.append(1.0)
        
        # Tag match
        if actual.tag.lower() == expected["tag"]:
            scores.append(0.8)
        
        # Position match (if available)
        if actual.bbox and expected["bbox"]:
            dom_center = (
                actual.bbox["x"] + actual.bbox["width"] / 2,
                actual.bbox["y"] + actual.bbox["height"] / 2
            )
            expected_center = (
                expected["bbox"][0] + expected["bbox"][2] / 2,
                expected["bbox"][1] + expected["bbox"][3] / 2
            )
            distance = (
                (dom_center[0] - expected_center[0])**2 +
                (dom_center[1] - expected_center[1])**2
            )**0.5
            if distance < 50:
                scores.append(0.9)
            elif distance < 100:
                scores.append(0.6)
        
        return max(scores) if scores else 0.0
