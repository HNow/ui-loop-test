"""
Main orchestration loop for the UI Cloning Agent.
Implements the DesignCoder 3-phase pipeline.

Flow: image -> Phase 1 (group/label) -> Phase 2 (codegen) -> Phase 3 (refine)
Each phase can be invoked independently via AgentLoop.run_phaseN_only().

All artifacts are saved to {output_dir}/artifacts/ for inspection.
"""

import asyncio
import json
import logging
import subprocess
import time
from pathlib import Path
from typing import Optional, List, Dict

from PIL import Image, ImageDraw, ImageFont

from config import Config
from llm_client import DualProviderClient
from storage.component import (
    Component,
    ComponentStore,
    Region,
    Element,
    ComponentTree,
    Iteration,
)
from utils.image import (
    load_image,
    save_image,
    extract_colors,
    compute_ssim,
    create_diff_overlay,
    annotate_image,
)
from utils.dom import render_html
from utils.metrics import compute_all_metrics

from phases.phase1_grouping.division import UIDivision, crop_and_save_regions
from phases.phase1_grouping.semantic import SemanticExtraction
from phases.phase1_grouping.grouping import ComponentGrouping

from phases.phase2_codegen.html_gen import HTMLGenerator
from phases.phase2_codegen.style_gen import StyleGenerator

from phases.phase3_refinement.matcher import ComponentMatcher
from phases.phase3_refinement.comparator import VisualComparator
from phases.phase3_refinement.repair import FullPageRepair
from phases.phase3_refinement.element_comparator import ElementCloseupComparator


REGION_PALETTE = [
    (255, 60, 60),
    (60, 60, 255),
    (0, 200, 80),
    (255, 165, 0),
    (160, 0, 200),
    (0, 190, 190),
    (200, 0, 100),
    (100, 100, 0),
    (0, 100, 100),
    (150, 50, 200),
]


