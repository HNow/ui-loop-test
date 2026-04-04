"""
Phase 2 Debug Script
====================
Runs Phase 2 in isolation using existing Phase 1 artifacts.
Saves raw LLM responses and the generated HTML for inspection.

Usage:
    uv run python scripts/debug_phase2.py output/<component_dir>
"""

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from log import setup_logging
from config import Config
from llm_client import DualProviderClient
from storage.component import Component, ComponentStore
from utils.image import load_image, extract_colors, compute_ssim, save_image
from phases.phase2_codegen.html_gen import HTMLGenerator
from phases.phase2_codegen.style_gen import StyleGenerator


async def run(component: Component, config: Config, store: ComponentStore):
    log = setup_logging(component.output_dir)
    artifacts = component.output_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    raw_dir = artifacts / "raw_llm"
    raw_dir.mkdir(parents=True, exist_ok=True)

    code_cfg = config.get_llm_config(for_vision=False)
    vision_cfg = config.get_llm_config(for_vision=True)

    async with DualProviderClient(code_cfg, vision_cfg) as client:
        # ============================================================
        # Color Extraction
        # ============================================================
        log.info("=" * 50)
        log.info("Color Palette Extraction")
        log.info("=" * 50)
        colors = extract_colors(component.reference_path)
        for c in colors[:6]:
            log.info(f"  {c['hex']} ({c['coverage_pct']:.1f}%)")

        # ============================================================
        # HTML Generation — inspect raw LLM responses
        # ============================================================
        log.info("=" * 50)
        log.info("HTML Generation (Phase 2.1)")
        log.info("=" * 50)
        html_gen = HTMLGenerator(client, config)

        region_roots = html_gen._get_region_roots(component.tree)
        html_fragments = []

        for region_root_id, region in region_roots:
            log.info(f"  Region: {region.name} (root={region_root_id})")

            sub_tree = html_gen._extract_subtree(component.tree, region_root_id)
            log.info(f"    Sub-tree: {len(sub_tree.elements)} elements")

            prompt = html_gen._build_tree_to_html_prompt(region.name, sub_tree, colors)
            (raw_dir / f"phase2_html_prompt_{region.id}.txt").write_text(
                prompt, encoding="utf-8"
            )

            log.info(f"    Prompt length: {len(prompt)} chars")

            try:
                from llm_client import Message

                response = await client.code_complete(
                    messages=[Message.text("user", prompt)],
                    temperature=0.2,
                )
                raw = response.content
                (raw_dir / f"phase2_html_response_{region.id}.txt").write_text(
                    raw, encoding="utf-8"
                )
                log.info(f"    Response length: {len(raw)} chars")
                log.info(f"    Preview: {raw[:200]}...")

                html = html_gen._extract_html(raw)
                log.info(f"    Extracted HTML: {len(html)} chars")
            except Exception as e:
                log.error(f"    FAILED: {e}")
                html = ""

            html_fragments.append(
                {
                    "region_id": region.id,
                    "region_name": region.name,
                    "html_fragment": html,
                    "root_element_id": region_root_id,
                }
            )

        # ============================================================
        # Style Generation — inspect layout computation
        # ============================================================
        log.info("=" * 50)
        log.info("Style Generation (Phase 2.2)")
        log.info("=" * 50)
        style_gen = StyleGenerator(client, config)

        layout_styles = {}
        for elem_id in component.tree.elements:
            styles = style_gen._compute_layout_styles(elem_id, component.tree)
            if styles.get("display") == "flex":
                layout_styles[elem_id] = styles
                elem = component.tree.elements[elem_id]
                log.info(
                    f"  {elem_id} ({elem.type}): "
                    f"display={styles['display']} dir={styles['flex_direction']} "
                    f"w={styles['width']} h={styles['height']} "
                    f"gap={styles['gap']} padding={styles['padding']}"
                )

        custom_css = style_gen._generate_custom_css(
            component.tree, layout_styles, colors
        )
        log.info(f"  Custom CSS: {len(custom_css)} chars")
        log.info(f"  CSS rules: {custom_css[:500]}")
        (artifacts / "phase2_custom_css.txt").write_text(custom_css, encoding="utf-8")

        # ============================================================
        # Assemble and save HTML
        # ============================================================
        full_html = style_gen._assemble_document(
            "\n".join(f["html_fragment"] for f in html_fragments),
            custom_css,
            colors,
        )
        html_path = component.output_dir / "index_debug.html"
        html_path.write_text(full_html, encoding="utf-8")
        log.info(f"  Full HTML saved: {html_path.name} ({len(full_html)} chars)")

        # ============================================================
        # Render and compute SSIM
        # ============================================================
        log.info("=" * 50)
        log.info("Render & SSIM Check")
        log.info("=" * 50)

        import subprocess
        import http.server
        import threading

        server_proc = subprocess.Popen(
            [
                "python",
                "-m",
                "http.server",
                "8765",
                "--directory",
                str(component.output_dir),
                "--bind",
                "127.0.0.1",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(0.5)

        try:
            from utils.dom import render_html

            screenshot, dom_tree, console_errors = await render_html(
                str(html_path),
                "http://127.0.0.1:8765/index_debug.html",
                viewport_width=1280,
                viewport_height=800,
            )

            screenshot_path = component.output_dir / "debug_phase2.png"
            with open(screenshot_path, "wb") as f:
                f.write(screenshot)

            ref_img = load_image(component.reference_path)
            gen_img = load_image(screenshot_path)
            ssim_score, _ = compute_ssim(ref_img, gen_img)

            log.info(f"  SSIM: {ssim_score:.4f}")
            log.info(f"  Console errors: {len(console_errors)}")
            for err in console_errors[:5]:
                log.info(f"    {err}")

            log.info(f"  DOM tree:\n{dom_tree.to_tree_string()[:500]}")
        finally:
            server_proc.terminate()
            server_proc.wait()

        log.info("Phase 2 debug complete")


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if not arg:
        print(f"Usage: {sys.argv[0]} <output_dir>")
        print("  Provide the component output directory from a Phase 1 run.")
        sys.exit(1)

    path = Path(arg)
    comp_path = path / "component.json"
    if not comp_path.exists():
        print(f"No component.json in {path}")
        sys.exit(1)

    config = Config(provider="openrouter", output_dir=Path("./output"))
    store = ComponentStore(config.output_dir)
    component = Component.from_dict(json.loads(comp_path.read_text()))

    if not component.tree:
        print("Component has no tree — run Phase 1 first")
        sys.exit(1)

    print(f"Loaded component: {component.id}")
    print(
        f"Tree: {len(component.tree.elements)} nodes, {len(component.tree.regions)} regions"
    )

    asyncio.run(run(component, config, store))


if __name__ == "__main__":
    main()
