"""
Phase 3.3: Visual Comparison

Compare rendered components against reference crops to identify issues.
Categorizes errors as: misarrangement, style error, or missing element.

The comparison has two tiers:
  1. Quick pixel-level SSIM between cropped regions (local, free).
  2. Detailed vision-model analysis when SSIM is below threshold (API call).

DesignCoder showed that per-component comparison catches issues that
full-page SSIM averages away. A button misaligned by 10px in a 1200px
page barely moves the needle on global SSIM, but per-component SSIM
will flag it clearly.
"""

import json
import re
import tempfile
from pathlib import Path
from typing import List, Dict, Optional, Tuple

from PIL import Image
import numpy as np

from storage.component import Component
from llm_client import DualProviderClient
from config import Config
from utils.image import compute_ssim, load_image


class VisualComparator:
    """
    Compares rendered components to reference using per-component SSIM
    and optional vision-model analysis.

    Flow for each matched component:
      1. Crop reference image to the expected bounding box.
      2. Crop the rendered screenshot to the actual (DOM) bounding box.
      3. Compute per-component SSIM between the two crops.
      4. If SSIM < threshold, optionally send both crops to the vision
         model for qualitative analysis and repair suggestions.
    """

    def __init__(self, client: DualProviderClient, config: Config):
        self.client = client
        self.config = config

    async def compare(
        self,
        matches: List[Dict],
        component: Component,
        rendered_screenshot_path: Optional[Path] = None,
    ) -> List[Dict]:
        """
        Compare matched components and identify issues.

        Args:
            matches: Output from ComponentMatcher — each dict has
                     'expected_id', 'dom_node', and 'confidence'.
            component: The component being refined (holds tree + reference).
            rendered_screenshot_path: Path to the latest rendered screenshot.
                      Falls back to the most recent iteration screenshot.

        Returns list of issues, each with:
            - component_id: which component has the issue
            - issue_type: misarrangement | style_error | missing_element
            - severity: major | minor
            - description: human-readable explanation
            - repair_suggestion: specific CSS/HTML fix
        """
        if not component.tree:
            return []

        # Load reference and rendered images
        ref_img = load_image(component.reference_path)

        # Find the rendered screenshot: prefer explicit path, otherwise
        # fall back to the latest iteration's screenshot
        rendered_img = None
        if rendered_screenshot_path and rendered_screenshot_path.exists():
            rendered_img = load_image(rendered_screenshot_path)
        elif component.iterations:
            last_iter = component.iterations[-1]
            if last_iter.screenshot_path and last_iter.screenshot_path.exists():
                rendered_img = load_image(last_iter.screenshot_path)

        issues = []

        for match in matches:
            expected_id = match["expected_id"]
            dom_node = match["dom_node"]
            confidence = match.get("confidence", 0)

            # Skip very low-confidence matches — they're probably wrong
            if confidence < 0.3:
                continue

            # Look up the expected element in the component tree
            expected_elem = component.tree.elements.get(expected_id)
            if not expected_elem:
                continue

            # --- Per-component SSIM ---
            ssim_score = self._compute_component_ssim(
                ref_img, rendered_img, dom_node, expected_elem.bbox
            )

            # If the component looks good enough, skip it
            if ssim_score > self.config.per_component_threshold:
                continue

            # --- Vision-model analysis for components that fail SSIM ---
            try:
                issue = await self._analyze_component(
                    ref_img, rendered_img, dom_node, expected_elem, ssim_score
                )
                if issue:
                    issues.append(issue)

            except Exception as e:
                # Fallback: create a generic issue from the SSIM score alone
                severity = self._severity_from_ssim(ssim_score)
                issues.append(
                    {
                        "component_id": expected_id,
                        "issue_type": "style_error",
                        "severity": severity,
                        "description": (
                            f"Visual mismatch on '{expected_elem.type}' "
                            f"(SSIM: {ssim_score:.2f}, error: {e})"
                        ),
                        "repair_suggestion": (
                            "Review and adjust styling to match reference"
                        ),
                    }
                )

        return issues

    # ------------------------------------------------------------------
    # Per-component SSIM
    # ------------------------------------------------------------------

    def _compute_component_ssim(
        self,
        ref_img: Image.Image,
        rendered_img: Optional[Image.Image],
        dom_node,
        expected_bbox: Tuple[int, int, int, int],
    ) -> float:
        """
        Compute SSIM between the reference crop and the rendered crop
        for a single component.

        Both images are cropped to the *expected* bounding box (from the
        component tree). If the DOM node also has a bounding box we crop
        the rendered image at the *actual* position to account for layout
        shifts.

        Returns SSIM in [0, 1]. Returns 0.0 when images aren't available.
        """
        # We need a rendered screenshot to compare against
        if rendered_img is None:
            # No rendered screenshot available — flag for review
            return 0.0

        # Crop reference to the expected bounding box
        ex, ey, ew, eh = expected_bbox
        ref_crop = ref_img.crop((ex, ey, ex + ew, ey + eh))

        # Determine where to crop the rendered image.
        # Use the DOM node's actual bbox if available (accounts for layout
        # shifts); otherwise fall back to the expected position.
        if dom_node.bbox and dom_node.bbox.get("width", 0) > 0:
            ax = int(dom_node.bbox["x"])
            ay = int(dom_node.bbox["y"])
            aw = int(dom_node.bbox["width"])
            ah = int(dom_node.bbox["height"])
        else:
            ax, ay, aw, ah = ex, ey, ew, eh

        # Guard against out-of-bounds crops
        img_w, img_h = rendered_img.size
        if ax < 0 or ay < 0 or ax + aw > img_w or ay + ah > img_h:
            # Crop is partially or fully outside the rendered image
            return 0.0

        if aw <= 0 or ah <= 0:
            return 0.0

        gen_crop = rendered_img.crop((ax, ay, ax + aw, ay + ah))

        # Resize generated crop to match reference crop dimensions for SSIM
        if gen_crop.size != ref_crop.size:
            gen_crop = gen_crop.resize(ref_crop.size, Image.Resampling.LANCZOS)

        # Compute SSIM
        try:
            score, _ = compute_ssim(ref_crop, gen_crop, resize_to_match=False)
            return float(score)
        except Exception:
            # SSIM can fail on very small images; treat as needing review
            return 0.0

    # ------------------------------------------------------------------
    # Vision-model analysis
    # ------------------------------------------------------------------

    async def _analyze_component(
        self,
        ref_img: Image.Image,
        rendered_img: Optional[Image.Image],
        dom_node,
        expected_elem,
        ssim_score: float,
    ) -> Optional[Dict]:
        """
        Use the vision model to analyze a component that failed the SSIM
        check. Sends both the reference crop and rendered crop to the
        model for qualitative feedback.

        Falls back to a generic issue description if the API call fails
        or no rendered image is available.
        """
        # Crop reference image to the expected bbox
        x, y, w, h = expected_elem.bbox
        ref_crop = ref_img.crop((x, y, x + w, y + h))

        # Save crops to temp files for the vision API
        temp_dir = tempfile.mkdtemp(prefix="ui_compare_")
        ref_crop_path = Path(temp_dir) / f"ref_{expected_elem.id}.png"
        ref_crop.save(ref_crop_path)

        images = [ref_crop_path]

        # Also save the rendered crop if available
        if rendered_img is not None:
            if dom_node.bbox and dom_node.bbox.get("width", 0) > 0:
                ax = int(dom_node.bbox["x"])
                ay = int(dom_node.bbox["y"])
                aw = int(dom_node.bbox["width"])
                ah = int(dom_node.bbox["height"])
                img_w, img_h = rendered_img.size
                ax = max(0, ax)
                ay = max(0, ay)
                aw = min(aw, img_w - ax)
                ah = min(ah, img_h - ay)
                if aw > 0 and ah > 0:
                    gen_crop = rendered_img.crop((ax, ay, ax + aw, ay + ah))
                    gen_crop_path = Path(temp_dir) / f"gen_{expected_elem.id}.png"
                    gen_crop.save(gen_crop_path)
                    images.append(gen_crop_path)

        # Build the vision prompt
        prompt = self._build_comparison_prompt(expected_elem.type, ssim_score)

        # Try calling the vision model for detailed analysis
        try:
            response = await self.client.vision_analyze(
                prompt=prompt, images=images, temperature=0.3
            )

            # Parse the structured response
            parsed_issues = self._parse_comparison_response(response.content)
            if parsed_issues:
                # Return the first issue (most relevant)
                issue = parsed_issues[0]
                issue["component_id"] = expected_elem.id
                return issue
        except Exception:
            pass
        finally:
            # Clean up temp files
            for img_path in images:
                img_path.unlink(missing_ok=True)
            Path(temp_dir).rmdir()

        # Fallback: create a structured issue from SSIM alone
        severity = self._severity_from_ssim(ssim_score)
        issue_type = "style_error" if ssim_score > 0.5 else "misarrangement"

        return {
            "component_id": expected_elem.id,
            "issue_type": issue_type,
            "severity": severity,
            "description": (
                f"{expected_elem.type} component visual mismatch "
                f"(SSIM: {ssim_score:.2f})"
            ),
            "repair_suggestion": "Adjust CSS to match reference appearance",
        }

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def _build_comparison_prompt(self, component_type: str, ssim_score: float) -> str:
        """Build prompt for visual comparison."""
        return f"""Compare these two images of the same UI component.

Left: Expected (from reference)
Right: Generated (current implementation)

Component type: {component_type}
SSIM score: {ssim_score:.3f}

Analyze the differences and categorize:

1. Misarrangement: Wrong position, size, or layout structure
2. Style Error: Wrong colors, fonts, spacing, borders, shadows
3. Missing Element: Something from reference is not in generated
4. Good Match: Visually acceptable

For each issue found, provide:
- Category (misarrangement/style_error/missing)
- Severity (major/minor)
- Description: what exactly is wrong
- Repair suggestion: specific CSS or HTML fix

Output as JSON:
{{
  "issues": [
    {{
      "category": "style_error",
      "severity": "minor",
      "description": "Button background is #333 but should be #222",
      "repair": "Change background-color from #333 to #222"
    }}
  ],
  "overall_assessment": "brief summary"
}}

Respond with valid JSON only."""

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    def _categorize_issue(self, description: str) -> Tuple[str, str]:
        """Categorize an issue from its description text."""
        desc_lower = description.lower()

        # Misarrangement keywords
        if any(
            kw in desc_lower
            for kw in [
                "position",
                "size",
                "layout",
                "alignment",
                "placed",
                "offset",
                "shifted",
                "misaligned",
            ]
        ):
            return "misarrangement", "major"

        # Style keywords
        if any(
            kw in desc_lower
            for kw in [
                "color",
                "font",
                "spacing",
                "border",
                "shadow",
                "background",
                "text",
                "padding",
                "margin",
                "radius",
            ]
        ):
            return "style_error", "minor"

        # Missing-element keywords
        if any(
            kw in desc_lower
            for kw in ["missing", "not found", "absent", "gone", "omitted"]
        ):
            return "missing_element", "major"

        return "style_error", "minor"

    def _severity_from_ssim(self, ssim: float) -> str:
        """Determine severity from SSIM score."""
        if ssim < 0.7:
            return "major"
        elif ssim < 0.9:
            return "minor"
        return "none"

    def _parse_comparison_response(self, content: str) -> List[Dict]:
        """
        Parse the vision model's JSON response into a list of issue dicts.
        Handles common LLM JSON formatting mistakes (trailing commas,
        single quotes, etc.).
        """
        # Extract JSON block from the response
        json_match = re.search(r"\{[\s\S]*\}", content)
        if not json_match:
            return []

        json_str = json_match.group()

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            json_str = self._fix_json_issues(json_str)
            try:
                data = json.loads(json_str)
            except json.JSONDecodeError:
                return []

        issues = []
        for issue_data in data.get("issues", []):
            category = issue_data.get("category", "style_error")
            severity = issue_data.get("severity", "minor")

            issues.append(
                {
                    "issue_type": category,
                    "severity": severity,
                    "description": issue_data.get("description", ""),
                    "repair_suggestion": issue_data.get(
                        "repair", issue_data.get("repair_suggestion", "")
                    ),
                }
            )

        return issues

    def _fix_json_issues(self, json_str: str) -> str:
        """Fix common JSON formatting mistakes from LLM responses."""
        # Remove trailing commas before } or ]
        json_str = re.sub(r",\s*}", "}", json_str)
        json_str = re.sub(r",\s*]", "]", json_str)
        # Convert single quotes to double quotes
        json_str = json_str.replace("'", '"')
        return json_str
