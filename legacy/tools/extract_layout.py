"""
extract_layout — Pull computed styles and bounding boxes from the live DOM via Playwright.
Token-budget aware: filters zero-size elements, collapses repeated siblings.
"""
import asyncio
import json

# JS function injected into the page to walk the DOM
_DOM_WALKER_JS = """
(function(rootSelector, maxDepth) {
    const STYLE_PROPS = [
        'display','position','flexDirection','flexWrap','justifyContent','alignItems',
        'gridTemplateColumns','gridTemplateRows','gap','rowGap','columnGap',
        'width','height','minWidth','minHeight','maxWidth','maxHeight',
        'paddingTop','paddingRight','paddingBottom','paddingLeft',
        'marginTop','marginRight','marginBottom','marginLeft',
        'fontSize','fontFamily','fontWeight','lineHeight','color',
        'backgroundColor','backgroundImage','borderRadius','border',
        'boxShadow','opacity','overflow','zIndex','transform'
    ];

    function getCSSVars(el) {
        const style = getComputedStyle(el);
        const vars = {};
        for (const prop of style) {
            if (prop.startsWith('--')) vars[prop] = style.getPropertyValue(prop).trim();
        }
        return vars;
    }

    function walk(el, depth) {
        if (depth > maxDepth) return null;

        const rect = el.getBoundingClientRect();
        // Skip zero-size invisible elements
        if (rect.width === 0 && rect.height === 0 && el.tagName !== 'HTML') return null;

        const style = getComputedStyle(el);
        const styles = {};
        for (const prop of STYLE_PROPS) {
            const val = style[prop];
            if (val && val !== 'none' && val !== 'normal' && val !== 'auto' && val !== '0px') {
                styles[prop] = val;
            }
        }

        const text = el.childNodes.length === 1 && el.firstChild?.nodeType === 3
            ? el.firstChild.textContent.trim().slice(0, 80)
            : null;

        const children = [];
        const childEls = Array.from(el.children);

        // Collapse repeated identical siblings (e.g. 50 list items → 1 + count)
        let i = 0;
        while (i < childEls.length) {
            const child = childEls[i];
            const tag = child.tagName;
            let runLen = 1;
            while (i + runLen < childEls.length && childEls[i + runLen].tagName === tag) runLen++;
            const node = walk(child, depth + 1);
            if (node) {
                if (runLen > 3) node._repeated = runLen;
                children.push(node);
                i += runLen;
            } else {
                i++;
            }
        }

        return {
            tag: el.tagName.toLowerCase(),
            id: el.id || undefined,
            classes: el.className ? el.className.split(' ').filter(Boolean) : undefined,
            text: text || undefined,
            rect: { x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height) },
            styles,
            children: children.length ? children : undefined
        };
    }

    const root = document.querySelector(rootSelector) || document.body;
    const cssVars = getCSSVars(document.documentElement);
    return { tree: walk(root, 0), cssVars };
})(arguments[0], arguments[1]);
"""


async def _extract(target: str, selector: str, max_depth: int) -> dict:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(target, wait_until="networkidle")

        result = await page.evaluate(_DOM_WALKER_JS, selector, max_depth)

        # Accessibility tree as a lightweight semantic complement
        try:
            a11y = await page.accessibility.snapshot()
        except Exception:
            a11y = None

        await browser.close()

    return {
        "layout": result.get("tree"),
        "css_vars": result.get("cssVars", {}),
        "accessibility": a11y,
    }


def extract_layout(target: str, selector: str = "body", max_depth: int = 5) -> dict:
    """
    Extract DOM tree with computed styles and bounding boxes from the rendered page.

    Returns:
        {
            "layout": nested dict tree,
            "css_vars": {--var-name: value, ...},
            "accessibility": a11y snapshot dict
        }
    """
    try:
        return asyncio.run(_extract(target, selector, max_depth))
    except Exception as e:
        return {"error": str(e)}
