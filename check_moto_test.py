"""
Checks mvdis.gov.tw for available motorcycle road test (路考) slots
in Taipei (台北) and New Taipei City (新北).
Skips 危險感知測驗 (danger/hazard perception exam).

Setup:
    pip install playwright
    playwright install chromium
Run:
    python3 check_moto_test.py
"""

import asyncio
from playwright.async_api import async_playwright

TARGET_CITIES = ["台北", "新北"]
SKIP_KEYWORDS = ["危險感知", "危感"]
URL = "https://www.mvdis.gov.tw/m3-emv-trn/exm/locations#"


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)  # set True to run silently
        page = await browser.new_page()

        print(f"Opening {URL} ...")
        await page.goto(URL, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(2000)

        # Dump all visible text so we can understand the page structure
        # (useful on first run — comment out after)
        body_text = await page.inner_text("body")
        print("\n--- Page text (first 3000 chars) ---")
        print(body_text[:3000])
        print("------------------------------------\n")

        # Try to find exam-type options and pick road-test entries
        # The site likely has a list of exam types; look for buttons/links
        all_items = await page.query_selector_all(
            "a, button, li, tr, .exam-item, [class*='exam'], [class*='item']"
        )

        print(f"Found {len(all_items)} candidate elements.\n")

        results = []

        for el in all_items:
            try:
                text = (await el.inner_text()).strip()
            except Exception:
                continue

            if not text:
                continue

            # Skip danger/hazard exam
            if any(kw in text for kw in SKIP_KEYWORDS):
                continue

            # Only keep entries mentioning target cities
            if not any(city in text for city in TARGET_CITIES):
                continue

            # Look for date/time patterns (民國 or yyyy-mm-dd or time like 09:00)
            import re

            has_date = bool(re.search(r"\d{2,4}[-/年]\d{1,2}[-/月]\d{1,2}", text))
            has_time = bool(re.search(r"\d{1,2}:\d{2}", text))

            if has_date or has_time:
                results.append(text)

        if results:
            print("=== Available slots (Taipei / New Taipei, road test only) ===")
            for r in results:
                print(r)
                print("-" * 60)
        else:
            print("No matching slots found via element scan.")
            print(
                "The site may need manual interaction (e.g. clicking a city or exam type first)."
            )
            print("A screenshot has been saved to: mvdis_screenshot.png")
            await page.screenshot(path="mvdis_screenshot.png", full_page=True)

        await browser.close()


asyncio.run(main())
