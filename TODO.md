# UI Loop Test - Project TODO

Issue tracker and implementation checklist for the DesignCoder-inspired 3-phase UI cloning pipeline.

---

## Status Overview

| Phase | Status | Progress |
|-------|--------|----------|
| Phase 1: UI Grouping | ✅ Fixed | All regions group via vision; names normalized and deduped |
| Phase 2: Code Generation | ✅ Fixed | Hallucination validation, data-elem-id on all elements, viewport matches reference |
| Phase 3: Refinement | ✅ Fixed | data-elem-id selectors, top-5 severity cap, vision-context repair, baseline SSIM |
| Infrastructure | ✅ Fixed | Retries, timeouts, revert-if-worse, matching metrics |
| Tests | ✅ Complete | 140 tests passing (130 original + 10 BUG-008 label-only) |

**Overall: All Implementation, Tests, and Bug Fixes Complete (BUG-001 through BUG-008)**

---

## Quick Reference

### Running the Pipeline
```bash
# Install dependencies
pip install -r requirements.txt
playwright install chromium

# Set API keys
export OPENROUTER_API_KEY=your_key
export FIREWORKS_API_KEY=your_key

# Run full pipeline
python main.py ui-inspo/sample.png --name my-component

# Run specific phase
python main.py ui-inspo/sample.png --phase 1  # Just analyze structure
python main.py ui-inspo/sample.png --phase 2  # Just generate code
python main.py ui-inspo/sample.png --phase 3  # Just refine

# Use different providers
python main.py ui-inspo/sample.png --provider fireworks
python main.py ui-inspo/sample.png --provider openrouter --vision-provider fireworks
```

### Project Structure
```
ui-loop-test/
├── main.py              # CLI entry point
├── loop.py              # Main orchestration (AgentLoop)
├── config.py            # Settings & providers
├── llm_client.py        # OpenAI-compatible HTTP client
├── storage/             # Component state management (JSON)
├── utils/               # Image, DOM, metrics utilities
├── phases/              # 3-phase pipeline
│   ├── phase1_grouping/ # Division, Semantic, Grouping
│   ├── phase2_codegen/  # HTML + plain CSS generation
│   └── phase3_refinement/ # Matching, Comparison, Repair (BeautifulSoup)
├── tests/               # Unit tests (130 tests, all passing)
│   ├── test_phase1.py   # Phase 1: grouping + semantic extraction
│   ├── test_phase2.py   # Phase 2: HTML + style generation
│   ├── test_phase3.py   # Phase 3: matching, comparison, repair
│   ├── test_metrics.py  # TreeBLEU, ContainerMatch, conversions
│   ├── test_storage.py  # Component/Store serialization round-trip
│   └── test_utils.py    # DOMNode, image crop/resize/base64
├── src/                # SvelteKit viewer app
├── SKILL.md            # Agent skill documentation
├── TODO.md             # This file
└── legacy/             # Old agent tools (moved from agent/)
```

---

## Implementation Complete

All phases of the DesignCoder-inspired pipeline are implemented:

- [x] **Phase 1.1**: UIDivision - Segments UI into 3-10 semantic regions
- [x] **Phase 1.2**: SemanticExtraction - Labels elements with types
- [x] **Phase 1.3**: ComponentGrouping - Builds hierarchical tree (with cycle detection, conflict resolution, geometric fallback)
- [x] **Phase 2.1**: HTMLGenerator - Creates HTML from tree structure
- [x] **Phase 2.2**: StyleGenerator - Applies plain CSS (no Tailwind)
- [x] **Phase 3.2**: ComponentMatcher - Matches DOM to expected tree (class/tag/position)
- [x] **Phase 3.3**: VisualComparator - Per-component SSIM + vision analysis
- [x] **Phase 3.4**: TargetedRepair - Fixes specific components via BeautifulSoup

---

## Completed Items

