# UI Loop Test

A standalone UI cloning agent that converts screenshots into pixel-accurate HTML/CSS using a DesignCoder-inspired 3-phase pipeline. Feed it a screenshot, get back a self-contained HTML page that looks like the original.

## Quick Start

```bash
# Install dependencies (using uv)
uv sync

# Install Playwright browsers (needed for rendering)
uv run playwright install chromium

# Set your API key
cp .env.example .env
# Edit .env and add your OPENROUTER_API_KEY

# Run the full pipeline
uv run python main.py ui-inspo/ui-booking-confirmation.jpg --name booking

# Or use VLLM single-shot codegen for a higher fidelity baseline
uv run python main.py ui-inspo/ui-booking-confirmation.jpg --name booking \
  --codegen-model qwen/qwen-2.5-vl-72b-instruct
```

## How It Works

The pipeline has three phases. Each phase feeds into the next, and the whole thing runs as an async loop.

### Phase 1: UI Grouping

Analyzes the screenshot to understand its structure before generating any code.

| Step | Module | What it does |
|------|--------|-------------|
| 1.0 | `element_detection.py` | Detect all UI elements (buttons, text, images, etc.) with bounding boxes |
| 1.1 | `division.py` | Partition the page into 3-10 semantic regions (navigation, hero, content-grid, etc.) using element positions to inform boundaries |
| 1.2 | `semantic.py` | Label each element with type, content, and interactability via a label-only path that preserves Phase 1.0 bounding boxes |
| 1.3 | `grouping.py` | Build a hierarchical component tree where parent-child relationships reflect visual containment |

Key details:
- Element detection runs *first* so region boundaries never split an element in half
- Regions use 0-1000 normalized coordinates from the model, rescaled to actual pixels
- Post-tightening overlap resolution handles cases where regions end up nested after bbox recomputation
- All coordinates are saved to `artifacts/` as overlay images for debugging

### Phase 2: Code Generation

Turns the component tree into HTML/CSS. Two modes:

**Tree-based (default):** Generates HTML per-region by walking the component tree. Each element gets a `data-elem-id` attribute and semantic HTML tag. Layout CSS (flex direction, gap, padding) is computed from bounding box geometry. Region roots are absolutely positioned within a page container.

**VLLM single-shot (`--codegen-model`):** Sends the full screenshot to a strong vision-language model in one call to generate the complete page. The output is sanitized (external URLs stripped, images replaced with placeholders) and wrapped in proper document structure. This typically produces a higher-fidelity baseline.

Both modes produce plain CSS only, no Tailwind.

### Phase 3: Self-Correcting Refinement

Iteratively improves the generated HTML by comparing it against the reference screenshot.

Each iteration:
1. Render the HTML via Playwright, screenshot it at reference dimensions
2. Compute per-region SSIM between reference and rendered
3. **Element closeup comparison**: for each Phase 1 element bbox, crop both reference and rendered at the same coordinates, compute per-element SSIM
4. Send the worst-scoring element closeups to VLLM for qualitative diff analysis
5. Targeted repair: fix specific components using the issue list + closeup crops as visual context
6. If SSIM drops, revert to best and stop; if SSIM plateaus, stop; if SSIM exceeds threshold, converge

Artifacts saved each iteration:
- `iter_N.png` — rendered screenshot
- `iter_N_diff.png` — per-region diff overlay
- `artifacts/iter_N_closeups/` — ref and gen crops for each element
- `artifacts/iter_N_element_comparison.json` — full per-element SSIM log

## Usage

```bash
# Full pipeline
uv run python main.py ui-inspo/sample.png --name my-component

# Specific phase
uv run python main.py ui-inspo/sample.png --phase 1   # grouping only
uv run python main.py ui-inspo/sample.png --phase 2   # codegen only
uv run python main.py ui-inspo/sample.png --phase 3   # refinement only

# VLLM codegen (single-shot from screenshot)
uv run python main.py ui-inspo/sample.png --codegen-model qwen/qwen-2.5-vl-72b-instruct

# Provider selection
uv run python main.py ui-inspo/sample.png --provider openrouter          # default
uv run python main.py ui-inspo/sample.png --provider fireworks
uv run python main.py ui-inspo/sample.png --vision-provider openrouter   # different model for vision

# Tuning
uv run python main.py ui-inspo/sample.png --max-iter 16 --output-dir ./my-output

# Run tests
uv run python -m pytest tests/ -v --tb=short
```

## Output Structure

```
output/{component_id}/
├── reference.png                          # Original screenshot
├── component.json                         # Full state (regions, tree, iterations, metrics)
├── pipeline.log                           # Detailed pipeline log
├── index.html                             # Generated HTML
├── region_*.png                           # Cropped region images from Phase 1
├── iter_*.png                             # Rendered screenshots per iteration
├── iter_*_diff.png                        # Per-region diff overlays
└── artifacts/
    ├── phase1_detection_overlay.png       # Element bboxes drawn on reference
    ├── phase1_segmentation_overlay.png    # Region bboxes with element outlines
    ├── phase1_drift_overlay.png           # Phase 1.0 vs 1.2 bbox drift
    ├── phase1_tree.json                   # Component tree structure
    ├── phase1_elements.json               # Per-region element data
    ├── phase2_colors.json                 # Extracted color palette
    ├── phase3_metrics.json                # SSIM/TreeBLEU/etc per iteration
    ├── iter_N_closeups/                   # Per-element ref+gen crops
    │   ├── elem_0_ref.png
    │   ├── elem_0_gen.png
    │   └── ...
    └── iter_N_element_comparison.json     # Per-element SSIM log
```

