"""
Main orchestration loop for the UI Cloning Agent.
Implements the DesignCoder 3-phase pipeline.

Flow: image -> Phase 1 (group/label) -> Phase 2 (codegen) -> Phase 3 (refine)
Each phase can be invoked independently via AgentLoop.run_phaseN_only().
"""

import asyncio
import subprocess
import time
from pathlib import Path
from typing import Optional

from config import Config
from llm_client import DualProviderClient
from storage.component import Component, ComponentStore, Region, Element, ComponentTree
from utils.image import (
    load_image,
    save_image,
    extract_colors,
    compute_ssim,
    create_diff_overlay,
    image_to_base64,
)
from utils.dom import render_html
from utils.metrics import compute_all_metrics

# -- Phase 1: Vision-driven grouping pipeline --
from phases.phase1_grouping.division import UIDivision, crop_and_save_regions
from phases.phase1_grouping.semantic import SemanticExtraction
from phases.phase1_grouping.grouping import ComponentGrouping

# -- Phase 2: Code generation from component tree --
from phases.phase2_codegen.html_gen import HTMLGenerator
from phases.phase2_codegen.style_gen import StyleGenerator

# -- Phase 3: Render-compare-repair refinement loop --
from phases.phase3_refinement.matcher import ComponentMatcher
from phases.phase3_refinement.comparator import VisualComparator
from phases.phase3_refinement.repair import TargetedRepair


class FileServer:
    """Simple HTTP file server for Playwright."""

    def __init__(self, directory: Path, port: int = 8080, host: str = "127.0.0.1"):
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
        print(f"[server] http://{self.host}:{self.port}/ → {self.directory}")

    def stop(self):
        if self._proc:
            self._proc.terminate()
            self._proc.wait()
            self._proc = None
            print("[server] stopped")

    def url(self, path: str = "") -> str:
        return f"http://{self.host}:{self.port}/{path}"


