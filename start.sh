#!/usr/bin/env bash
# start.sh — Verify ui-cloner environment is ready
#
# Checks that the new 3-phase pipeline (main.py) can be imported
# and that the required environment variables are set.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Load .env if present (for OPENROUTER_API_KEY, FIREWORKS_API_KEY)
if [ -f "$SCRIPT_DIR/.env" ]; then
    set -a
    source "$SCRIPT_DIR/.env"
    set +a
fi

cd "$SCRIPT_DIR"

echo "[check] Verifying Python pipeline imports..."
.venv/bin/python -c "
from loop import AgentLoop
from config import Config
from storage.component import ComponentStore
from phases.phase1_grouping.division import UIDivision
from phases.phase1_grouping.semantic import SemanticExtraction
from phases.phase1_grouping.grouping import ComponentGrouping
from phases.phase2_codegen.html_gen import HTMLGenerator
from phases.phase2_codegen.style_gen import StyleGenerator
from phases.phase3_refinement.matcher import ComponentMatcher
from phases.phase3_refinement.comparator import VisualComparator
from phases.phase3_refinement.repair import TargetedRepair
from utils.image import compute_ssim, extract_colors, create_diff_overlay
from utils.dom import render_html, extract_dom_tree
from utils.metrics import compute_all_metrics
print('  All pipeline modules imported OK')
"

echo ""
echo "[check] Verifying API keys..."
if [ -n "$OPENROUTER_API_KEY" ]; then
    echo "  OPENROUTER_API_KEY: set"
else
    echo "  OPENROUTER_API_KEY: NOT SET (required for openrouter provider)"
fi

if [ -n "$FIREWORKS_API_KEY" ]; then
    echo "  FIREWORKS_API_KEY: set"
else
    echo "  FIREWORKS_API_KEY: not set (optional, for fireworks provider)"
fi

echo ""
echo "[check] Verifying npm dependencies..."
if [ -d "node_modules" ]; then
    echo "  node_modules: present"
else
    echo "  node_modules: missing — run 'npm install'"
fi

echo ""
echo "[ready] Run the pipeline:"
echo "  python main.py ui-inspo/sample.png --name my-component"
echo ""
echo "[ready] Run the SvelteKit viewer:"
echo "  npm run dev"
