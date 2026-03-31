"""
Standalone iteration runner for the new 3-phase pipeline.

This script runs a single iteration of the pipeline (render, compare, save)
for a given component. It replaces the old run_iteration.py which referenced
the legacy agent.tools (now moved to legacy/).

Usage:
    python run_iteration.py <component_id> [--output-dir ./output]

Example:
    python run_iteration.py my-component_abc12345
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from config import Config
from storage.component import ComponentStore
from loop import AgentLoop


def main():
    parser = argparse.ArgumentParser(
        description="Run a single iteration for a component"
    )
    parser.add_argument("component_id", type=str, help="Component ID to iterate on")
    parser.add_argument(
        "--output-dir",
        "-o",
        type=str,
        default="./output",
        help="Output directory (default: ./output)",
    )
    args = parser.parse_args()

    config = Config(output_dir=Path(args.output_dir))
    store = ComponentStore(config.output_dir)

    component = store.load(args.component_id)
    if not component:
        print(f"Error: Component '{args.component_id}' not found in {args.output_dir}")
        sys.exit(1)

    if not component.html_path or not component.html_path.exists():
        print(f"Error: Component has no HTML file. Run Phase 2 first.")
        sys.exit(1)

    print(f"Running Phase 3 iteration for: {component.id}")
    print(f"Current SSIM: {component.final_ssim or 'N/A'}")

    loop = AgentLoop(config, store)
    result = asyncio.run(loop.run_phase3_only(component))

    print(f"\nResult:")
    print(f"  SSIM: {result.get('ssim', 'N/A')}")
    print(f"  Iterations: {result.get('iterations', 0)}")
    print(f"  TreeBLEU: {result.get('treebleu', 'N/A')}")
    print(f"  ContainerMatch: {result.get('container_match', 'N/A')}")


if __name__ == "__main__":
    main()
