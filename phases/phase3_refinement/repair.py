"""
Phase 3.4: Repair

Two repair strategies:
  - FullPageRepair: send full HTML + reference + screenshot to VLLM for
    holistic repair. Fixes global issues (border-radius, font sizes,
    container proportions) and can edit <style> blocks.
  - TargetedRepair (legacy): per-element fragment repair via BeautifulSoup.
"""

import logging
import re
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from bs4 import BeautifulSoup, Tag

from storage.component import Component, ComponentTree
from llm_client import DualProviderClient, Message
from config import Config
from utils.dom import DOMNode

_log = logging.getLogger("pipeline.repair")

# Only repair the top-N highest-severity components per iteration.
# Repairing too many at once (25+) causes cascading breakage.
MAX_REPAIRS_PER_ITERATION = 5

# Max issues to include in the full-page repair prompt
MAX_ISSUE_SUMMARY = 15

_SEVERITY_RANK = {"major": 0, "minor": 1, "none": 2}


# ======================================================================
# Full-page repair (primary)
# ======================================================================


class FullPageRepair:
    """
    Holistic full-page repair: sends the complete HTML + reference image +
    current screenshot + issue summary to the VLLM codegen model, gets back
    corrected HTML.

    This replaces per-element TargetedRepair to fix:
      1. ID mismatch between detected elements and tree elements
      2. Inability to fix <style> block CSS rules
      3. Lack of holistic/cross-element repair context
    """

    def __init__(self, client: DualProviderClient, config: Config):
        self.client = client
        self.config = config

    async def repair(
        self,
        component: Component,
        issues: List[Dict],
        comparison_log: List[Dict],
        screenshot_path: Path,
    ) -> str:
        """
        Repair the full HTML page by sending it with both images to VLLM.

        Args:
            component: Component with html_path and reference_path.
            issues: Issue dicts from ElementCloseupComparator.
            comparison_log: Per-element SSIM comparison data.
            screenshot_path: Path to the current rendered screenshot.

        Returns:
            Repaired full-page HTML string, or original if repair fails.
        """
        if not component.html_path:
            raise ValueError("No HTML file to repair")

        original_html = component.html_path.read_text(encoding="utf-8")

        issue_summary = self._build_issue_summary(issues, comparison_log)
        prompt = self._build_repair_prompt(original_html, issue_summary)

        images = [component.reference_path, screenshot_path]

        try:
            response = await self.client.codegen_from_vision(
                prompt=prompt,
                images=images,
                temperature=0.3,
            )

            repaired_html = self._extract_html(response.content)

            if not repaired_html:
                _log.warning("Could not extract HTML from repair response")
                return original_html

            if not self._validate_repair(original_html, repaired_html):
                _log.warning("Repaired HTML failed validation, keeping original")
                return original_html

            _log.info(
                f"  Full-page repair: {len(original_html)} → "
                f"{len(repaired_html)} chars"
            )
            return repaired_html

        except Exception as e:
            _log.error(f"Full-page repair failed: {e}")
            return original_html

    def _build_issue_summary(
        self, issues: List[Dict], comparison_log: List[Dict]
    ) -> str:
        """Format the worst issues into a concise textual summary.

        Includes element bbox positions so the repair model knows where
        each element SHOULD be on the page.
        """
        lines = []

        # Use issues (from VLLM analysis) first — they have descriptions
        for issue in issues[:MAX_ISSUE_SUMMARY]:
            severity = issue.get("severity", "minor").upper()
            comp_id = issue.get("component_id", "?")
            issue_type = issue.get("issue_type", "?")
            desc = issue.get("description", "")[:120]
            ssim = issue.get("ssim", 0.0)
            bbox = issue.get("bbox")
            pos_hint = ""
            if bbox:
                pos_hint = f" [expected at ({bbox[0]},{bbox[1]}) {bbox[2]}x{bbox[3]}px]"
            lines.append(
                f"- [{severity}] {comp_id} ({issue_type}, SSIM={ssim:.3f}){pos_hint}: {desc}"
            )

        # Fill remaining slots from comparison_log if we have room
        seen_ids = {i.get("component_id") for i in issues[:MAX_ISSUE_SUMMARY]}
        for entry in comparison_log:
            if len(lines) >= MAX_ISSUE_SUMMARY:
                break
            if entry["element_id"] in seen_ids:
                continue
            if entry["ssim"] >= self.config.per_component_threshold:
                continue
            bbox = entry.get("bbox", [])
            pos_hint = ""
            if bbox:
                pos_hint = f" [expected at ({bbox[0]},{bbox[1]}) {bbox[2]}x{bbox[3]}px]"
            lines.append(
                f"- [LOW_SSIM] {entry['element_id']} "
                f"({entry['element_type']}, SSIM={entry['ssim']:.3f}){pos_hint}"
            )

        return "\n".join(lines) if lines else "No specific issues identified."

    def _build_repair_prompt(self, full_html: str, issue_summary: str) -> str:
        """Build the full-page repair prompt."""
        return f"""You are fixing a cloned UI page. Image 1 is the REFERENCE (target). Image 2 is the CURRENT RENDERING of the HTML below.

Fix the HTML so the rendering matches the reference. Fix issues in this priority order:

PRIORITY 1 — Layout & Position (fix these FIRST):
- Container positions: left/top values must match where elements appear in the reference
- Container dimensions: width/height must match the reference proportions
- Element stacking: cards should not overlap incorrectly; z-index order must match

PRIORITY 2 — Structural appearance:
- Border-radius, shadows, background colors/opacity
- Font sizes, weight, and text alignment
- Spacing and padding within containers

PRIORITY 3 — Fine details:
- Exact color matching
- Icon appearance
- Minor alignment tweaks

IDENTIFIED ISSUES:
{issue_summary}

CURRENT HTML:
```html
{full_html}
```

RULES:
1. Output the COMPLETE fixed HTML page (DOCTYPE through </html>)
2. Fix CSS in the <style> block AND/OR inline styles as needed
3. Preserve all data-elem-id attributes exactly as they are
4. No external URLs, no Tailwind, plain CSS only
5. Do NOT remove or add HTML elements — only fix styling and layout
6. Keep the same document structure
7. Compare the two images carefully — if a container is in the wrong position, fix its left/top/width/height FIRST

Output ONLY the complete HTML. No explanation."""

    def _extract_html(self, content: str) -> Optional[str]:
        """Extract HTML from the model's response."""
        # Try code fences first
        code_match = re.search(r"```html\s*([\s\S]*?)```", content, re.IGNORECASE)
        if code_match:
            return code_match.group(1).strip()

        code_match = re.search(r"```\s*([\s\S]*?)```", content)
        if code_match:
            return code_match.group(1).strip()

        # Look for a full HTML document
        doc_match = re.search(
            r"(<!DOCTYPE[\s\S]*</html>)", content, re.IGNORECASE
        )
        if doc_match:
            return doc_match.group(1).strip()

        # Look for any HTML tags
        html_match = re.search(r"<[^>]+>.*</[^>]+>", content, re.DOTALL)
        if html_match:
            return content[html_match.start() : html_match.end()]

        # If the whole thing looks like HTML, return it
        if "<" in content and ">" in content:
            return content.strip()

        return None

    def _validate_repair(self, original_html: str, repaired_html: str) -> bool:
        """
        Validate that the repaired HTML is structurally sound.

        Rejects:
          - Truncated responses (missing </html>)
          - Massive size changes (>3x growth or <0.3x shrink)
          - Loss of most data-elem-id attributes
        """
        # Must have closing html tag
        if "</html>" not in repaired_html.lower():
            _log.warning("Repair validation: missing </html>")
            return False

        # Size sanity check
        orig_len = len(original_html)
        repair_len = len(repaired_html)
        if repair_len > orig_len * 3:
            _log.warning(
                f"Repair validation: output too large "
                f"({repair_len} vs {orig_len})"
            )
            return False
        if repair_len < orig_len * 0.3:
            _log.warning(
                f"Repair validation: output too small "
                f"({repair_len} vs {orig_len})"
            )
            return False

        # Check data-elem-id preservation
        orig_ids = set(re.findall(r'data-elem-id="([^"]+)"', original_html))
        repair_ids = set(re.findall(r'data-elem-id="([^"]+)"', repaired_html))
        if orig_ids and len(repair_ids) < len(orig_ids) * 0.5:
            _log.warning(
                f"Repair validation: lost data-elem-id attrs "
                f"({len(repair_ids)} vs {len(orig_ids)})"
            )
            return False

        return True


