"""
Utility modules for the UI cloning pipeline:

    - image.py  — SSIM computation, color extraction, diff overlays, cropping
    - dom.py     — Playwright-based DOM extraction and screenshot capture
    - metrics.py — Structural metrics (TreeBLEU, ContainerMatch, TreeEditDistance)
"""

from utils.image import (
    compute_ssim,
    extract_colors,
    create_diff_overlay,
    load_image,
    save_image,
)
from utils.dom import render_html, extract_dom_tree, DOMNode
from utils.metrics import compute_all_metrics

__all__ = [
    "compute_ssim",
    "extract_colors",
    "create_diff_overlay",
    "load_image",
    "save_image",
    "render_html",
    "extract_dom_tree",
    "DOMNode",
    "compute_all_metrics",
]
