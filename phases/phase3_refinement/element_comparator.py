"""
Phase 3: Element-Level Closeup Comparison

Replace the ComponentMatcher + VisualComparator pipeline with direct
bbox-based closeup comparison.  For each Phase 1 detected element:

  1. Crop the reference image at the element's bbox.
  2. Crop the rendered screenshot at the same coordinates.
  3. Compute per-element SSIM between the two crops.
  4. For the worst elements (below threshold), use VLLM to analyze
     the visual diff and suggest repairs.

All crops and comparison data are saved to artifacts/ for inspection.
"""

import json
import logging
from pathlib import Path
from typing import List, Dict, Optional, Tuple

from PIL import Image

from config import Config
from llm_client import DualProviderClient
from storage.component import Component, DetectedElement
from utils.image import compute_ssim

_log = logging.getLogger("pipeline.element_comparator")

# How many worst-scoring elements to send to VLLM for analysis
MAX_VLLM_ANALYSES = 5

# Minimum crop dimension — skip tiny elements that produce noisy SSIM
MIN_CROP_DIM = 40

# Minimum crop area (w*h) — filters out narrow slivers and tiny icons
MIN_CROP_AREA = 3000

# Context padding (px) added around each crop so the LLM sees surrounding
# layout, not just a sliver of pixels
CONTEXT_PAD = 24

# Element types worth sending to VLLM for analysis (larger, structural).
# Tiny text labels and icons are not useful for vision-based comparison.
SIGNIFICANT_TYPES = {
    "card", "container", "input", "button", "image", "banner",
    "section", "navigation", "heading", "dropdown", "grid",
}