class TargetedRepair:
    """
    Repairs specific components without rewriting the entire page.

    Strategy:
      1. Group issues by component ID, keep only top-N by severity.
      2. For each component with issues:
         a. Parse the full HTML with BeautifulSoup.
         b. Locate the component's element by data-elem-id attribute.
         c. Send the element's HTML + issue list + region crop to
            the vision model for context-aware repair.
         d. Parse the model's repaired HTML.
         e. Replace the old element in the BeautifulSoup tree.
      3. Serialize the modified tree back to an HTML string.
    """

    def __init__(self, client: DualProviderClient, config: Config):
        self.client = client
        self.config = config

    async def repair(
        self,
        component: Component,
        issues: List[Dict],
        dom_tree: DOMNode,
        closeup_context: Optional[List[Dict]] = None,
    ) -> str:
        """
        Repair identified issues in the HTML.

        Args:
            component: The component being refined (holds html_path and tree).
            issues: List of issue dicts from VisualComparator or ElementCloseupComparator.
            dom_tree: The rendered DOM tree (used for position context).
            closeup_context: Optional per-element comparison log from
                ElementCloseupComparator.  When provided, the repair prompt
                includes element-level SSIM data for better context.

        Returns:
            Modified full-page HTML as a string.
        """
        if not component.html_path:
            raise ValueError("No HTML file to repair")

        full_html = component.html_path.read_text(encoding="utf-8")

        # Sort issues so major ones are repaired first
        sorted_issues = sorted(
            issues,
            key=lambda i: _SEVERITY_RANK.get(i.get("severity", "none"), 2),
        )

        # Group issues by component ID
        issues_by_component: Dict[str, List[Dict]] = {}
        for issue in sorted_issues:
            comp_id = issue.get("component_id", "unknown")
            if comp_id not in issues_by_component:
                issues_by_component[comp_id] = []
            issues_by_component[comp_id].append(issue)

        # Limit to top-N components to avoid cascading breakage
        repair_ids = list(issues_by_component.keys())[:MAX_REPAIRS_PER_ITERATION]

        print(
            f"  Repairing {len(repair_ids)} of "
            f"{len(issues_by_component)} components with issues..."
        )

        # Apply repairs sequentially so earlier fixes are visible to later ones
        for comp_id in repair_ids:
            comp_issues = issues_by_component[comp_id]
            print(f"    Repairing {comp_id} ({len(comp_issues)} issues)...")

            # Locate the component's HTML element via BeautifulSoup
            component_html, selector_type, selector_value = (
                self._extract_component_html(full_html, comp_id, component)
            )

            if not component_html:
                print(f"      Could not find component HTML for {comp_id}")
                continue

            # Gather visual context images: prefer closeup crops,
            # fall back to region crop
            context_images = self._gather_context_images(
                comp_id, comp_issues, closeup_context, component
            )

            # Ask the model to repair this fragment
            prompt = self._build_repair_prompt(
                component_html, comp_issues, comp_id,
                closeup_context=closeup_context,
            )

            try:
                if context_images:
                    response = await self.client.vision_analyze(
                        prompt=prompt,
                        images=context_images,
                        temperature=0.3,
                    )
                else:
                    response = await self.client.code_complete(
                        messages=[Message.text("user", prompt)], temperature=0.3
                    )

                repaired_html = self._extract_repaired_html(response.content)

                if repaired_html:
                    full_html = self._replace_component_html(
                        full_html, selector_type, selector_value, repaired_html
                    )
                    print(f"      Repaired")
                else:
                    print(f"      Could not extract repaired HTML from model response")

            except Exception as e:
                print(f"      Repair failed: {e}")
                continue

        return full_html

    # ------------------------------------------------------------------
    # HTML extraction via BeautifulSoup
    # ------------------------------------------------------------------

    def _extract_component_html(
        self, full_html: str, component_id: str, component: Component
    ) -> Tuple[Optional[str], str, str]:
        """
        Find and extract a specific component's HTML from the full page.

        Prioritises data-elem-id (unique per element) over class/tag
        selectors which often match the wrong element when multiple
        components share the same type.

        Returns:
            (html_string, selector_type, selector_value)
            selector_type is 'data-elem-id', 'class', 'id', or 'tag'.
            Returns (None, '', '') if not found.
        """
        if not component.tree:
            return None, "", ""

        elem = component.tree.elements.get(component_id)
        if not elem:
            return None, "", ""

        soup = BeautifulSoup(full_html, "html.parser")

        # Strategy 1 (preferred): Find by data-elem-id attribute — unique
        by_data_id = soup.find(attrs={"data-elem-id": component_id})
        if by_data_id:
            return str(by_data_id), "data-elem-id", component_id

        # Strategy 2: Find by class name matching element type
        class_name = elem.type.lower()
        candidates = soup.find_all(class_=class_name)
        if candidates:
            best = self._pick_best_candidate(candidates, elem.bbox)
            return str(best), "class", class_name

        # Strategy 3: Find by element ID
        elem_id = elem.id.lower().replace("_", "-")
        by_id = soup.find(id=elem_id)
        if by_id:
            return str(by_id), "id", elem_id

        # Strategy 4: Find by HTML tag matching the semantic type
        tag = self._map_type_to_tag(elem.type)
        tag_candidates = soup.find_all(tag)
        if tag_candidates:
            best = self._pick_best_candidate(tag_candidates, elem.bbox)
            return str(best), "tag", tag

        return None, "", ""

    def _pick_best_candidate(
        self, candidates: list, expected_bbox: Tuple[int, int, int, int]
    ) -> Tag:
        """
        When multiple elements match, pick the one whose inline style
        dimensions are closest to the expected bounding box.

        Falls back to the first candidate if no style information exists.
        """
        if len(candidates) == 1:
            return candidates[0]

        ex, ey, ew, eh = expected_bbox
        best = candidates[0]
        best_diff = float("inf")

        for candidate in candidates:
            style = candidate.get("style", "")
            # Try to extract width/height from inline style
            w = self._parse_css_px(style, "width")
            h = self._parse_css_px(style, "height")

            if w is not None and h is not None:
                diff = abs(w - ew) + abs(h - eh)
                if diff < best_diff:
                    best_diff = diff
                    best = candidate

        return best

    @staticmethod
    def _parse_css_px(style_str: str, prop: str) -> Optional[int]:
        """Extract a pixel value from an inline style string."""
        match = re.search(rf"{prop}\s*:\s*(\d+)px", style_str, re.IGNORECASE)
        return int(match.group(1)) if match else None

    # ------------------------------------------------------------------
    # HTML replacement via BeautifulSoup
    # ------------------------------------------------------------------

    def _replace_component_html(
        self, full_html: str, selector_type: str, selector_value: str, new_html: str
    ) -> str:
        """
        Replace a component's HTML in the full page using BeautifulSoup.

        Locates the old element by selector, parses the new HTML, and
        swaps them. This is robust to nested tags, special characters,
        and minor HTML malformation.
        """
        soup = BeautifulSoup(full_html, "html.parser")

        # Find the target element
        target = None
        if selector_type == "data-elem-id":
            target = soup.find(attrs={"data-elem-id": selector_value})
        elif selector_type == "class":
            candidates = soup.find_all(class_=selector_value)
            if candidates:
                target = candidates[0]
        elif selector_type == "id":
            target = soup.find(id=selector_value)
        elif selector_type == "tag":
            candidates = soup.find_all(selector_value)
            if candidates:
                target = candidates[0]

        if not target:
            return full_html

        # Parse the repaired HTML fragment
        replacement = BeautifulSoup(new_html, "html.parser")

        # Swap: replace old element with repaired version
        target.replace_with(replacement)

        return str(soup)

    # ------------------------------------------------------------------
    # Region crop lookup
    # ------------------------------------------------------------------

    def _find_region_crop(
        self, component_id: str, component: Component
    ) -> Optional[Path]:
        """
        Find the region crop image that contains this component,
        so the repair model can see what the element should look like.
        """
        if not component.tree or not component.regions:
            return None

        elem = component.tree.elements.get(component_id)
        if not elem:
            return None

        # Walk up via parent_id to find which region owns this element
        current_id = component_id
        visited = set()
        while current_id and current_id not in visited:
            visited.add(current_id)
            for region in component.regions:
                if current_id in region.element_ids:
                    if region.crop_path and Path(region.crop_path).exists():
                        return Path(region.crop_path)
            parent = component.tree.elements.get(current_id)
            current_id = parent.parent_id if parent else None

        # Fallback: return any region crop whose bbox overlaps the element
        ex, ey, ew, eh = elem.bbox
        for region in component.regions:
            rx, ry, rw, rh = region.bbox
            if ex >= rx and ey >= ry and ex + ew <= rx + rw and ey + eh <= ry + rh:
                if region.crop_path and Path(region.crop_path).exists():
                    return Path(region.crop_path)

        return None

    # ------------------------------------------------------------------
    # Context image gathering
    # ------------------------------------------------------------------

    def _gather_context_images(
        self,
        comp_id: str,
        comp_issues: List[Dict],
        closeup_context: Optional[List[Dict]],
        component: Component,
    ) -> List[Path]:
        """
        Collect visual context images for the repair prompt.

        Prefers closeup ref crops from ElementCloseupComparator;
        falls back to the region crop.
        """
        images = []

        # Try closeup crops from issues (set by ElementCloseupComparator)
        for issue in comp_issues:
            ref_crop = issue.get("ref_crop")
            if ref_crop and Path(ref_crop).exists():
                images.append(Path(ref_crop))
                break  # One ref crop is enough for context

        # Fallback to region crop
        if not images:
            region_crop = self._find_region_crop(comp_id, component)
            if region_crop:
                images.append(region_crop)

        return images

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def _build_repair_prompt(
        self,
        component_html: str,
        issues: List[Dict],
        component_type: str,
        closeup_context: Optional[List[Dict]] = None,
    ) -> str:
        """Build prompt for targeted repair of a single component."""
        issues_text = "\n".join(
            [f"- [{i['severity'].upper()}] {i['description']}" for i in issues]
        )

        # Add element-level SSIM context if available
        context_block = ""
        if closeup_context:
            relevant = [
                e for e in closeup_context
                if e["ssim"] < self.config.per_component_threshold
            ][:5]
            if relevant:
                lines = []
                for e in relevant:
                    lines.append(
                        f"  - {e['element_type']} ({e['element_id']}): "
                        f"SSIM={e['ssim']:.3f} at ({e['bbox'][0]},{e['bbox'][1]})"
                    )
                context_block = (
                    "\nElement-level comparison (worst scoring):\n"
                    + "\n".join(lines)
                    + "\n"
                )

        return f"""Repair this {component_type} component HTML.
Look at the attached reference image to see what this component should look like.

Current HTML:
```html
{component_html}
```

Issues to fix:
{issues_text}
{context_block}
Instructions:
1. Make ONLY the changes needed to fix these specific issues
2. Preserve all other structure and styling
3. Preserve the data-elem-id attribute on the root element
4. Return ONLY the repaired HTML for this component
5. Do not add comments or explanations
6. Keep the same root element tag and classes if possible
7. Do NOT use external URLs — use background-color placeholders for images

Output just the HTML:
"""

    # ------------------------------------------------------------------
    # Response extraction
    # ------------------------------------------------------------------

    def _extract_repaired_html(self, content: str) -> Optional[str]:
        """Extract repaired HTML from the model's response."""

        # Look for HTML in code fences
        code_match = re.search(r"```html\s*([\s\S]*?)```", content, re.IGNORECASE)
        if code_match:
            return code_match.group(1).strip()

        code_match = re.search(r"```\s*([\s\S]*?)```", content)
        if code_match:
            return code_match.group(1).strip()

        # Look for HTML tags
        html_match = re.search(r"<[^>]+>.*<\/[^>]+>", content, re.DOTALL)
        if html_match:
            return content[html_match.start() : html_match.end()]

        # Return full content if it looks like HTML
        if "<" in content and ">" in content:
            return content.strip()

        return None

    # ------------------------------------------------------------------
    # Type-to-tag mapping
    # ------------------------------------------------------------------

    def _map_type_to_tag(self, element_type: str) -> str:
        """Map semantic element type to HTML tag name."""
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
