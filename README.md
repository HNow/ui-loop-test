# UI Loop Test

A standalone UI cloning agent that converts screenshots to HTML components using a DesignCoder-inspired 3-phase hierarchy-aware pipeline.

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Set API keys
export OPENROUTER_API_KEY=your_key
export FIREWORKS_API_KEY=your_key

# Run the pipeline
python main.py ui-inspo/sample.png --name my-component
```

## How It Works

The system follows the **DesignCoder** paper's three-phase approach:

### Phase 1: UI Grouping Chain

**1.1 UI Division** - Partition the screenshot into 3-10 semantic regions (navigation, hero, content grid, etc.)

**1.2 Semantic Extraction** - Identify and label all elements within each region (buttons, headings, images, etc.)

**1.3 Component Grouping** - Build a hierarchical component tree where parent-child relationships reflect visual containment

### Phase 2: Hierarchy-Aware Code Generation

**2.1 HTML Generation** - Generate HTML structure that follows the component tree exactly

**2.2 Style Generation** - Apply plain CSS based on computed layout from bounding boxes (no Tailwind)

### Phase 3: Self-Correcting Refinement

**3.2 Component Matching** - Match rendered DOM elements back to expected tree nodes

**3.3 Visual Comparison** - Compare components and categorize issues (misarrangement, style error, missing element)

**3.4 Targeted Repair** - Fix specific components without rewriting the entire page

## Why This Approach?

Traditional screenshot-to-code tools produce "flat div soup" - they describe what's visible but miss the hierarchy (which elements contain which). This matters because:

- Two UIs can look pixel-identical with different DOM trees
- Hierarchy affects responsiveness, accessibility, and maintainability
- SSIM alone can't catch "button outside card" vs "button inside card" errors

The DesignCoder paper showed that adding hierarchy extraction improves structural metrics by 25-30% and visual similarity by ~10%.

## Usage Examples

### Run Full Pipeline
```bash
python main.py ui-inspo/sample.png --name login-page
```

### Run Specific Phase
```bash
# Just analyze structure
python main.py ui-inspo/sample.png --phase 1

# Generate code from existing analysis
python main.py ui-inspo/sample.png --phase 2

# Refine existing code
python main.py ui-inspo/sample.png --phase 3
```

### Provider Selection
```bash
# Use OpenRouter (default)
python main.py ui-inspo/sample.png --provider openrouter

# Use Fireworks
python main.py ui-inspo/sample.png --provider fireworks

# Different providers for code vs vision
python main.py ui-inspo/sample.png --provider fireworks --vision-provider openrouter
```

### Advanced Options
```bash
python main.py ui-inspo/sample.png \
  --name my-component \
  --max-iter 10 \
  --output-dir ./my-output \
  --provider fireworks
