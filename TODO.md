# UI Loop Test - Project TODO

Issue tracker and implementation checklist for the DesignCoder-inspired 3-phase UI cloning pipeline.

---

## Status Overview

| Phase | Status | Progress |
|-------|--------|----------|
| Phase 1: UI Grouping | ✅ Complete | 100% |
| Phase 2: Code Generation | ✅ Complete | 100% |
| Phase 3: Refinement | ✅ Complete | 100% |
| Infrastructure | ✅ Complete | 100% |
| Documentation | ✅ Complete | 100% |
| Tests | ✅ Complete | 100% |

**Overall: All Implementation and Tests Complete**

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

## Tests Complete (130 tests, all passing)

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

---

## For Future Development

### P0: Critical
- [ ] **FUTURE-001**: Add OmniParser V2 integration for Phase 1 element detection
- [ ] **FUTURE-002**: Add checkpoint/resume functionality (save state after each phase)
- [ ] **FUTURE-003**: Add parallel component comparison in Phase 3

### P1: High Priority
- [ ] **FUTURE-004**: Add more sample images to ui-inspo/ (dashboards, landing pages, forms, e-commerce)
- [ ] **FUTURE-005**: Add CLIP Score metric for perceptual similarity
- [ ] **FUTURE-006**: Add progress logging with color-coded output and progress bars

### P2: Medium Priority
- [ ] **FUTURE-007**: Add example usage script with sample image
- [ ] **FUTURE-008**: Add heatmap diff overlay (alternative to magenta overlay)
- [ ] **FUTURE-009**: Add video/interactive UI capture mode

---

## Known Limitations

1. **No Metadata**: Unlike original DesignCoder (Figma input), we work from raw screenshots only
2. **Approximate Layout**: Bounding boxes give approximate sizes, not exact measurements
3. **Vision Model Dependency**: Phase 1 quality depends on vision model's region detection
4. **No Interactions**: Generates static HTML only (no JavaScript for interactive behaviors)
5. **Single Sample Image**: Only one reference image in ui-inspo/ currently

---

## Development Workflow

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

*Last updated: 2026-03-30*
