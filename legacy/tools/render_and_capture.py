"""
render_and_capture — Headless Playwright screenshot with console capture.
"""
import asyncio
import base64
from typing import Optional


async def _capture(
    target: str,
    viewport_width: int,
    viewport_height: int,
    full_page: bool,
    wait_ms: int,
) -> dict:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": viewport_width, "height": viewport_height}
        )
        page = await context.new_page()

        console_messages: list[dict] = []
        page_errors: list[str] = []

        page.on(
            "console",
            lambda msg: console_messages.append({"type": msg.type, "text": msg.text}),
        )
        page.on("pageerror", lambda err: page_errors.append(str(err)))

        await page.goto(target, wait_until="networkidle")
        await page.wait_for_timeout(wait_ms)

        screenshot_bytes = await page.screenshot(full_page=full_page)
        actual_viewport = page.viewport_size or {"width": viewport_width, "height": viewport_height}
        page_height = await page.evaluate("document.documentElement.scrollHeight")

        await browser.close()

    return {
        "screenshot": base64.b64encode(screenshot_bytes).decode(),
        "viewport": actual_viewport,
        "page_height": page_height,
        "console_errors": [
            m for m in console_messages if m["type"] in ("error", "warning")
        ],
        "page_errors": page_errors,
    }


def render_and_capture(
    target: str,
    viewport_width: int = 1280,
    viewport_height: int = 800,
    full_page: bool = True,
    wait_ms: int = 1500,
) -> dict:
    """
    Render target URL and capture a screenshot via headless Chromium.

    Returns:
        {
            "screenshot": base64 PNG string,
            "viewport": {"width": int, "height": int},
            "page_height": int,
            "console_errors": [{"type": str, "text": str}, ...],
            "page_errors": [str, ...]
        }
    """
    try:
        return asyncio.run(
            _capture(target, viewport_width, viewport_height, full_page, wait_ms)
        )
    except Exception as e:
        return {"error": str(e)}