```

## Output Structure

```
output/
└── {component_id}/
    ├── reference.png          # Original reference image
    ├── component.json         # Full component state (regions, tree, iterations)
    ├── index.html            # Generated HTML output
    ├── region_*.png          # Cropped region images
    └── iter_*.png            # Screenshots from refinement iterations
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  STANDALONE UI CLONING AGENT                                 │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ PHASE 1: UI Grouping Chain                          │   │
│  │ ├── UIDivision: Segment into semantic regions       │   │
│  │ ├── SemanticExtraction: Label elements             │   │
│  │ └── ComponentGrouping: Build hierarchy tree         │   │
│  └─────────────────────────────────────────────────────┘   │
│                           ↓                                 │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ PHASE 2: Hierarchy-Aware Code Generation            │   │
│  │ ├── HTMLGenerator: Generate from tree structure       │   │
│  │ └── StyleGenerator: Apply plain CSS styles           │   │
│  └─────────────────────────────────────────────────────┘   │
│                           ↓                                 │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ PHASE 3: Self-Correcting Refinement                 │   │
│  │ ├── ComponentMatcher: Match DOM to tree              │   │
│  │ ├── VisualComparator: Find issues                  │   │
│  │ └── TargetedRepair: Fix specific components          │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                              │
├─────────────────────────────────────────────────────────────┤
│  Key Components:                                            │
│  • DualProviderClient: OpenRouter + Fireworks support      │
│  • ComponentStore: JSON persistence for state             │
│  • Structural Metrics: TreeBLEU, Container Match, TED       │
│  • DOM Extraction: Playwright integration                   │
│  • Image Processing: SSIM, color extraction, cropping       │
└─────────────────────────────────────────────────────────────┘
```

## Configuration

Create a `.env` file:

```bash
OPENROUTER_API_KEY=sk-or-v1-...
FIREWORKS_API_KEY=fw-...
DEFAULT_PROVIDER=openrouter
```

Or set environment variables directly.

## Evaluation Metrics

The system tracks three structural metrics from the DesignCoder paper:

- **TreeBLEU** (0-1): Proportion of matching height-1 subtrees between generated and reference
- **Container Match** (0-1): Percentage of containers with structurally equivalent matches
- **Tree Edit Distance** (0+): Minimum operations needed to transform generated tree to reference

Plus standard visual metrics:
- **SSIM** (0-1): Structural similarity between screenshots
- **MSE**: Mean squared pixel error

## Dependencies

Core:
- `aiohttp` - HTTP client for API calls
- `playwright` - Browser automation for rendering
- `pillow` - Image processing
- `scikit-learn` - K-means clustering for color extraction
- `scikit-image` - SSIM computation
- `zss` - Tree edit distance (Zhang-Shasha algorithm)

See `requirements.txt` for full list.

## Design Decisions

1. **No SDK Dependencies**: Pure HTTP requests to OpenRouter/Fireworks for flexibility
2. **Standalone Operation**: Runs outside Hermes Agent for better image context handling
3. **Async Throughout**: All API calls are async for performance
4. **Dual Provider Support**: Can use different models for code gen vs vision tasks
5. **Geometric Fallbacks**: Vision models can fail; geometric heuristics provide fallbacks
6. **Per-Component Repair**: Targeted fixes instead of full rewrites for efficiency

## Known Limitations

1. **No Metadata**: Unlike original DesignCoder (Figma input), we work from raw screenshots only
2. **Approximate Layout**: Bounding boxes give approximate sizes, not exact measurements
3. **Vision Model Dependency**: Phase 1 quality depends on vision model's region detection
4. **No Interactions**: Generates static HTML only (no JavaScript for interactive behaviors)

## References

- **DesignCoder** (Chen et al., 2025) - Hierarchy-aware UI code generation
- **VIGA** - Write-run-render-compare-revise loop pattern
- **abi/screenshot-to-code** - Single-pass baseline (~60k stars on GitHub)

## Developer Tips

### Debugging Phase 1 (Grouping)

If region detection is poor:
```python
# Run just Phase 1
python main.py ui-inspo/sample.png --phase 1

# Check output/component_id/component.json for regions array
# Check output/component_id/region_*.png for cropped images
```

### Debugging Phase 2 (Code Gen)

If HTML structure is wrong:
- Check `component.json` -> `tree` field for hierarchy
- The tree should show parent-child relationships via `children_ids`
- If tree is wrong, the issue is in Phase 1.3 (ComponentGrouping)
- If tree is right but HTML is wrong, issue is in Phase 2.1 (HTMLGenerator)

### Debugging Phase 3 (Refinement)

If refinement isn't converging:
```python
# Check iteration history in component.json
# Each iteration has: ssim, treebleu, container_match
# Look for iterations where metrics don't improve (plateau)
```

### Common Issues

**API Rate Limits**: Add delays between calls or reduce max_iterations

**Vision Model Hallucination**: If regions don't match the image, try:
- Lower temperature (0.2 instead of 0.3)
- Different vision provider
- Manual region specification (future feature)

**Geometric Fallback**: If ComponentGrouping falls back to geometric mode often,
the vision model is failing to parse the hierarchy prompt. Check:
- Prompt clarity
- Model capabilities (some vision models struggle with complex reasoning)
- Element count (too many elements can overwhelm the model)

### Adding New Element Types

To add a new element type:
1. Add to `VALID_TYPES` in `phases/phase1_grouping/semantic.py`
2. Add mapping in `_normalize_type()` method
3. Add HTML tag mapping in `phases/phase2_codegen/html_gen.py`
4. Update prompts to mention the new type

### Extending Metrics

To add a new structural metric:
1. Add function in `utils/metrics.py`
2. Update `compute_all_metrics()` to include it
3. Add to Iteration dataclass in `storage/component.py`
4. Update output printing in `loop.py`

## Testing Checklist

Before claiming a component works:
- [ ] Phase 1 produces 3-10 regions covering full image
- [ ] Phase 1 crops are reasonable (not zero-size, within bounds)
- [ ] Phase 2 HTML renders without errors
- [ ] Phase 3 SSIM improves over iterations
- [ ] Final output visually resembles reference
- [ ] TreeBLEU > 0.5 (at least some hierarchy correct)

## Performance Notes

- Phase 1: ~3-5 API calls per region (one per subtask)
- Phase 2: ~2 API calls per region
- Phase 3: ~3 API calls per iteration (render is local)
- Total: ~5-10 + (3 * iterations) calls per component

## License

MIT
