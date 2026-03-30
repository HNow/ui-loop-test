"""
CLI for UI Cloner Tools v3.

Usage:
    python -m agent.tools <command> [args...]

Commands:
    create <name> [reference_image]  - Create new component
    get <comp_id>                    - Get component info
    write <comp_id>                  - Write HTML (from stdin)
    render <url>                     - Render and screenshot
    diff <ref_path> <gen_b64>        - Compare images
    colors <image_path>              - Extract colors
    save <comp_id> <json>            - Save iteration data
    vision <prompt> <images...>      - Analyze with Gemini

Examples:
    python -m agent.tools create Card ui-inspo/card.png
    python -m agent.tools get comp_123456_7890
    
    echo '<html>...</html>' | python -m agent.tools write comp_123456_7890
    
    python -m agent.tools render http://localhost:8080/preview.html
    
    python -m agent.tools diff ui-inspo/card.png "$(cat screenshot.b64)"
"""
import re
import sys
import json
from pathlib import Path


def _infer_comp_id(image_paths=None):
    """
    Infer which component is active without requiring an env var.

    1. Parse comp_id out of any image path that lives under .../components/<id>/...
    2. Fall back to the most-recently-updated 'iterating' component in registry.json
    """
    if image_paths:
        for p in image_paths:
            m = re.search(r'components[/\\](comp_[^/\\]+)[/\\]', str(p))
            if m:
                return m.group(1)

    registry_path = Path(__file__).parent.parent.parent / "static" / "components" / "registry.json"
    if registry_path.exists():
        try:
            registry = json.loads(registry_path.read_text())
            active = [c for c in registry.get("components", [])
                      if c.get("status") in ("iterating", "initial")]
            if active:
                active.sort(key=lambda c: c.get("updated_at", ""), reverse=True)
                return active[0]["id"]
        except Exception:
            pass

    return None


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    
    cmd = sys.argv[1]
    args = sys.argv[2:]
    
    # Import tools
    from . import (
        create_component, get_component, write_html, save_iteration,
        render_and_capture, visual_diff, extract_colors, vision_analyze,
        get_reference_path, COMPONENTS_DIR
    )
    from pathlib import Path
    
    if cmd == "create":
        name = args[0] if args else "NewComponent"
        ref = args[1] if len(args) > 1 else None
        result = create_component(name, ref)
        print(json.dumps(result))
    
    elif cmd == "get":
        if not args:
            print(json.dumps({"error": "Usage: get <comp_id>"}))
            sys.exit(1)
        result = get_component(args[0])
        # Don't print html_code in full, just indicate if present
        if "html_code" in result:
            result["has_html"] = bool(result.pop("html_code"))
        print(json.dumps(result, indent=2))
    
    elif cmd in ("write", "write_html"):
        if not args:
            print(json.dumps({"error": "Usage: write <comp_id>"}))
            sys.exit(1)
        comp_id = args[0]
        # Read HTML from stdin or next arg
        if len(args) > 1:
            html = args[1]
        else:
            html = sys.stdin.read()
        result = write_html(comp_id, html)
        print(json.dumps(result))
    
    elif cmd == "save":
        if not args:
            print(json.dumps({"error": "Usage: save <comp_id>"}))
            sys.exit(1)
        comp_id = args[0]
        # Read JSON from stdin or next arg
        if len(args) > 1:
            data = json.loads(args[1])
        else:
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
        if not args:
            print(json.dumps({"error": "Usage: render <url>"}))
            sys.exit(1)
        result = render_and_capture(args[0])
        print(json.dumps(result))
    
    elif cmd == "diff":
        if len(args) < 2:
            print(json.dumps({"error": "Usage: diff <ref_path> <gen_b64>"}))
            sys.exit(1)
        result = visual_diff(args[0], args[1])
        # Don't print full overlay, just indicate presence
        if "overlay" in result:
            result["has_overlay"] = bool(result.pop("overlay"))
        print(json.dumps(result))
    
    elif cmd == "colors":
        if not args:
            print(json.dumps({"error": "Usage: colors <image_path>"}))
            sys.exit(1)
        result = extract_colors(args[0])
        print(json.dumps(result))
        comp_id = _infer_comp_id([args[0]])
        if comp_id and "colors" in result:
            from .log_event import log_event
            log_event(comp_id, "colors_extracted", colors=result["colors"])
    
    elif cmd == "layout":
        if not args:
            print(json.dumps({"error": "Usage: layout <url>"}))
            sys.exit(1)
        from .extract_layout import extract_layout
        result = extract_layout(args[0])
        print(json.dumps(result))
    
    elif cmd == "vision":
        if len(args) < 2:
            print(json.dumps({"error": "Usage: vision <prompt> <image1> [image2] ..."}))
            sys.exit(1)
        prompt = args[0]
        images = args[1:]
        result = vision_analyze(images, prompt)
        print(json.dumps(result))
        comp_id = _infer_comp_id(images)
        if comp_id and "analysis" in result:
            from .log_event import log_event
            log_event(comp_id, "gemini_feedback", context="vision_analyze",
                      text=result["analysis"], prompt=prompt[:200])
    
    elif cmd == "ref":
        if not args:
            print(json.dumps({"error": "Usage: ref <comp_id>"}))
            sys.exit(1)
        result = get_reference_path(args[0])
        print(json.dumps({"reference_path": result}))
    
    elif cmd == "scratchpad":
        if len(args) < 2:
            print(json.dumps({"error": "Usage: scratchpad <comp_id> <action> [content]"}))
            sys.exit(1)
        from . import update_scratchpad
        comp_id = args[0]
        action = args[1]
        content = args[2] if len(args) > 2 else sys.stdin.read()
        result = update_scratchpad(comp_id, content, action)
        print(json.dumps(result))
    
    elif cmd == "list":
        # List all components
        registry_path = COMPONENTS_DIR / "registry.json"
        if registry_path.exists():
            registry = json.loads(registry_path.read_text())
            print(json.dumps(registry, indent=2))
        else:
            print(json.dumps({"components": []}))
    
    else:
        print(json.dumps({"error": f"Unknown command: {cmd}"}))
        sys.exit(1)


if __name__ == "__main__":
    main()
