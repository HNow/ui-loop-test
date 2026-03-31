# DesignCoder-Inspired UI Cloning: Implementation Handoff

## Context

This document describes an approach to generating code from UI screenshots that is *hierarchy-aware* — meaning the generated code correctly reflects which elements contain which, not just what elements exist. It is based on the DesignCoder framework (Chen et al., Zhejiang University + Huawei, 2025) but adapted for our use case: an agentic loop using a local model (Kimi K2.5 / Qwen 3.5 27B) for code generation with Gemini 3 Flash for vision analysis.

The original paper targets React Native from Figma mockups with design metadata. We target HTML/Tailwind from raw screenshots with no metadata. This changes several things — noted throughout.

---

## Why This Matters

The core problem: vision-language models describe UI screenshots in terms of "what's there" but not "what's inside what." They'll say "there's a card with a title, price, and Buy Now button" but produce code where the button is *inside* the card div even when it's visually *outside* it — or vice versa. Flat div soup. SSIM can't catch this because two UIs with different DOM trees often look pixel-identical.

DesignCoder found that adding a dedicated hierarchy-extraction step before code generation improved structural metrics (TreeBLEU, Container Match, Tree Edit Distance) by 25-30%, and removing this step caused visual similarity (SSIM) to drop from 0.88 to 0.79 even though the model was the same. The hierarchy step is the single highest-leverage intervention.

---

## The Three-Phase Pipeline

The system has three phases. Each phase completes fully before the next begins. The output of each phase feeds into the next as structured input.

```
Phase 1: UI Grouping Chain
  Screenshot → Component Tree (JSON)
  
Phase 2: Hierarchy-Aware Code Generation  
  Component Tree + Screenshot → HTML/CSS Code
  
Phase 3: Self-Correcting Refinement
  Code + Rendered Screenshot vs Reference → Corrected Code
```

---

## Phase 1: UI Grouping Chain

This is the critical new piece. It converts a flat screenshot into a hierarchical component tree through three sequential subtasks. Each subtask is a separate model call with a specialized prompt. The key insight is that no single prompt can reliably produce a correct hierarchy from a full page — you must decompose the problem.

### Subtask 1.1: UI Division

**Goal:** Partition the screenshot into 3-10 semantic regions. Not a grid. Semantic regions — a nav bar is one region, a hero section is one region, a card grid is one region.

**Input:**
- The full reference screenshot
- (If available) a list of detected element bounding boxes from an element detector. In the original paper this came from Figma metadata. In our case, we can get this from OmniParser V2, or skip it and rely purely on the vision model.

**Process:**
Send the screenshot to a vision model (Gemini Flash) with a prompt that instructs it to divide the page into semantic regions. The prompt should ask for:
- A list of regions, each with a human-readable name and a bounding box (x, y, width, height in pixels)
- Regions must be mutually exclusive — no element should appear in two regions
- Target 3-10 regions. Fewer than 3 means the regions are too large for the next step to handle well. More than 10 means they're too granular and you lose inter-region context.

**Post-processing — Division Correction:**
The original paper includes a correction algorithm for ensuring region quality. The rules:
- Every detected element must belong to exactly one region. If an element falls in the gap between two regions, assign it to the nearest region by centroid distance.
- If a region contains only 1 element, merge it into the nearest adjacent region.
- If a region contains more than ~40% of all elements, try to split it further.
- Regions must tile the full page vertically — no uncovered vertical gaps.

**Output:** A list of region definitions, each with a name, bounding box, and a list of the element IDs (or bounding boxes) it contains.

**Adaptation note:** The original paper had Figma layer metadata (element IDs, types, bounding boxes) as input. Without that, you have two options:
1. Run OmniParser V2 first to detect elements and get bounding boxes, then pass those as the element list
2. Let the vision model both detect elements and define regions in one step (simpler but less precise)

Option 1 is recommended. OmniParser runs in <1 second and gives you concrete element coordinates to work with rather than relying on the vision model to estimate bounding boxes.

### Subtask 1.2: Semantic Extraction

**Goal:** For each region identified in 1.1, produce a flat list of elements with semantic labels. Not hierarchy yet — just "what is each element and what does it do."

