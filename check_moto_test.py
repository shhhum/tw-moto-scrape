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

Output is a JSON object on stdout — {ok, scraped_at, new_slots, current_slots,
errors}. On a successful scrape the script also rewrites slot_state.json next
to this file; that is how runs dedupe — only slots absent from the previous
state land in new_slots. A total scrape failure reports {ok: false}, leaves
the state file untouched, and exits non-zero.

Setup:
    pip install -r requirements.txt
    playwright install chromium
Run:
    python3 check_moto_test.py
"""

import asyncio
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

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

# Persistent dedupe state. Committed to the repo so each scheduled run can
# diff against the previous one — the run container is ephemeral, so an
# uncommitted state file is lost.
STATE_FILE = Path(__file__).with_name("slot_state.json")

# The schedule and the target site both live in Asia/Taipei.
TAIPEI_TZ = timezone(timedelta(hours=8))


def today_roc_date() -> str:
    """ROC date for the expectExamDateStr field (民國 YYYMMDD)."""
    t = date.today()
    return f"{t.year - 1911:03d}{t.month:02d}{t.day:02d}"


def clean_desc(text: str) -> str:
    """Collapse newlines / runs of whitespace into single spaces."""
    return re.sub(r"\s+", " ", text).strip()


def slot_key(s: dict) -> str:
    """Stable identity for a slot across runs (seat count deliberately excluded
    so a 2→3 seat change does not re-notify)."""
    return "|".join((s["station"], s["license"], s["date"], s["desc"]))


def load_prev_slots() -> list:
    """Slots recorded by the previous run; empty list if there is no state yet."""
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f).get("slots", [])
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def write_state(slots: list) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {
                "updated_at": datetime.now(TAIPEI_TZ).isoformat(timespec="seconds"),
                "slots": slots,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
        f.write("\n")


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
    scraped = []        # freshly scraped slot dicts this run
    errors = []         # non-fatal per-query errors
    done_units = set()  # (station, license) pairs that scraped without error

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
        # assets on every submit. None affect the form mechanics or the slot
        # table, and the round-trip-per-asset to Taiwan dominates run time, so
        # abort them.
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
                    errors.append(f"{name} — {lic}: {type(e).__name__}: {e}")
                    continue
                done_units.add((name, lic))
                for s in slots:
                    scraped.append({
                        "station": name,
                        "license": lic,
                        "date": s["date"],
                        "desc": s["desc"],
                        "available": s["available"],
                    })

        await browser.close()

    now = datetime.now(TAIPEI_TZ).isoformat(timespec="seconds")
    units_total = len(STATIONS) * len(MOTORCYCLE_LICENSES)

    # Every query failed — site down, network blocked, or selectors broke.
    # Leave the state file untouched so the last-known slots are not lost.
    if not done_units:
        print(json.dumps(
            {"ok": False, "scraped_at": now, "errors": errors},
            ensure_ascii=False,
            indent=2,
        ))
        sys.exit(1)

    prev_slots = load_prev_slots()
    prev_keys = {slot_key(s) for s in prev_slots}

    # Carry forward last-known slots for any (station, license) we could not
    # reach this run, so a transient timeout does not drop them and then
    # re-notify when they reappear. Freshly scraped units fully replace theirs.
    current = {
        slot_key(s): s
        for s in prev_slots
        if (s["station"], s["license"]) not in done_units
    }
    for s in scraped:
        current[slot_key(s)] = s
    current = list(current.values())

    new_slots = [s for s in current if slot_key(s) not in prev_keys]

    write_state(current)

    print(json.dumps({
        "ok": True,
        "scraped_at": now,
        "new_slots": new_slots,
        "current_slots": current,
        "errors": errors,
        "units_total": units_total,
        "units_failed": units_total - len(done_units),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
