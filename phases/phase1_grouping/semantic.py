"""
Phase 1.2: Semantic Extraction

For each region, produce flat list of elements with semantic labels.
Not hierarchy yet - just "what is each element and what does it do."

This phase feeds into ComponentGrouping (1.3) which determines hierarchy.
The output is a flat list per region: each element has type, bbox, and description.

Element types include:
- container: layout wrappers, cards, sections
- text/heading: content text
- button: interactive actions
- image/icon: visual elements
- input/dropdown/checkbox: form controls
- badge/chip: status indicators
- etc.

Post-processing:
- Deduplicate overlapping detections (IoU > 0.8 considered duplicate)
- Validate types make sense for dimensions (buttons shouldn't be full-width, etc.)
- Normalize bboxes to absolute image coordinates
"""

import json
import re
from pathlib import Path
from typing import List, Dict, Tuple
from storage.component import Component, Region, Element
from llm_client import DualProviderClient
from config import Config


class SemanticExtraction:
    """Extracts semantic labels for elements within each region."""
    
    # Element types from DesignCoder paper + common UI patterns
    VALID_TYPES = {
        "container", "text", "heading", "button", "image", "icon",
        "input", "link", "divider", "badge", "list", "card",
        "nav-item", "dropdown", "checkbox", "radio", "slider",
        "textarea", "label", "tab", "accordion", "tooltip",
        "avatar", "chip", "banner", "modal", "toast"
    }
    
    def __init__(self, client: DualProviderClient, config: Config):
        self.client = client
        self.config = config
    
    async def extract(
        self,
        component: Component,
        regions: List[Region]
    ) -> Dict[str, List[Element]]:
        """
        Extract semantic elements from each region.
        
        Returns dict mapping region_id -> list of Element objects.
        Each Element has:
        - id: unique identifier
        - type: container, text, heading, button, image, icon, input, link, divider, badge, list, card, nav-item
        - bbox: (x, y, w, h) relative to region
        - content_description: what the element is/does
        - interactable: whether user can click/tap it
        """
        elements_by_region = {}
        
        for region in regions:
            print(f"  Extracting from region: {region.name}...", end=" ")
            
            if not region.crop_path or not Path(region.crop_path).exists():
                print(f"⚠ No crop available for {region.name}")
                elements_by_region[region.id] = []
                continue
            
            # Send region crop to vision model
            prompt = self._build_extraction_prompt(region.name)
            
            try:
                response = await self.client.vision_analyze(
                    prompt=prompt,
                    images=[region.crop_path],
                    temperature=0.2  # Lower temp for consistent extraction
                )
                
                # Parse elements from response
                elements = self._parse_extraction_response(response.content, region.id)
                
                # Post-process
                elements = self._deduplicate_elements(elements)
                elements = self._validate_element_types(elements)
                elements = self._normalize_bboxes(elements, region)
                
                elements_by_region[region.id] = elements
                print(f"✓ ({len(elements)} elements)")
                
            except Exception as e:
                print(f"✗ Error: {e}")
                elements_by_region[region.id] = []
        
        return elements_by_region
    
    def _build_extraction_prompt(self, region_name: str) -> str:
        """Build prompt for semantic extraction."""
        return f"""Analyze this UI region ({region_name}) and identify ALL elements.

For each element, provide:
1. Element type (choose most specific):
   - container: layout wrapper, card wrapper, section container
   - text: body text, paragraph, description
   - heading: h1-h6, title, headline (including prices like "$29.99")
   - button: clickable button, CTA, submit
   - image: photo, product image, illustration
   - icon: small symbolic image, SVG icon, font icon
   - input: text field, search box, number input
   - link: navigational link, anchor text
   - divider: separator line, horizontal rule
   - badge: status indicator, tag, pill
   - list: bulleted/numbered list container
   - card: self-contained content unit with border/shadow
   - nav-item: navigation element, menu item
   - dropdown: select menu, dropdown button
   - checkbox: checkable option
   - radio: radio button option
   - slider: range input, toggle
   - textarea: multi-line text input
   - label: form label, caption
   - avatar: user profile image
   - chip: small removable tag

2. Bounding box (x, y, width, height within this region, in pixels)

3. Content description:
   - For text/heading: the actual text content (or first 50 chars)
   - For button: button label + action if obvious
   - For image: what the image depicts
   - For input: placeholder text or label
   - For icon: what icon represents (if known)

4. Interactable: true/false (can user click/tap/scroll/type this?)

Guidelines:
- Include EVERY visible element, even small ones
- Text elements include prices, labels, captions
- Nested elements: if text is inside a button, list BOTH the button and the text separately
- Use "container" for layout wrappers that hold multiple elements
- If unsure about type, choose the more specific one

Output format - JSON only:
{{
  "elements": [
    {{
      "type": "heading",
      "bbox": {{"x": 20, "y": 30, "width": 200, "height": 24}},
      "content": "Product Name",
      "interactable": false
    }},
    {{
      "type": "text",
      "bbox": {{"x": 20, "y": 60, "width": 80, "height": 18}},
      "content": "$29.99",
      "interactable": false
    }},
    {{
      "type": "button",
      "bbox": {{"x": 20, "y": 90, "width": 120, "height": 40}},
      "content": "Add to Cart button",
      "interactable": true
    }}
  ]
}}

Region: {region_name}

Respond with valid JSON only. Be thorough - include all elements."""
    
    def _parse_extraction_response(
        self,
        content: str,
        region_id: str
    ) -> List[Element]:
        """Parse vision model response into Element objects."""
        # Extract JSON
        json_match = re.search(r'\{[\s\S]*\}', content)
        if not json_match:
            raise ValueError(f"No JSON found in response: {content[:200]}")
        
        json_str = json_match.group()
        
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            # Try to fix common issues
            json_str = self._fix_json_issues(json_str)
            try:
                data = json.loads(json_str)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON: {e}\nContent: {content[:500]}")
        
        elements = []
        for i, elem_data in enumerate(data.get("elements", [])):
            elem_type = elem_data.get("type", "container").lower().strip()
            
            # Normalize type
            elem_type = self._normalize_type(elem_type)
            
            # Parse bbox
            bbox_data = elem_data.get("bbox", elem_data.get("bounding_box", {}))
            bbox = self._parse_bbox(bbox_data)
            
            element = Element(
                id=f"{region_id}_elem_{i}",
                type=elem_type,
                bbox=bbox,
                content_description=elem_data.get("content", elem_data.get("description", "")),
                interactable=elem_data.get("interactable", False),
                parent_id=None,
                children_ids=[]
            )
            
            elements.append(element)
        
        return elements
    
    def _fix_json_issues(self, json_str: str) -> str:
        """Fix common JSON formatting issues."""
        # Remove trailing commas
        json_str = re.sub(r',\s*}', '}', json_str)
        json_str = re.sub(r',\s*]', ']', json_str)
        # Fix single quotes
        json_str = json_str.replace("'", '"')
        return json_str
    
    def _normalize_type(self, elem_type: str) -> str:
        """Normalize element type to valid type."""
        # Handle common variations
        type_mapping = {
            "txt": "text",
            "lbl": "label",
            "btn": "button",
            "img": "image",
            "nav": "nav-item",
            "navigation": "nav-item",
            "link": "link",
            "a": "link",
            "h1": "heading",
            "h2": "heading",
            "h3": "heading",
            "h4": "heading",
            "h5": "heading",
            "h6": "heading",
            "title": "heading",
            "header": "heading",
            "div": "container",
            "section": "container",
            "p": "text",
            "span": "text",
            "input": "input",
            "field": "input",
            "select": "dropdown",
            "checkbox": "checkbox",
            "check": "checkbox",
            "radio": "radio",
            "toggle": "slider",
            "switch": "slider",
            "tag": "badge",
            "pill": "badge",
            "separator": "divider",
            "line": "divider",
            "logo": "image",
            "thumbnail": "image",
            "photo": "image",
            "picture": "image",
            "avatar": "avatar",
            "profile": "avatar",
            "user": "avatar",
            "chip": "chip",
        }
        
        normalized = type_mapping.get(elem_type.lower(), elem_type.lower())
        
        # Ensure it's in valid types
        if normalized not in self.VALID_TYPES:
            return "container"  # Default fallback
        
        return normalized
    
    def _parse_bbox(self, bbox_data) -> Tuple[int, int, int, int]:
        """Parse bbox from various formats."""
        if isinstance(bbox_data, list):
            if len(bbox_data) == 4:
                return tuple(int(x) for x in bbox_data)
        elif isinstance(bbox_data, dict):
            x = int(bbox_data.get("x", 0))
            y = int(bbox_data.get("y", 0))
            w = int(bbox_data.get("width", bbox_data.get("w", 10)))
            h = int(bbox_data.get("height", bbox_data.get("h", 10)))
            return (x, y, w, h)
        
        return (0, 0, 10, 10)  # Default fallback
    
    def _deduplicate_elements(self, elements: List[Element]) -> List[Element]:
        """Remove duplicate/overlapping element detections."""
        if not elements:
            return elements
        
        # Sort by area (larger first)
        sorted_elems = sorted(
            elements,
            key=lambda e: e.bbox[2] * e.bbox[3],
            reverse=True
        )
        
        kept = []
        for elem in sorted_elems:
            # Check for significant overlap with kept elements
            is_duplicate = False
            for kept_elem in kept:
                iou = self._compute_iou(elem.bbox, kept_elem.bbox)
                if iou > 0.8:  # 80% overlap = duplicate
                    # Keep more specific type (prefer non-container)
                    if elem.type != "container" and kept_elem.type == "container":
                        # Replace the container with specific element
                        kept[kept.index(kept_elem)] = elem
                    is_duplicate = True
                    break
            
            if not is_duplicate:
                kept.append(elem)
        
        return kept
    
    def _compute_iou(
        self,
        bbox1: Tuple[int, int, int, int],
        bbox2: Tuple[int, int, int, int]
    ) -> float:
        """Compute Intersection over Union of two bboxes."""
        x1, y1, w1, h1 = bbox1
        x2, y2, w2, h2 = bbox2
        
        # Intersection
        xi = max(x1, x2)
        yi = max(y1, y2)
        wi = min(x1 + w1, x2 + w2) - xi
        hi = min(y1 + h1, y2 + h2) - yi
        
        if wi <= 0 or hi <= 0:
            return 0.0
        
        intersection = wi * hi
        
        # Union
        area1 = w1 * h1
        area2 = w2 * h2
        union = area1 + area2 - intersection
        
        return intersection / union if union > 0 else 0.0
    
    def _validate_element_types(self, elements: List[Element]) -> List[Element]:
        """Validate that element types make sense for their dimensions."""
        validated = []
        
        for elem in elements:
            x, y, w, h = elem.bbox
            
            # Button should not be full-width (>90% of typical container)
            if elem.type == "button" and w > 1000:
                elem.type = "container"
            
            # Icon should be small (< 64x64)
            if elem.type == "icon" and (w > 64 or h > 64):
                if w > 200 or h > 200:
                    elem.type = "image"
                else:
                    elem.type = "container"
            
            # Heading should be wider than tall (typically)
            if elem.type == "heading" and h > w * 2:
                # Very tall - might be vertical text or misclassified
                if h > 100:
                    elem.type = "container"
            
            # Checkbox/radio should be small and roughly square
            if elem.type in ("checkbox", "radio"):
                aspect = w / h if h > 0 else 1
                if aspect < 0.5 or aspect > 2.0 or w > 50:
                    elem.type = "button" if elem.interactable else "container"
            
            validated.append(elem)
        
        return validated
    
    def _normalize_bboxes(
        self,
        elements: List[Element],
        region: Region
    ) -> List[Element]:
        """Convert relative bboxes to absolute image coordinates."""
        rx, ry, rw, rh = region.bbox
        
        for elem in elements:
            ex, ey, ew, eh = elem.bbox
            # Convert to absolute coordinates
            elem.bbox = (
                rx + ex,
                ry + ey,
                ew,
                eh
            )
        
        return elements
