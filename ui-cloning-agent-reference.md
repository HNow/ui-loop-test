# UI Cloning Agent — Reference Architecture

A local-first agentic loop for recreating UI components from reference images using Qwen 3.5 27B via Hermes Agent with Gemini Flash as a cheap vision fallback.

---

## Related Projects

**[VIGA](https://github.com/Fugtemypt123/VIGA)** — The closest architectural match to this project. A write→run→render→compare→revise agent for 3D scene reconstruction in Blender. Key ideas to borrow:
- Dual-role agent: Generator writes code, Verifier analyzes rendered output against reference
- Evolving context memory: persistent store of plans, code diffs, and render history across iterations
- 35% improvement over one-shot baselines by closing the loop
- Paper: [arxiv.org/abs/2601.11109](https://arxiv.org/abs/2601.11109)

**[abi/screenshot-to-code](https://github.com/abi/screenshot-to-code)** (~60k stars) — Single-pass screenshot→code using GPT-4V/Claude/Gemini. No iterative loop, but useful for:
- Their [model evaluation methodology](https://github.com/abi/screenshot-to-code/blob/main/blog/evaluating-claude.md) (16 reference screenshots, human 0-4 rating scale)
- Finding that HTML+Tailwind is the stack where models perform best
- Video-to-prototype mode for capturing interactive UIs

**[OpenKombai](https://github.com/gojodennis/OpenKombai)** — Local screenshot→React+Tailwind using Llama 3.2 Vision + Qwen 2.5 via Ollama. Proof that local models can do this. No iterative loop.

**[DCGen](https://arxiv.org/html/2406.16386v1)** — Academic paper identifying three failure modes of one-shot UI generation: element omission, element distortion, element misarrangement. Their fix (segment the screenshot into smaller regions for focused generation) is a strategy your agent can adopt organically through reasoning rather than as a hard-coded tool.

**[Hermes Agent](https://github.com/NousResearch/hermes-agent)** — The agent framework. Supports custom tools, persistent memory, autonomous skill creation, and the `<tool_call>`/`<tool_response>` format. Skills follow the [agentskills.io](https://agentskills.io) open format. Can connect to Nous Portal, OpenRouter, or any OpenAI-compatible endpoint (including local Ollama).

**[OmniParser V2](https://github.com/microsoft/OmniParser)** — Microsoft's UI screenshot parser (YOLOv8 + Florence-2). Not in the core loop (you have DOM access for the generated side), but potentially useful as a one-shot reference analysis tool. Tiny VRAM footprint (~300MB). Worth keeping in your back pocket.

---

## Architecture

```
Reference Image (provided once)
       │
       ├── extract_colors (local, iteration 0)
       ├── vision_analyze via Gemini Flash (iteration 0, optional)
       │
       ▼
┌─────────────────────────────────────────────────┐
│                  AGENT LOOP                      │
│                                                  │
│  ┌──────────┐    ┌───────────────────┐          │
│  │ Qwen 3.5 │───▶│   write_code      │          │
│  │   27B    │    │   (HTML/Tailwind)  │          │
│  └──────────┘    └────────┬──────────┘          │
│       ▲                   │                      │
│       │                   ▼                      │
│       │          ┌───────────────────┐          │
│       │          │ render_and_capture │          │
│       │          │   (Playwright)     │          │
│       │          └────────┬──────────┘          │
│       │                   │                      │
│       │                   ▼                      │
│       │          ┌───────────────────┐          │
│       │          │   visual_diff      │          │
│       │          │ (SSIM + overlay)   │          │
│       │          └────────┬──────────┘          │
│       │                   │                      │
│       │          SSIM ≥ threshold? ──YES──▶ DONE │
│       │                   │ NO                   │
│       │                   ▼                      │
│       │          ┌───────────────────┐          │
│       │          │  extract_layout    │          │
│       │          │ (Playwright DOM)   │          │
│       │          └────────┬──────────┘          │
│       │                   │                      │
│       │          Plateaued? ──YES──▶ vision_analyze
│       │                   │          (Gemini Flash)
│       │                   │                      │
│       └───────────────────┘                      │
│           feedback (text + images)                │
└─────────────────────────────────────────────────┘
```

Every iteration feeds back to the model:
- The reference image (multimodal)
- The diff overlay image (multimodal)
- SSIM score + per-region scores (text)
- Console errors from Playwright (text)
- Computed layout data from the DOM (text)
- Scratchpad contents (text)

---

## VRAM Budget (~48GB across 2 GPUs)

| Component | VRAM | Where |
|---|---|---|
| Qwen 3.5 27B (Q4_K_M) | ~16-18 GB | GPU1 (full 24GB) |
| Display / compositor | ~1-2 GB | GPU0 |
| Playwright Chromium | ~0.5-1 GB system RAM | CPU |
| SSIM / pixel diff | CPU only | CPU |
| k-means color extraction | CPU only | CPU |
| **Total GPU** | **~18 GB** | |
| **Headroom** | **~28 GB free** | |

At Q5_K_M quantization (~20GB) you still have plenty of room. Even Q8 (~27GB) fits on the non-display GPU. All the tools besides the model itself run on CPU/system RAM.

---

## Tool Specifications

### 1. `write_code`

Writes or overwrites the generated HTML file.

```json
{
  "type": "function",
  "function": {
    "name": "write_code",
    "description": "Write a self-contained HTML file with inline CSS and JS. Uses Tailwind CDN for utility classes. The file is served by a local dev server for Playwright to render. Returns the file path on success and any write errors on failure. Always produce a single file — no separate CSS/JS files.",
    "parameters": {
      "type": "object",
      "required": ["filepath", "content"],
      "properties": {
        "filepath": {
          "type": "string",
          "description": "Path to write, e.g. 'output/index.html'."
        },
        "content": {
          "type": "string",
          "description": "Complete HTML document content."
        }
      }
    }
  }
}
```

**Implementation notes:**
- Copy each version to `output/v{n}.html` for history — useful for debugging regressions and for the scratchpad to reference.
- Serve from a simple `python -m http.server` or `live-server` on a fixed port.

---

### 2. `render_and_capture`

Renders the current code in a headless browser and captures a screenshot.

```json
{
  "type": "function",
  "function": {
    "name": "render_and_capture",
    "description": "Open a headless Chromium browser via Playwright, navigate to the target URL, wait for fonts and content to load, capture a screenshot. Returns: base64 PNG screenshot, viewport dimensions, page height, and any console errors/warnings. Console errors are critical feedback — a broken CDN import or JS error explains rendering issues without needing visual analysis.",
    "parameters": {
      "type": "object",
      "required": ["target"],
      "properties": {
        "target": {
          "type": "string",
          "description": "URL to render, e.g. 'http://localhost:8080/index.html'."
        },
        "viewport_width": {
          "type": "integer",
          "default": 1280,
          "description": "Viewport width in px. Match the reference image width."
        },
        "viewport_height": {
          "type": "integer",
          "default": 800,
          "description": "Viewport height in px."
        },
        "full_page": {
          "type": "boolean",
          "default": true,
          "description": "Capture full scrollable page vs viewport only."
        },
        "wait_ms": {
          "type": "integer",
          "default": 1500,
          "description": "Extra ms to wait after load for fonts/animations. Tailwind CDN + Google Fonts need ~1-1.5s."
        }
      }
    }
  }
}
```

**Implementation notes:**
- Use Playwright Python (`playwright.async_api`). Better font rendering and webfont handling than Puppeteer in headless mode.
- Capture console messages via `page.on("console", ...)` and page errors via `page.on("pageerror", ...)`. Feed these back as text — they're free debugging signal.
- Return both viewport-cropped and full-page screenshots if the page scrolls.

---

### 3. `visual_diff`

Quantitative comparison + visual diff overlay.

```json
{
  "type": "function",
  "function": {
    "name": "visual_diff",
    "description": "Compare reference and generated screenshots. Returns: SSIM score (0.0-1.0), pixel match percentage, a diff overlay image (base64 PNG) highlighting mismatched regions in magenta. The diff overlay is the most valuable output — feed it back to the model as an image so it can see exactly where problems are. Optionally computes per-region SSIM if regions are provided.",
    "parameters": {
      "type": "object",
      "required": ["reference_image", "generated_image"],
      "properties": {
        "reference_image": {
          "type": "string",
          "description": "Path or base64 of the reference image."
        },
        "generated_image": {
          "type": "string",
          "description": "Path or base64 of the generated screenshot."
        },
        "resize_to_match": {
          "type": "boolean",
          "default": true,
          "description": "Resize generated to match reference dimensions before comparing."
        },
        "regions": {
          "type": "array",
          "default": [],
          "description": "Optional named regions for per-area SSIM. Each: {name, x, y, width, height}. Helps the model know which sections are converging vs stuck.",
          "items": {
            "type": "object",
            "properties": {
              "name": { "type": "string" },
              "x": { "type": "integer" },
              "y": { "type": "integer" },
              "width": { "type": "integer" },
              "height": { "type": "integer" }
            }
          }
        },
        "diff_threshold": {
          "type": "integer",
          "default": 35,
          "description": "Per-pixel difference threshold (0-255). Higher is more forgiving of anti-aliasing."
        }
      }
    }
  }
}
```

**Implementation notes:**
- SSIM: `skimage.metrics.structural_similarity` with `channel_axis=-1` for color images.
- Diff overlay: compute absolute per-pixel difference with Pillow/numpy, threshold, paint mismatched pixels in magenta over the reference. This image is the primary visual feedback for the model.
- Consider also computing a heatmap version (red=hot where diff is large) — some models respond better to this than binary overlays.
- All CPU. No VRAM.

---

### 4. `extract_layout`

Pulls computed styles and bounding boxes from the live DOM.

```json
{
  "type": "function",
  "function": {
    "name": "extract_layout",
    "description": "Extract DOM structure and computed CSS properties from the rendered page via Playwright. Returns a tree of elements with: tag name, text content, bounding box (x, y, width, height), and computed styles (display, position, flex props, font, color, background, padding, margin, border-radius, gap, box-shadow). Also returns CSS custom properties from :root. This gives the model precise numeric feedback — 'the nav is 64px tall' instead of guessing from pixels.",
    "parameters": {
      "type": "object",
      "required": ["target"],
      "properties": {
        "target": {
          "type": "string",
          "description": "URL of the rendered page."
        },
        "selector": {
          "type": "string",
          "default": "body",
          "description": "CSS selector to scope extraction. Use to focus on a specific section."
        },
        "max_depth": {
          "type": "integer",
          "default": 5,
          "description": "Max DOM depth to traverse. Keep low to avoid token bloat."
        }
      }
    }
  }
}
```

**Implementation notes:**
- Implemented via `page.evaluate()` running a JS function that walks the DOM, calls `getComputedStyle()` + `getBoundingClientRect()` on each element.
- Token management is critical. Filter aggressively:
  - Skip zero-dimension elements
  - Skip whitespace-only text nodes
  - Collapse repeated identical siblings (e.g. 50 list items → one example + count)
  - Only extract the styles listed in the description, not all ~300 CSS properties
- The accessibility tree (`page.accessibility.snapshot()`) is a useful complement — gives semantic structure without CSS noise.

---

### 5. `extract_colors`

Pulls the dominant color palette from the reference image.

```json
{
  "type": "function",
  "function": {
    "name": "extract_colors",
    "description": "Extract the dominant color palette from an image using k-means clustering. Returns ordered list of colors (most dominant first) with hex values, RGB tuples, and approximate coverage percentage. Run this once on the reference image at iteration 0 and inject results into context so the model has exact color targets.",
    "parameters": {
      "type": "object",
      "required": ["image"],
      "properties": {
        "image": {
          "type": "string",
          "description": "Path or base64 of the image."
        },
        "num_colors": {
          "type": "integer",
          "default": 8,
          "description": "Number of dominant colors to extract."
        }
      }
    }
  }
}
```

**Implementation notes:**
- Resize to ~150x150 before clustering for speed. Use sklearn `KMeans` or just the `colorthief` library (one-liner).
- Run once, cache, inject into system prompt. Not a per-iteration tool.

---

### 6. `scratchpad`

Persistent memory across iterations.

```json
{
  "type": "function",
  "function": {
    "name": "scratchpad",
    "description": "Read or write persistent notes across loop iterations. Use for observations, plans, and warnings that must survive context window truncation. Examples: 'Reference uses 3-column grid, roughly 1:2:1', 'Header SSIM is 0.95 — do NOT touch it, focus on card section', 'Tailwind CDN loaded, Google Fonts loaded, no console errors'. Automatically includes iteration number and SSIM history.",
    "parameters": {
      "type": "object",
      "required": ["action"],
      "properties": {
        "action": {
          "type": "string",
          "enum": ["read", "write", "append", "clear"]
        },
        "content": {
          "type": "string",
          "default": null,
          "description": "Text to write/append. Required for write and append."
        }
      }
    }
  }
}
```

**Implementation notes:**
- Just a text file, injected into every prompt.
- Auto-append SSIM score + iteration count after each iteration so the model can see its own convergence trajectory.
- This is borrowed from VIGA's "evolving context memory" — prevents the model from oscillating between changes.

---

### 7. `vision_analyze`

API call to Gemini Flash for qualitative visual analysis.

```json
{
  "type": "function",
  "function": {
    "name": "vision_analyze",
    "description": "Send images to Gemini 3 Flash for qualitative visual analysis. Use sparingly — only when local tools (SSIM, layout extraction, console errors) aren't enough. Primary use cases: (1) initial reference description at iteration 0, (2) breaking through SSIM plateaus by asking what's visually wrong, (3) final QA pass. Supports up to 4 images per call. Returns natural language analysis with specific, actionable feedback.",
    "parameters": {
      "type": "object",
      "required": ["images", "prompt"],
      "properties": {
        "images": {
          "type": "array",
          "items": { "type": "string" },
          "maxItems": 4,
          "description": "Image paths or base64 strings. Describe their roles in the prompt."
        },
        "prompt": {
          "type": "string",
          "description": "The analysis question. Be specific. Include context like SSIM score and iteration number."
        },
        "thinking_level": {
          "type": "string",
          "enum": ["minimal", "low", "medium", "high"],
          "default": "medium",
          "description": "Reasoning depth. 'minimal' for quick checks (~$0.001), 'high' for deep analysis (~$0.005)."
        }
      }
    }
  }
}
```

**Implementation notes:**
- Use via OpenRouter (`google/gemini-3-flash-preview`) or direct Google AI Studio API. OpenRouter is easier and gives you model fallback for free.
- At `$0.50/1M` input and `$3/1M` output, a typical 2-image comparison with a 500-token response costs around $0.002-0.005.
- Gemini 3 Flash's "visual thinking" feature (code execution on images) is available but adds latency. Worth enabling for plateau-breaking calls only.
- Estimated 2-4 calls per clone = $0.01-0.02 total API spend.

---

## Loop Orchestration

```python
MAX_ITERATIONS = 8
SSIM_THRESHOLD = 0.88
PLATEAU_PATIENCE = 2   # escalate to vision API if no improvement for N rounds
PLATEAU_DELTA = 0.005  # minimum SSIM improvement to count as progress

scores = []

# ── Iteration 0: Bootstrap ──
colors = extract_colors(reference_image)
# Optional: vision_analyze for a qualitative description of the reference

for i in range(MAX_ITERATIONS):

    # ── Generate ──
    # Model sees: reference image, scratchpad, colors,
    #   and (if i > 0) diff overlay + layout + console errors
    # Model calls: write_code (and optionally scratchpad.append)

    # ── Render ──
    result = render_and_capture(url)
    screenshot = result.screenshot
    console_errors = result.errors

    # ── Compare ──
    diff = visual_diff(reference_image, screenshot)
    scores.append(diff.ssim)

    # ── Converged? ──
    if diff.ssim >= SSIM_THRESHOLD:
        break

    # ── Plateaued? ──
    plateaued = (
        len(scores) > PLATEAU_PATIENCE and
        max(scores[-PLATEAU_PATIENCE:]) - min(scores[-PLATEAU_PATIENCE:]) < PLATEAU_DELTA
    )

    if plateaued:
        # Escalate to Gemini for qualitative feedback
        analysis = vision_analyze(
            images=[reference_image, screenshot, diff.overlay],
            prompt=f"Iteration {i}, SSIM {diff.ssim:.3f}, plateaued. "
                   f"What specific visual issues remain? Give CSS-level fixes.",
            thinking_level="high"
        )
        # Inject analysis text into next iteration's context

    # ── Extract layout for next iteration ──
    layout = extract_layout(url)

    # ── Update scratchpad ──
    # Auto-append: iteration, SSIM, brief status
```

**Convergence tips:**
- Phase the work via system prompt: iteration 1-2 focus on structure/layout, 3-4 on colors/typography, 5+ on spacing/polish.
- Set per-region SSIM targets so the model focuses effort where it matters most.
- If SSIM is stuck below 0.7 after 3 iterations, the issue is almost always structural — the model should rewrite from scratch rather than patch.

---

## Hermes Agent Integration

These tools map directly to Hermes's tool format. The Hermes 4.x series uses:

```
<tools>
  {tool JSON schema}
</tools>
```

And the model emits:
```
<tool_call>{"name": "write_code", "arguments": {"filepath": "...", "content": "..."}}</tool_call>
```

Responses come back as:
```
<tool_response>{"result": "..."}</tool_response>
```

Package the loop as a Hermes skill (`SKILL.md` + tool definitions) and Hermes's memory system will learn patterns across sessions — which CDN versions work, which layout strategies converge fastest, what common pitfalls to note in the scratchpad early.

The agent can be configured to use Qwen 3.5 27B locally via Ollama as its primary model, with Gemini Flash accessible as a tool rather than as the agent's own model. This keeps all reasoning and code generation local while using the API only for vision.
