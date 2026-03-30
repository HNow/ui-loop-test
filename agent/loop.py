"""
loop.py — Standalone fallback orchestrator (bypasses Hermes Agent).

NOTE: The primary integration path is via MCP — run `./start.sh` and load
the skill through Hermes Agent. Use this script only for offline testing
without Hermes, or to verify the tool implementations directly.

Usage:
    python agent/loop.py --image ui-inspo/my-ref.png [--run-id my-run] [--max-iter 8]

The loop:
  1. extract_colors on the reference image (once)
  2. Optionally: vision_analyze for initial description
  3. For each iteration:
     a. Feed context → model writes code via write_code tool
     b. render_and_capture → screenshot
     c. visual_diff → SSIM + overlay
     d. Check convergence / plateau
     e. extract_layout for next iteration's feedback
     f. auto-append scratchpad
  4. Save run metadata to output/{run_id}/run.json
"""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# Add parent to path so `agent` is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.tools.write_code import write_code
from agent.tools.render_and_capture import render_and_capture
from agent.tools.visual_diff import visual_diff
from agent.tools.extract_layout import extract_layout
from agent.tools.extract_colors import extract_colors
from agent.tools.scratchpad import scratchpad, auto_append_iteration
from agent.tools.vision_analyze import vision_analyze
from agent.tools.log_event import log_event, _thumb, clear_log

# ── Constants ──────────────────────────────────────────────────────────────────
MAX_ITERATIONS = 8
SERVE_PORT = 8080
OUTPUT_BASE = Path(__file__).parent.parent / "output"