- [x] **ARCH-001**: Create project structure with phases/, utils/, storage/
- [x] **ARCH-002**: Implement config.py with dual provider support (OpenRouter, Fireworks)
- [x] **ARCH-003**: Implement llm_client.py (OpenAI-compatible, async, no SDK)
- [x] **ARCH-004**: Implement storage/component.py (Component, Region, Element, ComponentTree)
- [x] **ARCH-005**: Implement utils/image.py (SSIM, color extraction, diff overlay)
- [x] **ARCH-006**: Implement utils/dom.py (Playwright DOM extraction + screenshot)
- [x] **ARCH-007**: Implement utils/metrics.py (TreeBLEU, ContainerMatch, TreeEditDistance)
- [x] **ARCH-008**: Implement loop.py orchestrator (AgentLoop with phase selection)
- [x] **ARCH-009**: Implement main.py entry point (argparse CLI)
- [x] **ARCH-010**: Create phase module skeletons with real algorithms
- [x] **ARCH-011**: Move old agent tools to legacy/
- [x] **ARCH-012**: Move old docs to legacy/
- [x] **SETUP-001**: Create requirements.txt with all dependencies
- [x] **SETUP-002**: Add __init__.py files to all packages
- [x] **SETUP-003**: Create .env.example with API key placeholders
- [x] **SETUP-004**: Verify imports work via start.sh
- [x] **FIX-001**: Replace hardcoded SSIM 0.5 with real per-component SSIM computation in comparator.py
- [x] **FIX-002**: Fix start.sh to verify new pipeline imports instead of broken agent.tools references
- [x] **FIX-003**: Reconcile Tailwind/plain CSS across all documentation (README, TODO, SKILL.md, __init__.py)
- [x] **FIX-004**: Replace fragile regex HTML manipulation in repair.py with BeautifulSoup
- [x] **FIX-005**: Add SvelteKit missing files (+layout.svelte, app.d.ts)
- [x] **FIX-006**: Update SKILL.md to reflect 3-phase pipeline instead of old agent tools
- [x] **FIX-007**: Clean up dead code (run_iteration.py references to legacy agent.tools)
- [x] **FIX-008**: Pass rendered_screenshot_path to comparator in loop.py for real per-component SSIM

---

## Tests Complete (140 tests, all passing)

- [x] **TEST-001**: Unit tests for Phase 1.3 tree construction (geometric grouping, orphan resolution, cycle detection)
- [x] **TEST-002**: Unit tests for Phase 1.2 semantic extraction (deduplication, type validation)
- [x] **TEST-003**: Unit tests for Phase 2.1 HTML generation (tag mapping, class names, recursive fallback, subtree extraction)
- [x] **TEST-004**: Unit tests for Phase 2.2 style generation (layout computation: flex direction, gap, CSS generation, document assembly)
- [x] **TEST-005**: Unit tests for Phase 3.3 visual comparison (severity classification, issue categorization, JSON parsing)
- [x] **TEST-006**: Unit tests for Phase 3.4 targeted repair (BeautifulSoup extraction/replacement, CSS pixel parsing, prompt building)
- [x] **TEST-007**: Unit tests for Phase 3.2 component matching (class/semantic/position strategies, index building)
- [x] **TEST-008**: Verify metrics implementations (TreeBLEU, ContainerMatch, TreeEditDist, DOM/component-tree conversions)
- [x] **TEST-009**: Storage round-trip tests (Component to_dict/from_dict, ComponentStore create/save/load/list)
- [x] **TEST-010**: Utils tests (DOMNode tree string, dict conversion, image crop/resize/base64)
- [x] **TEST-011**: BUG-008 label-only path tests (_parse_label_response, _build_label_only_prompt, _label_existing_elements, extract with region_detections)

---

## Future Development

### P0: Critical
- [ ] **FUTURE-001**: Upgrade to stronger vision model for Phase 2 code generation
- [ ] **FUTURE-002**: Add full-page single-pass HTML generation (alternative to per-region)
- [ ] **FUTURE-003**: Add visual context to Phase 3 repair (pass region crops to repair prompt)

### P1: High Priority
- [ ] **FUTURE-004**: Add more sample images to ui-inspo/ (dashboards, landing pages, forms, e-commerce)
- [ ] **FUTURE-005**: Fix TreeBLEU/ContainerMatch metrics (currently always 0.0)
- [ ] **FUTURE-006**: Add checkpoint/resume functionality (save state after each phase)

### P2: Medium Priority
- [ ] **FUTURE-007**: Add example usage script with sample image
- [ ] **FUTURE-008**: Add heatmap diff overlay (alternative to magenta overlay)
- [ ] **FUTURE-009**: Add video/interactive UI capture mode

---

## Persisting Bugs & Issues

### BUG-009: Collage layout + meaningless SSIM (IN PROGRESS)

**Symptom:** Rendered `iter_N.png` images show components as a vertical collage (spread out, left-aligned) instead of positioned where they belong. The `iter_N_diff.png` images are entirely magenta because the collage is compared against the full reference image. SSIM scores are meaningless, so the repair loop cannot converge.

**Root Cause (2 parts):**

1. **Phase 2 has no positioning CSS:** `style_gen.py` only emits `flex/gap/padding` for containers within regions. Region root elements have accurate bboxes from Phase 1 but are never positioned absolutely. HTML fragments are concatenated into `<body>` in normal document flow.

