"""
log_event — Appends structured debug events to a component's log.ndjson.
Gives the SvelteKit viewer real-time insight into every step of the agent loop.

Events are newline-delimited JSON. Each line: {"ts": "...", "type": "...", ...kwargs}
"""
import base64
import io
import json
from datetime import datetime
from pathlib import Path

COMPONENTS_DIR = Path(__file__).parent.parent.parent / "static" / "components"


def _thumb(b64: str, max_px: int = 260) -> str:
    """Downsize a base64-encoded PNG/JPEG to a small JPEG thumbnail.
    Returns empty string on failure (PIL missing, bad data, etc.)."""
    if not b64:
        return ""
    try:
        from PIL import Image
        data = base64.b64decode(b64)
        img = Image.open(io.BytesIO(data)).convert("RGB")
        if img.width > max_px:
            h = int(img.height * max_px / img.width)
            img = img.resize((max_px, h), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=55)
        return base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return ""


def log_event(comp_id: str, event_type: str, **kwargs) -> None:
    """Append one structured event to static/components/{comp_id}/log.ndjson.
    Never raises — logging failures are silently swallowed."""
    if not comp_id:
        return
    log_path = COMPONENTS_DIR / comp_id / "log.ndjson"
    if not log_path.parent.exists():
        return
    event = {"ts": datetime.now().isoformat(), "type": event_type, **kwargs}
    try:
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
    except Exception:
        pass


def clear_log(comp_id: str) -> None:
    """Truncate the log file for a fresh run."""
    if not comp_id:
        return
    log_path = COMPONENTS_DIR / comp_id / "log.ndjson"
    if log_path.parent.exists():
        try:
            log_path.write_text("", encoding="utf-8")
        except Exception:
            pass
