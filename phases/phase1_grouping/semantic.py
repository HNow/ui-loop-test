"""
Phase 1.2: Semantic Extraction

For each region, produce flat list of elements with semantic labels.
Not hierarchy yet - just "what is each element and what does it do."

This phase feeds into ComponentGrouping (1.3) which determines hierarchy.
The output is a flat list per region: each element has type, bbox, and description.

ARCHITECTURE (BUG-008 fix):
  When Phase 1.0 detections are available for a region, we use the
  LABEL-ONLY path: bboxes come directly from Phase 1.0 (accurate
  full-image detection) and the vision model only classifies type,
  content_description, and interactable.  This eliminates the bbox
  drift that occurred when re-detecting from cropped regions.

  When no detections are available (rare), we fall back to the old
  RE-DETECT path which asks the model to find elements from scratch.

Element types include:
- container: layout wrappers, cards, sections
- text/heading: content text
- button: interactive actions
- image/icon: visual elements
- input/dropdown/checkbox: form controls
- badge/chip: status indicators
- etc.
"""

import json
import re
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from storage.component import Component, Region, Element, DetectedElement
from llm_client import DualProviderClient
from config import Config

_DRIFT_THRESHOLD = 50
_MAX_GAP_FILL_PX = 20


class SemanticExtraction:
    """Extracts semantic labels for elements within each region."""

    VALID_TYPES = {
        "container",
        "text",
        "heading",
        "button",
        "image",
        "icon",
        "input",
        "link",
        "divider",
        "badge",
        "list",
        "card",
        "nav-item",
        "dropdown",
        "checkbox",
        "radio",
        "slider",
        "textarea",
        "label",
        "tab",
        "accordion",
        "tooltip",
        "avatar",
        "chip",
        "banner",
        "modal",
        "toast",
    }

    def __init__(self, client: DualProviderClient, config: Config):
        self.client = client
        self.config = config

    async def extract(
        self,
        component: Component,
        regions: List[Region],
        detected_elements: Optional[List[DetectedElement]] = None,
        region_detections: Optional[Dict[str, List[DetectedElement]]] = None,
    ) -> Tuple[Dict[str, List[Element]], Optional[Dict[str, float]]]:
        """
        Extract semantic elements from each region.

        Two modes:
          LABEL-ONLY (preferred): When *region_detections* is provided,
          Phase 1.0 bboxes are used verbatim and the vision model only
          classifies type / content / interactable.  No bbox drift.

          RE-DETECT (fallback): When no detections are available the
          model re-detects elements from the region crop, followed by
          normalisation, clamping, and cross-validation.

        Returns:
            (elements_by_region, aggregate_stats)
        """
        elements_by_region: Dict[str, List[Element]] = {}
        label_only_regions = 0
        redetect_regions = 0

        for region in regions:
            region_dets = (
                region_detections.get(region.id, []) if region_detections else []
            )
            has_crop = region.crop_path and Path(region.crop_path).exists()

            if region_dets:
                try:
                    elements = await self._label_existing_elements(
                        region, region_dets, has_crop
                    )
                    label_only_regions += 1
                    print(
                        f"  Labeling {region.name}: "
                        f"✓ {len(elements)} elements (label-only)"
                    )
                except Exception as e:
                    print(f"  Labeling {region.name}: ✗ {e}, falling back to re-detect")
                    elements = await self._redetect_region(region, detected_elements)
                    redetect_regions += 1
            else:
                if not has_crop:
                    print(f"  {region.name}: ⚠ No detections and no crop, skipping")
                    elements_by_region[region.id] = []
                    continue
                elements = await self._redetect_region(region, detected_elements)
                redetect_regions += 1

            elements = self._validate_element_types(elements)
            elements_by_region[region.id] = elements

        aggregate_stats: Optional[Dict[str, float]] = {
            "method": "label-only" if redetect_regions == 0 else "mixed",
            "regions_label_only": label_only_regions,
            "regions_redetect": redetect_regions,
            "total_regions": len(regions),
            "total_elements": sum(len(e) for e in elements_by_region.values()),
        }
        return elements_by_region, aggregate_stats

    # ------------------------------------------------------------------
    # LABEL-ONLY PATH (primary)
    # ------------------------------------------------------------------

    async def _label_existing_elements(
        self,
        region: Region,
        detections: List[DetectedElement],
        has_crop: bool,
    ) -> List[Element]:
        """
        Convert Phase 1.0 detections to Elements with model-classified
        type / content / interactable.  Bboxes come from Phase 1.0.

        Falls back to using Phase 1.0 data directly if the model fails
        to classify any element.
        """
        images = [region.crop_path] if has_crop else []
        prompt = self._build_label_only_prompt(region.name, detections)

        response = await self.client.vision_analyze(
            prompt=prompt,
            images=images,
            temperature=0.2,
        )

        classifications = self._parse_label_response(response.content)

        det_by_idx: Dict[int, DetectedElement] = {
            i: d for i, d in enumerate(detections)
        }

        elements: List[Element] = []
        for i, det in enumerate(detections):
            cls = classifications.get(i)

            elem_type = (
                self._normalize_type(cls["type"])
                if cls
                else self._normalize_type(det.type)
            )
            content = (
                (cls.get("content", "") or "").strip() if cls else det.text.strip()
            )
            if not content:
                content = (
                    det.text.strip() if det.text.strip() else f"{elem_type} element"
                )
            interactable = cls.get("interactable", False) if cls else False

            elements.append(
                Element(
                    id=f"{region.id}_{det.id}",
                    type=elem_type,
                    bbox=det.bbox,
                    content_description=content,
                    interactable=interactable,
                    parent_id=None,
                    children_ids=[],
                )
            )

        return elements

    def _build_label_only_prompt(
        self, region_name: str, detections: List[DetectedElement]
    ) -> str:
        elem_lines = []
        for i, d in enumerate(detections):
            x, y, w, h = d.bbox
            text_preview = d.text[:40] if d.text else "(no text)"
            elem_lines.append(f'  [{i}] at ({x},{y}) {w}x{h} — "{text_preview}"')
        elem_text = "\n".join(elem_lines)

        return f"""You are looking at the "{region_name}" region of a UI. Below is a list of elements already detected with accurate bounding boxes.

For each element, provide:
1. **type** — choose the most specific from: container, text, heading, button, image, icon, input, link, divider, badge, list, card, nav-item, dropdown, checkbox, radio, slider, textarea, label, tab, accordion, tooltip, avatar, chip, banner, modal, toast
2. **content** — actual text content (for text/heading/button), description of what's depicted (for image/icon), or a brief label (for container/card)
3. **interactable** — true if the user can click/tap/type this element

Elements:
{elem_text}

Output JSON only:
{{
  "classifications": [
    {{"index": 0, "type": "heading", "content": "Booking Details", "interactable": false}},
    {{"index": 1, "type": "button", "content": "Book", "interactable": true}}
  ]
}}

Respond with valid JSON only. Classify EVERY element listed above."""

    def _parse_label_response(self, content: str) -> Dict[int, dict]:
        json_match = re.search(r"\{[\s\S]*\}", content)
        if not json_match:
            print(f"    ⚠ No JSON in label response, using Phase 1.0 types")
            return {}

        json_str = self._fix_json_issues(json_match.group())
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            print(f"    ⚠ Invalid JSON in label response, using Phase 1.0 types")
            return {}

        result: Dict[int, dict] = {}
        for cls in data.get("classifications", []):
            idx = cls.get("index")
            if isinstance(idx, int):
                result[idx] = cls
        return result

    # ------------------------------------------------------------------
    # RE-DETECT PATH (fallback)
    # ------------------------------------------------------------------

    async def _redetect_region(
        self,
        region: Region,
        all_detections: Optional[List[DetectedElement]] = None,
    ) -> List[Element]:
        """
        Fallback: ask the vision model to detect elements from the
        region crop.  Applies clamping + cross-validation.
        """
        if not region.crop_path or not Path(region.crop_path).exists():
            return []

        prompt = self._build_redetect_prompt(region.name)
        response = await self.client.vision_analyze(
            prompt=prompt,
            images=[region.crop_path],
            temperature=0.2,
        )

        elements = self._parse_redetect_response(response.content, region.id)
        elements = self._deduplicate_elements(elements)
        elements = self._normalize_bboxes(elements, region)

        if all_detections:
            elements, _ = self._cross_validate_bboxes(elements, region, all_detections)

        print(f"  {region.name}: ✓ {len(elements)} elements (re-detect)")
        return elements

    def _build_redetect_prompt(self, region_name: str) -> str:
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

    def _parse_redetect_response(self, content: str, region_id: str) -> List[Element]:
        json_match = re.search(r"\{[\s\S]*\}", content)
        if not json_match:
            raise ValueError(f"No JSON found in response: {content[:200]}")

        json_str = json_match.group()
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            json_str = self._fix_json_issues(json_str)
            try:
                data = json.loads(json_str)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON: {e}\nContent: {content[:500]}")

        elements = []
        for i, elem_data in enumerate(data.get("elements", [])):
            elem_type = elem_data.get("type", "container").lower().strip()
            elem_type = self._normalize_type(elem_type)
            bbox_data = elem_data.get("bbox", elem_data.get("bounding_box", {}))
            bbox = self._parse_bbox(bbox_data)

            elements.append(
                Element(
                    id=f"{region_id}_elem_{i}",
                    type=elem_type,
                    bbox=bbox,
                    content_description=elem_data.get(
                        "content", elem_data.get("description", "")
                    ),
                    interactable=elem_data.get("interactable", False),
                    parent_id=None,
                    children_ids=[],
                )
            )
        return elements

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _fix_json_issues(self, json_str: str) -> str:
        json_str = re.sub(r",\s*}", "}", json_str)
        json_str = re.sub(r",\s*]", "]", json_str)
        json_str = json_str.replace("'", '"')
        return json_str

    def _normalize_type(self, elem_type: str) -> str:
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
        if normalized not in self.VALID_TYPES:
            return "container"
        return normalized

    def _parse_bbox(self, bbox_data) -> Tuple[int, int, int, int]:
        if isinstance(bbox_data, list):
            if len(bbox_data) == 4:
                return tuple(int(x) for x in bbox_data)
        elif isinstance(bbox_data, dict):
            x = int(bbox_data.get("x", 0))
            y = int(bbox_data.get("y", 0))
            w = int(bbox_data.get("width", bbox_data.get("w", 10)))
            h = int(bbox_data.get("height", bbox_data.get("h", 10)))
            return (x, y, w, h)
        return (0, 0, 10, 10)

    def _deduplicate_elements(self, elements: List[Element]) -> List[Element]:
        if not elements:
            return elements
        sorted_elems = sorted(
            elements, key=lambda e: e.bbox[2] * e.bbox[3], reverse=True
        )
        kept = []
        for elem in sorted_elems:
            is_duplicate = False
            for kept_elem in kept:
                iou = self._compute_iou(elem.bbox, kept_elem.bbox)
                if iou > 0.8:
                    if elem.type != "container" and kept_elem.type == "container":
                        kept[kept.index(kept_elem)] = elem
                    is_duplicate = True
                    break
            if not is_duplicate:
                kept.append(elem)
        return kept

    def _compute_iou(
        self, bbox1: Tuple[int, int, int, int], bbox2: Tuple[int, int, int, int]
    ) -> float:
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

    def _validate_element_types(self, elements: List[Element]) -> List[Element]:
        validated = []
        for elem in elements:
            x, y, w, h = elem.bbox
            if elem.type == "button" and w > 1000:
                elem.type = "container"
            if elem.type == "icon" and (w > 64 or h > 64):
                if w > 200 or h > 200:
                    elem.type = "image"
                else:
                    elem.type = "container"
            if elem.type == "heading" and h > w * 2:
                if h > 100:
                    elem.type = "container"
            if elem.type in ("checkbox", "radio"):
                aspect = w / h if h > 0 else 1
                if aspect < 0.5 or aspect > 2.0 or w > 50:
                    elem.type = "button" if elem.interactable else "container"
            validated.append(elem)
        return validated

    def _normalize_bboxes(
        self, elements: List[Element], region: Region
    ) -> List[Element]:
        """
        Fallback-only: convert crop-relative bboxes to absolute coords
        and clamp to region bounds.
        """
        rx, ry, rw, rh = region.bbox
        region_right = rx + rw
        region_bottom = ry + rh
        kept = []
        for elem in elements:
            ex, ey, ew, eh = elem.bbox
            abs_x = rx + ex
            abs_y = ry + ey
            clamped_x = max(rx, abs_x)
            clamped_y = max(ry, abs_y)
            clamped_r = min(region_right, abs_x + ew)
            clamped_b = min(region_bottom, abs_y + eh)
            clamped_w = clamped_r - clamped_x
            clamped_h = clamped_b - clamped_y
            if clamped_w <= 0 or clamped_h <= 0:
                print(
                    f"    ⚠ Dropped {elem.id} ({elem.type}) — "
                    f"bbox [{abs_x},{abs_y},{ew},{eh}] outside "
                    f"region [{rx},{ry},{rw},{rh}]"
                )
                continue
            if clamped_w < ew or clamped_h < eh:
                print(
                    f"    ⚠ Clamped {elem.id} ({elem.type}) — "
                    f"[{abs_x},{abs_y},{ew},{eh}] → "
                    f"[{clamped_x},{clamped_y},{clamped_w},{clamped_h}]"
                )
            elem.bbox = (clamped_x, clamped_y, clamped_w, clamped_h)
            kept.append(elem)
        return kept

    def _cross_validate_bboxes(
        self,
        elements: List[Element],
        region: Region,
        detected_elements: List[DetectedElement],
    ) -> Tuple[List[Element], Dict[str, float]]:
        """
        Fallback-only: cross-validate re-detected bboxes against Phase 1.0.
        """
        rx, ry, rw, rh = region.bbox
        region_right = rx + rw
        region_bottom = ry + rh
        det_by_text: Dict[str, DetectedElement] = {}
        for d in detected_elements:
            key = d.text.strip().lower()
            if key and len(key) >= 2:
                det_by_text[key] = d
        corrected_count = 0
        drifts: List[float] = []
        max_drift = 0.0
        for elem in elements:
            elem_text = elem.content_description.strip().lower()
            best_det = None
            for key, det in det_by_text.items():
                if key in elem_text or elem_text in key:
                    best_det = det
                    break
            if best_det is None:
                continue
            dx, dy, dw, dh = best_det.bbox
            ex, ey, ew, eh = elem.bbox
            center_det = (dx + dw / 2, dy + dh / 2)
            center_elem = (ex + ew / 2, ey + eh / 2)
            drift = (
                (center_elem[0] - center_det[0]) ** 2
                + (center_elem[1] - center_det[1]) ** 2
            ) ** 0.5
            drifts.append(drift)
            max_drift = max(max_drift, drift)
            if drift > _DRIFT_THRESHOLD:
                det_x = max(rx, dx)
                det_y = max(ry, dy)
                det_w = min(dx + dw, region_right) - det_x
                det_h = min(dy + dh, region_bottom) - det_y
                if det_w > 0 and det_h > 0:
                    print(
                        f"    ✎ {elem.id} ({elem.type}) drift "
                        f"{drift:.0f}px — bbox "
                        f"[{ex},{ey},{ew},{eh}] → "
                        f"[{det_x},{det_y},{det_w},{det_h}] "
                        f"(ground truth from '{best_det.text[:25]}')"
                    )
                    elem.bbox = (det_x, det_y, det_w, det_h)
                    corrected_count += 1
        stats = {
            "total": len(det_by_text),
            "corrected": corrected_count,
            "mean_drift": sum(drifts) / len(drifts) if drifts else 0.0,
            "max_drift": max_drift,
        }
        return elements, stats