2. **Phase 3 uses whole-page SSIM:** `loop.py:614-616` compares the full rendered screenshot against the full reference image. When layouts don't match, this comparison is noise. The per-component SSIM in `comparator.py` works correctly but only drives issue detection, not the convergence metric.

**Fix plan (4 steps):**

- [ ] **FIX-A** `style_gen.py` — Absolute positioning for region roots:
  - Page root gets `position: relative; width: {W}px; height: {H}px`
  - Each region root gets `position: absolute; left/top/width/height` from Phase 1 bboxes
  - Wrap concatenated fragments in `<div data-elem-id="page_root">`
  - Body background uses dominant palette color instead of `#ffffff`

- [ ] **FIX-B** `loop.py` — Per-region SSIM:
  - New `_compute_per_region_ssim()` method crops ref + rendered at region bboxes
  - Replace whole-page SSIM with per-region average as primary convergence metric
  - Log whole-page SSIM as secondary info

- [ ] **FIX-C** `loop.py` — Per-region diff overlay:
  - `_save_phase3_diff` computes diff per region at its bbox position
  - Areas outside regions stay clean (no meaningless magenta)

- [ ] **FIX-D** `tests/test_phase2.py` — Update tests:
  - Test `_compute_layout_styles` returns `is_page_root` for page-type elements
  - Test `_generate_custom_css` emits `position: absolute` for region roots
  - Update background color assertion

---

### BUG-008: Bounding box offset pipeline (CLOSED — Sprint complete)

**Symptom:** Output photos show bounding boxes systematically offset from actual UI elements. Mean Y drift +301px, max +602px.

**Root Cause (architectural):** Phase 1.2 (`SemanticExtraction`) re-detects bboxes from crops instead of labeling Phase 1.0 detections. The vision model hallucinates elements outside crop bounds. Cross-validation and clamping are band-aids — the fundamental problem is that Phase 1.2 should only label, not re-detect. The DesignCoder paper gets exact bboxes from Figma; Phase 1.0 is our Figma.

**Sprint plan (4 priorities) — ALL COMPLETE:**

- [x] **SPRINT-1** `semantic.py` — Rewrite `extract()` with label-only path:
  - New `_label_existing_elements()`: receives region-filtered `DetectedElement` list, converts to `Element` with Phase 1.0 bboxes (absolute), sends crop + element list to model for type/description/interactable classification only
  - New prompt: "Here are N elements at known positions. Classify each." — model returns type/content/interactable, NOT bboxes
  - Falls back to old re-detection path when no Phase 1.0 detections available
  - `_normalize_bboxes` + `_cross_validate_bboxes` only used in fallback path
  - Stats include `method: "label-only"` or `method: "re-detect"`

- [x] **SPRINT-2** `loop.py` — Wire region detections into `extract()`:
  - Build `region_detections` map from `filter_elements_for_region`
  - Pass into `semantic.extract()` as new parameter
  - Update drift logging to reflect method used

- [x] **SPRINT-3** `division.py` — Tighten `_ensure_vertical_tiling`:
  - Replace aggressive gap absorption with 20px max gap fill threshold
  - Leave larger gaps unfilled (log warning)
  - Only extend last region to page bottom

- [x] **SPRINT-4** `grouping.py` — Tighten `_compute_container_bboxes` drift guard:
  - Replace 3x parent-size multiplier with 2x child-size + 200px absolute cap
  - Log skipped children with IDs and drift magnitude

**Tests added (10 new):**
- `_parse_label_response`: valid JSON, no JSON, trailing commas, missing index
- `_build_label_only_prompt`: prompt contains region name, indices, text
- `_label_existing_elements`: bbox preservation, fallback on bad response
- `extract`: label-only path, skip when no detections/crop, mixed modes

**Previous band-aid fixes (still in code, used by fallback path only):**
- [x] ~~FIX-A~~: `semantic.py` — clamp elements to region bounds (now fallback-only)
- [x] ~~FIX-B~~: `semantic.py` — cross-validate bboxes (now fallback-only)
- [x] ~~FIX-C~~: `grouping.py` — drift guard in `_compute_container_bboxes`
- [x] ~~FIX-D~~: `storage/component.py` + `loop.py` — `bbox_drift_stats` field
- [x] ~~FIX-E~~: `loop.py` — drift overlay visualization

---

## Recently Fixed (Session 2026-03-31)

