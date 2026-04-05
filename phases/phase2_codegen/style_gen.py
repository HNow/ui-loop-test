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
        colors: List[dict],
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

        # Get reference image dimensions for page-level positioning
        from PIL import Image as _PILImage

        ref_width, ref_height = 0, 0
        if component.reference_path:
            try:
                ref_img = _PILImage.open(component.reference_path)
                ref_width, ref_height = ref_img.size
            except Exception:
                pass

        # Compute layout styles for every element in the tree
        layout_styles = {}
        for elem_id in component.tree.elements:
            layout_styles[elem_id] = self._compute_layout_styles(
                elem_id, component.tree
            )

        # Turn layout data into a CSS block
        custom_css = self._generate_custom_css(
            component.tree, layout_styles, colors, ref_width, ref_height
        )

        # Concatenate all HTML fragments into one body
        inner_html = "\n".join(f["html_fragment"] for f in html_fragments)

        # Wrap in a page_root container if the tree has a page root.
        # HTMLGenerator only generates region root children, not page_root
        # itself, so we need this wrapper for absolute positioning to work.
        has_page_root = (
            component.tree.root_id == "page_root"
            and component.tree.elements.get("page_root") is not None
        )
        if has_page_root:
            body_html = f'<div data-elem-id="page_root">\n{inner_html}\n</div>'
        else:
            body_html = inner_html

        # Wrap everything in a full HTML document
        full_html = self._assemble_document(body_html, custom_css, colors)

        return full_html

    # ------------------------------------------------------------------
    # Layout computation from bounding boxes
    # ------------------------------------------------------------------

    def _compute_layout_styles(self, element_id: str, tree: ComponentTree) -> dict:
        elem = tree.elements.get(element_id)
        if not elem:
            return {}

        x, y, w, h = elem.bbox

        # Page root is a synthetic wrapper — don't compute flex from its
        # placeholder bbox (0,0,1,1).  Flag it for special CSS treatment.
        if elem.type == "page":
            return {
                "id": element_id,
                "type": elem.type,
                "is_page_root": True,
                "x": x, "y": y, "width": w, "height": h,
                "display": "block",
                "flex_direction": None,
                "padding": 0,
                "gap": 0,
            }

        styles = {
            "id": element_id,
            "type": elem.type,
            "x": x,
            "y": y,
            "width": w,
            "height": h,
            "display": "block",
            "flex_direction": None,
            "padding": 0,
            "gap": 0,
        }

        if not elem.children_ids:
            return styles

        children = [tree.elements.get(cid) for cid in elem.children_ids]
        children = [c for c in children if c]

        if not children:
            return styles

        child_centers_x = []
        child_centers_y = []
        for child in children:
            cx, cy, cw, ch = child.bbox
            child_centers_x.append(cx + cw / 2)
            child_centers_y.append(cy + ch / 2)

        x_variance = max(child_centers_x) - min(child_centers_x)
        y_variance = max(child_centers_y) - min(child_centers_y)

        if x_variance > y_variance * 2:
            styles["display"] = "flex"
            styles["flex_direction"] = "row"
        elif y_variance > x_variance * 2:
            styles["display"] = "flex"
            styles["flex_direction"] = "column"
        else:
            styles["display"] = "flex"
            styles["flex_direction"] = "column" if y_variance > x_variance else "row"

        first_child = children[0]
        fx, fy, fw, fh = first_child.bbox
        padding_left = max(0, fx - x)
        padding_top = max(0, fy - y)
        styles["padding"] = min(padding_left, padding_top)

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
        colors: List[dict],
        ref_width: int = 0,
        ref_height: int = 0,
    ) -> str:
        """
        Generate CSS from computed layout styles.

        - Page root: positioned container matching reference dimensions
        - Region roots (children of page root): absolutely positioned
          at their Phase 1 bboxes
        - All other containers: flex direction, gap, padding only
        """
        css_rules = []

        # Identify region root element IDs (children of page_root)
        root_elem = tree.elements.get(tree.root_id)
        region_root_ids = set()
        if root_elem and root_elem.type == "page":
            region_root_ids = set(root_elem.children_ids)

        for elem_id, styles in layout_styles.items():
            elem = tree.elements.get(elem_id)
            if not elem:
                continue

            selector = f'[data-elem-id="{elem_id}"]'
            css_props = []

            # Page root — fixed-size positioned container
            if styles.get("is_page_root") and ref_width > 0:
                css_props.append("  position: relative;")
                css_props.append(f"  width: {ref_width}px;")
                css_props.append(f"  height: {ref_height}px;")
                css_props.append("  overflow: hidden;")
                rule = f"{selector} {{\n" + "\n".join(css_props) + "\n}"
                css_rules.append(rule)
                continue

            # Region roots — absolutely positioned at their bbox
            if elem_id in region_root_ids:
                x = styles.get("x", 0)
                y = styles.get("y", 0)
                w = styles.get("width", 0)
                h = styles.get("height", 0)
                css_props.append("  position: absolute;")
                css_props.append(f"  left: {x}px;")
                css_props.append(f"  top: {y}px;")
                css_props.append(f"  width: {w}px;")
                css_props.append(f"  height: {h}px;")
                css_props.append("  overflow: hidden;")

            # Flex layout for containers with children
            if styles.get("display") == "flex":
                css_props.append("  display: flex;")
                if styles.get("flex_direction"):
                    css_props.append(f"  flex-direction: {styles['flex_direction']};")
                if styles.get("gap", 0) > 0:
                    css_props.append(f"  gap: {styles['gap']}px;")

            if styles.get("padding", 0) > 0:
                css_props.append(f"  padding: {styles['padding']}px;")

            if css_props:
                rule = f"{selector} {{\n" + "\n".join(css_props) + "\n}"
                css_rules.append(rule)

        return "\n\n".join(css_rules)

    # ------------------------------------------------------------------
    # Document assembly
    # ------------------------------------------------------------------

    def ensure_document_structure(self, html: str, colors: List[dict]) -> str:
        """
        Ensure VLLM output has proper document structure.

        If the HTML already has <!DOCTYPE> or <html>, return as-is
        (after injecting CSS reset and color vars if missing).
        Otherwise wrap in full document structure.
        """
        html_lower = html.lower().strip()

        # Already a full document — inject reset CSS if missing
        if html_lower.startswith("<!doctype") or html_lower.startswith("<html"):
            if "box-sizing: border-box" not in html:
                # Inject reset into existing <style> or add one
                reset = self._css_reset(colors)
                if "<style>" in html.lower():
                    html = html.replace(
                        "<style>", f"<style>\n{reset}\n", 1
                    )
                elif "</head>" in html.lower():
                    html = html.replace(
                        "</head>",
                        f"<style>\n{reset}\n</style>\n</head>",
                        1,
                    )
            return html

        # Fragment — wrap in full document
        return self._assemble_document(html, "", colors)

    def _css_reset(self, colors: List[dict]) -> str:
        """Generate CSS reset + color variables block."""
        color_vars = []
        for i, color in enumerate(colors[:6]):
            var_name = "--color-primary" if i == 0 else f"--color-{i}"
            color_vars.append(f"  {var_name}: {color['hex']};")
        color_vars_block = "\n".join(color_vars) if color_vars else ""

        return f"""*, *::before, *::after {{
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}}

:root {{
{color_vars_block}
}}"""

    def _assemble_document(
        self, body_html: str, custom_css: str, colors: List[dict]
    ) -> str:
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
  background: var(--color-primary, #ffffff);
  width: 100%;
  min-height: 100vh;
}}

img {{
  max-width: 100%;
  display: block;
}}

:root {{
{color_vars_block}
}}

/* ---------- Layout from bounding boxes ---------- */
{custom_css}
    </style>
</head>
<body>
{body_html}
</body>
</html>"""
