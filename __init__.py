"""
UI Loop Test - Standalone UI Cloning Agent
=============================================

A DesignCoder-inspired 3-phase pipeline for converting UI screenshots
to HTML components with hierarchical awareness.

Architecture Overview
---------------------

The system follows the DesignCoder paper's three-phase approach:

Phase 1: UI Grouping Chain
    1.1 UI Division       - Partition screenshot into 3-10 semantic regions
    1.2 Semantic Extraction - Label elements within each region
    1.3 Component Grouping  - Build hierarchical component tree

Phase 2: Hierarchy-Aware Code Generation
    2.1 HTML Generation   - Generate structure from component tree
    2.2 Style Generation  - Apply plain CSS based on bounding boxes (no Tailwind)

Phase 3: Self-Correcting Refinement
    3.2 Component Matching - Match rendered DOM to expected tree
    3.3 Visual Comparison  - Identify issues (misarrangement/style/missing)
    3.4 Targeted Repair    - Fix specific components without full rewrite

Key Design Decisions
--------------------

1. Standalone Architecture
   - Runs outside Hermes as pure Python
   - Direct HTTP API calls (no SDK dependencies)
   - Supports OpenRouter and Fireworks providers

2. Hierarchy-First Approach
   - Tree structure drives HTML generation
   - Bounding box containment determines parent-child relationships
   - Structural metrics (TreeBLEU, Container Match) for evaluation

3. Divide-and-Conquer
   - Process each region independently
   - Keeps context window manageable
   - Parallelizable component comparison

Usage
-----

# Run full pipeline
python main.py ui-inspo/sample.png --name my-component

# Run specific phase only
python main.py ui-inspo/sample.png --phase 1  # Just grouping
python main.py ui-inspo/sample.png --phase 2  # Just code generation
python main.py ui-inspo/sample.png --phase 3  # Just refinement

# Use different providers
python main.py ui-inspo/sample.png --provider fireworks
python main.py ui-inspo/sample.png --provider openrouter --vision-provider fireworks

Output Structure
----------------

output/
└── {component_id}/
    ├── reference.png          # Original reference image
    ├── component.json         # Full component state
    ├── index.html            # Generated HTML
    ├── region_{id}.png       # Cropped region images
    └── iter_{n}.png          # Iteration screenshots

Environment Variables
---------------------

OPENROUTER_API_KEY    - API key for OpenRouter
FIREWORKS_API_KEY     - API key for Fireworks
DEFAULT_PROVIDER      - Default LLM provider (openrouter/fireworks)

Implementation Notes
--------------------

- Phase 1 uses vision models (Gemini Flash, Llama 3.2 Vision)
- Phase 2 uses code generation models
- Phase 3 uses both vision and code models
- All API calls are async for performance
- TreeBLEU and Container Match require zss library

References
----------

DesignCoder Paper (2025)
- Chen et al., Zhejiang University + Huawei
- Hierarchy-aware UI code generation from screenshots
- https://arxiv.org (search: DesignCoder UI hierarchy)

Related Projects
- VIGA: Write-run-render-compare-revise loop
- abi/screenshot-to-code: Single-pass baseline
- OmniParser V2: Element detection (future integration)

Author
------
Built for the UI Loop Test project.
"""