| Bug | Description | Fix |
|-----|-------------|-----|
| Grouping parser crash | `grouping.py` lines 234-248 had corrupted syntax from failed edit | Restored clean `_parse_grouping_response`, added bracket-stripping ID matching |
| Grouping prompt IDs | Prompt used `"child-1"` examples; LLM returned `"[0]"` which didn't match lookup keys `"0"` | Changed example to use `"0"`, `"1"` index IDs; added `raw_id.strip("[]()")` |
| Strict validation ValueError | `group()` raised when tree had fewer nodes than elements | Changed to warning; unmatched elements attached to root |
| HTML gen no vision | `html_gen.py` used `code_complete` (text-only) for HTML generation | Switched to `vision_analyze` with region crop images |
| `sub_tree` NameError | `_build_tree_to_html_prompt` referenced `sub_tree` instead of `tree` parameter | Fixed variable reference |
| LLM client no retries | `llm_client.py` had 300s default timeout, zero retries | Added 600s timeout, 3 retries with exponential backoff (10s/30s/60s) |
| Phase 3 no revert | Repair loop always degraded HTML with no recovery | Added revert-if-worse: saves best HTML, reverts + breaks on SSIM drop > 0.01 |
| CSS class mismatch | CSS used generic type names (`.container`) that didn't match LLM HTML classes | Changed to `[data-elem-id]` selectors (partially working — see BUG-003) |
| BUG-001: LLM hallucinated HTML | Vision model invented Unsplash images, wrong text, extra sections not in tree | Added `_validate_html` post-processing in `html_gen.py`: strips external URLs, replaces external `<img>` with placeholder divs, removes elements with invalid `data-elem-id`, neutralizes external links |
| BUG-002: Phase 3 repair degraded quality | Repair replaced wrong elements (type-based selectors), no visual context, too many repairs per iteration | 1) `_extract_component_html` now prioritises `data-elem-id` selectors; 2) Repairs limited to top-5 highest-severity components via `MAX_REPAIRS_PER_ITERATION`; 3) Uses `vision_analyze` with region crop for visual context instead of blind `code_complete` |
| BUG-003: CSS `[data-elem-id]` selectors dead code | Fallback `_tree_to_html_recursive` didn't emit `data-elem-id` attrs, so layout CSS from bounding boxes never applied | Added `data-elem-id` attribute to every element in `_tree_to_html_recursive`; updated stale tests to expect `[data-elem-id]` selectors |
| BUG-004: Small screenshot size (18KB render) | Viewport hardcoded to 1280x800 but reference was 1200x1500; SSIM penalised by stretch/squish | `loop.py` now reads reference image dimensions and passes them as viewport size to `render_html`; `style_gen.py` body changed from `width: 1200px` to `width: 100%; min-height: 100vh` |
| BUG-005: Region division inconsistency | LLM named regions inconsistently ("Header" vs "Nav", duplicated "form-section") | Added `_normalize_region_names` in `division.py`: canonical alias map (28 entries), lowercase/strip, dedup with `-2` suffix |
| BUG-006: TreeBLEU/ContainerMatch always 0.0 | `dom_to_tree_node` used `tag.class` labels, `component_tree_to_tree_node` used `type.id` labels — different vocabularies, zero matches | Both now use bare semantic type labels; added `_TAG_TO_TYPE` reverse map (HTML tag → semantic type) in `metrics.py` |
| BUG-007: `best_ssim` starts at 0.0 | Phase 3 `best_ssim` initialized to 0.0; first iteration always became "best" even with mediocre SSIM | `loop.py` now renders Phase 2 output before the repair loop to establish baseline SSIM; `best_ssim` and `best_html` seeded from that render |
| BUG-003 regression: bbox CSS breaks layout | BUG-003 fix connected `data-elem-id` attrs to CSS, but `_generate_custom_css` set explicit pixel `width`/`height` from bounding boxes on every element — broke flex layout (nav forced to 57px wide, etc.) | Removed `width`/`height` from CSS output; only flex direction, gap, and padding are emitted — elements now size from content within flex containers |

---

## Old Entries (Pre-Session)2026-03-31)

```bash
# Quick import test
python -c "from phases.phase1_grouping.grouping import ComponentGrouping; print('OK')"

# Run tests
python -m pytest tests/ -v

# Run full pipeline test
python main.py ui-inspo/sample.png --name test

# Run specific phase only
python main.py ui-inspo/sample.png --name test --phase 1
```

---

## API Key Setup

```bash
# Create .env file
echo "OPENROUTER_API_KEY=your_key" > .env
echo "FIREWORKS_API_KEY=your_key" >> .env

# Or export directly
export OPENROUTER_API_KEY=your_key
export FIREWORKS_API_KEY=your_key
```

---

*Last updated: 2026-04-03*
