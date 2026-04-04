"""
UI Loop Test - Standalone UI Cloning Agent
==========================================

DesignCoder-inspired 3-phase hierarchy-aware pipeline for converting
UI screenshots to HTML components.

Usage:
    uv run python main.py ui-inspo/sample.png --name my-component
    uv run python main.py ui-inspo/sample.png --phase 1
    uv run python main.py ui-inspo/sample.png --max-iter 3

Output directory structure:
    ./output/{component_id}/
    ├── reference.png
    ├── component.json
    ├── pipeline.log
    ├── structured.log
    ├── artifacts/
    │   ├── phase1_detection_overlay.png
    │   ├── phase1_segmentation_overlay.png
    │   ├── phase1_tree.json
    │   ├── phase1_elements.json
    │   ├── phase2_colors.json
    │   └── phase3_metrics.json
    ├── region_*.png
    ├── index.html
    └── iter_*.png
"""

from pathlib import Path
from typing import Optional
import argparse
import asyncio

from log import setup_logging
from loop import AgentLoop
from config import Config
from storage.component import ComponentStore


def main():
    parser = argparse.ArgumentParser(
        description="UI Cloning Agent - Clone screenshots to HTML components"
    )
    parser.add_argument("image", type=str, help="Path to reference image to clone")
    parser.add_argument(
        "--name",
        "-n",
        type=str,
        default=None,
        help="Component name (default: derived from image filename)",
    )
    parser.add_argument(
        "--provider",
        "-p",
        type=str,
        choices=["openrouter", "fireworks"],
        default="openrouter",
        help="LLM provider to use (default: openrouter)",
    )
    parser.add_argument(
        "--vision-provider",
        type=str,
        choices=["openrouter", "fireworks", "gemini"],
        default="openrouter",
        help="Vision model provider (default: same as --provider)",
    )
    parser.add_argument(
        "--max-iter",
        type=int,
        default=8,
        help="Maximum refinement iterations (default: 8)",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=str,
        default="./output",
        help="Output directory for generated components",
    )
    parser.add_argument(
        "--phase",
        type=str,
        choices=["1", "2", "3", "all"],
        default="all",
        help="Run specific phase only (1=grouping, 2=codegen, 3=refinement)",
    )

    args = parser.parse_args()

    image_path = Path(args.image)
    if not image_path.exists():
        print(f"Error: Image not found: {image_path}")
        return 1

    name = args.name or image_path.stem

    config = Config(
        provider=args.provider,
        vision_provider=args.vision_provider or args.provider,
        max_iterations=args.max_iter,
        output_dir=Path(args.output_dir),
    )

    store = ComponentStore(config.output_dir)
    component = store.create(name, image_path)

    logger = setup_logging(component.output_dir)

    logger.info("=" * 60)
    logger.info(f"UI Cloning Agent - {name}")
    logger.info("=" * 60)
    logger.info(f"Reference:      {image_path}")
    logger.info(f"Component ID:   {component.id}")
    logger.info(f"Provider:       {config.provider}")
    logger.info(f"Vision:         {config.vision_provider}")
    logger.info(f"Max Iterations: {config.max_iterations}")
    logger.info(f"Output:         {component.output_dir}")
    logger.info(f"Log file:       {component.output_dir / 'pipeline.log'}")
    logger.info("=" * 60)

    loop = AgentLoop(config, store, logger)

    try:
        if args.phase == "1":
            result = asyncio.run(loop.run_phase1_only(component))
        elif args.phase == "2":
            result = asyncio.run(loop.run_phase2_only(component))
        elif args.phase == "3":
            result = asyncio.run(loop.run_phase3_only(component))
        else:
            result = asyncio.run(loop.run_full_pipeline(component))

        logger.info("=" * 60)
        logger.info("COMPLETE")
        logger.info("=" * 60)
        logger.info(f"Final SSIM:    {result.get('ssim', 'N/A')}")
        logger.info(f"Iterations:    {result.get('iterations', 0)}")
        logger.info(f"Output dir:    {component.output_dir}")
        logger.info(f"Pipeline log:  {component.output_dir / 'pipeline.log'}")

    except KeyboardInterrupt:
        logger.warning("Interrupted by user")
        return 130
    except Exception as e:
        logger.error(f"Pipeline failed: {e}")
        import traceback

        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
