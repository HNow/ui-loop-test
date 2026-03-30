"""
UI Cloner Tools v3 - Svelte Component Builder Architecture

Tools work with component directories under static/components/{id}/
Each component has:
  - Component.svelte (generated component)
  - preview.html (live preview)
  - meta.json (iteration history, SSIM, etc.)
  - reference.png (reference image)
  - screenshots/{n}.png (screenshots per iteration)
  - diffs/{n}.png (diff overlays per iteration)
"""
import base64
import json
import shutil
import subprocess
import socket
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

# Base paths
REPO = Path(__file__).parent.parent.parent  # ui-loop-test/
COMPONENTS_DIR = REPO / "static" / "components"
UI_INSPO_DIR = REPO / "ui-inspo"


def create_component(name: str, reference_image: Optional[str] = None) -> dict:
    """
    Create a new component directory structure.
    
    Returns component ID and paths.
    """
    import random
    comp_id = f"comp_{int(time.time())}_{random.randint(1000, 9999)}"
    comp_dir = COMPONENTS_DIR / comp_id
    
    comp_dir.mkdir(parents=True, exist_ok=True)
    (comp_dir / "screenshots").mkdir(exist_ok=True)
    (comp_dir / "diffs").mkdir(exist_ok=True)
    
    # Copy reference image if provided
    ref_filename = None
    if reference_image:
        ref_path = Path(reference_image)
        if not ref_path.is_absolute():
            # Check if it already has ui-inspo prefix or not
            if ref_path.parts[0] == "ui-inspo":
                ref_path = REPO / ref_path
            else:
                ref_path = UI_INSPO_DIR / ref_path.name
        if ref_path.exists():
            ext = ref_path.suffix
            shutil.copy(ref_path, comp_dir / f"reference{ext}")
            ref_filename = f"reference{ext}"
    
    # Create initial preview.html
    (comp_dir / "preview.html").write_text("""<!DOCTYPE html>
<html>
<head>
  <style>
    body { margin: 0; padding: 2rem; background: #fff; font-family: system-ui; }
    .placeholder { color: #999; text-align: center; padding: 4rem; }
  </style>
</head>
<body>
  <div class="placeholder">
    <p>Component not yet generated</p>
  </div>
</body>
</html>
""")
    
    # Create meta.json
    meta = {
        "id": comp_id,
        "name": name,
        "reference": ref_filename,
        "status": "initial",
        "iterations": [],
        "colors": [],
        "scratchpad": "",
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat()
    }
    (comp_dir / "meta.json").write_text(json.dumps(meta, indent=2))
    
    # Update registry
    _update_registry(comp_id, name, "initial", 0, None)
    
    return {
        "id": comp_id,
        "path": str(comp_dir),
        "reference": ref_filename
    }


def _update_registry(comp_id: str, name: str, status: str, iter_count: int, best_ssim: Optional[float]):
    """Update the component registry."""
    registry_path = COMPONENTS_DIR / "registry.json"
    if registry_path.exists():
        registry = json.loads(registry_path.read_text())
    else:
        registry = {"components": []}
    
    # Update or add component
    existing = next((c for c in registry["components"] if c["id"] == comp_id), None)
    if existing:
        existing.update({
            "name": name,
            "status": status,
            "iteration_count": iter_count,
            "best_ssim": best_ssim,
            "updated_at": datetime.now().isoformat()
        })
    else:
        registry["components"].append({
            "id": comp_id,
            "name": name,
            "status": status,
            "iteration_count": iter_count,
            "best_ssim": best_ssim,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        })
    
    registry_path.write_text(json.dumps(registry, indent=2))


def get_component(comp_id: str) -> dict:
    """Get component metadata and state."""
    comp_dir = COMPONENTS_DIR / comp_id
    meta_path = comp_dir / "meta.json"
    
    if not meta_path.exists():
        return {"error": f"Component {comp_id} not found"}
    
    meta = json.loads(meta_path.read_text())
    
    # Read current preview.html
    preview_path = comp_dir / "preview.html"
    if preview_path.exists():
        meta["html_code"] = preview_path.read_text()
    
    return meta


def write_html(comp_id: str, html_content: str) -> dict:
    """
    Write HTML to preview.html.
    
    Also saves a versioned copy.
    """
    comp_dir = COMPONENTS_DIR / comp_id
    if not comp_dir.exists():
        return {"error": f"Component {comp_id} not found"}
    
    meta = json.loads((comp_dir / "meta.json").read_text())
    iter_num = len(meta["iterations"]) + 1
    
    # Write preview.html
    (comp_dir / "preview.html").write_text(html_content)

    # Save versioned copy
    (comp_dir / f"v{iter_num}.html").write_text(html_content)

    log_event(comp_id, "html_written", iter=iter_num, preview=html_content[:400])

    return {
        "ok": True,
        "iteration": iter_num,
        "path": str(comp_dir / "preview.html")
    }