class ElementCloseupComparator:
    """
    Per-element closeup comparison using bbox crops from Phase 1.

    Produces a list of issues compatible with TargetedRepair, plus
    saved crops and a JSON comparison log.
    """

    def __init__(self, client: DualProviderClient, config: Config):
        self.client = client
        self.config = config

    async def compare(
        self,
        component: Component,
        screenshot_path: Path,
        iteration: int,
    ) -> Tuple[List[Dict], List[Dict]]:
        """
        Compare reference vs rendered at each element bbox.

        Args:
            component: Component with detected_elements and reference_path.
            screenshot_path: Path to the rendered screenshot.
            iteration: Current iteration number (for artifact naming).

        Returns:
            (issues, comparison_log)
            - issues: list of issue dicts for TargetedRepair
            - comparison_log: full per-element comparison data
        """
        elements = component.detected_elements or []
        if not elements:
            return [], []

        ref_img = Image.open(component.reference_path)
        gen_img = Image.open(screenshot_path)

        # Resize generated to match reference if needed
        if gen_img.size != ref_img.size:
            gen_img = gen_img.resize(ref_img.size, Image.Resampling.LANCZOS)

        # Set up closeup directory
        closeup_dir = self._closeup_dir(component, iteration)

        # 1. Compute per-element SSIM
        comparison_log = []
        for elem in elements:
            entry = self._compare_element(elem, ref_img, gen_img, closeup_dir)
            if entry is not None:
                comparison_log.append(entry)

        # Sort by SSIM ascending (worst first)
        comparison_log.sort(key=lambda e: e["ssim"])

        # 2. Save comparison log
        self._save_comparison_log(component, iteration, comparison_log)

        # 3. Pick worst elements for VLLM analysis
        #    Filter: only significant element types (containers, inputs,
        #    buttons, cards) — tiny text/icon crops waste VLLM calls.
        below_threshold = [
            e for e in comparison_log
            if e["ssim"] < self.config.per_component_threshold
        ]

        # Prioritize significant structural elements for VLLM analysis
        significant = [
            e for e in below_threshold
            if e["element_type"] in SIGNIFICANT_TYPES
        ]
        # Fill remaining slots with non-significant if we have room
        non_significant = [
            e for e in below_threshold
            if e["element_type"] not in SIGNIFICANT_TYPES
        ]
        to_analyze = (significant + non_significant)[:MAX_VLLM_ANALYSES]

        _log.info(
            f"  {len(comparison_log)} elements compared, "
            f"{len(below_threshold)} below threshold, "
            f"{len(to_analyze)} selected for VLLM analysis"
        )

        # 4. VLLM closeup analysis
        issues = []
        if to_analyze:
            issues = await self._analyze_worst_elements(
                to_analyze, component, closeup_dir
            )

        return issues, comparison_log

    # ------------------------------------------------------------------
    # Per-element SSIM
    # ------------------------------------------------------------------

    def _compare_element(
        self,
        elem: DetectedElement,
        ref_img: Image.Image,
        gen_img: Image.Image,
        closeup_dir: Path,
    ) -> Optional[Dict]:
        """
        Crop ref and gen at element bbox, compute SSIM, save crops.
        Returns comparison entry dict or None if element is too small.

        Crops include CONTEXT_PAD pixels of surrounding context so the
        vision model sees the element in situ, not an isolated sliver.
        SSIM is computed on the tight (unpadded) crop for accuracy.
        """
        x, y, w, h = elem.bbox

        # Clamp to image bounds
        img_w, img_h = ref_img.size
        x2 = min(x + w, img_w)
        y2 = min(y + h, img_h)
        x = max(0, x)
        y = max(0, y)
        crop_w = x2 - x
        crop_h = y2 - y

        # Skip tiny elements (dimension or area)
        if crop_w < MIN_CROP_DIM or crop_h < MIN_CROP_DIM:
            return None
        if crop_w * crop_h < MIN_CROP_AREA:
            return None

        # Tight crop for SSIM (no padding)
        ref_crop = ref_img.crop((x, y, x2, y2))
        gen_crop = gen_img.crop((x, y, x2, y2))

        # Compute SSIM on tight crop
        try:
            score, _ = compute_ssim(ref_crop, gen_crop, resize_to_match=False)
            score = float(score)
        except Exception:
            score = 0.0

        # Padded crop for visual context (saved to disk for VLLM)
        pad = CONTEXT_PAD
        px1 = max(0, x - pad)
        py1 = max(0, y - pad)
        px2 = min(img_w, x2 + pad)
        py2 = min(img_h, y2 + pad)
        ref_ctx = ref_img.crop((px1, py1, px2, py2))
        gen_ctx = gen_img.crop((px1, py1, px2, py2))

        # Save padded crops (these are what VLLM sees)
        safe_id = elem.id.replace("/", "_")
        ref_path = closeup_dir / f"{safe_id}_ref.png"
        gen_path = closeup_dir / f"{safe_id}_gen.png"
        ref_ctx.save(ref_path, "PNG")
        gen_ctx.save(gen_path, "PNG")

        return {
            "element_id": elem.id,
            "element_type": elem.type,
            "text": elem.text,
            "bbox": list(elem.bbox),
            "ssim": score,
            "ref_crop_path": str(ref_path),
            "gen_crop_path": str(gen_path),
        }

    # ------------------------------------------------------------------
    # VLLM closeup analysis
    # ------------------------------------------------------------------

    async def _analyze_worst_elements(
        self,
        entries: List[Dict],
        component: Component,
        closeup_dir: Path,
    ) -> List[Dict]:
        """
        Send worst-scoring element closeup pairs to VLLM for
        qualitative analysis and repair suggestions.
        """
        issues = []

        for entry in entries:
            ref_path = Path(entry["ref_crop_path"])
            gen_path = Path(entry["gen_crop_path"])

            if not ref_path.exists() or not gen_path.exists():
                # Fallback: issue from SSIM alone
                issues.append(self._issue_from_ssim(entry))
                continue

            prompt = self._build_closeup_prompt(entry)

            try:
                response = await self.client.codegen_from_vision(
                    prompt=prompt,
                    images=[ref_path, gen_path],
                    temperature=0.3,
                )
                parsed = self._parse_closeup_response(
                    response.content, entry
                )
                if parsed:
                    issues.append(parsed)
                else:
                    issues.append(self._issue_from_ssim(entry))
            except Exception as e:
                _log.warning(
                    f"VLLM analysis failed for {entry['element_id']}: {e}"
                )
                issues.append(self._issue_from_ssim(entry))

        return issues

    def _build_closeup_prompt(self, entry: Dict) -> str:
        """Build prompt for VLLM closeup comparison of a single element."""
        return f"""Compare these two closeup crops of the same UI element.

IMAGE 1 (left): Reference (expected appearance)
IMAGE 2 (right): Generated (current implementation)

Element type: {entry['element_type']}
Element text: "{entry.get('text', '')}"
SSIM score: {entry['ssim']:.3f}
Bounding box: x={entry['bbox'][0]}, y={entry['bbox'][1]}, w={entry['bbox'][2]}, h={entry['bbox'][3]}

Analyze what is different and provide a specific CSS/HTML fix.

Output as JSON:
{{
  "category": "misarrangement|style_error|missing_element",
  "severity": "major|minor",
  "description": "what exactly is wrong",
  "repair": "specific CSS or HTML change to fix it"
}}

Respond with valid JSON only."""

    def _parse_closeup_response(
        self, content: str, entry: Dict
    ) -> Optional[Dict]:
        """Parse VLLM closeup response into an issue dict."""
        import re

        json_match = re.search(r"\{[\s\S]*\}", content)
        if not json_match:
            return None

        json_str = json_match.group()
        # Fix common LLM JSON issues
        json_str = re.sub(r",\s*}", "}", json_str)
        json_str = re.sub(r",\s*]", "]", json_str)

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            return None

        return {
            "component_id": entry["element_id"],
            "issue_type": data.get("category", "style_error"),
            "severity": data.get("severity", "minor"),
            "description": data.get("description", ""),
            "repair_suggestion": data.get("repair", ""),
            "ssim": entry["ssim"],
            "bbox": entry["bbox"],
            "ref_crop": entry["ref_crop_path"],
            "gen_crop": entry["gen_crop_path"],
        }

    def _issue_from_ssim(self, entry: Dict) -> Dict:
        """Create a fallback issue from SSIM score alone."""
        ssim = entry["ssim"]
        if ssim < 0.5:
            severity = "major"
            issue_type = "misarrangement"
        elif ssim < 0.7:
            severity = "major"
            issue_type = "style_error"
        else:
            severity = "minor"
            issue_type = "style_error"

        return {
            "component_id": entry["element_id"],
            "issue_type": issue_type,
            "severity": severity,
            "description": (
                f"{entry['element_type']} visual mismatch "
                f"(SSIM: {ssim:.3f})"
            ),
            "repair_suggestion": "Adjust CSS to match reference appearance",
            "ssim": ssim,
            "bbox": entry["bbox"],
            "ref_crop": entry["ref_crop_path"],
            "gen_crop": entry["gen_crop_path"],
        }

    # ------------------------------------------------------------------
    # Artifact helpers
    # ------------------------------------------------------------------

    def _closeup_dir(self, component: Component, iteration: int) -> Path:
        """Create and return the closeup directory for this iteration."""
        d = component.output_dir / "artifacts" / f"iter_{iteration}_closeups"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _save_comparison_log(
        self,
        component: Component,
        iteration: int,
        comparison_log: List[Dict],
    ) -> None:
        """Save the per-element comparison log as JSON."""
        artifacts = component.output_dir / "artifacts"
        artifacts.mkdir(parents=True, exist_ok=True)
        path = artifacts / f"iter_{iteration}_element_comparison.json"

        # Strip Path objects for JSON serialization
        serializable = []
        for entry in comparison_log:
            e = dict(entry)
            e["ref_crop_path"] = str(e.get("ref_crop_path", ""))
            e["gen_crop_path"] = str(e.get("gen_crop_path", ""))
            serializable.append(e)

        path.write_text(json.dumps(serializable, indent=2), encoding="utf-8")
        _log.info(
            f"Saved element comparison: {path.name} "
            f"({len(comparison_log)} elements)"
        )
