#!/usr/bin/env bash
# start.sh — Verify ui-cloner environment is ready
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Load .env if present (for OPENROUTER_API_KEY)
if [ -f "$SCRIPT_DIR/.env" ]; then
    set -a
    source "$SCRIPT_DIR/.env"
    set +a
fi

cd "$SCRIPT_DIR"

echo "[check] Verifying tools..."
uv run --with-requirements agent/requirements.txt python -c "
from agent.tools import write_code, render_and_capture, visual_diff, extract_layout, extract_colors, scratchpad, vision_analyze
print('  All tools imported OK')
"

echo ""
echo "[ready] Run tools via: uv run --with-requirements agent/requirements.txt python -c '...'"
echo "[ready] Or load the ui-cloner skill in Hermes"
