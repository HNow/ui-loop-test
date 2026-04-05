"""
Phase 1.1: UI Division

Partition screenshot into 3-10 semantic regions.
Each region has: name, bbox (x, y, w, h), element_ids.

CRITICAL: Element detection runs FIRST (pre-step).
The division algorithm uses detected elements to make informed decisions.
Without element data, the model is guessing boundaries.

DesignCoder paper: "Division is informed by where elements actually are,
not purely visual. Regions group elements."
"""

import json
import re
from pathlib import Path
from typing import List, Tuple, Optional
from storage.component import Component, Region, DetectedElement
from llm_client import DualProviderClient, Message
from config import Config
from phases.phase1_grouping.element_detection import ElementDetector


def crop_and_save_regions(
    component: Component, regions: List[Region], reference_path: Path
) -> List[Region]:
    """
    Crop reference image to each region's bbox and save.
    Updates region.crop_path for each region.
    """
    from PIL import Image

    img = Image.open(reference_path)

    for region in regions:
        x, y, w, h = region.bbox

        # Ensure within bounds
        x = max(0, x)
        y = max(0, y)
        w = min(w, img.width - x)
        h = min(h, img.height - y)

        # Crop and save
        crop = img.crop((x, y, x + w, y + h))
        crop_path = component.output_dir / f"region_{region.id}.png"
        crop.save(crop_path, "PNG")

        region.crop_path = crop_path

    return regions


