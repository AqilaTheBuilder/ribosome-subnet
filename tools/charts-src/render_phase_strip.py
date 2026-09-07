"""Render the compact phase strip for PDF embedding."""
import asyncio
import os
from pathlib import Path

from playwright.async_api import async_playwright

HTML = Path("/home/z/my-project/scripts/chart_phase_strip.html")
OUT = Path("/home/z/my-project/download/ribosome-network/docs/charts/pdf/fig_phase_strip.png")


async def render() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1900, "height": 500},
                                      device_scale_factor=2)
        await page.goto(f"file://{HTML}", wait_until="networkidle")
        await page.wait_for_timeout(300)
        el = page.locator("#root")
        bbox = await el.bounding_box()
        if bbox:
            await page.set_viewport_size({"width": int(bbox["width"] + 40),
                                          "height": int(bbox["height"] + 40)})
            await page.wait_for_timeout(200)
        OUT.parent.mkdir(parents=True, exist_ok=True)
        await el.screenshot(path=str(OUT))
        await browser.close()
    print(f"OK {OUT} ({os.path.getsize(OUT)/1024:.0f} KB)")


if __name__ == "__main__":
    asyncio.run(render())
