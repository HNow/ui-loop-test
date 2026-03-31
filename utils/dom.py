"""
DOM extraction utilities using Playwright.
"""

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from playwright.async_api import async_playwright, Page


@dataclass
class DOMNode:
    """Simplified DOM node representation."""
    tag: str
    classes: List[str] = field(default_factory=list)
    id: Optional[str] = None
    text: str = ""
    bbox: Optional[Dict[str, float]] = None  # x, y, width, height
    computed_styles: Dict[str, str] = field(default_factory=dict)
    children: List["DOMNode"] = field(default_factory=list)
    
    def to_tree_string(self, indent: int = 0) -> str:
        """Convert to simple tree string representation."""
        prefix = "  " * indent
        attrs = []
        if self.id:
            attrs.append(f"#{self.id}")
        if self.classes:
            attrs.append(f".{'.'.join(self.classes)}")
        
        attrs_str = "".join(attrs)
        text_preview = self.text[:30] + "..." if len(self.text) > 30 else self.text
        
        result = f"{prefix}{self.tag}{attrs_str}"
        if text_preview:
            result += f' "{text_preview}"'
        if self.bbox:
            result += f' [{int(self.bbox["width"])}x{int(self.bbox["height"])}]'
        
        for child in self.children:
            result += "\n" + child.to_tree_string(indent + 1)
        
        return result


async def extract_dom_tree(
    page: Page,
    selector: str = "body",
    max_depth: int = 5,
    skip_invisible: bool = True
) -> DOMNode:
    """
    Extract DOM tree with computed styles and bounding boxes.
    """
    js_code = """
    (args) => {
        const selector = args.selector;
        const maxDepth = args.maxDepth;
        const skipInvisible = args.skipInvisible;
        
        function extractNode(element, depth) {
            if (!element) return null;
            
            // Skip invisible elements
            if (skipInvisible) {
                const style = window.getComputedStyle(element);
                if (style.display === 'none' || style.visibility === 'hidden') {
                    return null;
                }
            }
            
            // Get bounding box
            const rect = element.getBoundingClientRect();
            const bbox = {
                x: rect.x,
                y: rect.y,
                width: rect.width,
                height: rect.height
            };
            
            // Skip zero-size elements
            if (bbox.width === 0 && bbox.height === 0) {
                return null;
            }
            
            // Get computed styles (subset)
            const computed = window.getComputedStyle(element);
            const styles = {
                display: computed.display,
                position: computed.position,
                flexDirection: computed.flexDirection,
                justifyContent: computed.justifyContent,
                alignItems: computed.alignItems,
                backgroundColor: computed.backgroundColor,
                color: computed.color,
                fontSize: computed.fontSize,
                fontWeight: computed.fontWeight,
                padding: computed.padding,
                margin: computed.margin,
                borderRadius: computed.borderRadius,
                gap: computed.gap
            };
            
            const node = {
                tag: element.tagName.toLowerCase(),
                id: element.id || null,
                classes: Array.from(element.classList),
                text: element.innerText?.substring(0, 100) || "",
                bbox: bbox,
                computed_styles: styles,
                children: []
            };
            
            // Recurse if not at max depth
            if (depth < maxDepth) {
                for (const child of element.children) {
                    const childNode = extractNode(child, depth + 1);
                    if (childNode) {
                        node.children.push(childNode);
                    }
                }
            }
            
            return node;
        }
        
        const root = document.querySelector(selector);
        return extractNode(root, 0);
    }
    """
    
    result = await page.evaluate(js_code, {
        "selector": selector,
        "maxDepth": max_depth,
        "skipInvisible": skip_invisible
    })
    
    return _dict_to_dom_node(result)


def _dict_to_dom_node(data: dict) -> DOMNode:
    """Convert dict result to DOMNode."""
    if not data:
        return DOMNode(tag="empty")
    
    children = [_dict_to_dom_node(c) for c in data.get("children", [])]
    
    return DOMNode(
        tag=data.get("tag", "unknown"),
        id=data.get("id"),
        classes=data.get("classes", []),
        text=data.get("text", ""),
        bbox=data.get("bbox"),
        computed_styles=data.get("computed_styles", {}),
        children=children
    )


async def capture_screenshot(
    page: Page,
    full_page: bool = True,
    viewport_width: int = 1280,
    viewport_height: int = 800
) -> bytes:
    """Capture screenshot as PNG bytes."""
    await page.set_viewport_size({
        "width": viewport_width,
        "height": viewport_height
    })
    
    if full_page:
        return await page.screenshot(full_page=True, type="png")
    else:
        return await page.screenshot(type="png")


async def render_html(
    html_path: str,
    server_url: str,
    viewport_width: int = 1280,
    viewport_height: int = 800,
    wait_ms: int = 1500
) -> tuple[bytes, DOMNode, List[str]]:
    """
    Render HTML file and capture screenshot + DOM.
    Returns: (screenshot_bytes, dom_tree, console_errors).
    """
    console_errors = []
    
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        
        # Capture console errors
        page.on("console", lambda msg: console_errors.append(f"{msg.type}: {msg.text}") if msg.type == "error" else None)
        page.on("pageerror", lambda err: console_errors.append(f"Page error: {err}"))
        
        # Navigate
        await page.goto(server_url, wait_until="networkidle")
        
        # Wait for fonts/CDN
        await page.wait_for_timeout(wait_ms)
        
        # Extract DOM
        dom_tree = await extract_dom_tree(page, max_depth=5)
        
        # Capture screenshot
        screenshot = await capture_screenshot(
            page,
            full_page=True,
            viewport_width=viewport_width,
            viewport_height=viewport_height
        )
        
        await browser.close()
        
        return screenshot, dom_tree, console_errors
