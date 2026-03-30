"""
scratchpad — Persistent text memory across loop iterations.
Stored as a plain text file inside the run directory.
Auto-appended with iteration number and SSIM history after each round.
"""
from pathlib import Path


def scratchpad(
    action: str,
    run_dir: str,
    content: str | None = None,
) -> dict:
    """
    Read, write, append, or clear the run's scratchpad.

    Args:
        action:   "read" | "write" | "append" | "clear"
        run_dir:  Absolute path to current run directory
        content:  Required for "write" and "append"

    Returns:
        {"content": str}  for read
        {"ok": True}      for write / append / clear
        {"error": str}    on failure
    """
    try:
        path = Path(run_dir) / "scratchpad.txt"

        if action == "read":
            return {"content": path.read_text(encoding="utf-8") if path.exists() else ""}

        if action == "write":
            if content is None:
                return {"error": "content required for write"}
            path.write_text(content, encoding="utf-8")
            return {"ok": True}

        if action == "append":
            if content is None:
                return {"error": "content required for append"}
            with path.open("a", encoding="utf-8") as f:
                f.write(content if content.endswith("\n") else content + "\n")
            return {"ok": True}

        if action == "clear":
            path.write_text("", encoding="utf-8")
            return {"ok": True}

        return {"error": f"unknown action '{action}'"}

    except Exception as e:
        return {"error": str(e)}


def auto_append_iteration(run_dir: str, iteration: int, ssim: float, status: str = "") -> None:
    """Convenience: called by the loop after each iteration to record progress."""
    line = f"[iter {iteration}] SSIM={ssim:.4f}"
    if status:
        line += f" — {status}"
    scratchpad("append", run_dir, line)