# ── Tiny file server ───────────────────────────────────────────────────────────
class _FileServer:
    """Serves the output/{run_id} directory so Playwright can load the HTML."""

    def __init__(self, directory: Path, port: int):
        self.directory = directory
        self.port = port
        self._proc: subprocess.Popen | None = None

    def start(self):
        self._proc = subprocess.Popen(
            [sys.executable, "-m", "http.server", str(self.port), "--directory", str(self.directory)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(0.5)
        print(f"[serve] http://localhost:{self.port}/ → {self.directory}")

    def stop(self):
        if self._proc:
            self._proc.terminate()
            self._proc = None


# ── Metadata helpers ───────────────────────────────────────────────────────────
def _save_meta(run_dir: Path, meta: dict):
    (run_dir / "run.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


# ── Viewer bridge ──────────────────────────────────────────────────────────────
def _post_to_viewer(
    svelte_url: str,
    component_id: str,
    *,
    html_code: str | None = None,
    screenshot: str | None = None,
    diff: str | None = None,
    ssim: float | None = None,
    console_errors: list | None = None,
    note: str | None = None,
) -> None:
    """POST iteration data to the SvelteKit viewer API."""
    try:
        import requests as _req
        payload = {
            "html_code": html_code,
            "screenshot": f"data:image/png;base64,{screenshot}" if screenshot else None,
            "diff": f"data:image/png;base64,{diff}" if diff else None,
            "ssim": ssim,
            "console_errors": console_errors or [],
            "note": note,
        }
        resp = _req.post(
            f"{svelte_url}/api/components/{component_id}",
            json=payload,
            timeout=15,
        )
        print(f"  [viewer] POST → {resp.status_code}")
    except Exception as e:
        print(f"  [viewer] Post failed: {e}")


# ── Tool arg summariser (strips large base64 so logs stay readable) ────────────
def _safe_args(tool_name: str, args: dict) -> str:
    _BIG = {"content", "generated_image", "screenshot", "images", "reference_image"}
    parts = []
    for k, v in args.items():
        if k in _BIG or (isinstance(v, str) and len(v) > 200):
            parts.append(f"{k}=<{len(str(v))} chars>")
        else:
            val = json.dumps(v)
            parts.append(f"{k}={val[:80]}")
    return ", ".join(parts)


# ── Tool dispatcher ────────────────────────────────────────────────────────────
def dispatch_tool(name: str, args: dict, run_dir: str, server_url: str) -> dict:
    if name == "write_code":
        return write_code(args["filepath"], args["content"], run_dir)
    if name == "render_and_capture":
        url = args.get("target", f"{server_url}/index.html")
        return render_and_capture(
            url,
            args.get("viewport_width", 1280),
            args.get("viewport_height", 800),
            args.get("full_page", True),
            args.get("wait_ms", 1500),
        )
    if name == "visual_diff":
        return visual_diff(
            args["reference_image"],
            args["generated_image"],
            args.get("resize_to_match", True),
            args.get("diff_threshold", 35),
        )
    if name == "extract_layout":
        return extract_layout(
            args.get("target", f"{server_url}/index.html"),
            args.get("selector", "body"),
            args.get("max_depth", 5),
        )
    if name == "extract_colors":
        return extract_colors(args["image"], args.get("num_colors", 8))
    if name == "scratchpad":
        return scratchpad(args["action"], run_dir, args.get("content"))
    if name == "vision_analyze":
        return vision_analyze(
            args["images"],
            args["prompt"],
        )
    return {"error": f"unknown tool: {name}"}


# ── Main loop ──────────────────────────────────────────────────────────────────
def run_loop(
    reference_image: str,
    run_id: str | None = None,
    max_iterations: int = MAX_ITERATIONS,
    hermes_endpoint: str = "http://localhost:11434/v1",
    model: str = "qwen2.5:27b",
    initial_vision: bool = False,
    component_id: str | None = None,
    svelte_url: str = "http://localhost:5173",
):
    """
    Run the UI cloning loop against a reference image.

    Args:
        reference_image:   Path to reference PNG/JPG in ui-inspo/
        run_id:            Unique run identifier (defaults to timestamp + image stem)
        max_iterations:    Max loop iterations
        hermes_endpoint:   OpenAI-compatible endpoint for Qwen via Ollama/Hermes
        model:             Model name at the endpoint
        initial_vision:    Call Gemini Flash at iteration 0 for reference description
        component_id:      SvelteKit component ID — enables live viewer updates + log
        svelte_url:        SvelteKit dev server URL
    """
    import base64
    from openai import OpenAI

    # Fall back to env vars if not passed
    component_id = component_id or os.getenv("VIEWER_COMPONENT_ID")
    svelte_url = svelte_url or os.getenv("VIEWER_URL", "http://localhost:5173")

    ref_path = Path(reference_image).resolve()
    if not ref_path.exists():
        print(f"[error] Reference image not found: {ref_path}")
        sys.exit(1)

    run_id = run_id or f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{ref_path.stem}"
    run_dir = OUTPUT_BASE / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    run_dir_str = str(run_dir)

    # Clear log for a fresh run
    if component_id:
        clear_log(component_id)

    server_url = f"http://localhost:{SERVE_PORT}"
    server = _FileServer(run_dir, SERVE_PORT)
    server.start()

    meta = {
        "run_id": run_id,
        "reference": str(ref_path),
        "started_at": datetime.now().isoformat(),
        "iterations": [],
    }
    _save_meta(run_dir, meta)

    # ── Bootstrap ──────────────────────────────────────────────────────────────
    print(f"[init] Extracting colors from {ref_path.name}")
    colors_result = extract_colors(str(ref_path))
    colors_str = json.dumps(colors_result.get("colors", []), indent=2)

    ref_b64 = base64.b64encode(ref_path.read_bytes()).decode()

    if component_id:
        log_event(component_id, "loop_start",
                  ref_thumb=_thumb(ref_b64),
                  ref_name=ref_path.name,
                  max_iter=max_iterations,
                  model=model,
                  colors=colors_result.get("colors", []))

    initial_analysis = ""
    if initial_vision:
        print("[init] Requesting initial vision analysis from Gemini Flash")
        if component_id:
            log_event(component_id, "status", msg="Running initial Gemini vision analysis…")
        va = vision_analyze(
            [ref_b64],
            "Describe this UI in detail: layout structure, color palette, typography, spacing, components. Be specific and actionable.",
        )
        initial_analysis = va.get("analysis", "")
        if component_id and initial_analysis:
            log_event(component_id, "gemini_feedback",
                      context="initial_analysis", text=initial_analysis)

    scratchpad("write", run_dir_str, f"Run: {run_id}\nReference: {ref_path.name}\n")

    # ── Build tool schema list for the model ───────────────────────────────────
    tools_path = Path(__file__).parent / "hermes_tools.json"
    with open(tools_path) as f:
        tool_schemas = json.load(f)

    client = OpenAI(
        base_url=hermes_endpoint,
        api_key=os.getenv("OLLAMA_API_KEY", "ollama"),
    )

    # ── System prompt ──────────────────────────────────────────────────────────
    system_prompt = f"""You are a UI cloning expert. Your task is to recreate a reference UI screenshot as a self-contained HTML file.

REFERENCE COLORS (k-means, most dominant first):
{colors_str}

{f'INITIAL REFERENCE ANALYSIS:{chr(10)}{initial_analysis}' if initial_analysis else ''}

WORKFLOW PER ITERATION:
1. Call write_code to output a self-contained HTML file (filepath: "index.html")
2. Call render_and_capture to get a screenshot
3. Call visual_diff with the reference image path and the screenshot
4. Call extract_layout to understand the DOM structure
5. Optionally call scratchpad to record observations
6. Study the diff overlay and SSIM score — focus your next iteration on the worst regions

RULES:
- Always produce a single self-contained HTML file — no external CSS/JS files
- Use plain CSS only: inline <style> blocks or style attributes. No frameworks.
- Match exact colors from the palette above
- Phase your work: iterations 1-2 = structure/layout, 3-4 = colors/typography, 5+ = spacing/polish
- If SSIM is below 0.70 after 3 iterations, rewrite from scratch rather than patching
- Record key observations in the scratchpad to guide future iterations
"""

    messages = [{"role": "system", "content": system_prompt}]

    # ── Loop ───────────────────────────────────────────────────────────────────
    for i in range(max_iterations):
        print(f"\n{'='*60}")
        print(f"[iter {i+1}/{max_iterations}]")

        if component_id:
            log_event(component_id, "iteration_start", iter=i + 1, total=max_iterations)

        # Build user message: reference image + diff overlay from last iter + scratchpad
        user_content: list[dict] = [
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{ref_b64}"},
            },
            {
                "type": "text",
                "text": f"Iteration {i+1}. Reference image shown above. "
                        + (f"Previous SSIM scores: {scores}. " if scores else "First iteration — start fresh. ")
                        + "Analyze the reference carefully and produce the HTML.",
            },
        ]

        # Inject diff overlay from previous iteration if available
        overlay_for_log: str | None = None
        if i > 0 and meta["iterations"]:
            last = meta["iterations"][-1]
            if last.get("overlay"):
                overlay_for_log = last["overlay"]
                user_content.insert(1, {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{last['overlay']}"},
                })
                user_content.insert(2, {
                    "type": "text",
                    "text": f"Diff overlay shown above (magenta = mismatch). Last SSIM: {last['ssim']}.",
                })

        # Log what images are being sent to the model this iteration
        if component_id:
            thumbs = [_thumb(ref_b64)]
            labels = ["reference"]
            if overlay_for_log:
                thumbs.append(_thumb(overlay_for_log))
                labels.append("diff overlay (prev iter)")
            log_event(component_id, "images_to_model",
                      iter=i + 1, thumbs=thumbs, labels=labels)

        # Inject scratchpad
        pad = scratchpad("read", run_dir_str)
        if pad.get("content"):
            user_content.append({"type": "text", "text": f"SCRATCHPAD:\n{pad['content']}"})

        messages.append({"role": "user", "content": user_content})

        # ── Model call with tool loop ───────────────────────────────────────────
        iteration_data: dict = {"iteration": i + 1, "tool_calls": []}
        current_screenshot_b64: str | None = None
        current_overlay: str | None = None
        current_html: str | None = None
        current_console_errors: list = []

        while True:
            if component_id:
                log_event(component_id, "model_thinking", iter=i + 1)

            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=tool_schemas,
                tool_choice="auto",
            )
            msg = response.choices[0].message
            messages.append(msg.model_dump())

            if not msg.tool_calls:
                # Model finished — log any text it produced
                if component_id and msg.content:
                    text = msg.content
                    if isinstance(text, list):
                        text = " ".join(
                            b.get("text", "") if isinstance(b, dict) else str(b)
                            for b in text
                        )
                    if text and text.strip():
                        log_event(component_id, "model_text",
                                  iter=i + 1, text=str(text).strip()[:800])
                break

            for tc in msg.tool_calls:
                name = tc.function.name
                args = json.loads(tc.function.arguments)
                print(f"  [tool] {name}({list(args.keys())})")

                # Inject reference image path for visual_diff
                if name == "visual_diff" and "reference_image" not in args:
                    args["reference_image"] = str(ref_path)

                # Log tool call start
                if component_id:
                    log_event(component_id, "tool_call",
                              iter=i + 1, tool=name,
                              args_preview=_safe_args(name, args))

                result = dispatch_tool(name, args, run_dir_str, server_url)

                # Capture key outputs and build rich tool_result event
                tool_result_kwargs: dict = {"iter": i + 1, "tool": name}

                if name == "write_code":
                    html_path = Path(run_dir_str) / "index.html"
                    if html_path.exists():
                        current_html = html_path.read_text(encoding="utf-8")
                        tool_result_kwargs["html_preview"] = current_html[:500]

                if name == "render_and_capture":
                    if "screenshot" in result:
                        current_screenshot_b64 = result["screenshot"]
                        tool_result_kwargs["screenshot_thumb"] = _thumb(current_screenshot_b64)
                    current_console_errors = result.get("console_errors", [])
                    if current_console_errors:
                        tool_result_kwargs["console_errors"] = current_console_errors
                        tool_result_kwargs["console_error_count"] = len(current_console_errors)
                    tool_result_kwargs["page_height"] = result.get("page_height")
                    tool_result_kwargs["viewport"] = result.get("viewport")

                if name == "visual_diff":
                    current_overlay = result.get("overlay")
                    tool_result_kwargs["pixel_diff_pct"] = result.get("pixel_diff_pct")
                    if current_overlay:
                        tool_result_kwargs["overlay_thumb"] = _thumb(current_overlay)
                    if result.get("pixel_diff_pct") is not None:
                        print(f"  [diff] {result['pixel_diff_pct']}% pixels differ")

                if name == "extract_layout":
                    tool_result_kwargs["node_count"] = result.get("node_count")

                if name == "scratchpad":
                    tool_result_kwargs["content"] = result.get("content", "")[:400]

                if "error" in result:
                    tool_result_kwargs["error"] = result["error"]

                if component_id:
                    log_event(component_id, "tool_result", **tool_result_kwargs)

                iteration_data["tool_calls"].append({"tool": name, "result_keys": list(result.keys())})

                # Feed result back as tool message
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result),
                })

        # Record iteration
        if current_overlay:
            iteration_data["overlay"] = current_overlay
        auto_append_iteration(run_dir_str, i + 1, None)

        meta["iterations"].append(iteration_data)
        _save_meta(run_dir, meta)

        # Push to SvelteKit viewer
        if component_id:
            _post_to_viewer(
                svelte_url,
                component_id,
                html_code=current_html,
                screenshot=current_screenshot_b64,
                diff=current_overlay,
                ssim=None,
                console_errors=current_console_errors,
            )
            log_event(component_id, "iteration_end", iter=i + 1)

        # ── Gemini analysis after every iteration ───────────────────────────────
        if current_screenshot_b64 and current_overlay:
            print(f"[gemini] Requesting analysis for iter {i+1}")
            if component_id:
                log_event(component_id, "status", msg=f"Asking Gemini to analyse iteration {i+1}…")
            images_for_vision = [ref_b64, current_screenshot_b64, current_overlay]
            va = vision_analyze(
                images_for_vision,
                f"Iteration {i+1} of {max_iterations}. "
                "Image 1: reference target. Image 2: current render. Image 3: pixel diff (magenta = mismatch). "
                "What specific visual issues remain? List concrete CSS fixes. Be direct and actionable.",
            )
            analysis = va.get("analysis", "")
            if analysis:
                print(f"  [gemini] {analysis[:200]}...")
                if component_id:
                    log_event(component_id, "gemini_feedback",
                              context=f"iter_{i+1}_analysis",
                              iter=i + 1, text=analysis)
                messages.append({
                    "role": "user",
                    "content": f"Gemini analysis of iteration {i+1}:\n{analysis}\n\nAddress these issues in the next iteration.",
                })

    # ── Cleanup ─────────────────────────────────────────────────────────────────
    meta["finished_at"] = datetime.now().isoformat()
    _save_meta(run_dir, meta)
    server.stop()

    # Mark component as done so the viewer stops polling
    if component_id:
        from agent.tools import COMPONENTS_DIR
        comp_meta_path = Path(COMPONENTS_DIR) / component_id / "meta.json"
        if comp_meta_path.exists():
            try:
                m = json.loads(comp_meta_path.read_text())
                m["status"] = "done"
                comp_meta_path.write_text(json.dumps(m, indent=2))
            except Exception:
                pass
        log_event(component_id, "loop_end", total_iter=len(meta["iterations"]))

    print(f"\n[done] Run: {run_id}")
    print(f"[done] Iterations: {len(meta['iterations'])}")
    print(f"[done] Output: {run_dir}")
    return meta


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="UI Cloning Agent Loop")
    parser.add_argument("--image", required=True, help="Path to reference image")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--max-iter", type=int, default=MAX_ITERATIONS)
    parser.add_argument("--endpoint", default="http://localhost:11434/v1")
    parser.add_argument("--model", default="qwen2.5:27b")
    parser.add_argument("--initial-vision", action="store_true")
    parser.add_argument("--component-id", default=None,
                        help="SvelteKit component ID (or set VIEWER_COMPONENT_ID env var)")
    parser.add_argument("--svelte-url", default="http://localhost:5173")
    args = parser.parse_args()

    run_loop(
        reference_image=args.image,
        run_id=args.run_id,
        max_iterations=args.max_iter,
        hermes_endpoint=args.endpoint,
        model=args.model,
        initial_vision=args.initial_vision,
        component_id=args.component_id,
        svelte_url=args.svelte_url,
    )
