---
name: ui-cloner
description: Clone UI components from reference screenshots using a DesignCoder-inspired 3-phase hierarchy-aware pipeline. Generates plain CSS (no Tailwind).
version: 4.0.0
---

# UI Cloner

Clone a reference UI screenshot into an HTML component using a hierarchy-aware 3-phase pipeline.

## Architecture

The This project uses a **DesignCoder-inspired 3-phase pipeline** that extracts hierarchy information before generating code — unlike single-pass screenshot-to-code tools, it it3-phase approach produces structurally correct HTML, not "flat div soup."

```
ui-loop-test/
├── main.py                    # CLI entry point
├── loop.py                    # Pipeline orchestration
├── config.py                  # Provider & pipeline settings
├── llm_client.py              # OpenAI-compatible HTTP client
├── phases/
│   ├── phase1_grouping/
│   │   ├── division.py        # 1.1 UI Division
│   │   ├── semantic.py       # 1.2 Semantic Extraction
│   │   └── grouping.py        # 1.3 Component Grouping
│   ├── phase2_codegen/
│   │   ├── html_gen.py        # 2.1 HTML Generation
│   │   └── style_gen.py       # 2.2 Style Generation (plain CSS)
│   └── phase3_refinement/
│       ├── matcher.py          # 3.2 Component Matching
│       ├── comparator.py       # 3.3 Visual Comparison (per-component SSIM)
│       └── repair.py            # 3.4 Targeted Repair (BeautifulSoup)
├── utils/
│   ├── image.py               # SSIM, color extraction, diff overlay
│   ├── dom.py                 # Playwright DOM extraction
│   └── metrics.py             # TreeBLEU, ContainerMatch, TreeEditDist
├── storage/
│   └── component.py           # Component state persistence (JSON)
├── src/                       # SvelteKit viewer app
│   ├── routes/
│   │   ├── +page.svelte            # Component list
│   │   ├── component/[id]/        # Component detail + preview
│   │   └── api/components/     # REST API for component data
│   └── lib/
├── output/                   # Generated component files
└── ui-inspo/                  # Reference images to clone
```

## CLI Usage

```bash
# Install dependencies
pip install -r requirements.txt

# Set API keys
export OPENROUTER_API_KEY=your_key
export FIREWORKS_API_KEY=your_key

# Run the full 3-phase pipeline
python main.py ui-inspo/sample.png --name my-component

# Run specific phases
python main.py ui-inspo/sample.png --phase 1  # Just analyze structure
python main.py ui-inspo/sample.png --phase 2  # Just generate code
python main.py ui-inspo/sample.png --phase 3  # Just refine

# Use different providers
python main.py ui-inspo/sample.png --provider fireworks
python main.py ui-inspo/sample.png --provider openrouter --vision-provider fireworks
```

## How It Works

### Phase 1: UI Grouping Chain

1. **UI Division** — Partition screenshot into 3-10 semantic regions (nav, hero, footer, etc.)
2. **Semantic Extraction** — Label elements within each region (buttons, headings, images, etc.)
3. **Component Grouping** — Build a hierarchical component tree from flat elements

### Phase 2: Hierarchy-Aware Code Generation

1. **HTML Generation** — Generate HTML structure that mirrors the component tree exactly
2. **Style Generation** — Apply plain CSS styles based on bounding box geometry (no Tailwind)

### Phase 3: Self-Correcting Refinement

1. **Render & Extract** — Render HTML in Playwright, capture screenshot + DOM
2. **Component Matching** — Match rendered DOM elements to expected tree nodes
3. **Visual Comparison** — Per-component SSIM + optional vision-model analysis
4. **Targeted Repair** — Fix specific components via BeautifulSoup (no full-page rewrite)
5. **Iterate** until SSIM threshold or max iterations reached

## Rules

- **Plain CSS only** — no Tailwind, no utility classes, Use CSS custom properties and plain selectors.
- Use colors from `extract_colors` for the palette.
- The component tree from Phase 1 is the structural contract for Phase 2.
- Phase 3 uses per-component SSIM, not just global SSIM.
- Check the web UI (SvelteKit viewer) to see iteration history.
- User decides when done.

## View Progress

The SvelteKit viewer shows live progress:

1. **Home page**: `/` — List all components with status
2. **Component page**: `/component/[id]` — Preview, iterations, diffs, activity feed
3. **Test page**: `/test` — Phase 1 segmentation testing

Start the dev server:
```bash
npm run dev
```

## Configuration

Create a `.env` file:

```bash
OPENROUTER_API_KEY=sk-or-v1-...
FIREWORKS_API_KEY=fw-...
DEFAULT_PROVIDER=openrouter
```
