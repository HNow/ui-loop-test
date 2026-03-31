"""
Phase 2.1: Component Code Generation

Generate HTML structure that follows the component tree exactly.
The HTML nesting MUST mirror the tree structure.
"""

import json
from typing import List, Dict
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
        self,
        component: Component,
        colors: List[dict]
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
                
                # Generate HTML via vision model
                prompt = self._build_tree_to_html_prompt(region.name, sub_tree, colors)
                
                response = await self.client.code_complete(
                    messages=[Message.text("user", prompt)],
                    temperature=0.2
                )
                
                # Extract HTML from response
                html = self._extract_html(response.content)
                
                # If vision model fails, use recursive generation
                if not html:
                    html = self._tree_to_html_recursive(region_root_id, sub_tree, [])
                
                fragments.append({
                    "region_id": region.id,
                    "region_name": region.name,
                    "html_fragment": html,
                    "root_element_id": region_root_id
                })
                print("✓")
                
            except Exception as e:
                print(f"✗ Error: {e}")
                # Fallback: generate basic structure
                sub_tree = self._extract_subtree(component.tree, region_root_id)
                html = self._tree_to_html_recursive(region_root_id, sub_tree, [])
                fragments.append({
                    "region_id": region.id,
                    "region_name": region.name,
                    "html_fragment": html,
                    "root_element_id": region_root_id
                })
        
        return fragments
    
    def _get_region_roots(self, tree: ComponentTree) -> List[tuple]:
        """Get root element IDs for each region."""
        # If there's a page root, its children are region roots
        root_elem = tree.elements.get(tree.root_id)
        if not root_elem:
            return [(tree.root_id, tree.regions[0] if tree.regions else Region(id="root", name="page", bbox=(0,0,1,1)))]
        
        region_roots = []
        for i, child_id in enumerate(root_elem.children_ids):
            region = tree.regions[i] if i < len(tree.regions) else Region(
                id=f"region_{i}",
                name=f"section_{i}",
                bbox=(0, 0, 1, 1)
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

        return ComponentTree(
            root_id=root_id,
            elements=elements,
            regions=[]
        )
    
    def _build_tree_to_html_prompt(
        self,
        region_name: str,
        tree: ComponentTree,
        colors: List[dict]
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
                    c for c in (serialize_node(cid) for cid in elem.children_ids)
                    if c is not None
                ]
            }
            return node

        tree_json = json.dumps(serialize_node(tree.root_id), indent=2)
        
        # Build color palette text
        colors_text = "\n".join([
            f"- {c['hex']} ({c['coverage_pct']:.1f}% coverage)"
            for c in colors[:6]
        ])
        
        return f"""Generate HTML for the "{region_name}" region.

Component Tree (MUST follow this structure exactly):
{tree_json}

Color Palette (use these for styling):
{colors_text}

Requirements:
1. HTML nesting MUST mirror the tree structure exactly
2. Use semantic HTML tags (not just divs):
   - navigation -> <nav>
   - heading -> <h1> to <h6>
   - card -> <article>
   - button -> <button>
   - text -> <p>
   - list -> <ul>/<ol>
   - image -> <img>
   - container -> <div> or <section>
3. Add descriptive class names based on element type and position
4. Include content from the tree (text, labels, etc.)
5. Use placeholder images with descriptive alt text
6. Output only the HTML fragment (no <html>, <head>, <body> tags)
7. Use plain CSS class names ONLY — do NOT use Tailwind utility classes

Example output format:
<section class="hero-section">
  <h1 class="hero-title">Product Name</h1>
  <p class="hero-description">Description text</p>
  <button class="hero-cta">Click Me</button>
</section>

Generate the HTML fragment now:"""
    
    def _extract_html(self, content: str) -> str:
        """Extract HTML from model response."""
        # Look for HTML tags
        import re
        
        # Try to find content between code fences
        code_match = re.search(r'```html\s*([\s\S]*?)```', content, re.IGNORECASE)
        if code_match:
            return code_match.group(1).strip()
        
        code_match = re.search(r'```\s*([\s\S]*?)```', content)
        if code_match:
            return code_match.group(1).strip()
        
        # Look for HTML tags
        html_match = re.search(r'<[^>]+>.*<\/[^>]+>', content, re.DOTALL)
        if html_match:
            return content[html_match.start():html_match.end()]
        
        return content.strip()
    
    def _map_type_to_tag(self, element_type: str) -> str:
        """Map semantic element type to HTML tag."""
        return self.TYPE_TO_TAG.get(element_type.lower(), "div")
    
    def _generate_class_name(
        self,
        element: Element,
        parent_classes: List[str],
        index: int = 0
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
        _visited: set = None
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

        # Build attributes
        attrs = [f'class="{class_name}"']

        if tag == "img":
            attrs.append(f'alt="{elem.content_description[:50]}"')
            attrs.append('src="data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' width=\'100\' height=\'100\'/%3E"')
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
            return f'<{tag} {" ".join(attrs)} />'
        else:
            content = elem.content_description if not children_html else ""
            return f'<{tag} {" ".join(attrs)}>{content}{children_html}</{tag}>'
    
    def _generate_svg_placeholder(self, width: int = 100, height: int = 100) -> str:
        """Generate SVG placeholder for images."""
        svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}"><rect width="100%" height="100%" fill="#e5e7eb"/></svg>'
        import urllib.parse
        return f"data:image/svg+xml,{urllib.parse.quote(svg)}"