class FileServer:
    def __init__(self, directory: Path, port: int = 8765, host: str = "127.0.0.1"):
        self.directory = directory
        self.port = port
        self.host = host
        self._proc: Optional[subprocess.Popen] = None

    def start(self):
        self._proc = subprocess.Popen(
            [
                "python",
                "-m",
                "http.server",
                str(self.port),
                "--directory",
                str(self.directory),
                "--bind",
                self.host,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(0.5)

    def stop(self):
        if self._proc:
            self._proc.terminate()
            self._proc.wait()
            self._proc = None

    def url(self, path: str = "") -> str:
        return f"http://{self.host}:{self.port}/{path}"


class AgentLoop:
    def __init__(self, config: Config, store: ComponentStore, logger: logging.Logger):
        self.config = config
        self.store = store
        self.log = logger
        self.server: Optional[FileServer] = None

    def _artifacts_dir(self, component: Component) -> Path:
        d = component.output_dir / "artifacts"
        d.mkdir(parents=True, exist_ok=True)
        return d

    # ------------------------------------------------------------------
    # Artifact helpers
    # ------------------------------------------------------------------

    def _save_phase1_detection_overlay(self, component: Component):
        if not component.detected_elements:
            return
        ref = load_image(component.reference_path)
        elements = [(e.type, e.bbox) for e in component.detected_elements]
        overlay = annotate_image(ref.copy(), elements, color=(0, 200, 0), width=2)
        path = self._artifacts_dir(component) / "phase1_detection_overlay.png"
        save_image(overlay, path)
        self.log.info(f"Saved detection overlay: {path.name}")

    def _save_phase1_segmentation_overlay(self, component: Component):
        if not component.regions:
            return
        ref = load_image(component.reference_path).convert("RGBA")
        overlay = ref.copy()
        draw = ImageDraw.Draw(overlay, "RGBA")

        try:
            font = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 14
            )
            font_sm = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 11
            )
        except Exception:
            font = ImageFont.load_default()
            font_sm = font

        det_by_id = {e.id: e for e in (component.detected_elements or [])}

        for i, region in enumerate(component.regions):
            x, y, w, h = region.bbox
            color = REGION_PALETTE[i % len(REGION_PALETTE)]

            # Light fill + dashed-style border for region
            draw.rectangle(
                [x, y, x + w, y + h],
                fill=(*color, 30),
                outline=(*color, 180),
                width=2,
            )

            # Draw individual element bboxes inside this region
            for eid in region.element_ids:
                det = det_by_id.get(eid)
                if not det:
                    continue
                ex, ey, ew, eh = det.bbox
                draw.rectangle(
                    [ex, ey, ex + ew, ey + eh],
                    outline=(*color, 200),
                    width=1,
                )
                # Tiny type label
                draw.text(
                    (ex + 2, ey + 1),
                    det.type,
                    fill=(*color, 220),
                    font=font_sm,
                )

            # Region label
            n = len(region.element_ids)
            label = f"{i}: {region.name} ({n})"
            tb = draw.textbbox((0, 0), label, font=font)
            tw = tb[2] - tb[0] + 10
            draw.rectangle(
                [x, y, x + tw, y + 20],
                fill=(0, 0, 0, 180),
            )
            draw.text((x + 4, y + 3), label, fill="white", font=font)

        out = overlay.convert("RGB")
        path = self._artifacts_dir(component) / "phase1_segmentation_overlay.png"
        save_image(out, path)
        self.log.info(f"Saved segmentation overlay: {path.name}")

    def _save_phase1_drift_overlay(self, component: Component):
        """
        Dual-layer overlay comparing Phase 1.0 (green) vs Phase 1.2
        normalized (red) bboxes for text-matched elements.
        Shows drift magnitude and correction status.
        """
        if (
            not component.detected_elements
            or not component.tree
            or not component.regions
        ):
            return

        ref = load_image(component.reference_path).convert("RGBA")
        draw = ImageDraw.Draw(ref, "RGBA")

        try:
            font_sm = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 11
            )
            font_title = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 14
            )
        except Exception:
            font_sm = ImageFont.load_default()
            font_title = font_sm

        det_by_text = {}
        for d in component.detected_elements:
            key = d.text.strip().lower()
            if key and len(key) >= 2:
                det_by_text[key] = d

        tree_elems = component.tree.elements

        drifts = []
        for te_id, te in tree_elems.items():
            te_text = te.content_description.strip().lower()
            best_det = None
            for key, det in det_by_text.items():
                if key in te_text or te_text in key:
                    best_det = det
                    break
            if not best_det:
                continue

            dx, dy, dw, dh = best_det.bbox
            tx, ty, tw, th = te.bbox

            drift = (
                ((dx + dw / 2) - (tx + tw / 2)) ** 2
                + ((dy + dh / 2) - (ty + th / 2)) ** 2
            ) ** 0.5
            drifts.append(drift)

            draw.rectangle(
                [dx, dy, dx + dw, dy + dh],
                outline=(0, 200, 0, 180),
                width=2,
            )
            draw.rectangle(
                [tx, ty, tx + tw, ty + th],
                outline=(255, 60, 60, 180),
                width=2,
            )
            if drift > 50:
                draw.line(
                    [(dx + dw // 2, dy + dh // 2), (tx + tw // 2, ty + th // 2)],
                    fill=(255, 255, 0, 120),
                    width=1,
                )
                draw.text(
                    (tx + tw + 4, ty),
                    f"{drift:.0f}px",
                    fill=(255, 60, 60),
                    font=font_sm,
                )

        draw.rectangle([8, 8, 350, 56], fill=(0, 0, 0, 180))
        draw.text(
            (12, 10), "GREEN = Phase 1.0 (ground truth)", fill=(0, 200, 0), font=font_sm
        )
        draw.text(
            (12, 26),
            "RED   = Phase 1.2 (after normalize)",
            fill=(255, 60, 60),
            font=font_sm,
        )
        if drifts:
            mean_d = sum(drifts) / len(drifts)
            draw.text(
                (12, 42),
                f"Mean drift: {mean_d:.0f}px | Max: {max(drifts):.0f}px | n={len(drifts)}",
                fill="white",
                font=font_sm,
            )

        out = ref.convert("RGB")
        path = self._artifacts_dir(component) / "phase1_drift_overlay.png"
        save_image(out, path)
        self.log.info(f"Saved drift overlay: {path.name} ({len(drifts)} matched pairs)")

    def _save_phase1_tree(self, component: Component):
        if not component.tree:
            return
        elements_serialized = {}
        for eid, elem in component.tree.elements.items():
            elements_serialized[eid] = {
                "id": elem.id,
                "type": elem.type,
                "bbox": list(elem.bbox),
                "content": elem.content_description,
                "interactable": elem.interactable,
                "parent_id": elem.parent_id,
                "children_ids": elem.children_ids,
            }
        tree_data = {
            "root_id": component.tree.root_id,
            "elements": elements_serialized,
            "regions": [
                {
                    "id": r.id,
                    "name": r.name,
                    "bbox": list(r.bbox),
                    "element_count": len(r.element_ids),
                }
                for r in component.tree.regions
            ],
        }
        path = self._artifacts_dir(component) / "phase1_tree.json"
        path.write_text(json.dumps(tree_data, indent=2), encoding="utf-8")
        self.log.info(
            f"Saved component tree: {path.name} ({len(elements_serialized)} nodes)"
        )

    def _save_phase1_elements(self, component: Component, elements_by_region: Dict):
        data = {}
        for region_id, elems in elements_by_region.items():
            data[region_id] = [
                {
                    "id": e.id,
                    "type": e.type,
                    "bbox": list(e.bbox),
                    "content": e.content_description,
                    "interactable": e.interactable,
                }
                for e in elems
            ]
        path = self._artifacts_dir(component) / "phase1_elements.json"
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        self.log.info(f"Saved semantic elements: {path.name}")

    def _save_phase2_colors(self, colors: List[dict], component: Component):
        serializable = []
        for c in colors:
            serializable.append(
                {
                    "hex": c["hex"],
                    "rgb": [int(x) for x in c["rgb"]],
                    "coverage_pct": float(c["coverage_pct"]),
                }
            )
        path = self._artifacts_dir(component) / "phase2_colors.json"
        path.write_text(json.dumps(serializable, indent=2), encoding="utf-8")
        self.log.info(f"Saved color palette: {path.name} ({len(colors)} colors)")

    def _save_phase3_metrics(self, all_metrics: List[dict], component: Component):
        path = self._artifacts_dir(component) / "phase3_metrics.json"
        path.write_text(json.dumps(all_metrics, indent=2), encoding="utf-8")
        self.log.info(f"Saved metrics history: {path.name}")

    def _save_phase3_diff(self, component: Component, iteration: int):
        """Per-region diff overlay — only highlights differences within
        region bounds so that areas outside content stay clean."""
        ref_img = load_image(component.reference_path)
        screenshot_path = component.output_dir / f"iter_{iteration}.png"
        if not screenshot_path.exists():
            return
        gen_img = load_image(screenshot_path)

        # If no regions, fall back to whole-page diff
        if not component.regions:
            diff = create_diff_overlay(ref_img, gen_img)
        else:
            import numpy as np
            # Resize gen to match ref if needed
            if gen_img.size != ref_img.size:
                gen_img = gen_img.resize(ref_img.size, Image.Resampling.LANCZOS)
            base = np.array(ref_img).copy()
            ref_arr = np.array(ref_img)
            gen_arr = np.array(gen_img)
            for region in component.regions:
                x, y, w, h = region.bbox
                # Clamp to image bounds
                x2 = min(x + w, ref_img.width)
                y2 = min(y + h, ref_img.height)
                x, y = max(0, x), max(0, y)
                if x2 <= x or y2 <= y:
                    continue
                ref_crop = ref_arr[y:y2, x:x2]
                gen_crop = gen_arr[y:y2, x:x2]
                pixel_diff = np.abs(ref_crop.astype(float) - gen_crop.astype(float))
                mask = np.any(pixel_diff > 35, axis=-1)
                region_overlay = ref_crop.copy()
                region_overlay[mask] = [255, 0, 255]
                base[y:y2, x:x2] = region_overlay
            diff = Image.fromarray(base)

        diff_path = component.output_dir / f"iter_{iteration}_diff.png"
        save_image(diff, diff_path)
        self.log.info(f"  Saved diff overlay: {diff_path.name}")

    def _compute_per_region_ssim(
        self, component, screenshot_path: Path
    ) -> tuple:
        """Compute per-region SSIM by cropping ref and rendered at each
        region's bbox.  Returns (mean_ssim, per_region_list)."""
        if not component.regions or not screenshot_path.exists():
            # Fall back to whole-page SSIM
            ref_img = load_image(component.reference_path)
            gen_img = load_image(screenshot_path)
            score, _ = compute_ssim(ref_img, gen_img)
            return score, []

        ref_img = load_image(component.reference_path)
        gen_img = load_image(screenshot_path)
        if gen_img.size != ref_img.size:
            gen_img = gen_img.resize(ref_img.size, Image.Resampling.LANCZOS)

        scores = []
        for region in component.regions:
            x, y, w, h = region.bbox
            x2 = min(x + w, ref_img.width)
            y2 = min(y + h, ref_img.height)
            x, y = max(0, x), max(0, y)
            if x2 - x < 5 or y2 - y < 5:
                continue
            ref_crop = ref_img.crop((x, y, x2, y2))
            gen_crop = gen_img.crop((x, y, x2, y2))
            try:
                score, _ = compute_ssim(ref_crop, gen_crop, resize_to_match=False)
                scores.append({"region": region.name, "ssim": float(score)})
            except Exception:
                scores.append({"region": region.name, "ssim": 0.0})

        if not scores:
            ref_img2 = load_image(component.reference_path)
            gen_img2 = load_image(screenshot_path)
            s, _ = compute_ssim(ref_img2, gen_img2)
            return s, []

        mean = sum(s["ssim"] for s in scores) / len(scores)
        return mean, scores

    # ------------------------------------------------------------------
    # Pipeline entry points
    # ------------------------------------------------------------------

    async def run_full_pipeline(self, component: Component) -> dict:
        self.log.info("=" * 60)
        self.log.info("PHASE 1: UI Grouping Chain")
        self.log.info("=" * 60)
        await self._run_phase1(component)

        self.log.info("=" * 60)
        self.log.info("PHASE 2: Hierarchy-Aware Code Generation")
        self.log.info("=" * 60)
        await self._run_phase2(component)

        self.log.info("=" * 60)
        self.log.info("PHASE 3: Self-Correcting Refinement")
        self.log.info("=" * 60)
        result = await self._run_phase3(component)

        return result

    async def run_phase1_only(self, component: Component) -> dict:
        self.log.info("=" * 60)
        self.log.info("PHASE 1: UI Grouping Chain")
        self.log.info("=" * 60)
        await self._run_phase1(component)
        return {
            "phase": 1,
            "component_id": component.id,
            "regions": len(component.regions),
        }

    async def run_phase2_only(self, component: Component) -> dict:
        if not component.tree:
            self.log.error("Phase 1 must be completed first (no component tree)")
            return {"error": "Phase 1 required"}
        self.log.info("=" * 60)
        self.log.info("PHASE 2: Hierarchy-Aware Code Generation")
        self.log.info("=" * 60)
        await self._run_phase2(component)
        return {
            "phase": 2,
            "component_id": component.id,
            "html": str(component.html_path),
        }

    async def run_phase3_only(self, component: Component) -> dict:
        if not component.html_path:
            self.log.error("Phase 2 must be completed first (no HTML)")
            return {"error": "Phase 2 required"}
        self.log.info("=" * 60)
        self.log.info("PHASE 3: Self-Correcting Refinement")
        self.log.info("=" * 60)
        return await self._run_phase3(component)

    # ------------------------------------------------------------------
    # Phase implementations
    # ------------------------------------------------------------------

    async def _run_phase1(self, component: Component):
        t0 = time.time()
        code_config = self.config.get_llm_config(for_vision=False)
        vision_config = self.config.get_llm_config(for_vision=True)

        async with DualProviderClient(code_config, vision_config) as client:
            self.log.info("[1.0] Detecting UI elements...")
            division = UIDivision(client, self.config)
            regions = await division.divide(component)

            self._save_phase1_detection_overlay(component)

            self.log.info("[1.1] Cropping region images...")
            regions = crop_and_save_regions(
                component, regions, component.reference_path
            )
            component.regions = regions
            self.log.info(f"  -> {len(regions)} regions: {[r.name for r in regions]}")

            self._save_phase1_segmentation_overlay(component)

            self.log.info("[1.2] Semantic extraction...")
            detected_by_id = {e.id: e for e in component.detected_elements}
            region_detections = {}
            for region in regions:
                region_detections[region.id] = [
                    detected_by_id[eid]
                    for eid in region.element_ids
                    if eid in detected_by_id
                ]
            self.log.info(
                f"  -> region detections: "
                + ", ".join(
                    f"{r.name}={len(region_detections.get(r.id, []))}" for r in regions
                )
            )

            semantic = SemanticExtraction(client, self.config)
            elements_by_region, drift_stats = await semantic.extract(
                component,
                regions,
                detected_elements=component.detected_elements,
                region_detections=region_detections,
            )
            total = sum(len(e) for e in elements_by_region.values())
            self.log.info(
                f"  -> {total} elements across {len(elements_by_region)} regions"
            )

            if drift_stats:
                component.bbox_drift_stats = drift_stats
                method = drift_stats.get("method", "unknown")
                lo = drift_stats.get("regions_label_only", 0)
                rd = drift_stats.get("regions_redetect", 0)
                self.log.info(f"  -> method={method}, label-only={lo}, re-detect={rd}")

            self._save_phase1_elements(component, elements_by_region)

            self.log.info("[1.3] Building component hierarchy...")
            grouping = ComponentGrouping(client, self.config)
            tree = await grouping.group(component, regions, elements_by_region)
            component.tree = tree
            self.log.info(f"  -> Tree with {len(tree.elements)} nodes")

            self._save_phase1_tree(component)
            self._save_phase1_drift_overlay(component)

            self.store.save(component)
            self.log.info(f"Phase 1 complete in {time.time() - t0:.1f}s")

    async def _run_phase2(self, component: Component):
        t0 = time.time()
        code_config = self.config.get_llm_config(for_vision=False)
        vision_config = self.config.get_llm_config(for_vision=True)
        codegen_config = self.config.get_codegen_llm_config()

        async with DualProviderClient(code_config, vision_config, codegen_config) as client:
            self.log.info("[2.0] Extracting color palette...")
            colors = extract_colors(component.reference_path)
            self._save_phase2_colors(colors, component)
            for c in colors[:6]:
                self.log.info(f"  {c['hex']} ({c['coverage_pct']:.1f}%)")

            html_gen = HTMLGenerator(client, self.config)
            style_gen = StyleGenerator(client, self.config)

            if self.config.codegen_model:
                # VLLM single-shot codegen path
                self.log.info(
                    f"[2.1] VLLM single-shot codegen ({self.config.codegen_model})..."
                )
                raw_html = await html_gen.generate_vllm_fullpage(component, colors)
                self.log.info(f"  -> {len(raw_html)} chars raw HTML")

                self.log.info("[2.2] Ensuring document structure...")
                full_html = style_gen.ensure_document_structure(raw_html, colors)
            else:
                # Tree-based codegen path (default)
                self.log.info("[2.1] Generating HTML structure (tree-based)...")
                html_fragments = await html_gen.generate(component, colors)
                self.log.info(f"  -> {len(html_fragments)} HTML fragments")

                self.log.info("[2.2] Generating CSS styles...")
                full_html = await style_gen.apply_styles(
                    component, html_fragments, colors
                )

            html_path = component.output_dir / "index.html"
            html_path.write_text(full_html, encoding="utf-8")
            component.html_path = html_path
            self.log.info(f"  -> Written: {html_path.name} ({len(full_html)} chars)")

            self.store.save(component)
            self.log.info(f"Phase 2 complete in {time.time() - t0:.1f}s")

    async def _run_phase3(self, component: Component) -> dict:
        t0 = time.time()
        self.server = FileServer(
            component.output_dir,
            port=self.config.serve_port,
            host=self.config.serve_host,
        )
        self.server.start()
        self.log.info(f"File server: {self.server.url()}")

        try:
            code_config = self.config.get_llm_config(for_vision=False)
            vision_config = self.config.get_llm_config(for_vision=True)

            codegen_config = self.config.get_codegen_llm_config()

            async with DualProviderClient(code_config, vision_config, codegen_config) as client:
                element_comparator = ElementCloseupComparator(client, self.config)
                repair = FullPageRepair(client, self.config)

                scores: List[float] = []
                all_metrics: List[dict] = []
                plateau_count = 0

                # Use reference image dimensions for viewport so the
                # rendered screenshot matches the reference layout and
                # SSIM comparison is fair (avoids stretch/squish).
                ref_img_for_size = load_image(component.reference_path)
                ref_w, ref_h = ref_img_for_size.size
                self.log.info(
                    f"  Reference image: {ref_w}x{ref_h} — using as viewport size"
                )

                # Establish Phase 2 baseline SSIM before entering the
                # repair loop.  Without this, best_ssim starts at 0.0
                # and the first iteration always becomes "best" even
                # when SSIM is mediocre.
                self.log.info("  Establishing Phase 2 baseline...")
                baseline_ss, _, _ = await render_html(
                    str(component.html_path),
                    self.server.url("index.html"),
                    viewport_width=ref_w,
                    viewport_height=ref_h,
                )
                baseline_path = component.output_dir / "iter_0_baseline.png"
                with open(baseline_path, "wb") as f:
                    f.write(baseline_ss)
                baseline_ssim, baseline_regions = self._compute_per_region_ssim(
                    component, baseline_path
                )
                self.log.info(f"  Phase 2 baseline SSIM: {baseline_ssim:.4f} (per-region avg)")
                for rs in baseline_regions:
                    self.log.info(f"    {rs['region']}: {rs['ssim']:.4f}")

                best_ssim = baseline_ssim
                best_html = component.html_path.read_text(encoding="utf-8")

                for iteration in range(self.config.max_iterations):
                    self.log.info(
                        f"--- Iteration {iteration + 1}/{self.config.max_iterations} ---"
                    )

                    self.log.info("  Rendering HTML...")
                    screenshot, dom_tree, console_errors = await render_html(
                        str(component.html_path),
                        self.server.url("index.html"),
                        viewport_width=ref_w,
                        viewport_height=ref_h,
                    )
                    self.log.info(
                        f"  Screenshot: {len(screenshot)} bytes, "
                        f"console errors: {len(console_errors)}"
                    )
                    if console_errors:
                        for err in console_errors[:3]:
                            self.log.warning(f"    console: {err}")

                    screenshot_path = component.output_dir / f"iter_{iteration + 1}.png"
                    with open(screenshot_path, "wb") as f:
                        f.write(screenshot)

                    ssim_score, region_scores = self._compute_per_region_ssim(
                        component, screenshot_path
                    )
                    scores.append(ssim_score)
                    for rs in region_scores:
                        self.log.info(f"    {rs['region']}: {rs['ssim']:.4f}")

                    if ssim_score > best_ssim:
                        best_ssim = ssim_score
                        best_html = component.html_path.read_text(encoding="utf-8")
                        self.log.info(f"  New best SSIM: {best_ssim:.4f}")
                    elif best_html and ssim_score < best_ssim - 0.01:
                        self.log.warning(
                            f"  SSIM dropped ({ssim_score:.4f} < {best_ssim:.4f}), reverting and stopping"
                        )
                        component.html_path.write_text(best_html, encoding="utf-8")
                        break

                    structural = compute_all_metrics(dom_tree, component.tree)

                    metrics_entry = {
                        "iteration": iteration + 1,
                        "ssim": float(round(ssim_score, 4)),
                        "treebleu": (
                            float(round(structural["treebleu"], 4))
                            if structural["treebleu"] is not None
                            else None
                        ),
                        "container_match": (
                            float(round(structural["container_match"], 4))
                            if structural["container_match"] is not None
                            else None
                        ),
                        "tree_edit_distance": (
                            int(structural["tree_edit_distance"])
                            if structural.get("tree_edit_distance") is not None
                            else None
                        ),
                        "console_errors": len(console_errors),
                    }
                    all_metrics.append(metrics_entry)

                    self.log.info(f"  SSIM:            {ssim_score:.4f}")
                    if structural["treebleu"] is not None:
                        self.log.info(
                            f"  TreeBLEU:        {structural['treebleu']:.4f}"
                        )
                    if structural["container_match"] is not None:
                        self.log.info(
                            f"  ContainerMatch:  {structural['container_match']:.4f}"
                        )
                    if structural.get("tree_edit_distance") is not None:
                        self.log.info(
                            f"  TreeEditDist:    {structural['tree_edit_distance']}"
                        )

                    self._save_phase3_diff(component, iteration + 1)
                    self._save_phase3_metrics(all_metrics, component)

                    if ssim_score >= self.config.ssim_threshold:
                        self.log.info(
                            f"  CONVERGED at iteration {iteration + 1} "
                            f"(SSIM >= {self.config.ssim_threshold})"
                        )
                        break

                    if len(scores) > self.config.plateau_patience:
                        recent = scores[-self.config.plateau_patience :]
                        if max(recent) - min(recent) < self.config.plateau_delta:
                            plateau_count += 1
                            if plateau_count >= 1:
                                self.log.warning(
                                    "  Plateau detected - scores not improving"
                                )
                        else:
                            plateau_count = 0

                    self.log.info("  Element closeup comparison...")
                    issues, comparison_log = await element_comparator.compare(
                        component, screenshot_path, iteration + 1
                    )
                    n_below = sum(
                        1 for e in comparison_log
                        if e["ssim"] < self.config.per_component_threshold
                    )
                    self.log.info(
                        f"  {len(comparison_log)} elements compared, "
                        f"{n_below} below threshold"
                    )
                    for entry in comparison_log[:5]:
                        self.log.info(
                            f"    {entry['element_type']} "
                            f"({entry['element_id']}): "
                            f"SSIM={entry['ssim']:.3f}"
                        )

                    if not issues:
                        self.log.info("  No issues found - done")
                        break

                    self.log.info(f"  {len(issues)} issues to repair")
                    for issue in issues[:5]:
                        self.log.info(
                            f"    [{issue.get('severity', '?')}] "
                            f"{issue.get('issue_type', '?')}: "
                            f"{issue.get('description', '')[:80]}"
                        )

                    self.log.info("  Full-page repair...")
                    new_html = await repair.repair(
                        component, issues, comparison_log, screenshot_path,
                    )
                    component.html_path.write_text(new_html, encoding="utf-8")

                    component.iterations.append(
                        Iteration(
                            number=iteration + 1,
                            timestamp=time.time(),
                            ssim=ssim_score,
                            treebleu=structural.get("treebleu"),
                            container_match=structural.get("container_match"),
                            tree_edit_distance=structural.get("tree_edit_distance"),
                            html_path=component.html_path,
                            screenshot_path=screenshot_path,
                            notes=f"Repaired {len(issues)} issues",
                        )
                    )

                    self.store.save(component)

                final_ssim = scores[-1] if scores else 0.0
                component.final_ssim = final_ssim
                self._save_phase3_metrics(all_metrics, component)
                self.store.save(component)

                elapsed = time.time() - t0
                self.log.info(
                    f"Phase 3 complete in {elapsed:.1f}s | "
                    f"Final SSIM: {final_ssim:.4f} | "
                    f"{len(component.iterations)} iterations"
                )

                return {
                    "component_id": component.id,
                    "ssim": final_ssim,
                    "iterations": len(component.iterations),
                    "treebleu": (
                        component.iterations[-1].treebleu
                        if component.iterations
                        else None
                    ),
                    "container_match": (
                        component.iterations[-1].container_match
                        if component.iterations
                        else None
                    ),
                }

        finally:
            if self.server:
                self.server.stop()