**Input per region:**
- The cropped sub-image of this region
- The list of element bounding boxes within this region
- (Optional) visual annotations — draw numbered boxes on the sub-image around each element to help the model reference them precisely

**Process:**
Send each region's cropped image to the vision model with a prompt asking it to produce a list of elements with:
- Element ID or number (matching the bounding box annotations)
- Element type (one of: container, text, heading, button, image, icon, input, link, divider, badge, list, card, nav-item, or similar)
- Brief content description ("Product title", "Add to Cart button", "$29.99 price text")
- Interactability: is this something a user clicks/taps, or is it static content?

**Post-processing:**
- Deduplicate elements that appear to be the same thing detected twice
- Validate that the element types make sense (e.g., something labeled as a "button" should have button-like dimensions, not be a full-width container)

**Output per region:** A flat list of semantically-annotated elements. Still no hierarchy. Example:

```
Region: "product-card-grid"
  [1] container (bbox: [20,300,380,420]) — "product card"
  [2] image (bbox: [30,310,360,200]) — "product photo"  
  [3] heading (bbox: [30,520,200,24]) — "Product Name"
  [4] text (bbox: [30,550,80,18]) — "$29.99"
  [5] button (bbox: [30,580,120,36]) — "Add to Cart"
  [6] container (bbox: [400,300,380,420]) — "product card"  
  [7] image (bbox: [410,310,360,200]) — "product photo"
  ...
```

### Subtask 1.3: Component Grouping

**Goal:** Take the flat element list from 1.2 and organize it into a hierarchical component tree — the actual parent-child relationships.

This is the hardest and most important subtask. It's where "the button is outside the card" vs "the button is inside the card" gets decided.

**Input per region:**
- The cropped sub-image of this region
- The flat annotated element list from subtask 1.2

**Process:**
Send to the vision model with a prompt specifically focused on containment reasoning. The prompt must:

1. Define containment precisely: "Element B is a CHILD of element A if and only if B is visually enclosed within A's boundaries. If B is adjacent to A but not enclosed, B is a SIBLING of A, not a child."

2. Ask for output in a nested tree format using indentation or a structured notation:
   ```
   card-grid
     card
       product-photo
       product-name
       price
       add-to-cart-button
     card
       product-photo
       product-name
       price  
       add-to-cart-button
     view-all-button         ← sibling of cards, NOT a child
   ```

3. Explicitly instruct the model to cross-reference bounding boxes: "If element B's bounding box is entirely within element A's bounding box, B is a child of A. If they overlap partially or not at all, they are siblings or B belongs to a different parent."

**Post-processing — Critical:**
- **No orphan leaves:** Every element should belong to a group. Leaf elements that aren't inside any container should be wrapped in an implicit container (their parent region).
- **No overlapping containers:** If two containers claim to contain the same child element, resolve by checking which container's bounding box more tightly encloses the child.
- **Depth sanity check:** Real UIs rarely exceed 5-6 levels of nesting. If the tree is deeper than that, something is probably wrong — flatten any chains of single-child containers.

**Output per region:** A hierarchical sub-tree in JSON.

### Assembly: Stitching Sub-Trees Into a Full Component Tree

After processing all regions, assemble the sub-trees into a complete page tree:

```
page-root
  region-1-subtree (e.g., "navigation")
    ...
  region-2-subtree (e.g., "hero-section")
    ...
  region-3-subtree (e.g., "product-grid")
    ...
  region-4-subtree (e.g., "footer")
    ...
```

The region order should follow the visual layout order (top to bottom, left to right for side-by-side regions).

This assembled tree is the primary output of Phase 1 and becomes the structural contract for Phase 2.

---

## Phase 2: Hierarchy-Aware Code Generation

### Subtask 2.1: Component Code Generation

**Goal:** Generate HTML structure that follows the component tree exactly.

**Input:**
- The full component tree from Phase 1
- The reference screenshot (full page)
- The cropped sub-image for each region

**Process:**
For each sub-tree (region), send the region's sub-image along with its component tree to the code generation model. The prompt must:

1. Instruct the model to treat the component tree as a strict structural contract: "The HTML nesting MUST mirror this tree exactly. If the tree shows button as a sibling of card, the button element must NOT be inside the card div."

