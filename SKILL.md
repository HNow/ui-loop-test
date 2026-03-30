---
name: ui-cloner
description: Clone UI components from reference screenshots. Creates Svelte components with live preview, iteration history, and visual diff tracking.
version: 3.0.0
---

# UI Cloner

Clone a reference UI screenshot into a component with live preview and full iteration history.

## Architecture

```
ui-loop-test/
├── static/components/{comp_id}/
│   ├── preview.html        # Live preview (HTML)
│   ├── reference.png       # Reference image
│   ├── meta.json           # Iterations, SSIM, notes
│   ├── screenshots/{n}.png # Screenshots per iteration
│   └── diffs/{n}.png       # Diff overlays per iteration
└── ui-inspo/               # Reference images to clone
```

## CLI Commands

All tools run via:
```bash
uv run --with-requirements agent/requirements.txt python -m agent.tools <cmd> [args...]
```

### `create <name> [reference]`

Create a new component directory.

```bash
python -m agent.tools create Card ui-inspo/card.png
# Returns: {"id": "comp_xxx", "path": "...", "reference": "reference.png"}
```

### `get <comp_id>`

Get component metadata and state.

```bash
python -m agent.tools get comp_xxx
# Returns: {name, status, iterations, colors, scratchpad, ...}
```

### `write <comp_id>`

Write HTML to the component (reads from stdin).

```bash
cat << 'EOF' | python -m agent.tools write comp_xxx
<!DOCTYPE html>
<html>
<head><style>...</style></head>
<body>...</body>
</html>
EOF
```

### `render <url>`

Render URL in headless browser, get screenshot.

```bash
python -m agent.tools render http://localhost:8080/preview.html
# Returns: {"screenshot": "<base64>", "viewport": {...}, "console_errors": [...]}
```

### `diff <ref_path> <gen_b64>`

Compare reference to generated screenshot.

```bash
python -m agent.tools diff /path/to/reference.png "$SCREENSHOT_B64"
# Returns: {"ssim": 0.xx, "has_overlay": true}
```

### `colors <image_path>`

Extract dominant colors.

```bash
python -m agent.tools colors ui-inspo/card.png
# Returns: {"colors": [{"hex": "#xxx", "coverage_pct": xx}, ...]}
```

### `save <comp_id>`

Save iteration data (reads JSON from stdin).

```bash
echo '{"screenshot": "...", "diff": "...", "ssim": 0.75}' | \
  python -m agent.tools save comp_xxx
```

### `vision <prompt> <images...>`

Analyze images with Gemini Pro.

```bash
python -m agent.tools vision "What's wrong with this UI?" ref.png current.png
```

### `scratchpad <comp_id> <action> [content]`

Update component scratchpad (append/write/clear).

```bash
python -m agent.tools scratchpad comp_xxx append "Header looks good, focus on cards"
```

---

## Workflow

### 1. Create Component

```bash
cd ~/Documents/ui-loop-test
COMP_ID=$(uv run --with-requirements agent/requirements.txt python -m agent.tools create MyComponent ui-inspo/4-boxes-skeuomorphic.jpg | jq -r .id)
echo "Component ID: $COMP_ID"
```

### 2. Start File Server

```bash
uv run --with-requirements agent/requirements.txt python -m http.server 8080 --directory static/components/$COMP_ID --bind 127.0.0.1 &
SERVER_PID=$!
```

### 3. Iterate

```bash
# Write HTML
cat << 'HTML' | uv run --with-requirements agent/requirements.txt python -m agent.tools write $COMP_ID
<!DOCTYPE html>
<html>
<head>
<style>
  body { margin: 0; background: #e9e9e9; font-family: system-ui; }
  /* Your styles here */
</style>
</head>
<body>
  <!-- Your HTML here -->
</body>
</html>
HTML

# Render and capture
RESULT=$(uv run --with-requirements agent/requirements.txt python -m agent.tools render http://127.0.0.1:8080/preview.html)
SCREENSHOT=$(echo $RESULT | jq -r .screenshot)

# Compare to reference
REF_PATH="static/components/$COMP_ID/reference.png"
DIFF=$(uv run --with-requirements agent/requirements.txt python -m agent.tools diff $REF_PATH $SCREENSHOT)
SSIM=$(echo $DIFF | jq -r .ssim)
echo "SSIM: $SSIM"

# Save iteration
echo "{\"screenshot\": \"$SCREENSHOT\", \"ssim\": $SSIM}" | \
  uv run --with-requirements agent/requirements.txt python -m agent.tools save $COMP_ID
```

### 4. View in Browser

Open http://localhost:5173/component/$COMP_ID to see:
- Live preview
- Reference image
- Iteration history with screenshots and diffs

### 5. Get Gemini Feedback (when stuck)

```bash
uv run --with-requirements agent/requirements.txt python -m agent.tools vision \
  "SSIM is $SSIM. What CSS is wrong?" \
  $REF_PATH \
  "data:image/png;base64,$SCREENSHOT"
```

### 6. Cleanup

```bash
kill $SERVER_PID
```

---

## View Progress

The SvelteKit app shows live progress:

1. **Home page**: `/` - List all components with status
2. **Component page**: `/component/[id]` - Preview + iterations
3. **Preview**: `/component/[id]/preview` - Full page render

Start the dev server:
```bash
npm run dev
```

---

## Rules

- Plain CSS in HTML (no frameworks)
- Use colors from `colors` command
- Check the web UI to see iteration history
- Ask user after meaningful progress or 2-3 Gemini checkins
- User decides when done
