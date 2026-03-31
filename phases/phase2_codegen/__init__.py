"""
Phase 2: Hierarchy-Aware Code Generation

Modules:
    - html_gen.py  — HTMLGenerator: Generate HTML structure from component tree
    - style_gen.py — StyleGenerator: Apply plain CSS styles from bounding boxes

Both modules use plain CSS only — no Tailwind utility classes.
"""

from phases.phase2_codegen.html_gen import HTMLGenerator
from phases.phase2_codegen.style_gen import StyleGenerator

__all__ = [
    "HTMLGenerator",
    "StyleGenerator",
]
