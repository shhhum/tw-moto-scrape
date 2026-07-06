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

## Claude Code routine (Banqiao 普通重型機車, hourly)

An earlier routine attempt failed because the routine env's allowlist blocks `cdn.playwright.dev`, so `playwright install` couldn't fetch a browser. That's moot now: Claude Code cloud environments ship a pre-installed Chromium at `/opt/pw-browsers`, and the script falls back to it automatically (`chromium_executable()` in [check_moto_test.py](check_moto_test.py)). Still never run `playwright install` in the cloud env — it will fail and isn't needed.

### Environment (claude.ai/code → Environments)

- **Repository:** `shhhum/tw-moto-scrape`
- **Network policy:** trusted/custom allowlist including `mvdis.gov.tw` and `www.mvdis.gov.tw` (the browser traffic rides the env proxy automatically). Add `ntfy.sh` if you want the routine to push to your phone via the existing `tw_moto_exams` topic.
- **Setup script:**

  ```bash
  pip install -r requirements.txt
  ```

- **Env vars (optional — the routine prompt can also set them inline):** `MVDIS_STATIONS=板橋`, `MVDIS_LICENSES=普通重型機車`.

### Schedule

Hourly 08:00–16:00 Asia/Taipei, daily → UTC cron `0 0-8 * * *` (9 runs/day).

### Routine prompt

Every run notifies the phone, whatever the outcome — via ntfy (rich content) and via the routine's built-in push (enable push notifications on the routine; the prompt marks every run noteworthy).

> Check for open 普通重型機車 (ordinary heavy motorbike) road-test slots at 板橋 (Banqiao) and ALWAYS push a phone notification with the result. From the repo root run:
>
> `MVDIS_STATIONS=板橋 MVDIS_LICENSES=普通重型機車 python3 check_moto_test.py`
>
> Dependencies are installed by the environment setup script and Chromium is pre-installed — never run `playwright install`.
>
> Then notify, every run, regardless of outcome:
>
> - Slots open (output starts with "Upcoming motorcycle road-test slots"): `curl -H "Title: 板橋 slots OPEN" -H "Priority: high" -d "<slot lines + booking link https://www.mvdis.gov.tw/m3-emv-trn/exm/locations#>" ntfy.sh/tw_moto_exams`
> - No slots: `curl -H "Title: 板橋 check" -d "No 普通重型機車 slots at 板橋 this hour." ntfy.sh/tw_moto_exams`
> - Nonzero exit or "ERROR" output: retry once; if it still fails, `curl -H "Title: 板橋 checker ERROR" -H "Priority: high" -d "<error summary>" ntfy.sh/tw_moto_exams`. Do not rewrite the scraper.
>
> Treat every run as noteworthy. End with a one-line summary: the result and whether the ntfy push succeeded (if the curl fails, ntfy.sh is missing from the environment allowlist — say so).

## Implementation notes

Non-obvious things in [check_moto_test.py](check_moto_test.py) that future-you (or future-Claude) will probably wonder about:

- **Headless soft-block bypass.** mvdis.gov.tw 302-loops requests whose `User-Agent` says `HeadlessChrome` or whose `sec-ch-ua` brand string mentions Chromium. The script spoofs both headers and launches with `--disable-blink-features=AutomationControlled`. Drop any of those and `goto` enters an infinite redirect chain that surfaces as `ERR_TOO_MANY_REDIRECTS` (or a goto timeout, depending on Chrome version).
- **`expectExamDateStr` must be filled.** Without an ROC date in `民國 YYYMMDD` format, the form submits but the server replies "查詢不到符合的考試場次" (no matching slots) for every station, regardless of actual availability. We fill it with today's ROC date for a forward-looking window.
- **Submit is a JS link, not a button.** The page has a Google Custom Search widget whose 搜尋 button comes up first in any `<button>` query — its click handler is unrelated. The form's actual submit is `<a class="std_btn" onclick="query();" href="#anchor">`.
- **Station list is hardcoded.** The 4 entries in `STATIONS` ([check_moto_test.py:42](check_moto_test.py:42)) are 臺北市 / 新北市 stations distilled from the live `dmvNoLv1` / `dmvNo` dropdowns. Refresh by re-running the discovery snippet in the commit history if the gov ever adds or renames stations.
- **`額滿` is a sentinel, not a count.** Sessions with no remaining seats render the literal Chinese for "full" in the seat column rather than `0`. The parser drops those rows so the notification only contains slots you could actually book.
- **Duplicate listings across license types are intentional.** A single calendar slot at e.g. 蘆洲 typically accepts both 普通重型機車 and 普通輕型機車 retest candidates and shows up under each query. Output is grouped per license type, so the same physical session appears twice — fine for now since the per-license heading tells you which path it counts toward.