2. Map component tree nodes to HTML elements. The model should use the tree's semantic labels to choose appropriate tags (`<nav>`, `<section>`, `<article>`, `<button>`, `<img>`, etc.) rather than defaulting to divs for everything.

3. Assign stable class names or IDs to each component based on the tree node names. These identifiers are used in Phase 3 for matching rendered output back to the tree.

**The divide-and-conquer principle:** Generate code for each region independently. This keeps the context window manageable and prevents the model from getting confused by distant parts of the page. Each region produces a self-contained HTML fragment.

### Subtask 2.2: Style Generation

**Goal:** Generate CSS/Tailwind classes that match the reference visually.

**Input:**
- The component tree nodes with their bounding boxes
- The reference screenshot (for color/font reference)
- The extracted color palette (from the `extract_colors` tool)

**Process:**
Style information is derived from bounding boxes and visual inspection:

- **Layout:** Bounding boxes from the component tree give approximate sizes and positions. Use these to infer flex direction, gap, padding, and margin. The original paper traverses the tree bottom-up — leaf nodes keep their original bounding boxes, parent nodes compute their dimensions by aggregating children.
- **Typography:** Font family, size, weight, color, and line-height should be inferred from the reference image. The vision model or color extractor can help here.
- **Spacing:** Compute padding as the distance between a container's bounding box edges and its children's bounding box edges. Compute gap as the distance between sibling elements.
- **Visual properties:** Background colors, border-radius, box-shadow, borders are inferred visually.

**Output:** Complete styled HTML for each region, organized so regions can be concatenated into a full page.

### Assembly

Concatenate all region code fragments in layout order. Wrap in a full HTML document with the Tailwind CDN, any Google Fonts imports, and a viewport meta tag.

---

## Phase 3: Self-Correcting Refinement

This is the iterative loop. It uses visual comparison to find and fix errors in the generated code.

### Step 3.1: Render and Extract

Render the generated HTML in a headless browser (Playwright). Capture:
- A full-page screenshot
- Console errors/warnings
- The DOM tree with computed bounding boxes for each element (via `page.evaluate()` + `getBoundingClientRect()`)

### Step 3.2: Component-Level Matching

