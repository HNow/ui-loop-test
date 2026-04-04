"""
Phase 1 Debug Script
====================
Runs Phase 1 step-by-step, saves raw LLM responses for inspection.

Usage:
    uv run python scripts/debug_phase1.py ui-inspo/ui-booking-confirmation.jpg
    uv run python scripts/debug_phase1.py output/booking_xxx   (reuse existing component)
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
from phases.phase1_grouping.element_detection import ElementDetector
from phases.phase1_grouping.division import UIDivision, crop_and_save_regions
from phases.phase1_grouping.semantic import SemanticExtraction
from phases.phase1_grouping.grouping import ComponentGrouping


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
        # Step 1.0: Element Detection
        # ============================================================
        log.info("=" * 50)
        log.info("STEP 1.0 — Element Detection")
        log.info("=" * 50)
        detector = ElementDetector(client, config)
        t0 = time.time()
        elements = await detector.detect(component.reference_path)
        component.detected_elements = elements
        log.info(f"Detected {len(elements)} elements in {time.time() - t0:.1f}s")
        for e in elements:
            log.info(f"  {e.id:6s} {e.type:15s} bbox={e.bbox} text='{e.text[:40]}'")

        # ============================================================
        # Step 1.1: UI Division
        # ============================================================
        log.info("=" * 50)
        log.info("STEP 1.1 — UI Division")
        log.info("=" * 50)
        division = UIDivision(client, config)
        t0 = time.time()
        regions = await division.divide(component)
        log.info(f"Division took {time.time() - t0:.1f}s")

        regions = crop_and_save_regions(component, regions, component.reference_path)
        component.regions = regions
        log.info(f"  {len(regions)} regions:")
        for r in regions:
            log.info(
                f"    {r.id}: {r.name} bbox={r.bbox} elements={len(r.element_ids)}"
            )

        # Save segmentation overlay
        from PIL import Image, ImageDraw, ImageFont

        ref = Image.open(component.reference_path).convert("RGBA")
        overlay = ref.copy()
        draw = ImageDraw.Draw(overlay, "RGBA")
        palette = [
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
        try:
            font = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16
            )
        except Exception:
            font = ImageFont.load_default()
        for i, region in enumerate(regions):
            x, y, w, h = region.bbox
            c = palette[i % len(palette)]
            draw.rectangle(
                [x, y, x + w, y + h], fill=(*c, 50), outline=(*c, 255), width=3
            )
            draw.rectangle([x + 2, y + 2, x + 220, y + 24], fill=(0, 0, 0, 200))
            draw.text((x + 6, y + 4), f"{i}: {region.name}", fill="white", font=font)
        overlay.convert("RGB").save(artifacts / "phase1_segmentation_overlay.png")

        # ============================================================
        # Step 1.2: Semantic Extraction (with raw response logging)
        # ============================================================
        log.info("=" * 50)
        log.info("STEP 1.2 — Semantic Extraction")
        log.info("=" * 50)
        semantic = SemanticExtraction(client, config)
        elements_by_region = {}

        for region in regions:
            log.info(f"  Extracting region: {region.name}...")
            if not region.crop_path or not Path(region.crop_path).exists():
                log.warning(f"    No crop for {region.name}")
                elements_by_region[region.id] = []
                continue

            prompt = semantic._build_extraction_prompt(region.name)
            (raw_dir / f"semantic_prompt_{region.id}.txt").write_text(
                prompt, encoding="utf-8"
            )

            try:
                response = await client.vision_analyze(
                    prompt=prompt, images=[region.crop_path], temperature=0.2
                )
                raw_content = response.content
                (raw_dir / f"semantic_response_{region.id}.txt").write_text(
                    raw_content, encoding="utf-8"
                )
                log.info(f"    Raw response ({len(raw_content)} chars):")
                log.info(f"    {raw_content[:300]}...")

                elems = semantic._parse_extraction_response(raw_content, region.id)
                elems = semantic._deduplicate_elements(elems)
                elems = semantic._normalize_bboxes(elems, region)
                elements_by_region[region.id] = elems
                log.info(f"    Parsed {len(elems)} elements")
            except Exception as e:
                log.error(f"    FAILED: {e}")
                elements_by_region[region.id] = []

        total = sum(len(e) for e in elements_by_region.values())
        log.info(f"  Total: {total} elements across {len(elements_by_region)} regions")

        # Save elements JSON
        elem_data = {}
        for rid, elems in elements_by_region.items():
            elem_data[rid] = [
                {
                    "id": e.id,
                    "type": e.type,
                    "bbox": list(e.bbox),
                    "content": e.content_description,
                    "interactable": e.interactable,
                }
                for e in elems
            ]
        (artifacts / "phase1_elements.json").write_text(
            json.dumps(elem_data, indent=2), encoding="utf-8"
        )

        # ============================================================
        # Step 1.3: Component Grouping (with raw response logging)
        # ============================================================
        log.info("=" * 50)
        log.info("STEP 1.3 — Component Grouping")
        log.info("=" * 50)
        grouping = ComponentGrouping(client, config)

        for region in regions:
            elems = elements_by_region.get(region.id, [])
            if not elems:
                log.info(f"  Skipping {region.name}: no elements")
                continue

            log.info(f"  Grouping {region.name} ({len(elems)} elements)...")

            prompt = grouping._build_grouping_prompt(region.name, elems)
            (raw_dir / f"grouping_prompt_{region.id}.txt").write_text(
                prompt, encoding="utf-8"
            )

            try:
                response = await client.vision_analyze(
                    prompt=prompt,
                    images=[region.crop_path] if region.crop_path else [],
                    temperature=0.3,
                )
                raw_content = response.content
                (raw_dir / f"grouping_response_{region.id}.txt").write_text(
                    raw_content, encoding="utf-8"
                )
                log.info(f"    Raw response ({len(raw_content)} chars):")
                log.info(f"    {raw_content[:500]}")

                tree = grouping._parse_grouping_response(raw_content, region.id, elems)
                log.info(
                    f"    Parsed tree: {len(tree.elements)} nodes (expected {len(elems)})"
                )

                if len(tree.elements) < len(elems):
                    log.warning(
                        f"    Tree has {len(tree.elements)} nodes, expected {len(elems)}"
                    )
            except Exception as e:
                log.warning(f"    Vision grouping FAILED: {e}")
                log.info(f"    Using geometric fallback")
                tree = grouping._geometric_grouping(region.id, elems)
                log.info(f"    Geometric tree: {len(tree.elements)} nodes")

            tree = grouping._post_process_tree(tree, elems)
            log.info(f"    Post-processed: {len(tree.elements)} nodes")
            for eid, elem in tree.elements.items():
                log.info(
                    f"      {eid}: type={elem.type} parent={elem.parent_id} children={elem.children_ids}"
                )

        store.save(component)
        log.info(f"\nArtifacts saved to: {artifacts}")
        log.info(f"Raw LLM responses: {raw_dir}")
        log.info("Phase 1 debug complete")


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else "ui-inspo/ui-booking-confirmation.jpg"
    path = Path(arg)

    config = Config(provider="openrouter", output_dir=Path("./output"))

    if path.is_dir():
        comp_path = path / "component.json"
        if not comp_path.exists():
            print(f"No component.json in {path}")
            sys.exit(1)
        store = ComponentStore(config.output_dir)
        component = Component.from_dict(json.loads(comp_path.read_text()))
        print(f"Loaded existing component: {component.id}")
    elif path.suffix in (".jpg", ".jpeg", ".png", ".webp"):
        store = ComponentStore(config.output_dir)
        component = store.create(path.stem, path)
        print(f"Created new component: {component.id}")
    else:
        print(f"Usage: {sys.argv[0]} <image_path | output_dir>")
        sys.exit(1)

    asyncio.run(run(component, config, store))


if __name__ == "__main__":
    main()
