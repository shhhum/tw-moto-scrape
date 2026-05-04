"""
Checks mvdis.gov.tw for upcoming motorcycle road-test (路考) slots at
Taipei (臺北市) and New Taipei (新北市) DMV stations.

The site is a JS-rendered booking form. The flow per station:
  1. Pick license type (機車), fill expectExamDateStr (ROC date YYYMMDD —
     leave it blank and the site reports "no matching slots" for everything),
     pick DMV region + station
  2. Submit (the std_btn link calls a JS query() function which POSTs the form)
  3. The result page shows either an empty #trnTable with a "no matching slots"
     warning, or a populated tbody with dates / group descriptions / seat counts.
     Rows with "額滿" in the seat column are full and we skip them.

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
import re
from datetime import date
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


def today_roc_date() -> str:
    """ROC date for the expectExamDateStr field (民國 YYYMMDD)."""
    t = date.today()
    return f"{t.year - 1911:03d}{t.month:02d}{t.day:02d}"


def clean_desc(text: str) -> str:
    """Collapse newlines / runs of whitespace into single spaces."""
    return re.sub(r"\s+", " ", text).strip()


async def query_one(page, license_label, region_val, dmv_val, exam_date_roc):
    """Submit the form for one (license, station) and return parsed slot rows.

    Returns a list of {date, desc, available} dicts containing only slots that
    have at least one open seat (i.e. not 額滿). An empty list means the site
    reported no slots, or every slot was full.
    """
    await page.goto(URL, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(1500)

    await page.select_option("#licenseTypeCode", label=license_label)
    # Without expectExamDateStr the site reports "查詢不到符合的考試場次" even
    # when the station has slots. Fill with today's ROC date for a forward-
    # looking window.
    await page.fill("#expectExamDateStr", exam_date_roc)
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
        date_text = clean_desc(await cells[0].inner_text())
        desc_text = clean_desc(await cells[1].inner_text())
        avail_text = clean_desc(await cells[2].inner_text())
        if not date_text:
            continue
        if any(skip in desc_text for skip in SKIP_KEYWORDS):
            continue
        if "額滿" in avail_text:
            continue  # session is full
        rows_out.append({"date": date_text, "desc": desc_text, "available": avail_text})
    return rows_out


async def main():
    exam_date = today_roc_date()
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
        # The page re-fetches dozens of images / fonts / Google Custom Search
        # assets on every submit. Locally it's fine; from a US-region GH
        # Actions runner the round-trip-per-asset to Taiwan dominates and a
        # full run can blow past the job timeout. None of these resources
        # affect the form mechanics or the slot table, so abort them.
        async def block_junk(route):
            req = route.request
            if req.resource_type in ("image", "font", "media", "stylesheet"):
                await route.abort()
                return
            host = req.url.split("/")[2] if "://" in req.url else ""
            if any(h in host for h in ("google.com", "gstatic.com", "googleapis.com",
                                       "googletagmanager.com", "google-analytics.com")):
                await route.abort()
                return
            await route.continue_()

        await ctx.route("**/*", block_junk)
        page = await ctx.new_page()

        for region, dmv, name in STATIONS:
            for lic in MOTORCYCLE_LICENSES:
                try:
                    slots = await query_one(page, lic, region, dmv, exam_date)
                except Exception as e:
                    print(f"[warn] {name} — {lic}: {type(e).__name__}: {e}")
                    continue
                if slots:
                    rows = [
                        f"  - {s['date']}  seats: {s['available']}  {s['desc']}"
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
