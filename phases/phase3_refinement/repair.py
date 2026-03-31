"""
Phase 3.4: Targeted Repair

Modify specific components to fix identified issues.
Do not rewrite the whole page — only repair what needs fixing.

Uses BeautifulSoup for robust HTML parsing instead of regex,
which breaks on nested tags, special characters in class names,
and malformed HTML.
"""

from typing import List, Dict, Tuple, Optional
from bs4 import BeautifulSoup, Tag

from storage.component import Component, ComponentTree
from llm_client import DualProviderClient, Message
from config import Config
from utils.dom import DOMNode


class TargetedRepair:
    """
    Repairs specific components without rewriting the entire page.

    Strategy:
      1. Group issues by component ID.
      2. For each component with issues:
         a. Parse the full HTML with BeautifulSoup.
         b. Locate the component's element by class name / tag.
         c. Send the element's HTML + issue list to the code model.
         d. Parse the model's repaired HTML.
         e. Replace the old element in the BeautifulSoup tree.
      3. Serialize the modified tree back to an HTML string.
    """

    def __init__(self, client: DualProviderClient, config: Config):
        self.client = client
        self.config = config

    async def repair(
        self, component: Component, issues: List[Dict], dom_tree: DOMNode
    ) -> str:
        """
        Repair identified issues in the HTML.

        Args:
            component: The component being refined (holds html_path and tree).
            issues: List of issue dicts from VisualComparator.
            dom_tree: The rendered DOM tree (used for position context).

        Returns:
            Modified full-page HTML as a string.
        """
        if not component.html_path:
            raise ValueError("No HTML file to repair")

        full_html = component.html_path.read_text(encoding="utf-8")

        # Group issues by component ID
        issues_by_component: Dict[str, List[Dict]] = {}
        for issue in issues:
            comp_id = issue.get("component_id", "unknown")
            if comp_id not in issues_by_component:
                issues_by_component[comp_id] = []
            issues_by_component[comp_id].append(issue)

        print(f"  Repairing {len(issues_by_component)} components with issues...")

        # Apply repairs sequentially so earlier fixes are visible to later ones
        for comp_id, comp_issues in issues_by_component.items():
            print(f"    Repairing {comp_id} ({len(comp_issues)} issues)...")

            # Locate the component's HTML element via BeautifulSoup
            component_html, selector_type, selector_value = (
                self._extract_component_html(full_html, comp_id, component)
            )

            if not component_html:
                print(f"      Could not find component HTML for {comp_id}")
                continue

            # Ask the model to repair just this fragment
            prompt = self._build_repair_prompt(component_html, comp_issues, comp_id)

            try:
                response = await self.client.code_complete(
                    messages=[Message.text("user", prompt)], temperature=0.3
                )

                repaired_html = self._extract_repaired_html(response.content)

                if repaired_html:
                    full_html = self._replace_component_html(
                        full_html, selector_type, selector_value, repaired_html
                    )
                    print(f"      Repaired")
                else:
                    print(f"      Could not extract repaired HTML from model response")

            except Exception as e:
                print(f"      Repair failed: {e}")
                continue

        return full_html

    # ------------------------------------------------------------------
    # HTML extraction via BeautifulSoup
    # ------------------------------------------------------------------

    def _extract_component_html(
        self, full_html: str, component_id: str, component: Component
    ) -> Tuple[Optional[str], str, str]:
        """
        Find and extract a specific component's HTML from the full page.

        Uses BeautifulSoup to locate elements by class name or tag,
        falling back through multiple strategies.

        Returns:
            (html_string, selector_type, selector_value)
            selector_type is 'class', 'id', or 'tag'.
            Returns (None, '', '') if not found.
        """
        if not component.tree:
            return None, "", ""

        elem = component.tree.elements.get(component_id)
        if not elem:
            return None, "", ""

        soup = BeautifulSoup(full_html, "html.parser")

        # Strategy 1: Find by class name matching element type
        class_name = elem.type.lower()
        candidates = soup.find_all(class_=class_name)
        if candidates:
            best = self._pick_best_candidate(candidates, elem.bbox)
            return str(best), "class", class_name

        # Strategy 2: Find by element ID (if the component has one)
        elem_id = elem.id.lower().replace("_", "-")
        by_id = soup.find(id=elem_id)
        if by_id:
            return str(by_id), "id", elem_id

        # Strategy 3: Find by HTML tag matching the semantic type
        tag = self._map_type_to_tag(elem.type)
        tag_candidates = soup.find_all(tag)
        if tag_candidates:
            best = self._pick_best_candidate(tag_candidates, elem.bbox)
            return str(best), "tag", tag

        return None, "", ""

    def _pick_best_candidate(
        self, candidates: list, expected_bbox: Tuple[int, int, int, int]
    ) -> Tag:
        """
        When multiple elements match, pick the one whose inline style
        dimensions are closest to the expected bounding box.

        Falls back to the first candidate if no style information exists.
        """
        if len(candidates) == 1:
            return candidates[0]

        ex, ey, ew, eh = expected_bbox
        best = candidates[0]
        best_diff = float("inf")

        for candidate in candidates:
            style = candidate.get("style", "")
            # Try to extract width/height from inline style
            w = self._parse_css_px(style, "width")
            h = self._parse_css_px(style, "height")

            if w is not None and h is not None:
                diff = abs(w - ew) + abs(h - eh)
                if diff < best_diff:
                    best_diff = diff
                    best = candidate

        return best

    @staticmethod
    def _parse_css_px(style_str: str, prop: str) -> Optional[int]:
        """Extract a pixel value from an inline style string."""
        import re

        match = re.search(rf"{prop}\s*:\s*(\d+)px", style_str, re.IGNORECASE)
        return int(match.group(1)) if match else None

    # ------------------------------------------------------------------
    # HTML replacement via BeautifulSoup
    # ------------------------------------------------------------------

    def _replace_component_html(
        self, full_html: str, selector_type: str, selector_value: str, new_html: str
    ) -> str:
        """
        Replace a component's HTML in the full page using BeautifulSoup.

        Locates the old element by selector, parses the new HTML, and
        swaps them. This is robust to nested tags, special characters,
        and minor HTML malformation.
        """
        soup = BeautifulSoup(full_html, "html.parser")

        # Find the target element
        target = None
        if selector_type == "class":
            candidates = soup.find_all(class_=selector_value)
            if candidates:
                target = candidates[0]
        elif selector_type == "id":
            target = soup.find(id=selector_value)
        elif selector_type == "tag":
            candidates = soup.find_all(selector_value)
            if candidates:
                target = candidates[0]

        if not target:
            return full_html

        # Parse the repaired HTML fragment
        replacement = BeautifulSoup(new_html, "html.parser")

        # Swap: replace old element with repaired version
        target.replace_with(replacement)

        return str(soup)

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def _build_repair_prompt(
        self, component_html: str, issues: List[Dict], component_type: str
    ) -> str:
        """Build prompt for targeted repair of a single component."""
        issues_text = "\n".join(
            [f"- [{i['severity'].upper()}] {i['description']}" for i in issues]
        )

        return f"""Repair this {component_type} component HTML.

Current HTML:
```html
{component_html}
```

Issues to fix:
{issues_text}

Instructions:
1. Make ONLY the changes needed to fix these specific issues
2. Preserve all other structure and styling
3. Return ONLY the repaired HTML for this component
4. Do not add comments or explanations
5. Keep the same root element tag and classes if possible

Output just the HTML:
"""

    # ------------------------------------------------------------------
    # Response extraction
    # ------------------------------------------------------------------

    def _extract_repaired_html(self, content: str) -> Optional[str]:
        """Extract repaired HTML from the model's response."""
        import re

        # Look for HTML in code fences
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

        # Return full content if it looks like HTML
        if "<" in content and ">" in content:
            return content.strip()

        return None

    # ------------------------------------------------------------------
    # Type-to-tag mapping
    # ------------------------------------------------------------------

    def _map_type_to_tag(self, element_type: str) -> str:
        """Map semantic element type to HTML tag name."""
        mapping = {
            "container": "div",
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
            "card": "article",
            "nav-item": "a",
            "page": "main",
            "section": "section",
            "navigation": "nav",
        }
        return mapping.get(element_type.lower(), "div")
