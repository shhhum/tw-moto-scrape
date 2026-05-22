---
name: check-moto-slots
description: Check mvdis.gov.tw for motorcycle road-test (路考) slots in Taipei / New Taipei, push an ntfy notification only when genuinely new slots have appeared since the last run, and commit the dedupe state. Use this for the scheduled moto-slot check, or whenever asked to check for moto test slots.
---

# Check motorcycle road-test slots

Runs the Playwright scraper, diffs against the previous run, and notifies only
on *new* slots. Designed to run unattended on a schedule (every ~3h, 8am–8pm
Asia/Taipei), but works fine invoked by hand.

## Steps

1. **Run the scraper** from the repo root:

   ```bash
   .venv/bin/python check_moto_test.py
   ```

   It prints one JSON object to stdout and, on a successful scrape, rewrites
   `slot_state.json`. If `.venv` is missing the SessionStart hook did not run —
   create it once with `python3 -m venv .venv && .venv/bin/pip install -r
   requirements.txt && .venv/bin/playwright install --with-deps chromium`.

2. **Parse the JSON and branch on `ok`:**

   - **`ok: false`** — the scrape failed entirely (site down, network blocked,
     selectors broke). The state file was left untouched. Do **not** commit and
     do **not** send an ntfy notification. Report the `errors` array to the user
     and stop.
   - **`ok: true`** — continue.

3. **Notify only if `new_slots` is non-empty.** These are slots absent from the
   previous run. Compose a short, human-readable summary — group by station,
   one line per slot with date / seats / license — and POST it to ntfy:

   ```bash
   curl --fail-with-body \
     -H "Title: Motorcycle road-test slots — Taipei / New Taipei" \
     -H "Tags: motor_scooter" \
     -d "$SUMMARY" \
     https://ntfy.sh/tw_moto_exams
   ```

   If `new_slots` is empty, send nothing — that is the whole point of the
   dedupe. Still do step 4.

4. **Persist the dedupe state.** `slot_state.json` may have changed even with
   no new slots (a slot got booked / went full). The run container is
   ephemeral, so commit and push it or the next run loses the baseline:

   ```bash
   git add slot_state.json
   git commit -m "Update moto-slot state" && git push origin HEAD || \
     echo "no state change to commit"
   ```

5. **Report** one or two lines: new slots found (and that ntfy fired) / nothing
   new since last run / scrape failed. If `errors` is non-empty while
   `ok: true`, mention which stations timed out — it is non-fatal (the script
   carries their last-known slots forward) but worth surfacing.

## Notes

- **`errors` with `ok: true` is normal-ish.** One station can time out while
  the rest succeed; the script keeps that station's previous slots rather than
  treating them as gone. Don't fail the run over it.
- **Scheduling.** This skill does not schedule itself — create a scheduled
  session in the Claude Code web UI (cron `0 0,3,6,9,12 * * *` UTC = 8am–8pm
  Taipei every 3h) that runs this skill. Point that session at a fixed branch
  so `slot_state.json` commits accumulate on one line of history.
- **Network access required:** `cdn.playwright.dev` (browser download, hook
  time only), `mvdis.gov.tw` (the scrape), `ntfy.sh` (the notification). If the
  environment's network policy blocks any of these the run will fail — see
  README.md.
- **ntfy topic `tw_moto_exams`** is public-by-obscurity. To make it private,
  change it here and in the phone app together.
