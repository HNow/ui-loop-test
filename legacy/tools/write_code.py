"""
write_code — Writes a self-contained HTML file and version-stamps a copy.
Serves as the agent's primary output mechanism.
"""
import os
import shutil
from pathlib import Path


def write_code(filepath: str, content: str, run_dir: str) -> dict:
    """
    Write HTML content to filepath (relative to run_dir) and copy to a versioned backup.

    Args:
        filepath: Target filename, e.g. 'index.html'
        content:  Complete HTML document string
        run_dir:  Absolute path to the current run directory

    Returns:
        {"path": str, "version": int, "version_path": str} on success
        {"error": str} on failure
    """
    try:
        run_path = Path(run_dir)
        run_path.mkdir(parents=True, exist_ok=True)

        target = run_path / filepath
        target.write_text(content, encoding="utf-8")

        # Determine next version number
        existing = sorted(run_path.glob("v*.html"))
        version = len(existing) + 1
        version_path = run_path / f"v{version}.html"
        shutil.copy2(target, version_path)

        return {
            "path": str(target),
            "version": version,
            "version_path": str(version_path),
        }
    except Exception as e:
        return {"error": str(e)}
