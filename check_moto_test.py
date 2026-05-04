"""
Checks mvdis.gov.tw for upcoming motorcycle road-test (路考) slots at
Taipei (臺北市) and New Taipei (新北市) DMV stations.

The site is a JS-rendered booking form. The flow per station:
  1. Pick license type (機車) and DMV station
  2. Submit (the std_btn link calls a JS query() function which POSTs the form)
  3. The result page shows either an empty #trnTable with a "no matching slots"
     warning, or a populated tbody with dates / group descriptions / seat counts

The site soft-blocks headless browsers via UA / sec-ch-ua sniffing, so we spoof
both. Hazard-perception (危險感知) bookings live on a separate platform and
shouldn't appear in this table; we filter them out defensively anyway.

Setup:
    pip install -r requirements.txt
    playwright install chromium chromium-headless-shell
Run:
    python3 check_moto_test.py
"""

import asyncio
from playwright.async_api import async_playwright

URL = "https://www.mvdis.gov.tw/m3-emv-trn/exm/locations"

# Spoof a full Chrome to bypass the site's HeadlessChrome soft-block.
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
)
SEC_CH_UA = '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"'

# (region_value, dmv_value, friendly name) — derived from the live dropdown options
# on 2026-05-05. Re-run the discovery snippet in commit history if station IDs
# ever drift.
STATIONS = [
    ("20", "21", "士林 Shilin (Taipei)"),
    ("40", "40", "臺北區監理所 Shulin (New Taipei)"),
    ("40", "41", "板橋 Banqiao (New Taipei)"),
    ("40", "46", "蘆洲 Luzhou (New Taipei)"),
]

# Motorcycle license categories. We iterate by exact dropdown label.
MOTORCYCLE_LICENSES = [
    "普通重型機車",
    "普通輕型機車 (50cc 以下)",
]

# Filter out hazard-perception entries if the table ever contains them.
SKIP_KEYWORDS = ["危險感知", "危感"]


async def query_one(page, license_label, region_val, dmv_val):
    """Submit the form for one (license, station) and return parsed slot rows.

    Returns a list of {date, desc, available} dicts. An empty list means the
    site explicitly reported no matching slots for this combo.
    """
    await page.goto(URL, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(1500)

    await page.select_option("#licenseTypeCode", label=license_label)
    await page.select_option("#dmvNoLv1", value=region_val)
    # dmvNoLv1 onchange fetches dmvNo options via JS; give it a beat.
    await page.wait_for_timeout(1200)
    await page.select_option("#dmvNo", value=dmv_val)
    await page.click("a.std_btn[onclick*='query']")

    try:
        await page.wait_for_load_state("domcontentloaded", timeout=20000)
    except Exception:
        pass
    await page.wait_for_timeout(2500)

    # The site renders a "no matching slots" warning into #headerMessage when empty.
    msg_el = await page.query_selector("#headerMessage")
    if msg_el:
        msg_text = (await msg_el.inner_text() or "").strip()
        if "查詢不到" in msg_text:
            return []

    rows_out = []
    for tr in await page.query_selector_all("#trnTable tbody tr"):
        cells = await tr.query_selector_all("td")
        if len(cells) < 3:
            continue
        date_text = (await cells[0].inner_text()).strip()
        desc_text = (await cells[1].inner_text()).strip()
        avail_text = (await cells[2].inner_text()).strip()
        if any(skip in desc_text for skip in SKIP_KEYWORDS):
            continue
        if not date_text and not desc_text:
            continue
        rows_out.append({"date": date_text, "desc": desc_text, "available": avail_text})
    return rows_out


async def main():
    sections = []  # (header, [row strings])

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx = await browser.new_context(
            user_agent=UA,
            extra_http_headers={"sec-ch-ua": SEC_CH_UA},
            ignore_https_errors=True,
        )
        page = await ctx.new_page()

        for region, dmv, name in STATIONS:
            for lic in MOTORCYCLE_LICENSES:
                try:
                    slots = await query_one(page, lic, region, dmv)
                except Exception as e:
                    print(f"[warn] {name} — {lic}: {type(e).__name__}: {e}")
                    continue
                if slots:
                    rows = [
                        f"  - {s['date']}  {s['desc']}  (seats: {s['available']})"
                        for s in slots
                    ]
                    sections.append((f"{name} — {lic}", rows))

        await browser.close()

    if sections:
        print("Upcoming motorcycle road-test slots in Taipei / New Taipei DMV centers:\n")
        for header, rows in sections:
            print(header)
            print("\n".join(rows))
            print()
    else:
        print("No upcoming motorcycle road-test slots in Taipei or New Taipei DMV centers.")


if __name__ == "__main__":
    asyncio.run(main())