## Project Structure

```
├── main.py                     # CLI entry point
├── config.py                   # Configuration (providers, thresholds, codegen model)
├── loop.py                     # Main orchestration loop (Phase 1 → 2 → 3)
├── llm_client.py               # OpenAI-compatible HTTP client (OpenRouter/Fireworks)
├── log.py                      # Logging setup
│
├── phases/
│   ├── phase1_grouping/
│   │   ├── element_detection.py    # Pre-step: detect all UI elements with bboxes
│   │   ├── division.py             # 1.1: Partition into semantic regions
│   │   ├── semantic.py             # 1.2: Label elements (label-only path)
│   │   └── grouping.py            # 1.3: Build component tree
│   │
│   ├── phase2_codegen/
│   │   ├── html_gen.py            # 2.1: Tree-to-HTML + VLLM fullpage codegen
│   │   └── style_gen.py           # 2.2: Bbox-computed CSS + document assembly
│   │
│   └── phase3_refinement/
│       ├── element_comparator.py  # Per-element closeup SSIM + VLLM analysis
│       ├── repair.py              # Targeted component repair with closeup context
│       ├── matcher.py             # (legacy) DOM-to-tree matching
│       └── comparator.py          # (legacy) Per-component visual comparison
│
├── storage/
│   └── component.py               # Data models (Component, Region, Element, Tree, etc.)
│
├── utils/
│   ├── image.py                   # SSIM, color extraction, cropping, base64
│   ├── dom.py                     # Playwright rendering, DOM tree extraction
│   └── metrics.py                 # TreeBLEU, Container Match, Tree Edit Distance
│
├── tests/                         # 182 tests
│   ├── test_phase1.py
│   ├── test_phase2.py
│   ├── test_phase3.py
│   ├── test_metrics.py
│   ├── test_storage.py
│   └── test_utils.py
│
├── scripts/
│   ├── debug_phase1.py            # Standalone Phase 1 debugging
│   └── debug_phase2.py            # Standalone Phase 2 debugging
│
├── ui-inspo/                      # Input screenshots
├── output/                        # Generated output
├── requirements.txt
└── .env                           # API keys (not committed)
```

## Configuration

Create a `.env` file (or copy `.env.example`):

```bash
OPENROUTER_API_KEY=sk-or-v1-...
FIREWORKS_API_KEY=fw-...          # optional, only if using fireworks provider
```

Key config parameters (in `config.py`):

| Parameter | Default | Description |
|-----------|---------|-------------|
| `codegen_model` | `None` | VLLM model for single-shot codegen (e.g. `qwen/qwen-2.5-vl-72b-instruct`) |
| `max_iterations` | 32 | Max Phase 3 refinement iterations |
| `ssim_threshold` | 0.88 | Target SSIM to converge |
| `per_component_threshold` | 0.90 | Per-element SSIM threshold for flagging issues |
| `target_regions_min` / `max` | 3 / 10 | Region count bounds for Phase 1 |
| `plateau_patience` | 2 | Iterations of no improvement before stopping |

## Evaluation Metrics

Tracked per iteration:

| Metric | Range | Description |
|--------|-------|-------------|
| SSIM | 0-1 | Per-region structural similarity (mean across regions) |
| Per-element SSIM | 0-1 | Closeup SSIM at each detected element bbox |
| TreeBLEU | 0-1 | Proportion of matching height-1 subtrees |
| Container Match | 0-1 | Percentage of containers with structurally equivalent matches |
| Tree Edit Distance | 0+ | Min operations to transform generated tree to reference |

## Dependencies

```
aiohttp          # Async HTTP for API calls
playwright       # Browser rendering + DOM extraction
pillow           # Image processing
scikit-image     # SSIM computation
scikit-learn     # K-means color extraction
numpy            # Array ops
zss              # Zhang-Shasha tree edit distance
beautifulsoup4   # HTML parsing for targeted repair
python-dotenv    # .env file loading
```

## Design Decisions

- **No SDK dependencies** for LLM calls — pure HTTP to OpenRouter/Fireworks for flexibility
- **Plain CSS only** — no Tailwind utility classes, ever
- **Element detection first** — regions are informed by where elements actually are, not guessed from visual appearance
- **Label-only Phase 1.2** — bounding boxes from Phase 1.0 are preserved through semantic labeling, preventing coordinate drift
- **Per-element closeup comparison** — catches issues that whole-page SSIM averages away (a 10px button misalignment barely moves global SSIM)
- **Revert-if-worse** — if a repair iteration drops SSIM, the best HTML is restored and refinement stops
- **Dual/triple provider support** — different models for code gen, vision analysis, and VLLM codegen

## Known Limitations

- Works from raw screenshots only (no Figma metadata like original DesignCoder)
- Bounding boxes give approximate sizes, not pixel-perfect measurements
- Static HTML only (no JavaScript for interactive behaviors)
- TreeBLEU and Container Match metrics currently report 0.0 (known issue, see FUTURE-005 in TODO.md)
- Vision model quality directly impacts Phase 1 accuracy

## References

- **DesignCoder** (Chen et al., 2025) — Hierarchy-aware UI code generation
- **VIGA** — Write-run-render-compare-revise loop pattern
- **abi/screenshot-to-code** — Single-pass baseline comparison