class UIDivision:
    """
    Divides UI screenshot into semantic regions using element-informed grouping.

    This is Phase 1.1 of the DesignCoder pipeline. CRITICAL DIFFERENCE from
    naive approaches: we first detect ALL elements, then use that data to
    inform region boundaries. This prevents splitting elements in half.

    Key algorithm steps:
    1. PRE-STEP: Detect all UI elements with bboxes (ElementDetector)
    2. Send screenshot + element list to vision model for region grouping
    3. Parse JSON response into bounding boxes
    4. Apply correction rules (merge overlaps with element-aware tiebreakers,
       fill small gaps, enforce count limits)
    5. Crop and save region images for Phase 1.2
    """

    def __init__(self, client: DualProviderClient, config: Config):
        self.client = client
        self.config = config
        self.element_detector = ElementDetector(client, config)

    async def divide(self, component: Component) -> List[Region]:
        """
        Divide reference image into semantic regions.

        CRITICAL: This now runs element detection FIRST, then uses
        detected elements to inform region boundaries.

        Args:
            component: Component with reference_path to the screenshot

        Returns:
            List of Region objects with element_ids populated
        """
        from PIL import Image

        # 0. PRE-STEP: Detect all UI elements
        print("  [1.0] Detecting UI elements...")
        elements = await self.element_detector.detect(component.reference_path)
        print(f"  [1.0] Detected {len(elements)} elements")

        # Store elements on component for later phases
        component.detected_elements = elements

        # 1. Load reference image
        img = Image.open(component.reference_path)
        width, height = img.size

        # 2. Send to vision model with element-informed division prompt
        prompt = self._build_division_prompt(
            {"width": width, "height": height}, elements
        )

        response = await self.client.vision_analyze(
            prompt=prompt,
            images=[component.reference_path],
            temperature=0.2,  # Lower for consistent structure
        )

        # 3. Parse response into bounding boxes
        raw_regions = self._parse_division_response(response.content)

        # 3a. Rescale region bboxes from 0-1000 normalized if needed
        raw_regions = self._rescale_regions_if_normalized(
            raw_regions, width, height
        )

        # 3b. Normalize region names (deduplicate, canonicalize)
        raw_regions = self._normalize_region_names(raw_regions)

        # 4. Apply division correction rules (now element-aware)
        corrected_regions = self._apply_division_correction(
            raw_regions, width, height, elements
        )

        # 5. Create Region objects with element assignments
        regions = []
        for i, (name, bbox) in enumerate(corrected_regions):
            region_elements = self.element_detector.filter_elements_for_region(
                elements, bbox
            )
            element_ids = [e.id for e in region_elements]
            region = Region(
                id=f"region_{i}", name=name, bbox=bbox, element_ids=element_ids
            )
            regions.append(region)

        # 6. Tighten regions: reassign orphans, drop empties, fit to elements
        regions = self._tighten_regions(regions, elements, width, height)

        # 7. Resolve overlaps created by tightening
        regions = self._resolve_post_tighten_overlaps(
            regions, elements, width, height
        )

        for i, region in enumerate(regions):
            print(f"  [1.1] Region {i}: {region.name} with {len(region.element_ids)} elements")

        return regions

    def _build_division_prompt(
        self, image_info: dict, elements: List[DetectedElement]
    ) -> str:
        """Build element-informed prompt for UI Division."""
        # Format element list for prompt
        element_list = []
        for i, e in enumerate(elements[:50]):  # Limit to avoid token overflow
            element_list.append(
                f"  {i}. {e.type} at ({e.bbox[0]}, {e.bbox[1]}) size {e.bbox[2]}x{e.bbox[3]}"
            )

        elements_str = "\n".join(element_list)
        if len(elements) > 50:
            elements_str += f"\n  ... and {len(elements) - 50} more elements"

        return f"""Analyze this UI screenshot and group the detected elements into 3-10 semantic regions.

DETECTED ELEMENTS (with pixel bounding boxes):
{elements_str}

Your task: Group these elements into semantic regions. Each region should contain elements that functionally belong together.

Semantic region types:
- navigation: header elements, menu items, logo, search bar (top of page)
- hero-section: main headline, primary CTA, key value prop (below nav)
- content-grid: repeating cards, product lists, item grids
- sidebar: side panel with filters, secondary nav, widgets
- filters-section: filter controls, checkboxes, dropdowns
- form-section: input fields, submit buttons, form areas
- media-section: image galleries, video players, media grids
- tabs-section: tabbed navigation interface
- footer: bottom links, copyright, contact info

CRITICAL RULES:
1. Target 3-10 regions (fewer = too coarse, more = too granular)
2. Regions must be mutually exclusive (no overlapping areas)
3. Regions should tile the page vertically with minimal gaps
4. DO NOT cut through elements - boundaries should respect element bboxes
5. Group related elements together (e.g., all header items in "navigation")
6. Use semantic names, not positional ("navigation" not "top-section")
7. All bounding box coordinates must use 0-1000 normalized scale

Gap handling:
- Small gaps (< 30px) between regions are normal (dividers, spacing)
- Large gaps (> 5% of page height) should be their own region or assigned to nearest
- If you see a clear divider line, respect it as a boundary

Coordinate system: Use 0-1000 NORMALIZED coordinates for all bboxes.
  x=0 is left edge, x=1000 is right edge
  y=0 is top edge, y=1000 is bottom edge

Output format - JSON only, no markdown:
{{
  "regions": [
    {{
      "name": "navigation",
      "bbox": {{"x": 0, "y": 0, "width": 1000, "height": 50}},
      "element_indices": [0, 1, 2]
    }},
    {{
      "name": "hero-section",
      "bbox": {{"x": 0, "y": 50, "width": 1000, "height": 300}},
      "element_indices": [3, 4, 5, 6]
    }}
  ]
}}

Include "element_indices" to show which detected elements belong to each region.

Image dimensions: {image_info["width"]}x{image_info["height"]}
Total elements: {len(elements)}

Respond with valid JSON only."""

    def _parse_division_response(
        self, content: str
    ) -> List[Tuple[str, Tuple[int, int, int, int]]]:
        """Parse vision model response into region list."""
        # Try to extract JSON from response
        # Handle both raw JSON and markdown-wrapped JSON
        json_match = re.search(r"\{[\s\S]*\}", content)
        if not json_match:
            raise ValueError(f"No JSON found in response: {content[:200]}")

        json_str = json_match.group()

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            # Try to fix common JSON issues
            json_str = self._fix_json_issues(json_str)
            try:
                data = json.loads(json_str)
            except json.JSONDecodeError:
                raise ValueError(
                    f"Invalid JSON in response: {e}\nContent: {content[:500]}"
                )

        regions = []
        for r in data.get("regions", []):
            name = r.get("name", "unnamed")
            bbox_data = r.get("bbox", r.get("bounding_box", {}))

            # Handle different bbox formats
            if isinstance(bbox_data, list) and len(bbox_data) == 4:
                bbox = tuple(bbox_data)
            elif isinstance(bbox_data, dict):
                x = bbox_data.get("x", 0)
                y = bbox_data.get("y", 0)
                w = bbox_data.get("width", bbox_data.get("w", 100))
                h = bbox_data.get("height", bbox_data.get("h", 100))
                bbox = (x, y, w, h)
            else:
                bbox = (0, 0, 100, 100)  # Default fallback

            regions.append((name, bbox))

        return regions

    def _rescale_regions_if_normalized(
        self,
        regions: List[Tuple[str, Tuple[int, int, int, int]]],
        img_width: int,
        img_height: int,
    ) -> List[Tuple[str, Tuple[int, int, int, int]]]:
        """
        Rescale region bboxes from 0-1000 normalized coordinates to
        actual pixel coordinates if needed.

        Same heuristic as ElementDetector: if all right/bottom edges
        are ≤ 1010, assume 0-1000 normalized coords.
        """
        if not regions:
            return regions

        max_right = max(b[0] + b[2] for _, b in regions)
        max_bottom = max(b[1] + b[3] for _, b in regions)

        if max_right <= 1010 and max_bottom <= 1010:
            sx = img_width / 1000.0
            sy = img_height / 1000.0
            return [
                (name, (round(x * sx), round(y * sy), round(w * sx), round(h * sy)))
                for name, (x, y, w, h) in regions
            ]
        return regions

    # Canonical region names — map common LLM variations to stable names
    _NAME_ALIASES = {
        "nav": "navigation",
        "navbar": "navigation",
        "header": "navigation",
        "top-bar": "navigation",
        "menu": "navigation",
        "hero": "hero-section",
        "banner": "hero-section",
        "main-content": "content-section",
        "content": "content-section",
        "body": "content-section",
        "cards": "content-grid",
        "card-grid": "content-grid",
        "product-grid": "content-grid",
        "products": "content-grid",
        "items": "content-grid",
        "sidebar": "sidebar",
        "side-panel": "sidebar",
        "filters": "filters-section",
        "filter": "filters-section",
        "form": "form-section",
        "input-section": "form-section",
        "media": "media-section",
        "gallery": "media-section",
        "images": "media-section",
        "tabs": "tabs-section",
        "tab-bar": "tabs-section",
        "footer": "footer",
        "bottom": "footer",
    }

    def _normalize_region_names(
        self, regions: List[Tuple[str, Tuple[int, int, int, int]]]
    ) -> List[Tuple[str, Tuple[int, int, int, int]]]:
        """
        Normalize and deduplicate region names.

        1. Lowercase + strip whitespace
        2. Map common LLM name variations to canonical names
        3. Append -2, -3, ... suffix for any remaining duplicates
        """
        normalized = []
        for name, bbox in regions:
            clean = name.strip().lower().replace(" ", "-").replace("_", "-")
            clean = self._NAME_ALIASES.get(clean, clean)
            normalized.append((clean, bbox))

        # Deduplicate: append suffix for repeated names
        seen: dict[str, int] = {}
        deduped = []
        for name, bbox in normalized:
            if name in seen:
                seen[name] += 1
                deduped.append((f"{name}-{seen[name]}", bbox))
            else:
                seen[name] = 1
                deduped.append((name, bbox))

        return deduped

    def _fix_json_issues(self, json_str: str) -> str:
        """Fix common JSON formatting issues from LLM responses."""
        # Remove trailing commas
        json_str = re.sub(r",\s*}", "}", json_str)
        json_str = re.sub(r",\s*]", "]", json_str)

        # Fix single quotes to double quotes
        json_str = json_str.replace("'", '"')

        return json_str

    def _apply_division_correction(
        self,
        regions: List[Tuple[str, Tuple[int, int, int, int]]],
        img_width: int,
        img_height: int,
        elements: Optional[List[DetectedElement]] = None,
    ) -> List[Tuple[str, Tuple[int, int, int, int]]]:
        """
        Apply correction rules to ensure region quality.

        Now element-aware: uses element counts for tiebreakers.
        Gap handling: small gaps (< 5% height) are filled, large gaps create new regions.
        """
        if not regions:
            return regions

        # 1. Filter out invalid regions
        valid_regions = []
        for name, bbox in regions:
            x, y, w, h = bbox
            # Skip zero-size regions
            if w <= 0 or h <= 0:
                continue
            # Skip regions outside image bounds
            if x >= img_width or y >= img_height:
                continue
            # Clamp to image bounds
            x = max(0, x)
            y = max(0, y)
            w = min(w, img_width - x)
            h = min(h, img_height - y)
            valid_regions.append((name, (x, y, w, h)))

        # 2. Merge overlapping regions (element-aware tiebreaker)
        merged = self._merge_overlapping_regions(valid_regions, elements)

        # 3. Ensure vertical tiling (smart gap handling)
        merged = self._ensure_vertical_tiling(merged, img_width, img_height)

        # 4. Enforce min/max region count
        if len(merged) > self.config.target_regions_max:
            # Too many regions - merge adjacent ones (prefer keeping larger)
            merged = self._merge_excess_regions(
                merged, self.config.target_regions_max, elements
            )

        return merged

    def _merge_overlapping_regions(
        self,
        regions: List[Tuple[str, Tuple[int, int, int, int]]],
        elements: Optional[List[DetectedElement]] = None,
    ) -> List[Tuple[str, Tuple[int, int, int, int]]]:
        """
        Merge regions that overlap significantly.

        Tiebreaker: Keep region with more elements (if element data available),
        otherwise keep larger region.
        """
        if not regions:
            return regions

        # Helper to count elements in a bbox
        def count_elements_in_bbox(bbox):
            if not elements:
                return 0
            bx, by, bw, bh = bbox
            count = 0
            for e in elements:
                ex, ey, ew, eh = e.bbox
                # Check if element center is inside
                ecx, ecy = ex + ew / 2, ey + eh / 2
                if (bx <= ecx <= bx + bw) and (by <= ecy <= by + bh):
                    count += 1
            return count

        # Sort by y position (top to bottom)
        sorted_regions = sorted(regions, key=lambda r: (r[1][1], r[1][0]))

        merged = []
        for name, bbox in sorted_regions:
            x, y, w, h = bbox

            # Check overlap with existing merged regions
            overlaps = []
            for i, (m_name, m_bbox) in enumerate(merged):
                mx, my, mw, mh = m_bbox

                # Calculate intersection
                ix = max(x, mx)
                iy = max(y, my)
                iw = min(x + w, mx + mw) - ix
                ih = min(y + h, my + mh) - iy

                if iw > 0 and ih > 0:
                    overlap_area = iw * ih
                    area1 = w * h
                    area2 = mw * mh
                    min_area = min(area1, area2)

                    # If overlap > 50% of smaller region, consider merging
                    if overlap_area > 0.5 * min_area:
                        overlaps.append(i)

            if overlaps:
                # Merge with first overlapping region
                m_idx = overlaps[0]
                m_name, m_bbox = merged[m_idx]
                mx, my, mw, mh = m_bbox

                # Union of bboxes
                ux = min(x, mx)
                uy = min(y, my)
                uw = max(x + w, mx + mw) - ux
                uh = max(y + h, my + mh) - uy

                # Tiebreaker: Keep name of region with more elements
                elem_count_new = count_elements_in_bbox(bbox)
                elem_count_existing = count_elements_in_bbox(m_bbox)

                if elem_count_new > elem_count_existing:
                    new_name = name
                elif elem_count_existing > elem_count_new:
                    new_name = m_name
                else:
                    # Tie: keep larger region's name
                    area_new = w * h
                    area_existing = mw * mh
                    new_name = name if area_new > area_existing else m_name

                merged[m_idx] = (new_name, (ux, uy, uw, uh))
            else:
                merged.append((name, bbox))

        return merged

    _MAX_GAP_FILL_PX = 20

    def _ensure_vertical_tiling(
        self,
        regions: List[Tuple[str, Tuple[int, int, int, int]]],
        img_width: int,
        img_height: int,
    ) -> List[Tuple[str, Tuple[int, int, int, int]]]:
        """
        Ensure regions tile the page vertically with small gaps filled.

        Only gaps <= _MAX_GAP_FILL_PX are absorbed into the nearest
        region.  Larger gaps are left as-is — they represent genuine
        whitespace and should not distort region bounds.
        """
        if not regions:
            return [("full-page", (0, 0, img_width, img_height))]

        sorted_regions = sorted(regions, key=lambda r: r[1][1])

        filled = []
        current_y = 0

        for name, bbox in sorted_regions:
            x, y, w, h = bbox

            if y > current_y:
                gap_height = y - current_y

                if gap_height <= self._MAX_GAP_FILL_PX and filled:
                    prev_name, prev_bbox = filled[-1]
                    px, py, pw, ph = prev_bbox
                    filled[-1] = (prev_name, (px, py, pw, ph + gap_height))
                elif gap_height > self._MAX_GAP_FILL_PX:
                    print(
                        f"  ⚠ Large gap ({gap_height}px) at y={current_y}, leaving unfilled"
                    )

            filled.append((name, bbox))
            current_y = max(current_y, y + h)

        if current_y < img_height:
            gap_height = img_height - current_y
            if filled and gap_height <= self._MAX_GAP_FILL_PX:
                last_name, last_bbox = filled[-1]
                lx, ly, lw, lh = last_bbox
                filled[-1] = (last_name, (lx, ly, lw, lh + gap_height))
            elif gap_height > self._MAX_GAP_FILL_PX:
                print(
                    f"  ⚠ Large gap ({gap_height}px) at page bottom, leaving unfilled"
                )

        return filled

    def _merge_excess_regions(
        self,
        regions: List[Tuple[str, Tuple[int, int, int, int]]],
        max_count: int,
        elements: Optional[List[DetectedElement]] = None,
    ) -> List[Tuple[str, Tuple[int, int, int, int]]]:
        """
        Merge adjacent small regions if we have too many.

        Prefers merging regions with fewer elements.
        """

        # Helper to count elements
        def count_in_bbox(bbox):
            if not elements:
                return 0
            bx, by, bw, bh = bbox
            return sum(
                1
                for e in elements
                if (bx <= e.bbox[0] + e.bbox[2] / 2 <= bx + bw)
                and (by <= e.bbox[1] + e.bbox[3] / 2 <= by + bh)
            )

        while len(regions) > max_count:
            # Find smallest region (by area, weighted by element count)
            def region_score(i):
                name, bbox = regions[i]
                area = bbox[2] * bbox[3]
                elem_count = count_in_bbox(bbox)
                # Prefer merging regions with fewer elements
                return area / (elem_count + 1)  # +1 to avoid div by zero

            smallest_idx = min(range(len(regions)), key=region_score)

            # Find nearest neighbor to merge with
            smallest_name, smallest_bbox = regions[smallest_idx]
            sx, sy, sw, sh = smallest_bbox
            smallest_center = (sx + sw / 2, sy + sh / 2)

            nearest_idx = None
            nearest_dist = float("inf")

            for i, (name, bbox) in enumerate(regions):
                if i == smallest_idx:
                    continue
                x, y, w, h = bbox
                center = (x + w / 2, y + h / 2)
                dist = (
                    (center[0] - smallest_center[0]) ** 2
                    + (center[1] - smallest_center[1]) ** 2
                ) ** 0.5

                if dist < nearest_dist:
                    nearest_dist = dist
                    nearest_idx = i

            if nearest_idx is not None:
                # Merge with nearest
                nearest_name, nearest_bbox = regions[nearest_idx]
                nx, ny, nw, nh = nearest_bbox

                # Union bbox
                ux = min(sx, nx)
                uy = min(sy, ny)
                uw = max(sx + sw, nx + nw) - ux
                uh = max(sy + sh, ny + nh) - uy

                # Tiebreaker: Keep name of region with more elements
                elem_count_small = count_in_bbox(smallest_bbox)
                elem_count_near = count_in_bbox(nearest_bbox)

                if elem_count_small > elem_count_near:
                    new_name = smallest_name
                else:
                    new_name = nearest_name

                # Replace nearest with merged, remove smallest
                regions[nearest_idx] = (new_name, (ux, uy, uw, uh))
                regions.pop(smallest_idx)
            else:
                break

        return regions

    # Padding (px) added around element-derived region bboxes so that
    # region crops include enough visual context for downstream models.
    _REGION_PAD = 30

    def _tighten_regions(
        self,
        regions: List[Region],
        elements: List[DetectedElement],
        img_width: int,
        img_height: int,
    ) -> List[Region]:
        """
        Post-process regions to fix common model issues:

        1. Assign orphan elements (not in any region) to nearest region
        2. Drop regions with 0 elements
        3. Recompute each region's bbox as the tight union of its
           element bboxes + padding, so crops hug actual content
           instead of being arbitrary full-width strips
        """
        elem_by_id = {e.id: e for e in elements}

        # 1. Find orphan elements and assign to nearest region
        assigned = set()
        for r in regions:
            assigned.update(r.element_ids)

        orphans = [e for e in elements if e.id not in assigned]
        for elem in orphans:
            ecx = elem.bbox[0] + elem.bbox[2] / 2
            ecy = elem.bbox[1] + elem.bbox[3] / 2
            best_region = None
            best_dist = float("inf")
            for r in regions:
                rx, ry, rw, rh = r.bbox
                rcx = rx + rw / 2
                rcy = ry + rh / 2
                dist = ((ecx - rcx) ** 2 + (ecy - rcy) ** 2) ** 0.5
                if dist < best_dist:
                    best_dist = dist
                    best_region = r
            if best_region is not None:
                best_region.element_ids.append(elem.id)

        # 2. Drop regions with 0 elements
        regions = [r for r in regions if r.element_ids]

        # 3. Tighten each region's bbox to its elements + padding
        for r in regions:
            self._retighten_single_region(r, elem_by_id, img_width, img_height)

        # Re-sort by y position and reassign IDs
        regions.sort(key=lambda r: r.bbox[1])
        for i, r in enumerate(regions):
            r.id = f"region_{i}"

        return regions

    def _retighten_single_region(
        self,
        region: Region,
        elem_by_id: dict,
        img_width: int,
        img_height: int,
    ) -> None:
        """Recompute a single region's bbox from its element bboxes + padding."""
        bboxes = [
            elem_by_id[eid].bbox
            for eid in region.element_ids
            if eid in elem_by_id
        ]
        if not bboxes:
            return
        pad = self._REGION_PAD
        min_x = min(b[0] for b in bboxes)
        min_y = min(b[1] for b in bboxes)
        max_x = max(b[0] + b[2] for b in bboxes)
        max_y = max(b[1] + b[3] for b in bboxes)
        min_x = max(0, min_x - pad)
        min_y = max(0, min_y - pad)
        max_x = min(img_width, max_x + pad)
        max_y = min(img_height, max_y + pad)
        region.bbox = (min_x, min_y, max_x - min_x, max_y - min_y)

    def _resolve_post_tighten_overlaps(
        self,
        regions: List[Region],
        elements: List[DetectedElement],
        img_width: int,
        img_height: int,
    ) -> List[Region]:
        """
        Resolve region overlaps that were created by _tighten_regions.

        Two cases:
        1. Full containment: smaller region is inside larger — remove
           the smaller region's elements from the larger, retighten the larger.
        2. Partial overlap (IoU > 0.3): split disputed elements by closest
           centroid to region center, retighten both.
        """
        elem_by_id = {e.id: e for e in elements}

        changed = True
        while changed:
            changed = False
            for i in range(len(regions)):
                for j in range(i + 1, len(regions)):
                    ri, rj = regions[i], regions[j]
                    # Determine which is smaller by area
                    area_i = ri.bbox[2] * ri.bbox[3]
                    area_j = rj.bbox[2] * rj.bbox[3]
                    if area_i < area_j:
                        r_small, r_big = ri, rj
                    else:
                        r_small, r_big = rj, ri

                    if self._bbox_fully_contains(r_big.bbox, r_small.bbox):
                        # Full containment: remove small's elements from big
                        small_ids = set(r_small.element_ids)
                        old_len = len(r_big.element_ids)
                        r_big.element_ids = [
                            eid for eid in r_big.element_ids
                            if eid not in small_ids
                        ]
                        if len(r_big.element_ids) < old_len:
                            self._retighten_single_region(
                                r_big, elem_by_id, img_width, img_height
                            )
                            changed = True
                            break
                    elif self._bbox_iou(ri.bbox, rj.bbox) > 0.3:
                        # Partial overlap: split disputed elements by centroid
                        old_ids_i = set(ri.element_ids)
                        old_ids_j = set(rj.element_ids)
                        self._split_disputed_elements(
                            ri, rj, elem_by_id, img_width, img_height
                        )
                        if set(ri.element_ids) != old_ids_i or set(rj.element_ids) != old_ids_j:
                            changed = True
                            break
                if changed:
                    break

        # Drop regions with 0 elements, re-sort, reassign IDs
        regions = [r for r in regions if r.element_ids]
        regions.sort(key=lambda r: r.bbox[1])
        for i, r in enumerate(regions):
            r.id = f"region_{i}"
        return regions

    @staticmethod
    def _bbox_fully_contains(
        outer: Tuple[int, int, int, int],
        inner: Tuple[int, int, int, int],
    ) -> bool:
        """Check if outer bbox fully contains inner bbox."""
        ox, oy, ow, oh = outer
        ix, iy, iw, ih = inner
        return ix >= ox and iy >= oy and ix + iw <= ox + ow and iy + ih <= oy + oh

    @staticmethod
    def _bbox_iou(
        a: Tuple[int, int, int, int],
        b: Tuple[int, int, int, int],
    ) -> float:
        """Compute intersection-over-union of two bboxes."""
        ax, ay, aw, ah = a
        bx, by, bw, bh = b
        ix = max(ax, bx)
        iy = max(ay, by)
        ix2 = min(ax + aw, bx + bw)
        iy2 = min(ay + ah, by + bh)
        if ix2 <= ix or iy2 <= iy:
            return 0.0
        inter = (ix2 - ix) * (iy2 - iy)
        union = aw * ah + bw * bh - inter
        return inter / union if union > 0 else 0.0

    def _split_disputed_elements(
        self,
        r1: Region,
        r2: Region,
        elem_by_id: dict,
        img_width: int,
        img_height: int,
    ) -> None:
        """Split elements in the overlap zone by closest centroid to region center."""
        # Find elements that appear in both regions
        ids_1 = set(r1.element_ids)
        ids_2 = set(r2.element_ids)
        shared = ids_1 & ids_2
        if not shared:
            return

        c1x = r1.bbox[0] + r1.bbox[2] / 2
        c1y = r1.bbox[1] + r1.bbox[3] / 2
        c2x = r2.bbox[0] + r2.bbox[2] / 2
        c2y = r2.bbox[1] + r2.bbox[3] / 2

        for eid in shared:
            elem = elem_by_id.get(eid)
            if not elem:
                continue
            ecx = elem.bbox[0] + elem.bbox[2] / 2
            ecy = elem.bbox[1] + elem.bbox[3] / 2
            d1 = ((ecx - c1x) ** 2 + (ecy - c1y) ** 2) ** 0.5
            d2 = ((ecx - c2x) ** 2 + (ecy - c2y) ** 2) ** 0.5
            if d1 <= d2:
                r2.element_ids = [e for e in r2.element_ids if e != eid]
            else:
                r1.element_ids = [e for e in r1.element_ids if e != eid]

        self._retighten_single_region(r1, elem_by_id, img_width, img_height)
        self._retighten_single_region(r2, elem_by_id, img_width, img_height)

    def _centroid_distance(
        self, bbox1: Tuple[int, int, int, int], bbox2: Tuple[int, int, int, int]
    ) -> float:
        """Compute centroid distance between two bboxes."""
        x1, y1, w1, h1 = bbox1
        x2, y2, w2, h2 = bbox2

        c1x = x1 + w1 / 2
        c1y = y1 + h1 / 2
        c2x = x2 + w2 / 2
        c2y = y2 + h2 / 2

        return ((c1x - c2x) ** 2 + (c1y - c2y) ** 2) ** 0.5
