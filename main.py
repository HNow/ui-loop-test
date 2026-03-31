"""
UI Loop Test - Standalone UI Cloning Agent
==========================================

DesignCoder-inspired 3-phase hierarchy-aware pipeline for converting
UI screenshots to HTML components.

Usage:
    python main.py ui-inspo/sample.png --name my-component
    python main.py ui-inspo/sample.png --phase 1  # Just grouping
    python main.py ui-inspo/sample.png --provider fireworks

Environment:
    OPENROUTER_API_KEY or FIREWORKS_API_KEY must be set

Architecture:
    Phase 1: UI Grouping Chain (vision models)
    Phase 2: Hierarchy-Aware Code Generation  
    Phase 3: Self-Correcting Refinement (render-compare-repair loop)

Output:
    ./output/{component_id}/
    ├── reference.png          # Original image
    ├── component.json         # Full state
    ├── index.html            # Generated HTML
    └── region_*.png          # Cropped regions
"""

from pathlib import Path
from typing import Optional
import argparse
import asyncio

from loop import AgentLoop
from config import Config
from storage.component import ComponentStore


def main():
    parser = argparse.ArgumentParser(
        description="UI Cloning Agent - Clone screenshots to HTML components"
    )
    parser.add_argument(
        "image",
        type=str,
        help="Path to reference image to clone"
    )
    parser.add_argument(
        "--name",
        "-n",
        type=str,
        default=None,
        help="Component name (default: derived from image filename)"
    )
    parser.add_argument(
        "--provider",
        "-p",
        type=str,
        choices=["openrouter", "fireworks"],
        default="openrouter",
        help="LLM provider to use (default: openrouter)"
    )
    parser.add_argument(
        "--vision-provider",
        type=str,
        choices=["openrouter", "fireworks", "gemini"],
        default="openrouter",
        help="Vision model provider (default: same as --provider)"
    )
    parser.add_argument(
        "--max-iter",
        type=int,
        default=8,
        help="Maximum refinement iterations (default: 8)"
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=str,
        default="./output",
        help="Output directory for generated components"
    )
    parser.add_argument(
        "--phase",
        type=str,
        choices=["1", "2", "3", "all"],
        default="all",
        help="Run specific phase only (1=grouping, 2=codegen, 3=refinement)"
    )
    
    args = parser.parse_args()
    
    # Validate image exists
    image_path = Path(args.image)
    if not image_path.exists():
        print(f"Error: Image not found: {image_path}")
        return 1
    
    # Derive name from filename if not provided
    name = args.name or image_path.stem
    
    # Load config
    config = Config(
        provider=args.provider,
        vision_provider=args.vision_provider or args.provider,
        max_iterations=args.max_iter,
        output_dir=Path(args.output_dir)
    )
    
    # Initialize storage
    store = ComponentStore(config.output_dir)
    component = store.create(name, image_path)
    
    print(f"=" * 60)
    print(f"UI Cloning Agent - {name}")
    print(f"=" * 60)
    print(f"Reference: {image_path}")
    print(f"Component ID: {component.id}")
    print(f"Provider: {config.provider}")
    print(f"Vision Provider: {config.vision_provider}")
    print(f"Max Iterations: {config.max_iterations}")
    print(f"=" * 60)
    
    # Run the loop
    loop = AgentLoop(config, store)
    
    try:
        if args.phase == "1":
            result = asyncio.run(loop.run_phase1_only(component))
        elif args.phase == "2":
            result = asyncio.run(loop.run_phase2_only(component))
        elif args.phase == "3":
            result = asyncio.run(loop.run_phase3_only(component))
        else:
            result = asyncio.run(loop.run_full_pipeline(component))
        
        print(f"\n{'=' * 60}")
        print(f"COMPLETE")
        print(f"{'=' * 60}")
        print(f"Final SSIM: {result.get('ssim', 'N/A')}")
        print(f"Iterations: {result.get('iterations', 0)}")
        print(f"Output: {component.output_dir}")
        
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        return 130
    except Exception as e:
        print(f"\n\nError: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
