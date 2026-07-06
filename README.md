# tw-moto-scrape

A Playwright async scraper that checks [mvdis.gov.tw](https://www.mvdis.gov.tw/m3-emv-trn/exm/locations) for upcoming motorcycle road-test (路考) slots at Taipei (臺北市) and New Taipei (新北市) DMV stations. Runs hourly (8am–4pm) via launchd on a local Mac in Taiwan, targeting Banqiao 普通重型機車, and pushes a notification to ntfy.sh on every run — slots open, no slots, or error.

**Why local?** mvdis.gov.tw silently drops connections from datacenter IPs. GitHub Actions runners (Azure, US) time out on every query — verified in run logs from May 12 through July 6, 2026, every "successful" scheduled run was actually 8 timeouts reported as "no slots" — and Claude Code cloud environments get `ERR_CONNECTION_RESET` even with unrestricted egress. A Taiwan residential IP is the only origin that has ever worked.

## Local run

```bash
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
python3 check_moto_test.py
```

## Running on a schedule (macOS launchd — the actual deployment)

[run_check.sh](run_check.sh) runs the Banqiao 普通重型機車 check and pushes the result to ntfy on every run — slots found → high-priority "Banqiao slots OPEN" with the slot lines and booking link; none → "Banqiao check / no slots this hour"; scraper exit ≠ 0 → high-priority "Banqiao checker ERROR" with the output. Since every run notifies, silence unambiguously means the job didn't run. [launchd/com.twmoto.slotcheck.plist](launchd/com.twmoto.slotcheck.plist) schedules it hourly 08:00–16:00 local time.

Install (from the repo root, with `.venv` already set up per "Local run" above):

```bash
sed "s|__REPO__|$(pwd)|g" launchd/com.twmoto.slotcheck.plist > ~/Library/LaunchAgents/com.twmoto.slotcheck.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.twmoto.slotcheck.plist
```

Test immediately: `launchctl kickstart -k gui/$(id -u)/com.twmoto.slotcheck` (logs land in `/tmp/twmoto-slotcheck.log`).

Uninstall: `launchctl bootout gui/$(id -u)/com.twmoto.slotcheck && rm ~/Library/LaunchAgents/com.twmoto.slotcheck.plist`.

Caveats:

- **Sleep skips checks.** Fire times missed while the Mac sleeps coalesce into a single run on wake — lid closed all morning means no checks all morning.
- **Local timezone.** The plist schedules in the Mac's local time and assumes Asia/Taipei.
- **No state across runs.** Every run that finds slots fires a fresh notification; no dedupe against previous runs.

## GitHub Actions (manual runs only)

The workflow at [.github/workflows/scrape.yml](.github/workflows/scrape.yml) keeps the same check + always-notify logic behind `workflow_dispatch`, useful for testing the pipeline from the Actions tab. Its cron is deliberately removed: mvdis drops GH runner traffic, so scheduled runs could only ever produce timeout noise (or worse, the pre-July behavior — two months of green runs that were really 8 timeouts printed as "no slots").

### Push notifications via ntfy

The notify step is a single `curl` to [ntfy.sh](https://ntfy.sh) — no secrets, no account, no SMTP setup. Subscribe to the topic on your phone:

1. Install the [ntfy app](https://ntfy.sh/app) (iOS / Android / web).
2. Subscribe to topic `tw_moto_exams`.

ntfy topics are public-by-obscurity — anyone who knows the topic name can read or post to it. The motorcycle slot data isn't sensitive, but if you want to lock it down later, ntfy supports auth and self-hosted instances. Topic name is hardcoded in [run_check.sh](run_check.sh) and [.github/workflows/scrape.yml](.github/workflows/scrape.yml) — change it there + on your phone if you want a different one.

## Why not the cloud? (postmortem)

Three attempts, three walls — all variants of "mvdis doesn't talk to datacenters":

1. **Claude Code cloud routine, May 2026:** the routine env allowlist blocks `cdn.playwright.dev`, so `playwright install` couldn't fetch a browser. Since fixed by the pre-installed `/opt/pw-browsers` Chromium and `chromium_executable()` in [check_moto_test.py](check_moto_test.py) — but irrelevant given wall 3.
2. **GitHub Actions cron, May–July 2026:** every scheduled run "succeeded" while every query inside it timed out (`Page.goto` 60s timeouts / `ERR_CONNECTION_TIMED_OUT`) — verified in job logs back to May 12. The pre-July script had no failure semantics, so two months of runs printed "no slots" and exited 0. The cron is now removed; the failure-semantics fix (exit 1 + `ERROR:` line when every query fails) exists so this class of silent failure can't recur.
3. **Claude Code cloud routine, July 2026:** with browser fixed and full network egress, mvdis resets the connection (`net::ERR_CONNECTION_RESET` on both Chromium and plain curl) while ntfy.sh works fine — the block is on the egress IP / proxy fingerprint, not configuration.

Lesson: verify the scrape actually reached the site before trusting any green run. `額滿` for datacenters, apparently.

## Implementation notes

Non-obvious things in [check_moto_test.py](check_moto_test.py) that future-you (or future-Claude) will probably wonder about:

- **Headless soft-block bypass.** mvdis.gov.tw 302-loops requests whose `User-Agent` says `HeadlessChrome` or whose `sec-ch-ua` brand string mentions Chromium. The script spoofs both headers and launches with `--disable-blink-features=AutomationControlled`. Drop any of those and `goto` enters an infinite redirect chain that surfaces as `ERR_TOO_MANY_REDIRECTS` (or a goto timeout, depending on Chrome version).
- **`expectExamDateStr` must be filled.** Without an ROC date in `民國 YYYMMDD` format, the form submits but the server replies "查詢不到符合的考試場次" (no matching slots) for every station, regardless of actual availability. We fill it with today's ROC date for a forward-looking window.
- **Submit is a JS link, not a button.** The page has a Google Custom Search widget whose 搜尋 button comes up first in any `<button>` query — its click handler is unrelated. The form's actual submit is `<a class="std_btn" onclick="query();" href="#anchor">`.
- **Station list is hardcoded.** The 4 entries in `STATIONS` ([check_moto_test.py:42](check_moto_test.py:42)) are 臺北市 / 新北市 stations distilled from the live `dmvNoLv1` / `dmvNo` dropdowns. Refresh by re-running the discovery snippet in the commit history if the gov ever adds or renames stations.
- **`額滿` is a sentinel, not a count.** Sessions with no remaining seats render the literal Chinese for "full" in the seat column rather than `0`. The parser drops those rows so the notification only contains slots you could actually book.
- **Duplicate listings across license types are intentional.** A single calendar slot at e.g. 蘆洲 typically accepts both 普通重型機車 and 普通輕型機車 retest candidates and shows up under each query. Output is grouped per license type, so the same physical session appears twice — fine for now since the per-license heading tells you which path it counts toward.
