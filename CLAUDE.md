# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A single-file Playwright async scraper that checks mvdis.gov.tw for motorcycle road-test (路考) slot availability in Taipei (台北) and New Taipei (新北), skipping the hazard-perception exam (危險感知).

Entry point: [check_moto_test.py](check_moto_test.py). No tests, no linter.

Intended deployment: a Claude routine on a cron schedule (every 3h, 8am–8pm Asia/Taipei). [README.md](README.md) has the full deploy steps; [.claude/setup.sh](.claude/setup.sh) is the routine setup script that installs Python deps + Chromium (cached across runs).

## Setup & run

```bash
source .venv/bin/activate          # existing venv (Python 3.14 from Homebrew)
pip install -r requirements.txt
playwright install chromium        # one-time browser download
python3 check_moto_test.py
```

## Architecture

- **Async Playwright, non-headless by default.** Chromium launches with `headless=False` at [check_moto_test.py:23](check_moto_test.py:23) so the run is visible — the target site may need manual interaction (clicking a city or exam type) before slots render.
- **Selector strategy is a heuristic, not finished.** The script does a broad `query_selector_all("a, button, li, tr, .exam-item, [class*='exam'], [class*='item']")` and filters elements by Chinese substring matches. If the page structure becomes known, replace this with targeted selectors.
- **Filter pipeline** (per element): must contain a city in `TARGET_CITIES` → must NOT contain a `SKIP_KEYWORDS` token → must contain a date (`\d{2,4}[-/年]\d{1,2}[-/月]\d{1,2}`) or time (`\d{1,2}:\d{2}`) regex hit.
- **Debug fallback.** When no matches are found, the script dumps the first 3000 chars of `body` inner text to stdout and saves `mvdis_screenshot.png` (full page). It also prints the first 3000 body chars on every run — useful while iterating, worth gating behind a flag once selectors stabilize.

## Config knobs

The three top-level constants at [check_moto_test.py:16-18](check_moto_test.py:16) drive everything — edit them to retarget the scraper:

- `TARGET_CITIES` — Chinese city substrings to match.
- `SKIP_KEYWORDS` — Chinese exam-type substrings to exclude.
- `URL` — mvdis exam-locations page.

## Domain notes

The scraped page is Traditional Chinese. All matching is on raw Chinese substrings (路考, 危險感知, 台北, 新北) — do not lowercase, ASCII-fold, or otherwise normalize text before matching.
