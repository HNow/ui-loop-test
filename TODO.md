# UI Loop Test - Project TODO

DesignCoder-inspired 3-phase UI cloning pipeline: screenshot → HTML/CSS.

---

## Status Overview

| Phase | Status | Notes |
|-------|--------|-------|
| Phase 1: UI Grouping | ✅ Stable | Element detection, region division, semantic labeling, component tree |
| Phase 2: Code Generation | ✅ Stable | VLLM single-shot codegen via `--codegen-model`, tree-based as default fallback |
| Phase 3: Refinement | 🔧 BUG-010 | Per-element repair broken (ID mismatch), replacing with full-page repair |
| Infrastructure | ✅ Stable | Retries, timeouts, revert-if-worse, per-region SSIM |
| Tests | ✅ 197 passing | Includes BUG-008/009, VLLM codegen, element closeup comparator, full-page repair tests |

---

## Quick Reference

```bash
# Run full pipeline (tree-based codegen)
uv run python main.py ui-inspo/sample.png --name my-component

# Run with VLLM codegen (higher fidelity baseline)
uv run python main.py ui-inspo/sample.png --name my-component --codegen-model qwen/qwen-2.5-vl-72b-instruct

# Run specific phase
uv run python main.py ui-inspo/sample.png --phase 1
uv run python main.py ui-inspo/sample.png --phase 2
uv run python main.py ui-inspo/sample.png --phase 3

# Run tests
uv run python -m pytest tests/ -v --tb=short
```

---

## Active Work

### IMPROVE-002: Simplify Codegen + Fix Bbox Offset + Bbox Overlay Comparison

**Problem:** VLLM codegen prompt is stuffed with Phase 1 metadata (elements, colors, regions) that hurts output quality vs a bare "clone this UI" prompt on OpenRouter. Bbox rescaling heuristic breaks on images < 1000px. Phase 3 comparison uses pixel-level SSIM which misses structural/positional issues.

- [ ] **2.1** `html_gen.py` — Simplify `_build_vllm_prompt()`, strip all Phase 1 metadata
- [ ] **2.2** `element_detection.py` — Remove `image_exceeds` gate from bbox rescaling
- [ ] **2.3** `division.py` — Same rescaling fix
- [ ] **2.4** New `bbox_comparator.py` — `BboxOverlayComparator` with spatial IoU matching + overlay images
- [ ] **2.5** `loop.py` — Swap to `BboxOverlayComparator`, pass `dom_tree`
- [ ] **2.6** Tests for all changes

### BUG-010: Phase 3 Repair No-Op — Full-Page Repair (DONE)

- [x] **10.1** `repair.py` — `FullPageRepair` class
- [x] **10.2** `loop.py` — Swap `TargetedRepair` for `FullPageRepair`
- [x] **10.3** Tests (15 new, 197 total)

---

## Completed Work

### IMPROVE-001: VLLM Baseline + Element Closeup Comparison + Region Overlap Fix (DONE)

#### Part A: Region Overlap Fix — DONE
- [x] A.1–A.4: Post-tighten overlap resolution in `division.py`

#### Part B: VLLM Single-Shot Codegen — DONE
- [x] B.1–B.7: `--codegen-model` flag, `codegen_from_vision()`, VLLM prompt, sanitization

#### Part C: Element-Level Closeup Comparison — DONE
- [x] C.1–C.8: `ElementCloseupComparator`, per-element SSIM, VLLM closeup analysis, repair integration

---

## Completed Bugs

### BUG-009: Collage layout + meaningless SSIM (CLOSED)

Region roots now get absolute positioning CSS. Per-region SSIM replaces whole-page SSIM. Per-region diff overlay replaces all-magenta. 5 new tests added.

### BUG-008: Bounding box offset pipeline (CLOSED)

Phase 1.2 rewritten with label-only path. 0-1000 normalized coordinate rescaling. Region tightening. 10 new tests.

### BUG-001 through BUG-007 (CLOSED)

See git history. All resolved across sessions 2026-03-31 to 2026-04-03.

---

## Future Development

- [ ] **FUTURE-004**: Add more sample images to ui-inspo/
- [ ] **FUTURE-005**: Fix TreeBLEU/ContainerMatch metrics (currently always 0.0)
- [ ] **FUTURE-006**: Add checkpoint/resume functionality
- [ ] **FUTURE-008**: Add heatmap diff overlay

---

*Last updated: 2026-04-04*