Match each component in the rendered DOM back to the corresponding node in the component tree from Phase 1. Use the class names/IDs assigned in Phase 2 for matching. For each matched pair, extract:
- The rendered element's bounding box (from the DOM)
- The expected bounding box (from the component tree)
- A cropped image of just that component from the rendered screenshot
- A cropped image of just that component from the reference screenshot (using the component tree's bounding box)

### Step 3.3: Per-Component Visual Comparison

For each component, compare its rendered crop against its reference crop. Send both to the vision model with a prompt asking:
- Are there visible differences?
- If so, categorize the error: misarrangement (wrong position/size), style error (wrong color/font/spacing), or missing element
- Provide a specific repair suggestion in terms of CSS/HTML changes

This is per-component, not per-page. The original paper notes this can be parallelized — multiple component comparisons at once since they're independent.

### Step 3.4: Targeted Repair

For each component with an identified error, send the repair suggestion plus that component's current code to the code generation model. Ask it to modify only that specific component's code to fix the identified issue. Do not rewrite the whole page.

### Step 3.5: Merge and Re-render

Merge the repaired component code back into the full page, following the component tree order. Re-render and compare again.

### Iteration Control

- Repeat Steps 3.1-3.5 for up to N iterations (the paper doesn't specify; 2-3 is probably sufficient, your existing loop patience logic applies)
- Stop when per-component visual comparison finds no significant errors, or when overall SSIM exceeds the threshold
- The per-component comparison is more useful than full-page SSIM here — it catches localized issues that SSIM averages away

---

## Evaluation Metrics (For Measuring Your Implementation)

The original paper uses both visual and structural metrics. Structural metrics are the ones that actually measure what we care about — hierarchy correctness.

### Visual Metrics (You Probably Already Have These)
- **MSE** (lower is better): Mean squared pixel error between reference and rendered screenshots
- **SSIM** (higher is better): Structural similarity. Caps out fast; useful as a sanity check, not a fine-grained signal
- **CLIP Score** (higher is better): Cosine similarity of CLIP embeddings between reference and rendered. More perceptually meaningful than SSIM. Can be computed locally with the `clip` Python package

### Structural Metrics (Implement These)
- **TreeBLEU** (higher is better): Adapted from NLP's BLEU score but for DOM trees. Measures the proportion of subtrees in the generated HTML that match subtrees in a reference DOM. Specifically: extract all unique height-1 subtrees (a parent node + its immediate children) from both trees, then compute the overlap ratio. This directly measures whether parent-child relationships are correct.
- **Container Match** (higher is better): Percentage of container elements in the reference that have a structurally equivalent container in the generated code (same children in the same order). This catches exactly the "button inside vs outside the card" class of errors.
- **Tree Edit Distance** (lower is better): The minimum number of node insertions, deletions, and relabelings needed to transform the generated DOM tree into the reference DOM tree. Standard algorithm: Zhang-Shasha. Python implementations exist (`zss` library).

Implementing TreeBLEU and Container Match is strongly recommended for evaluating whether the hierarchy extraction is working. Without them, you'll have no quantitative signal for the thing you're actually trying to improve.

---

## Adaptation Notes: Paper vs Our Setup

| Aspect | Original Paper | Our Adaptation |
|---|---|---|
| **Input** | Figma mockup with layer metadata (id, type, bbox for every element) | Raw screenshot only — no metadata |
| **Element detection** | From Figma metadata directly | Use OmniParser V2 or the vision model to detect elements and get bounding boxes |
| **Models used** | GPT-4o for grouping chain, Claude 3.5/GPT-4o for code gen | Gemini 3 Flash for grouping chain, Kimi K2.5 / Qwen 3.5 27B for code gen |
| **Target framework** | React Native | HTML + plain CSS (no Tailwind) |
| **Rendering** | Appium (mobile simulator) | Playwright (headless Chromium) |
| **Style extraction** | From Figma metadata (exact font sizes, colors, spacing) | Inferred visually from the screenshot (approximate) |
| **Design metadata for CSS** | Rich — exact values for every property | We don't have this. Use `extract_colors` for palette, vision model for font estimation, bounding boxes for layout math. This is the biggest fidelity loss vs the paper. |

The biggest adaptation challenge is the lack of design metadata. The paper's CSS generation relies heavily on exact measurements from Figma (precise padding, font sizes, colors as hex values). Without that, our style accuracy will be lower. The hierarchy extraction, however, should work equivalently since it's primarily visual — the paper's division prompt uses the screenshot, not just metadata.

---

## Ablation Results From the Paper (What Matters Most)

The paper tested removing each component:

| Configuration | CLIP | SSIM | MSE | TreeBLEU | Container Match |
|---|---|---|---|---|---|
| Full DesignCoder | 0.92 | 0.88 | 22.43 | 0.65 | 0.50 |
| Without UI Grouping Chain | 0.84 | 0.79 | 38.92 | 0.43 | 0.29 |
| Without Self-Correction | 0.88 | 0.83 | 30.16 | 0.59 | 0.44 |
| Without both | 0.81 | 0.75 | 45.67 | 0.38 | 0.24 |

The UI Grouping Chain is the single most impactful component. Removing it causes a bigger quality drop than removing self-correction. The structural metrics (TreeBLEU, Container Match) are affected most dramatically — Container Match nearly halves without the grouping chain.

This confirms the implementation priority: get Phase 1 (the grouping chain) right first. Phase 3 (self-correction) adds incremental improvement on top.

---

## Implementation Priority Order

1. **Phase 1, Subtask 1.1 (UI Division)** — Get region segmentation working. This is the foundation.
2. **Phase 1, Subtask 1.3 (Component Grouping)** — Get hierarchy prediction working per region. This is the highest-value piece.
3. **Phase 2, Subtask 2.1 (Component Code Gen)** — Generate HTML that follows the tree. This replaces your current one-shot code generation.
4. **Phase 1, Subtask 1.2 (Semantic Extraction)** — Add semantic labels. This can be rough initially — even just "container", "text", "button", "image" is enough.
5. **Phase 2, Subtask 2.2 (Style Generation)** — Refine CSS. This is where you'll spend the most time iterating since we lack metadata.
6. **Phase 3 (Self-Correction)** — Add the per-component comparison loop. This bolts onto your existing refinement loop.

You could get a working prototype with just items 1-3 and compare results against your current single-pass approach. The hierarchy improvement should be visible immediately.
