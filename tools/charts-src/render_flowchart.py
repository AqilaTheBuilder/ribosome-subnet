"""Render the mechanism flowchart HTML to PNG via Playwright (scale=2)."""
import asyncio
import os
from pathlib import Path

from playwright.async_api import async_playwright

HTML = Path("/home/z/my-project/scripts/chart_mechanism_flowchart.html")
OUT = Path("/home/z/my-project/download/ribosome-network/docs/charts/chart_mechanism_flowchart.png")


async def render() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(
            viewport={"width": 1040, "height": 900}, device_scale_factor=2
        )
        await page.goto(f"file://{HTML}", wait_until="networkidle")
        await page.wait_for_timeout(400)
        el = page.locator("#root")
        bbox = await el.bounding_box()
        if bbox:
            await page.set_viewport_size(
                {"width": max(1040, int(bbox["width"] + 80)), "height": int(bbox["height"] + 80)}
            )
            await page.wait_for_timeout(200)
        OUT.parent.mkdir(parents=True, exist_ok=True)
        await el.screenshot(path=str(OUT))
        await browser.close()
    print(f"OK {OUT} ({os.path.getsize(OUT)/1024:.0f} KB)")


if __name__ == "__main__":
    asyncio.run(render())
