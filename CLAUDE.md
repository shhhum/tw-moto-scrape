# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A single-file Playwright async scraper that checks mvdis.gov.tw for motorcycle road-test (路考) slot availability at Taipei / New Taipei DMV stations, skipping the hazard-perception exam (危險感知).

Entry point: [check_moto_test.py](check_moto_test.py). No tests, no linter.

Deployment: local macOS launchd only ([run_check.sh](run_check.sh) + [launchd/](launchd/)), hourly 8am–4pm, Banqiao 普通重型機車, notifies ntfy.sh every run. **mvdis.gov.tw drops all datacenter traffic** — GitHub Actions runners time out (two months of green-but-useless cron runs, since removed) and Claude cloud environments get connection resets. Read "Why not the cloud?" in [README.md](README.md) before re-attempting any hosted scheduler; the GH workflow survives as `workflow_dispatch` for pipeline testing only.

## Setup & run

```bash
source .venv/bin/activate          # existing venv (Python 3.14 from Homebrew)
pip install -r requirements.txt
playwright install chromium        # local only — cloud envs use /opt/pw-browsers
python3 check_moto_test.py
```

## Architecture

- **Drives the real booking form, headless.** Per (station, license type): fill `#licenseTypeCode`, `#expectExamDateStr` (today's ROC date — mandatory, see below), `#dmvNoLv1`/`#dmvNo`, submit via the `a.std_btn[onclick*='query']` JS link, then parse `#trnTable tbody tr` rows into date / description / seat count.
- **Headless soft-block bypass.** mvdis 302-loops requests whose UA or `sec-ch-ua` reveals HeadlessChrome; the script spoofs both and launches with `--disable-blink-features=AutomationControlled`. Don't remove any of the three.
- **Chromium fallback for cloud envs.** `chromium_executable()` prefers `/opt/pw-browsers/chromium` when it exists (Claude Code cloud envs pre-install it; their allowlist blocks `playwright install`). Locally it returns None and Playwright resolves its own browser.
- **Asset blocking.** Images/fonts/stylesheets and Google-domain requests are aborted via `ctx.route` — they dominate wall-clock from non-Taiwan runners and don't affect the form.
- **Failure semantics.** Individual query failures warn and continue; if *every* query fails the script exits 1 with an `ERROR:` line so cron consumers can distinguish "site unreachable" from "no slots".

## Config knobs

- `STATIONS` / `MOTORCYCLE_LICENSES` constants in [check_moto_test.py](check_moto_test.py) — the full query matrix (station IDs distilled from the live dropdowns; refresh via the discovery snippet in commit history if they drift).
- `MVDIS_STATIONS` / `MVDIS_LICENSES` env vars — comma-separated substrings that narrow the matrix at runtime (e.g. `MVDIS_STATIONS=板橋 MVDIS_LICENSES=普通重型機車`). A filter matching nothing exits nonzero rather than silently scraping nothing.
- `SKIP_KEYWORDS` — Chinese exam-type substrings excluded from result rows.

## Domain notes

- The scraped page is Traditional Chinese. All matching is on raw Chinese substrings (路考, 危險感知, 額滿, 板橋…) — do not lowercase, ASCII-fold, or otherwise normalize text before matching.
- `expectExamDateStr` must contain an ROC date (民國 `YYYMMDD`) or the server reports "查詢不到符合的考試場次" for every station regardless of availability.
- `額滿` in the seats column is a "full" sentinel, not a count — those rows are dropped.
- The output prefix `Upcoming motorcycle road-test slots` is load-bearing: the GH Actions notify step and the Claude routine prompt both key off it.
