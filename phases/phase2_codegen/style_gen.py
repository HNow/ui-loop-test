"""
Phase 2.2: Style Generation

Generate plain CSS styles that match the reference visually.
Uses bounding boxes from the component tree to compute layout
(flex direction, gap, padding) and the extracted color palette
for visual styling.

NOTE: This module produces plain CSS only — no Tailwind.
The user preference is to avoid Tailwind utility classes entirely.
"""

import json
from typing import List, Dict, Optional
from storage.component import Component, ComponentTree, Element
from llm_client import DualProviderClient, Message
from config import Config


class StyleGenerator:
    """
    Generates plain CSS styles for the HTML structure produced by Phase 2.1.

    Style sources:
    - Layout (flex direction, gap, padding): computed from bounding boxes
    - Colors: extracted palette from the reference image
    - Typography: inferred from reference (font-size, weight, etc.)
    """

    def __init__(self, client: DualProviderClient, config: Config):
        self.client = client
        self.config = config

    async def apply_styles(
        self,
        component: Component,
        html_fragments: List[Dict[str, str]],
        colors: List[dict]
    ) -> str:
        """
        Apply plain CSS styles to HTML fragments.

        Returns a complete HTML document ready for rendering.

        Steps:
        1. Compute layout styles (flex, gap, padding) from bbox geometry
        2. Generate a CSS block from the computed styles
        3. Assemble a full HTML document (no Tailwind CDN)
        """
        if not component.tree:
            raise ValueError("Component tree required for style generation")

        print("  Computing layout styles from bounding boxes...")

        # Compute layout styles for every element in the tree
        layout_styles = {}
        for elem_id in component.tree.elements:
            layout_styles[elem_id] = self._compute_layout_styles(elem_id, component.tree)

        # Turn layout data into a CSS block
        custom_css = self._generate_custom_css(component.tree, layout_styles, colors)

        # Concatenate all HTML fragments into one body
        body_html = "\n".join(f["html_fragment"] for f in html_fragments)

        # Wrap everything in a full HTML document
        full_html = self._assemble_document(body_html, custom_css, colors)

        return full_html

    # ------------------------------------------------------------------
    # Layout computation from bounding boxes
    # ------------------------------------------------------------------

    def _compute_layout_styles(
        self,
        element_id: str,
        tree: ComponentTree
    ) -> dict:
        """
        Derive layout properties from the element's bbox and its
        children's bboxes.

        Returns a dict with: width, height, display, flex_direction,
        padding, gap.
        """
        elem = tree.elements.get(element_id)
        if not elem:
            return {}

        x, y, w, h = elem.bbox

        styles = {
            "width": w,
            "height": h,
            "display": "block",
            "flex_direction": None,
            "padding": 0,
            "gap": 0,
        }

        # Leaf nodes don't need layout computation
        if not elem.children_ids:
            return styles

        # Resolve child elements
        children = [tree.elements.get(cid) for cid in elem.children_ids]
        children = [c for c in children if c]

        if not children:
            return styles

        # Determine flex direction from child arrangement
        child_centers_x = []
        child_centers_y = []
        for child in children:
            cx, cy, cw, ch = child.bbox
            child_centers_x.append(cx + cw / 2)
            child_centers_y.append(cy + ch / 2)

        x_variance = max(child_centers_x) - min(child_centers_x)
        y_variance = max(child_centers_y) - min(child_centers_y)

        if x_variance > y_variance * 2:
            # Children spread horizontally → flex row
            styles["display"] = "flex"
            styles["flex_direction"] = "row"
        elif y_variance > x_variance * 2:
            # Children stacked vertically → flex column
            styles["display"] = "flex"
            styles["flex_direction"] = "column"
        else:
            # Ambiguous — default to column if more vertical, row otherwise
            styles["display"] = "flex"
            styles["flex_direction"] = "column" if y_variance > x_variance else "row"

        # Padding: distance from container edge to first child
        first_child = children[0]
        fx, fy, fw, fh = first_child.bbox
        padding_left = max(0, fx - x)
        padding_top = max(0, fy - y)
        styles["padding"] = min(padding_left, padding_top)

        # Gap: average distance between consecutive siblings
        if len(children) > 1:
            if styles["flex_direction"] == "row":
                prev_right = children[0].bbox[0] + children[0].bbox[2]
                gaps = []
                for child in children[1:]:
                    gap = child.bbox[0] - prev_right
                    if gap > 0:
                        gaps.append(gap)
                    prev_right = child.bbox[0] + child.bbox[2]
                styles["gap"] = int(sum(gaps) / len(gaps)) if gaps else 0
            else:
                prev_bottom = children[0].bbox[1] + children[0].bbox[3]
                gaps = []
                for child in children[1:]:
                    gap = child.bbox[1] - prev_bottom
                    if gap > 0:
                        gaps.append(gap)
                    prev_bottom = child.bbox[1] + child.bbox[3]
                styles["gap"] = int(sum(gaps) / len(gaps)) if gaps else 0

        return styles

    # ------------------------------------------------------------------
    # CSS generation
    # ------------------------------------------------------------------

    def _generate_custom_css(
        self,
        tree: ComponentTree,
        layout_styles: Dict[str, dict],
        colors: List[dict]
    ) -> str:
        """
        Build a plain CSS block from computed layout styles.

        Each element type gets a class rule with flex, gap, and
        size custom properties.
        """
        css_rules = []

        # Track which class names we've already emitted to avoid duplicates
        emitted_classes = set()

        for elem_id, styles in layout_styles.items():
            elem = tree.elements.get(elem_id)
            if not elem:
                continue

            class_name = elem.type.lower()

            # Skip duplicate class selectors (first occurrence wins)
            if class_name in emitted_classes:
                continue
            emitted_classes.add(class_name)

            css_props = []

            # Size custom properties for reference
            if styles.get("width"):
                css_props.append(f"  --computed-width: {styles['width']}px;")
            if styles.get("height"):
                css_props.append(f"  --computed-height: {styles['height']}px;")

            # Flex layout
            if styles.get("display") == "flex":
                css_props.append("  display: flex;")
                if styles.get("flex_direction"):
                    css_props.append(f"  flex-direction: {styles['flex_direction']};")
                if styles.get("gap", 0) > 0:
                    css_props.append(f"  gap: {styles['gap']}px;")

            # Padding
            if styles.get("padding", 0) > 0:
                css_props.append(f"  padding: {styles['padding']}px;")

            if css_props:
                rule = f".{class_name} {{\n" + "\n".join(css_props) + "\n}"
                css_rules.append(rule)

        return "\n\n".join(css_rules)

    # ------------------------------------------------------------------
    # Document assembly
    # ------------------------------------------------------------------

    def _assemble_document(
        self,
        body_html: str,
        custom_css: str,
        colors: List[dict]
    ) -> str:
        """
        Wrap HTML body + CSS into a complete, self-contained HTML document.

        Uses plain CSS only — no Tailwind CDN or utility classes.
        Color palette is injected as CSS custom properties on :root.
        """
        # Build CSS custom properties from extracted color palette
        color_vars = []
        for i, color in enumerate(colors[:6]):
            var_name = "--color-primary" if i == 0 else f"--color-{i}"
            color_vars.append(f"  {var_name}: {color['hex']};")

        color_vars_block = "\n".join(color_vars) if color_vars else ""

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Generated UI</title>
    <style>
/* ---------- Reset & Base ---------- */
*, *::before, *::after {{
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}}

body {{
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
               "Helvetica Neue", Arial, sans-serif;
  line-height: 1.5;
  color: #1a1a1a;
  background: #ffffff;
}}

img {{
  max-width: 100%;
  display: block;
}}

/* ---------- Color Palette ---------- */
:root {{
{color_vars_block}
}}

/* ---------- Component Styles ---------- */
{custom_css}
    </style>
</head>
<body>
{body_html}
</body>
</html>"""