def save_iteration(
    comp_id: str,
    screenshot_b64: str,
    diff_b64: Optional[str] = None,
    ssim: Optional[float] = None,
    console_errors: Optional[list] = None,
    note: Optional[str] = None
) -> dict:
    """
    Save iteration data (screenshot, diff, SSIM, etc.)
    """
    comp_dir = COMPONENTS_DIR / comp_id
    if not comp_dir.exists():
        return {"error": f"Component {comp_id} not found"}
    
    meta = json.loads((comp_dir / "meta.json").read_text())
    iter_num = len(meta["iterations"]) + 1
    
    # Save screenshot
    if screenshot_b64:
        # Strip data URL prefix if present
        if screenshot_b64.startswith("data:"):
            screenshot_b64 = screenshot_b64.split(",", 1)[1]
        (comp_dir / "screenshots" / f"{iter_num}.png").write_bytes(
            base64.b64decode(screenshot_b64)
        )
    
    # Save diff overlay
    if diff_b64:
        if diff_b64.startswith("data:"):
            diff_b64 = diff_b64.split(",", 1)[1]
        (comp_dir / "diffs" / f"{iter_num}.png").write_bytes(
            base64.b64decode(diff_b64)
        )
    
    # Update meta
    iteration = {
        "num": iter_num,
        "ssim": ssim,
        "has_screenshot": bool(screenshot_b64),
        "has_diff": bool(diff_b64),
        "console_errors": console_errors or [],
        "note": note,
        "created_at": datetime.now().isoformat()
    }
    meta["iterations"].append(iteration)
    meta["updated_at"] = datetime.now().isoformat()
    
    meta["status"] = "iterating"
    
    (comp_dir / "meta.json").write_text(json.dumps(meta, indent=2))

    # Update registry
    best_ssim = max((i.get("ssim") or 0 for i in meta["iterations"]), default=None)
    _update_registry(comp_id, meta["name"], meta["status"], len(meta["iterations"]), best_ssim)

    log_event(comp_id, "iteration_saved",
              iter=iter_num, ssim=ssim,
              has_screenshot=bool(screenshot_b64),
              has_diff=bool(diff_b64),
              status=meta["status"])

    return {
        "ok": True,
        "iteration": iter_num,
        "status": meta["status"],
        "ssim": ssim
    }


def update_scratchpad(comp_id: str, content: str, action: str = "append") -> dict:
    """Update component scratchpad."""
    comp_dir = COMPONENTS_DIR / comp_id
    if not comp_dir.exists():
        return {"error": f"Component {comp_id} not found"}
    
    meta = json.loads((comp_dir / "meta.json").read_text())
    
    if action == "append":
        meta["scratchpad"] = (meta.get("scratchpad", "") + "\n" + content).strip()
    elif action == "write":
        meta["scratchpad"] = content
    elif action == "clear":
        meta["scratchpad"] = ""

    (comp_dir / "meta.json").write_text(json.dumps(meta, indent=2))

    log_event(comp_id, "scratchpad_update",
              action=action, excerpt=meta["scratchpad"][-400:])

    return {"ok": True, "scratchpad": meta["scratchpad"]}


def get_reference_path(comp_id: str) -> Optional[str]:
    """Get the reference image path for a component."""
    comp_dir = COMPONENTS_DIR / comp_id
    if not comp_dir.exists():
        return None
    
    meta = json.loads((comp_dir / "meta.json").read_text())
    if meta.get("reference"):
        return str(comp_dir / meta["reference"])
    return None


# Re-export existing tools
from .render_and_capture import render_and_capture
from .visual_diff import visual_diff
from .extract_colors import extract_colors
from .extract_layout import extract_layout
from .vision_analyze import vision_analyze
from .log_event import log_event, _thumb, clear_log


if __name__ == "__main__":
    import sys
    # CLI interface
    if len(sys.argv) < 2:
        print("Usage: python -m agent.tools <command> [args...]")
        print("Commands: create, get, write_html, save_iteration, render, diff, colors, vision")
        sys.exit(1)
    
    cmd = sys.argv[1]
    
    if cmd == "create":
        name = sys.argv[2] if len(sys.argv) > 2 else "NewComponent"
        ref = sys.argv[3] if len(sys.argv) > 3 else None
        result = create_component(name, ref)
        print(json.dumps(result))
    
    elif cmd == "get":
        comp_id = sys.argv[2]
        result = get_component(comp_id)
        print(json.dumps(result, indent=2))
    
    elif cmd == "write_html":
        comp_id = sys.argv[2]
        html = sys.argv[3] if len(sys.argv) > 3 else ""
        if html == "-" or not html:
            html = sys.stdin.read()
        result = write_html(comp_id, html)
        print(json.dumps(result))
    
    elif cmd == "save_iteration":
        comp_id = sys.argv[2]
        # Read JSON from stdin
        data = json.loads(sys.stdin.read())
        result = save_iteration(
            comp_id,
            data.get("screenshot"),
            data.get("diff"),
            data.get("ssim"),
            data.get("console_errors"),
            data.get("note")
        )
        print(json.dumps(result))
    
    elif cmd == "render":
        url = sys.argv[2]
        result = render_and_capture(url)
        # Output as JSON with screenshot as base64
        print(json.dumps(result))
    
    elif cmd == "diff":
        ref = sys.argv[2]
        gen = sys.argv[3] if len(sys.argv) > 3 else "-"
        if gen == "-":
            gen = sys.stdin.read().strip()
        result = visual_diff(ref, gen)
        print(json.dumps(result))
    
    elif cmd == "colors":
        img = sys.argv[2]
        result = extract_colors(img)
        print(json.dumps(result, indent=2))
    
    elif cmd == "vision":
        prompt = sys.argv[2]
        images = sys.argv[3:] if len(sys.argv) > 3 else []
        result = vision_analyze(images, prompt)
        print(json.dumps(result))
    
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
