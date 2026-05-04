# tw-moto-scrape

A Playwright async scraper that checks [mvdis.gov.tw](https://www.mvdis.gov.tw/m3-emv-trn/exm/locations) for upcoming motorcycle road-test (路考) slots at Taipei (臺北市) and New Taipei (新北市) DMV stations. Runs on GitHub Actions every 3 hours and pushes a notification to ntfy.sh when slots are open.

## Local run

```bash
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
python3 check_moto_test.py
```

## Deploying to GitHub Actions

Goal: run every 3 hours from 8am–8pm Taipei time and surface matching slots in the Actions run log.

The workflow at [.github/workflows/scrape.yml](.github/workflows/scrape.yml):

- Triggers on cron `0 0,3,6,9,12 * * *` (UTC), which is 08:00, 11:00, 14:00, 17:00, 20:00 Asia/Taipei.
- Also exposes `workflow_dispatch` so you can run it on-demand from the Actions tab.
- Sets up Python 3.12 with pip cache, installs `requirements.txt`, runs `playwright install --with-deps chromium`, then executes the script.
- If the script's output contains `Upcoming motorcycle road-test slots`, POSTs the output as a push notification to `https://ntfy.sh/tw_moto_exams`. No-slot runs stay silent — the GH Actions log still has the full output if you want to verify.

### Push notifications via ntfy

The notify step is a single `curl` to [ntfy.sh](https://ntfy.sh) — no secrets, no account, no SMTP setup. Subscribe to the topic on your phone:

1. Install the [ntfy app](https://ntfy.sh/app) (iOS / Android / web).
2. Subscribe to topic `tw_moto_exams`.

ntfy topics are public-by-obscurity — anyone who knows the topic name can read or post to it. The motorcycle slot data isn't sensitive, but if you want to lock it down later, ntfy supports auth and self-hosted instances. Topic name is hardcoded at [.github/workflows/scrape.yml](.github/workflows/scrape.yml) — change it there + on your phone if you want a different one.

### Caveats

- **Schedule is best-effort.** GitHub-cron jobs can be delayed by up to ~15 min during peak load. Fine for a 3-hour cadence.
- **Inactive-repo pause.** GitHub auto-pauses scheduled workflows after 60 days without a push. Any commit reactivates them.
- **No state across runs.** Every run that finds slots fires a fresh notification; we don't dedupe against previous runs.
- **Free-tier is plenty.** 5 runs/day × ~2 min/run ≈ 5 hours/month, against 2,000 min/month free for private repos (unlimited for public).

### Why not Claude routines?

Tried it; the routine env's outbound allowlist blocks `cdn.playwright.dev`, so `playwright install` can't fetch the Chromium-for-Testing binary that Python Playwright 1.59 expects. Hosted-browser MCPs (Browserbase et al.) would work but cost ~$10/mo and require rewriting the script as a prompt. GitHub Actions has no allowlist, runs the script as-is, and is free at this volume.

## Implementation notes

Non-obvious things in [check_moto_test.py](check_moto_test.py) that future-you (or future-Claude) will probably wonder about:

- **Headless soft-block bypass.** mvdis.gov.tw 302-loops requests whose `User-Agent` says `HeadlessChrome` or whose `sec-ch-ua` brand string mentions Chromium. The script spoofs both headers and launches with `--disable-blink-features=AutomationControlled`. Drop any of those and `goto` enters an infinite redirect chain that surfaces as `ERR_TOO_MANY_REDIRECTS` (or a goto timeout, depending on Chrome version).
- **`expectExamDateStr` must be filled.** Without an ROC date in `民國 YYYMMDD` format, the form submits but the server replies "查詢不到符合的考試場次" (no matching slots) for every station, regardless of actual availability. We fill it with today's ROC date for a forward-looking window.
- **Submit is a JS link, not a button.** The page has a Google Custom Search widget whose 搜尋 button comes up first in any `<button>` query — its click handler is unrelated. The form's actual submit is `<a class="std_btn" onclick="query();" href="#anchor">`.
- **Station list is hardcoded.** The 4 entries in `STATIONS` ([check_moto_test.py:42](check_moto_test.py:42)) are 臺北市 / 新北市 stations distilled from the live `dmvNoLv1` / `dmvNo` dropdowns. Refresh by re-running the discovery snippet in the commit history if the gov ever adds or renames stations.
- **`額滿` is a sentinel, not a count.** Sessions with no remaining seats render the literal Chinese for "full" in the seat column rather than `0`. The parser drops those rows so the notification only contains slots you could actually book.
- **Duplicate listings across license types are intentional.** A single calendar slot at e.g. 蘆洲 typically accepts both 普通重型機車 and 普通輕型機車 retest candidates and shows up under each query. Output is grouped per license type, so the same physical session appears twice — fine for now since the per-license heading tells you which path it counts toward.
