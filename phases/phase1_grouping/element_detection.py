"""
Element Detection - Pre-Step for UI Division

Runs before Phase 1.1 to detect all UI elements with bounding boxes.
This gives the division algorithm actual element data to work with,
instead of asking the model to "eyeball" region boundaries.

DesignCoder paper insight: Division should be informed by element locations,
not purely visual. Regions group elements, so we need to know where elements are.
"""

import json
import re
from typing import List, Tuple, Dict
from pathlib import Path
from llm_client import DualProviderClient
from config import Config
from storage.component import DetectedElement


class ElementDetector:
    """
    Detects all UI elements in a screenshot before region division.
    
    This is the critical pre-step that enables informed region division.
    Without element data, the division model is guessing boundaries.
    With element data, it can make decisions like:
    - "These 6 elements cluster together → that's a region"
    - "Don't split this card across two regions"
    - "This boundary cuts through a button, move it"
    """
    
    # Element types we care about for region grouping
    VALID_TYPES = {
        'button', 'input', 'text', 'heading', 'image', 'icon',
        'card', 'container', 'divider', 'badge', 'chip',
        'checkbox', 'radio', 'dropdown', 'tab', 'link',
        'search', 'avatar', 'logo', 'banner', 'grid'
    }
    
    def __init__(self, client: DualProviderClient, config: Config):
        self.client = client
        self.config = config
    
    async def detect(self, image_path: Path) -> List[DetectedElement]:
        """
        Detect all UI elements in the screenshot.
        
        Returns flat list of elements with bboxes.
        These elements will be grouped into regions in Phase 1.1.
        """
        from PIL import Image
        
        # Load image for dimensions
        img = Image.open(image_path)
        width, height = img.size
        
        # Build element detection prompt
        prompt = self._build_detection_prompt(width, height)
        
        # Call vision model
        response = await self.client.vision_analyze(
            prompt=prompt,
            images=[image_path],
            temperature=0.2  # Very low for consistent detection
        )
        
        # Parse elements from response
        elements = self._parse_detection_response(response.content)
        
        # Post-process and validate
        elements = self._validate_elements(elements, width, height)
        
        return elements
    
    def _build_detection_prompt(self, width: int, height: int) -> str:
        """Build prompt for element detection.

        Asks the model to return bounding boxes in 0-1000 normalized
        coordinates (Gemini's native format) to avoid ambiguity about
        whether returned values are pixels or normalized.
        """
        return f"""Analyze this UI screenshot and detect ALL visible UI elements.

For every interactive or visual element, provide:
1. Element type (from the list below)
2. Bounding box in NORMALIZED coordinates (0-1000 scale for both axes)
   - x=0 is left edge, x=1000 is right edge
   - y=0 is top edge, y=1000 is bottom edge
   - width and height also on 0-1000 scale
3. Visible text content (if any)

Element types to detect:
- button: clickable buttons ("Submit", "Cancel", icon buttons)
- input: text inputs, search boxes, form fields
- heading: titles, section headers, h1-h6
- text: paragraphs, labels, descriptions
- image: photos, illustrations, icons that are images
- icon: small symbolic icons (not photos)
- card: container with border/shadow containing grouped content
- container: layout containers, sections, divs with visual grouping
- divider: horizontal/vertical lines separating sections
- badge: small status indicators ("New", "3", notification dots)
- chip: tags, pills, selectable options
- checkbox: checkboxes and their labels
- radio: radio buttons
- dropdown: select boxes, dropdown menus
- tab: tab navigation items
- link: text links, navigation links
- search: search input areas (often with magnifying glass icon)
- avatar: user profile pictures
- logo: brand logos
- banner: announcement banners, promotional strips
- grid: table/grid structure indicators

Rules:
1. Detect EVERY visible element, even small ones
2. Bounding boxes should tightly fit the element (no extra padding)
3. All coordinates must be on the 0-1000 normalized scale
4. For text elements, include the actual text content
5. Nested elements: detect both parent container AND child elements
6. If an element is partially visible, still detect it
7. Confidence: estimate how clearly you can see this element (0.5-1.0)

Output format - JSON only:
{{
  "elements": [
    {{
      "id": "elem_0",
      "type": "button",
      "bbox": {{"x": 100, "y": 200, "width": 120, "height": 40}},
      "text": "Submit",
      "confidence": 0.95
    }},
    {{
      "id": "elem_1",
      "type": "heading",
      "bbox": {{"x": 100, "y": 50, "width": 300, "height": 36}},
      "text": "Welcome to Our App",
      "confidence": 0.98
    }}
  ]
}}

Image dimensions: {width}x{height}
All bbox values must use the 0-1000 normalized scale.

Respond with valid JSON only. Include every element you can see."""

    def _parse_detection_response(self, content: str) -> List[DetectedElement]:
        """Parse element list from vision model response."""
        # Extract JSON
        json_match = re.search(r'\{[\s\S]*\}', content)
        if not json_match:
            raise ValueError(f"No JSON found in element detection response: {content[:200]}")
        
        json_str = json_match.group()
        
        # Fix common issues
        json_str = json_str.replace("'", '"')
        json_str = re.sub(r',\s*}', '}', json_str)
        json_str = re.sub(r',\s*\]', ']', json_str)
        
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in element detection: {e}")
        
        elements = []
        for e in data.get("elements", []):
            elem_id = e.get("id", f"elem_{len(elements)}")
            elem_type = e.get("type", "unknown").lower()
            text = e.get("text", "")
            confidence = e.get("confidence", 1.0)
            
            # Parse bbox
            bbox_data = e.get("bbox", e.get("bounding_box", {}))
            if isinstance(bbox_data, list) and len(bbox_data) == 4:
                bbox = tuple(bbox_data)
            elif isinstance(bbox_data, dict):
                x = bbox_data.get("x", 0)
                y = bbox_data.get("y", 0)
                w = bbox_data.get("width", bbox_data.get("w", 10))
                h = bbox_data.get("height", bbox_data.get("h", 10))
                bbox = (x, y, w, h)
            else:
                bbox = (0, 0, 10, 10)
            
            # Normalize type
            elem_type = self._normalize_type(elem_type)
            
            elements.append(DetectedElement(
                id=elem_id,
                type=elem_type,
                bbox=bbox,
                text=text,
                confidence=confidence
            ))
        
        return elements
    
    def _normalize_type(self, raw_type: str) -> str:
        """Normalize element type to valid category."""
        type_map = {
            'btn': 'button',
            'cta': 'button',
            'submit': 'button',
            'field': 'input',
            'textfield': 'input',
            'searchbox': 'input',
            'search': 'input',
            'h1': 'heading',
            'h2': 'heading',
            'h3': 'heading',
            'title': 'heading',
            'header': 'heading',
            'p': 'text',
            'label': 'text',
            'description': 'text',
            'img': 'image',
            'photo': 'image',
            'pic': 'image',
            'box': 'container',
            'section': 'container',
            'area': 'container',
            'separator': 'divider',
            'line': 'divider',
            'tag': 'chip',
            'pill': 'chip',
            'select': 'dropdown',
            'menu': 'dropdown',
            'url': 'link',
            'a': 'link',
            'profile': 'avatar',
            'userpic': 'avatar',
            'brand': 'logo',
            'promo': 'banner',
            'alert': 'banner',
            'table': 'grid',
            'list': 'grid',
        }
        
        normalized = type_map.get(raw_type, raw_type)
        if normalized not in self.VALID_TYPES:
            normalized = 'container'  # Default fallback
        
        return normalized
    
    def _rescale_from_normalized(
        self,
        elements: List[DetectedElement],
        img_width: int,
        img_height: int,
    ) -> List[DetectedElement]:
        """
        Rescale bounding boxes from 0-1000 normalized coordinates
        to actual pixel coordinates.

        Gemini models return bboxes in a 0-1000 normalized coordinate
        space regardless of actual image dimensions.  We detect this by
        checking whether all right/bottom edges fall within [0, 1000].
        """
        if not elements:
            return elements

        # Heuristic: if every right-edge (x+w) and bottom-edge (y+h)
        # is ≤ 1010 (small tolerance) AND the image exceeds 1000px in
        # at least one dimension, assume 0-1000 normalized coords.
        max_right = max(e.bbox[0] + e.bbox[2] for e in elements)
        max_bottom = max(e.bbox[1] + e.bbox[3] for e in elements)
        image_exceeds = img_width > 1000 or img_height > 1000

        if max_right <= 1010 and max_bottom <= 1010 and image_exceeds:
            sx = img_width / 1000.0
            sy = img_height / 1000.0
            for elem in elements:
                x, y, w, h = elem.bbox
                elem.bbox = (
                    round(x * sx),
                    round(y * sy),
                    round(w * sx),
                    round(h * sy),
                )
        return elements

    def _validate_elements(
        self,
        elements: List[DetectedElement],
        img_width: int,
        img_height: int
    ) -> List[DetectedElement]:
        """Validate and clean detected elements."""
        # Rescale from 0-1000 normalized coords to pixels
        elements = self._rescale_from_normalized(elements, img_width, img_height)

        valid = []

        for elem in elements:
            x, y, w, h = elem.bbox

            # Skip zero-size
            if w <= 0 or h <= 0:
                continue

            # Skip if completely outside image
            if x >= img_width or y >= img_height:
                continue

            # Clamp to image bounds
            x = max(0, x)
            y = max(0, y)
            w = min(w, img_width - x)
            h = min(h, img_height - y)

            # Skip very small elements (likely noise)
            if w < 5 or h < 5:
                continue

            elem.bbox = (x, y, w, h)
            valid.append(elem)

        # Sort by position (top-to-bottom, left-to-right)
        valid.sort(key=lambda e: (e.bbox[1], e.bbox[0]))

        # Reassign sequential IDs
        for i, elem in enumerate(valid):
            elem.id = f"elem_{i}"

        return valid
    
    def filter_elements_for_region(
        self,
        elements: List[DetectedElement],
        region_bbox: Tuple[int, int, int, int]
    ) -> List[DetectedElement]:
        """Get elements that fall within a specific region bbox."""
        rx, ry, rw, rh = region_bbox
        
        region_elements = []
        for elem in elements:
            ex, ey, ew, eh = elem.bbox
            
            # Check if element center is inside region
            ecx = ex + ew / 2
            ecy = ey + eh / 2
            
            if (rx <= ecx <= rx + rw) and (ry <= ecy <= ry + rh):
                region_elements.append(elem)
        
        return region_elements
