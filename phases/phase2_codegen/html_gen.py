"""
Phase 2.1: Component Code Generation

Generate HTML structure that follows the component tree exactly.
The HTML nesting MUST mirror the tree structure.
"""

import json
import re
from pathlib import Path
from typing import List, Dict
from bs4 import BeautifulSoup
from storage.component import Component, ComponentTree, Element, Region
from llm_client import DualProviderClient, Message
from config import Config


class HTMLGenerator:
    """Generates HTML structure from component tree."""

    # Semantic type to HTML tag mapping
    TYPE_TO_TAG = {
        "container": "div",
        "page": "main",
        "card": "article",
        "section": "section",
        "nav-item": "nav",
        "navigation": "nav",
        "text": "p",
        "heading": "h2",
        "button": "button",
        "image": "img",
        "icon": "span",
        "input": "input",
        "link": "a",
        "divider": "hr",
        "badge": "span",
        "list": "ul",
        "dropdown": "select",
        "checkbox": "input",
        "radio": "input",
        "slider": "input",
        "textarea": "textarea",
        "label": "label",
        "tab": "div",
        "accordion": "div",
        "tooltip": "span",
        "avatar": "img",
        "chip": "span",
        "banner": "div",
        "modal": "dialog",
        "toast": "div",
    }

    def __init__(self, client: DualProviderClient, config: Config):
        self.client = client
        self.config = config

    async def generate(
        self, component: Component, colors: List[dict]
    ) -> List[Dict[str, str]]:
        """
        Generate HTML fragments for each region.

        Returns list of {region_id, region_name, html_fragment} dicts.
        Each fragment is self-contained but designed to be concatenated.

        Strategy:
        1. Generate code for each region independently (divide-and-conquer)
        2. Map tree nodes to semantic HTML tags (not just divs)
        3. Assign stable class names based on tree node names
        """
        if not component.tree:
            raise ValueError("Component tree required for HTML generation")

        fragments = []

        # Get region sub-trees
        region_roots = self._get_region_roots(component.tree)

        for region_root_id, region in region_roots:
            print(f"  Generating HTML for: {region.name}...", end=" ")

            try:
                # Build sub-tree for this region
                sub_tree = self._extract_subtree(component.tree, region_root_id)

                prompt = self._build_tree_to_html_prompt(region.name, sub_tree, colors)

                images = []
                if region.crop_path and Path(region.crop_path).exists():
                    images.append(region.crop_path)

                response = await self.client.vision_analyze(
                    prompt=prompt,
                    images=images,
                    temperature=0.2,
                )

                # Extract HTML from response
                html = self._extract_html(response.content)

                # Validate: strip hallucinated content (external URLs, extra elements)
                if html:
                    html = self._validate_html(html, sub_tree)

                # If vision model fails, use recursive generation
                if not html:
                    html = self._tree_to_html_recursive(region_root_id, sub_tree, [])

                fragments.append(
                    {
                        "region_id": region.id,
                        "region_name": region.name,
                        "html_fragment": html,
                        "root_element_id": region_root_id,
                    }
                )
                print("✓")

            except Exception as e:
                print(f"✗ Error: {e}")
                # Fallback: generate basic structure
                sub_tree = self._extract_subtree(component.tree, region_root_id)
                html = self._tree_to_html_recursive(region_root_id, sub_tree, [])
                fragments.append(
                    {
                        "region_id": region.id,
                        "region_name": region.name,
                        "html_fragment": html,
                        "root_element_id": region_root_id,
                    }
                )

        return fragments

    def _get_region_roots(self, tree: ComponentTree) -> List[tuple]:
        """Get root element IDs for each region."""
        # If there's a page root, its children are region roots
        root_elem = tree.elements.get(tree.root_id)
        if not root_elem:
            return [
                (
                    tree.root_id,
                    tree.regions[0]
                    if tree.regions
                    else Region(id="root", name="page", bbox=(0, 0, 1, 1)),
                )
            ]

        region_roots = []
        for i, child_id in enumerate(root_elem.children_ids):
            region = (
                tree.regions[i]
                if i < len(tree.regions)
                else Region(id=f"region_{i}", name=f"section_{i}", bbox=(0, 0, 1, 1))
            )
            region_roots.append((child_id, region))

        return region_roots

    def _extract_subtree(self, tree: ComponentTree, root_id: str) -> ComponentTree:
        """
        Extract sub-tree starting from given root.
        Uses a visited set to prevent infinite recursion from cycles.
        """
        elements = {}
        visited = set()

        def collect_elements(elem_id):
            if elem_id in visited:
                return
            visited.add(elem_id)

            elem = tree.elements.get(elem_id)
            if not elem:
                return
            elements[elem_id] = elem
            for child_id in elem.children_ids:
                collect_elements(child_id)

        collect_elements(root_id)

        return ComponentTree(root_id=root_id, elements=elements, regions=[])

    def _build_tree_to_html_prompt(
        self, region_name: str, tree: ComponentTree, colors: List[dict]
    ) -> str:
        """Build prompt for HTML generation from tree."""
        # Serialize tree to JSON (with cycle guard)
        seen = set()

        def serialize_node(elem_id):
            if elem_id in seen:
                return None
            seen.add(elem_id)

            elem = tree.elements.get(elem_id)
            if not elem:
                return None

            node = {
                "id": elem_id,
                "type": elem.type,
                "content": elem.content_description,
                "children": [
                    c
                    for c in (serialize_node(cid) for cid in elem.children_ids)
                    if c is not None
                ],
            }
            return node

        tree_json = json.dumps(serialize_node(tree.root_id), indent=2)

        # Build color palette text
        colors_text = "\n".join(
            [f"- {c['hex']} ({c['coverage_pct']:.1f}% coverage)" for c in colors[:6]]
        )

        elem_lines = []
        for eid, e in tree.elements.items():
            x, y, w, h = e.bbox
            elem_lines.append(
                f'  id="{eid}" | {e.type} | ({x},{y}) {w}x{h} | "{e.content_description[:60]}"'
                f" | children: {e.children_ids}"
            )
        elem_table = "\n".join(elem_lines)

        return f"""You are an EXACT UI reproducer. You are looking at a screenshot of the "{region_name}" region.
Your job is to reproduce it as HTML+CSS that looks IDENTICAL to the screenshot.

ABSOLUTE RULES (violating ANY of these is a critical failure):
1. Use ONLY the exact text from the elements below — do NOT invent, paraphrase, or add any text
2. Use ONLY colors from the color palette below — no other colors allowed
3. Do NOT use any external URLs (no Unsplash, no external images, no CDN links)
4. For images, use a div with background-color: #e5e7eb and the correct dimensions
5. Every element MUST have a data-elem-id attribute matching its exact id from the table below
6. HTML nesting MUST follow the children structure shown below

Elements:
{elem_table}

Color Palette (use ONLY these):
{colors_text}

TREE STRUCTURE:
{tree_json}

INSTRUCTIONS:
- Look carefully at the screenshot and match its visual layout exactly
- Each element in the tree becomes an HTML element with data-elem-id="ITS_ID"
- Use semantic tags: nav, h1-h6, p, button, span, div, section, article, img, a, hr
- Include a <style> block at the top for layout CSS
- Match the spacing, sizing, and visual hierarchy from the screenshot
- Use inline styles for element-specific properties (colors, font-size, etc.)

Output ONLY the HTML fragment (no <html>, <head>, <body>). Start with <style> then elements."""

    def _extract_html(self, content: str) -> str:
        """Extract HTML from model response."""

        # Try to find content between code fences
        code_match = re.search(r"```html\s*([\s\S]*?)```", content, re.IGNORECASE)
        if code_match:
            return code_match.group(1).strip()

        code_match = re.search(r"```\s*([\s\S]*?)```", content)
        if code_match:
            return code_match.group(1).strip()

        # Look for HTML tags
        html_match = re.search(r"<[^>]+>.*<\/[^>]+>", content, re.DOTALL)
        if html_match:
            return content[html_match.start() : html_match.end()]

        return content.strip()

    def _validate_html(self, html: str, tree: ComponentTree) -> str:
        """
        Post-generation validation: strip hallucinated content.

        The vision model frequently invents external image URLs, wrong text,
        and extra sections not in the component tree. This method sanitizes
        the output by:
          1. Replacing external <img> src with placeholder divs
          2. Stripping external URLs from inline styles and <style> blocks
          3. Neutralizing external <a> hrefs
          4. Removing elements whose data-elem-id is not in the tree
        """
        soup = BeautifulSoup(html, "html.parser")
        valid_ids = set(tree.elements.keys())

        _EXT_URL_RE = re.compile(
            r'url\(["\']?https?://[^)]+["\']?\)',
            re.IGNORECASE,
        )
        _SVG_PLACEHOLDER = (
            'url("data:image/svg+xml,'
            "%3Csvg xmlns='http://www.w3.org/2000/svg'/%3E\")"
        )

        # 1. Replace external <img> src with placeholder divs
        for img in soup.find_all("img"):
            src = img.get("src", "")
            if src and not src.startswith("data:"):
                placeholder = soup.new_tag("div")
                # Carry over layout-relevant attributes
                for attr in ("data-elem-id", "class", "id", "style"):
                    if img.get(attr):
                        placeholder[attr] = img[attr]
                existing_style = placeholder.get("style", "")
                placeholder["style"] = (
                    existing_style
                    + "; background-color: #e5e7eb;"
                    + " min-height: 100px; min-width: 100px;"
                )
                img.replace_with(placeholder)

        # 2. Strip external URLs from inline styles (background-image, etc.)
        for tag in soup.find_all(style=True):
            tag["style"] = _EXT_URL_RE.sub(_SVG_PLACEHOLDER, tag["style"])

        # 3. Strip external URLs from <style> blocks
        for style_tag in soup.find_all("style"):
            if style_tag.string:
                style_tag.string = _EXT_URL_RE.sub(
                    _SVG_PLACEHOLDER, style_tag.string
                )

        # 4. Neutralize external <a> hrefs
        for a_tag in soup.find_all("a"):
            href = a_tag.get("href", "")
            if href.startswith("http"):
                a_tag["href"] = "#"

        # 5. Remove <link> tags pointing to external stylesheets
        for link in soup.find_all("link"):
            href = link.get("href", "")
            if href.startswith("http"):
                link.decompose()

        # 6. Remove elements with data-elem-id not present in the tree
        for elem in soup.find_all(attrs={"data-elem-id": True}):
            elem_id = elem.get("data-elem-id")
            if elem_id and elem_id not in valid_ids:
                elem.decompose()

        return str(soup)

    def _map_type_to_tag(self, element_type: str) -> str:
        """Map semantic element type to HTML tag."""
        return self.TYPE_TO_TAG.get(element_type.lower(), "div")

    def _generate_class_name(
        self, element: Element, parent_classes: List[str], index: int = 0
    ) -> str:
        """Generate stable class name for element."""
        base = element.type.lower()

        # Build hierarchical name
        if parent_classes:
            parent_prefix = "-".join(parent_classes)
            class_name = f"{parent_prefix}-{base}"
        else:
            class_name = base

        # Add index if needed for uniqueness
        if index > 0:
            class_name = f"{class_name}-{index}"

        return class_name

    def _tree_to_html_recursive(
        self,
        element_id: str,
        tree: ComponentTree,
        parent_classes: List[str] = None,
        index: int = 0,
        _visited: set = None,
    ) -> str:
        """
        Recursively convert tree to HTML string (fallback generator).
        Uses _visited set to guard against cycles in the tree.
        """
        if parent_classes is None:
            parent_classes = []
        if _visited is None:
            _visited = set()

        # Cycle guard
        if element_id in _visited:
            return ""
        _visited.add(element_id)

        elem = tree.elements.get(element_id)
        if not elem:
            return ""

        tag = self._map_type_to_tag(elem.type)
        class_name = self._generate_class_name(elem, parent_classes, index)
        new_parent_classes = parent_classes + [elem.type]

        # Build attributes — always include data-elem-id so CSS selectors work
        attrs = [f'data-elem-id="{element_id}"', f'class="{class_name}"']

        if tag == "img":
            attrs.append(f'alt="{elem.content_description[:50]}"')
            attrs.append(
                "src=\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='100' height='100'/%3E\""
            )
        elif tag == "input":
            attrs.append(f'placeholder="{elem.content_description[:30]}"')
        elif tag == "a":
            attrs.append('href="#"')

        # Build children HTML
        children_html = ""
        for i, child_id in enumerate(elem.children_ids):
            child_html = self._tree_to_html_recursive(
                child_id, tree, new_parent_classes, i, _visited
            )
            children_html += child_html

        # Build element HTML
        if tag in ("img", "input", "hr"):
            return f"<{tag} {' '.join(attrs)} />"
        else:
            content = elem.content_description if not children_html else ""
            return f"<{tag} {' '.join(attrs)}>{content}{children_html}</{tag}>"

    # ------------------------------------------------------------------
    # VLLM single-shot full-page codegen
    # ------------------------------------------------------------------

    async def generate_vllm_fullpage(
        self, component: Component, colors: List[dict]
    ) -> str:
        """
        Generate full-page HTML from screenshot in a single VLLM call.

        Returns raw HTML string (not wrapped in document structure yet —
        that's handled by StyleGenerator.ensure_document_structure).
        """
        prompt = self._build_vllm_prompt(component, colors)

        response = await self.client.codegen_from_vision(
            prompt=prompt,
            images=[component.reference_path],
            temperature=0.2,
        )

        html = self._extract_html(response.content)

        # Strip external URLs / hallucinated content
        if html:
            html = self._sanitize_vllm_output(html)

        return html

    def _build_vllm_prompt(
        self, component: Component, colors: List[dict]
    ) -> str:
        """Build prompt for VLLM single-shot full-page HTML generation."""
        ref_w, ref_h = 0, 0
        if component.reference_path:
            from PIL import Image as _PILImage
            try:
                img = _PILImage.open(component.reference_path)
                ref_w, ref_h = img.size
            except Exception:
                pass

        return f"""Clone the UI shown in this screenshot using HTML and CSS. Ignore the background/hero image — use a solid color placeholder instead.

Page must render at exactly {ref_w}x{ref_h}px.

Rules:
1. Complete self-contained HTML page (DOCTYPE, head, body) with embedded <style>
2. Plain CSS only — no Tailwind, no external frameworks, no external URLs
3. Semantic HTML tags (nav, section, h1-h6, p, button, article, etc.)
4. CSS reset: box-sizing border-box, margin 0, padding 0
5. Match text content, font sizes, spacing, and visual hierarchy exactly
6. For images, use a solid color div placeholder
7. Icons — use simple Unicode characters or minimal inline SVG

Output ONLY the HTML. No explanation."""

    def _sanitize_vllm_output(self, html: str) -> str:
        """Strip external URLs and hallucinated content from VLLM output."""
        import re as _re
        from bs4 import BeautifulSoup as _BS

        soup = _BS(html, "html.parser")

        _EXT_URL_RE = _re.compile(
            r'url\(["\']?https?://[^)]+["\']?\)',
            _re.IGNORECASE,
        )
        _SVG_PLACEHOLDER = (
            'url("data:image/svg+xml,'
            "%3Csvg xmlns='http://www.w3.org/2000/svg'/%3E\")"
        )

        # Replace external <img> src
        for img in soup.find_all("img"):
            src = img.get("src", "")
            if src and not src.startswith("data:"):
                placeholder = soup.new_tag("div")
                for attr in ("class", "id", "style"):
                    if img.get(attr):
                        placeholder[attr] = img[attr]
                existing_style = placeholder.get("style", "")
                placeholder["style"] = (
                    existing_style
                    + "; background-color: #e5e7eb;"
                    + " min-height: 100px; min-width: 100px;"
                )
                img.replace_with(placeholder)

        # Strip external URLs from inline styles
        for tag in soup.find_all(style=True):
            tag["style"] = _EXT_URL_RE.sub(_SVG_PLACEHOLDER, tag["style"])

        # Strip external URLs from <style> blocks
        for style_tag in soup.find_all("style"):
            if style_tag.string:
                style_tag.string = _EXT_URL_RE.sub(
                    _SVG_PLACEHOLDER, style_tag.string
                )

        # Neutralize external <a> hrefs
        for a_tag in soup.find_all("a"):
            href = a_tag.get("href", "")
            if href.startswith("http"):
                a_tag["href"] = "#"

        # Remove <link> tags pointing to external stylesheets
        for link in soup.find_all("link"):
            href = link.get("href", "")
            if href.startswith("http"):
                link.decompose()

        return str(soup)

    def _generate_svg_placeholder(self, width: int = 100, height: int = 100) -> str:
        """Generate SVG placeholder for images."""
        svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}"><rect width="100%" height="100%" fill="#e5e7eb"/></svg>'
        import urllib.parse

        return f"data:image/svg+xml,{urllib.parse.quote(svg)}"