class AgentLoop:
    """
    Main agent loop orchestrating all three phases.

    This class manages the full UI cloning pipeline:
    1. Phase 1: Analyze structure via vision models
    2. Phase 2: Generate code from tree structure
    3. Phase 3: Refine via render-compare-repair loop

    Each phase can be run independently for debugging/testing,
    or sequentially for full pipeline operation.
    """

    def __init__(self, config: Config, store: ComponentStore):
        self.config = config
        self.store = store
        self.server: Optional[FileServer] = None  # HTTP server for Playwright

    async def run_full_pipeline(self, component: Component) -> dict:
        """Run all three phases sequentially."""
        # Phase 1: Grouping Chain
        print("\n" + "=" * 60)
        print("PHASE 1: UI Grouping Chain")
        print("=" * 60)
        await self._run_phase1(component)

        # Phase 2: Code Generation
        print("\n" + "=" * 60)
        print("PHASE 2: Hierarchy-Aware Code Generation")
        print("=" * 60)
        await self._run_phase2(component)

        # Phase 3: Self-Correcting Refinement
        print("\n" + "=" * 60)
        print("PHASE 3: Self-Correcting Refinement")
        print("=" * 60)
        result = await self._run_phase3(component)

        return result

    async def run_phase1_only(self, component: Component) -> dict:
        """Run only Phase 1."""
        print("\n" + "=" * 60)
        print("PHASE 1: UI Grouping Chain")
        print("=" * 60)
        await self._run_phase1(component)
        return {
            "phase": 1,
            "component_id": component.id,
            "regions": len(component.regions),
        }

    async def run_phase2_only(self, component: Component) -> dict:
        """Run only Phase 2 (requires Phase 1 completed)."""
        if not component.tree:
            print("Error: Phase 1 must be completed first (no component tree found)")
            return {"error": "Phase 1 required"}

        print("\n" + "=" * 60)
        print("PHASE 2: Hierarchy-Aware Code Generation")
        print("=" * 60)
        await self._run_phase2(component)
        return {
            "phase": 2,
            "component_id": component.id,
            "html": str(component.html_path),
        }

    async def run_phase3_only(self, component: Component) -> dict:
        """Run only Phase 3 (requires Phase 2 completed)."""
        if not component.html_path:
            print("Error: Phase 2 must be completed first (no HTML found)")
            return {"error": "Phase 2 required"}

        print("\n" + "=" * 60)
        print("PHASE 3: Self-Correcting Refinement")
        print("=" * 60)
        return await self._run_phase3(component)

    async def _run_phase1(self, component: Component):
        """Execute Phase 1: UI Grouping Chain."""
        code_config = self.config.get_llm_config(for_vision=False)
        vision_config = self.config.get_llm_config(for_vision=True)

        async with DualProviderClient(code_config, vision_config) as client:
            # Subtask 1.1: UI Division
            print("\n[1.1] UI Division - Segmenting into regions...")
            division = UIDivision(client, self.config)
            regions = await division.divide(component)

            # Crop and save region images
            print("  Cropping region images...")
            regions = crop_and_save_regions(
                component, regions, component.reference_path
            )
            component.regions = regions
            print(f"  → Found {len(regions)} regions: {[r.name for r in regions]}")

            # Subtask 1.2: Semantic Extraction
            print("\n[1.2] Semantic Extraction - Labeling elements...")
            semantic = SemanticExtraction(client, self.config)
            elements_by_region = await semantic.extract(component, regions)
            print(
                f"  → Extracted {sum(len(e) for e in elements_by_region.values())} elements"
            )

            # Subtask 1.3: Component Grouping
            print("\n[1.3] Component Grouping - Building hierarchy...")
            grouping = ComponentGrouping(client, self.config)
            tree = await grouping.group(component, regions, elements_by_region)
            component.tree = tree
            print(f"  → Built tree with {len(tree.elements)} elements")

            # Save intermediate results
            self.store.save(component)

    async def _run_phase2(self, component: Component):
        """Execute Phase 2: Hierarchy-Aware Code Generation."""
        code_config = self.config.get_llm_config(for_vision=False)
        vision_config = self.config.get_llm_config(for_vision=True)

        async with DualProviderClient(code_config, vision_config) as client:
            # Extract colors from reference
            print("\n[2.0] Extracting color palette...")
            colors = extract_colors(component.reference_path)
            print(f"  → {len(colors)} dominant colors")

            # Subtask 2.1: Component Code Generation
            print("\n[2.1] Generating HTML structure...")
            html_gen = HTMLGenerator(client, self.config)
            html_fragments = await html_gen.generate(component, colors)

            # Subtask 2.2: Style Generation
            print("\n[2.2] Generating CSS styles...")
            style_gen = StyleGenerator(client, self.config)
            full_html = await style_gen.apply_styles(component, html_fragments, colors)

            # Write final HTML
            html_path = component.output_dir / "index.html"
            html_path.write_text(full_html, encoding="utf-8")
            component.html_path = html_path
            print(f"  → Written: {html_path}")

            self.store.save(component)

    async def _run_phase3(self, component: Component) -> dict:
        """Execute Phase 3: Self-Correcting Refinement."""
        # Start file server for rendering
        self.server = FileServer(
            component.output_dir,
            port=self.config.serve_port,
            host=self.config.serve_host,
        )
        self.server.start()

        try:
            code_config = self.config.get_llm_config(for_vision=False)
            vision_config = self.config.get_llm_config(for_vision=True)

            async with DualProviderClient(code_config, vision_config) as client:
                # Initialize phase 3 components
                matcher = ComponentMatcher(client, self.config)
                comparator = VisualComparator(client, self.config)
                repair = TargetedRepair(client, self.config)

                scores = []
                plateau_count = 0

                for iteration in range(self.config.max_iterations):
                    print(
                        f"\n[3.{iteration + 1}] Iteration {iteration + 1}/{self.config.max_iterations}"
                    )

                    # 3.1: Render and Extract
                    print("  Rendering...", end=" ")
                    screenshot, dom_tree, console_errors = await render_html(
                        str(component.html_path),
                        self.server.url("index.html"),
                        viewport_width=1280,
                        viewport_height=800,
                    )
                    print(f"✓ ({len(screenshot)} bytes, {len(console_errors)} errors)")

                    # Save screenshot
                    screenshot_path = component.output_dir / f"iter_{iteration + 1}.png"
                    with open(screenshot_path, "wb") as f:
                        f.write(screenshot)

                    # 3.2: Compute metrics
                    ref_img = load_image(component.reference_path)
                    gen_img = load_image(screenshot_path)
                    ssim_score, _ = compute_ssim(ref_img, gen_img)
                    scores.append(ssim_score)

                    # Structural metrics
                    structural = compute_all_metrics(dom_tree, component.tree)

                    print(f"  SSIM: {ssim_score:.3f}", end="")
                    if structural["treebleu"] is not None:
                        print(f" | TreeBLEU: {structural['treebleu']:.3f}", end="")
                    if structural["container_match"] is not None:
                        print(
                            f" | ContainerMatch: {structural['container_match']:.3f}",
                            end="",
                        )
                    print()

                    # Check convergence
                    if ssim_score >= self.config.ssim_threshold:
                        print(
                            f"  ✓ Converged at iteration {iteration + 1} (SSIM >= {self.config.ssim_threshold})"
                        )
                        break

                    # Check plateau
                    if len(scores) > self.config.plateau_patience:
                        recent_scores = scores[-self.config.plateau_patience :]
                        if (
                            max(recent_scores) - min(recent_scores)
                            < self.config.plateau_delta
                        ):
                            plateau_count += 1
                            if plateau_count >= 1:
                                print(
                                    f"  ⚠ Plateau detected - escalating to vision analysis"
                                )
                                # TODO: Trigger vision-based feedback
                        else:
                            plateau_count = 0

                    # 3.3: Component Matching and Comparison
                    print("  Comparing components...")
                    matches = await matcher.match(dom_tree, component.tree)
                    issues = await comparator.compare(
                        matches,
                        component,
                        rendered_screenshot_path=screenshot_path,
                    )

                    if not issues:
                        print("  ✓ No significant issues found")
                        break

                    print(f"  → Found {len(issues)} issues to repair")

                    # 3.4: Targeted Repair
                    print("  Repairing...")
                    new_html = await repair.repair(component, issues, dom_tree)

                    # Save repaired HTML
                    component.html_path.write_text(new_html, encoding="utf-8")

                    # Record iteration
                    from storage.component import Iteration

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

                # Final metrics
                final_ssim = scores[-1] if scores else 0.0
                component.final_ssim = final_ssim
                self.store.save(component)

                return {
                    "component_id": component.id,
                    "ssim": final_ssim,
                    "iterations": len(component.iterations),
                    "treebleu": component.iterations[-1].treebleu
                    if component.iterations
                    else None,
                    "container_match": component.iterations[-1].container_match
                    if component.iterations
                    else None,
                }

        finally:
            if self.server:
                self.server.stop()
