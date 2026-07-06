# tw-moto-scrape

A Playwright async scraper that checks [mvdis.gov.tw](https://www.mvdis.gov.tw/m3-emv-trn/exm/locations) for upcoming motorcycle road-test (路考) slots at Taipei (臺北市) and New Taipei (新北市) DMV stations. Runs hourly (8am–4pm Taipei) on GitHub Actions, targeting Banqiao 普通重型機車, and pushes a notification to ntfy.sh on every run — slots open, no slots, or error. A local launchd runner is included as an alternative scheduler.

## Local run

```bash
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
python3 check_moto_test.py
```

## Deploying to GitHub Actions

Goal: check Banqiao 普通重型機車 hourly from 8am–4pm Taipei time and push the result to the phone every run, so silence unambiguously means "the workflow didn't run".

The workflow at [.github/workflows/scrape.yml](.github/workflows/scrape.yml):

- Triggers on cron `0 0-8 * * *` (UTC), which is hourly 08:00–16:00 Asia/Taipei (9 runs/day).
- Also exposes `workflow_dispatch` so you can run it on-demand from the Actions tab.
- Narrows the scrape via `MVDIS_STATIONS=板橋` / `MVDIS_LICENSES=普通重型機車` job env vars — clear them to scan the full station × license matrix.
- Sets up Python 3.12 with pip cache, installs `requirements.txt`, runs `playwright install --with-deps chromium`, then executes the script.
- Notifies `https://ntfy.sh/tw_moto_exams` on **every** run: slots found → high-priority "Banqiao slots OPEN" with the slot lines and booking link; none → "Banqiao check / no slots this hour"; scraper exit ≠ 0 → high-priority "Banqiao checker ERROR" with the output tail.

### Push notifications via ntfy

The notify step is a single `curl` to [ntfy.sh](https://ntfy.sh) — no secrets, no account, no SMTP setup. Subscribe to the topic on your phone:

1. Install the [ntfy app](https://ntfy.sh/app) (iOS / Android / web).
2. Subscribe to topic `tw_moto_exams`.

ntfy topics are public-by-obscurity — anyone who knows the topic name can read or post to it. The motorcycle slot data isn't sensitive, but if you want to lock it down later, ntfy supports auth and self-hosted instances. Topic name is hardcoded at [.github/workflows/scrape.yml](.github/workflows/scrape.yml) — change it there + on your phone if you want a different one.

### Caveats

- **Schedule is best-effort.** GitHub-cron jobs can be delayed by up to ~15 min during peak load — expect the hourly push at :00–:15, not on the dot.
- **Inactive-repo pause.** GitHub auto-pauses scheduled workflows after 60 days without a push. Any commit reactivates them. With always-notify, the pause is at least visible: the hourly pushes stop.
- **No state across runs.** Every run that finds slots fires a fresh notification; we don't dedupe against previous runs.
- **Free-tier is plenty.** 9 runs/day × ~2 min/run ≈ 9 hours/month, against 2,000 min/month free for private repos (unlimited for public).

## Running locally on macOS (launchd)

Alternative to GitHub Actions: [run_check.sh](run_check.sh) runs the same Banqiao check and pushes the result to ntfy on every run, and [launchd/com.twmoto.slotcheck.plist](launchd/com.twmoto.slotcheck.plist) schedules it hourly 08:00–16:00 local time. Pick **one** scheduler — running both means two pushes per hour.

Install (from the repo root, with `.venv` already set up per "Local run" above):

```bash
sed "s|__REPO__|$(pwd)|g" launchd/com.twmoto.slotcheck.plist > ~/Library/LaunchAgents/com.twmoto.slotcheck.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.twmoto.slotcheck.plist
```

Test immediately: `launchctl kickstart -k gui/$(id -u)/com.twmoto.slotcheck` (logs land in `/tmp/twmoto-slotcheck.log`).

Uninstall: `launchctl bootout gui/$(id -u)/com.twmoto.slotcheck && rm ~/Library/LaunchAgents/com.twmoto.slotcheck.plist`.

Caveats vs Actions: fire times missed while the Mac sleeps coalesce into a single run on wake (lid closed all morning = no checks all morning), and the schedule is in the Mac's local timezone — the plist assumes Asia/Taipei.

## Why not Claude Code cloud routines?

Two failed attempts, two different walls. (1) May 2026: the routine env allowlist blocks `cdn.playwright.dev`, so `playwright install` couldn't fetch a browser — since fixed by the pre-installed `/opt/pw-browsers` Chromium and `chromium_executable()` in [check_moto_test.py](check_moto_test.py). (2) July 2026: even with full network access, mvdis.gov.tw resets connections from the Claude cloud egress (foreign datacenter IP and/or proxy TLS fingerprint) — `net::ERR_CONNECTION_RESET` on both Chromium and plain curl, while ntfy.sh works fine. Nothing configurable inside the environment changes the egress, so cloud routines are a dead end for this site. GitHub Actions runners get through fine.

## Implementation notes

Non-obvious things in [check_moto_test.py](check_moto_test.py) that future-you (or future-Claude) will probably wonder about:

- **Headless soft-block bypass.** mvdis.gov.tw 302-loops requests whose `User-Agent` says `HeadlessChrome` or whose `sec-ch-ua` brand string mentions Chromium. The script spoofs both headers and launches with `--disable-blink-features=AutomationControlled`. Drop any of those and `goto` enters an infinite redirect chain that surfaces as `ERR_TOO_MANY_REDIRECTS` (or a goto timeout, depending on Chrome version).
- **`expectExamDateStr` must be filled.** Without an ROC date in `民國 YYYMMDD` format, the form submits but the server replies "查詢不到符合的考試場次" (no matching slots) for every station, regardless of actual availability. We fill it with today's ROC date for a forward-looking window.
- **Submit is a JS link, not a button.** The page has a Google Custom Search widget whose 搜尋 button comes up first in any `<button>` query — its click handler is unrelated. The form's actual submit is `<a class="std_btn" onclick="query();" href="#anchor">`.
- **Station list is hardcoded.** The 4 entries in `STATIONS` ([check_moto_test.py:42](check_moto_test.py:42)) are 臺北市 / 新北市 stations distilled from the live `dmvNoLv1` / `dmvNo` dropdowns. Refresh by re-running the discovery snippet in the commit history if the gov ever adds or renames stations.
- **`額滿` is a sentinel, not a count.** Sessions with no remaining seats render the literal Chinese for "full" in the seat column rather than `0`. The parser drops those rows so the notification only contains slots you could actually book.
- **Duplicate listings across license types are intentional.** A single calendar slot at e.g. 蘆洲 typically accepts both 普通重型機車 and 普通輕型機車 retest candidates and shows up under each query. Output is grouped per license type, so the same physical session appears twice — fine for now since the per-license heading tells you which path it counts toward.
