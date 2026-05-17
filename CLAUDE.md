# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A single-file Playwright async scraper ([check_moto_test.py](check_moto_test.py)) that checks
mvdis.gov.tw for upcoming motorcycle road-test (路考) slots at four Taipei (臺北市) /
New Taipei (新北市) DMV stations, skipping anything full (額滿) or hazard-perception (危險感知).

No tests, no linter. Deployed as a GitHub Actions cron ([.github/workflows/scrape.yml](.github/workflows/scrape.yml))
that runs every 3h (08:00–20:00 Asia/Taipei) and pushes matches to `ntfy.sh/tw_moto_exams`.
[README.md](README.md) holds the full deploy notes and the "why not Claude routines" rationale
(the routine env's outbound allowlist blocks `cdn.playwright.dev` — don't re-litigate without
reading the README first).

## Setup & run

```bash
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium          # one-time browser download
python3 check_moto_test.py
```

The script takes no args and only prints to stdout. The GH Actions runner uses Python 3.12
and `playwright install --with-deps chromium`.

## Architecture

The site is a **JS-rendered booking form**, not a static listing. Control flow:

- `main()` launches headless Chromium with a spoofed full-Chrome UA, then iterates the
  cartesian product of `STATIONS` × `MOTORCYCLE_LICENSES`, calling `query_one()` for each.
- `query_one()` drives one form submission: select license type → fill
  `#expectExamDateStr` with today's ROC date → select region (`#dmvNoLv1`) → wait for the
  JS-populated `#dmvNo` options → select station → click the JS submit link → parse
  `#trnTable tbody tr`. Returns only rows with open seats.
- A request-blocking route (`block_junk`) aborts images/fonts/media/CSS and Google
  assets. This is a **correctness-relevant performance fix**, not just speed: from a
  US-region runner the per-asset round-trip to Taiwan can blow past the 10-min job
  timeout. None of the blocked resources affect form mechanics or the slot table.
- Output is grouped per `(station, license)` section. Empty → single "no slots" line,
  which the workflow greps for (`^Upcoming motorcycle road-test slots`) to decide whether
  to fire a notification.

## Config knobs (top of check_moto_test.py)

- `STATIONS` — hardcoded `(region_value, dmv_value, name)` tuples distilled from the live
  `dmvNoLv1`/`dmvNo` dropdowns (snapshot 2026-05-05). Refresh via the discovery snippet in
  git history if the gov adds/renames stations.
- `MOTORCYCLE_LICENSES` — exact dropdown labels to iterate.
- `SKIP_KEYWORDS` — hazard-perception substrings to drop defensively.
- `UA` / `SEC_CH_UA` — spoofed headers (see gotcha below).

## Non-obvious gotchas

These will bite you; most are documented at length in [README.md](README.md) "Implementation notes".

- **Headless soft-block bypass is load-bearing.** mvdis.gov.tw 302-loops requests whose
  `User-Agent` says `HeadlessChrome` or whose `sec-ch-ua` mentions Chromium. The spoofed
  `UA`/`SEC_CH_UA` headers + `--disable-blink-features=AutomationControlled` are all
  required — drop any and `goto` enters an infinite redirect (`ERR_TOO_MANY_REDIRECTS`
  or a goto timeout).
- **`#expectExamDateStr` must be filled** with a 民國 `YYYMMDD` ROC date (`today_roc_date()`).
  Leave it blank and the server returns "查詢不到符合的考試場次" (no slots) for *every*
  station regardless of real availability.
- **Submit is a JS `<a class="std_btn" onclick="query();">`, not a `<button>`.** A Google
  Custom Search widget's 搜尋 button wins any generic `<button>` query — don't retarget the
  submit by tag.
- **`額滿` is a sentinel, not `0`.** Full sessions render the literal Chinese for "full" in
  the seat column; the parser drops those rows.
- **Duplicate listings across license types are intentional.** One physical slot often
  accepts both 重型 and 輕型 retests and appears under each query; output is grouped per
  license so it shows twice.

## Domain notes

The page is Traditional Chinese. All matching is on raw Chinese substrings
(路考, 危險感知, 額滿, 臺北, 新北, dropdown labels) — never lowercase, ASCII-fold, or
normalize text before matching.
