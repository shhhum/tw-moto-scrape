# tw-moto-scrape

A Playwright async scraper that checks [mvdis.gov.tw](https://www.mvdis.gov.tw/m3-emv-trn/exm/locations#) for motorcycle road-test (路考) slot availability in Taipei (台北) and New Taipei (新北), skipping the hazard-perception exam (危險感知).

## Local run

```bash
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
python3 check_moto_test.py
```

## Deploying as a Claude routine

Goal: run every 3 hours from 8am–8pm Taipei time and surface new slots.

How the runtime works (per [routines.md](https://code.claude.com/docs/en/routines.md) and [claude-code-on-the-web.md](https://code.claude.com/docs/en/claude-code-on-the-web.md)):

- Each run clones a **GitHub repo** fresh into an Anthropic-managed VM. Routines do not support local-bundle deploys (`claude --remote`'s upload path is one-off only).
- **No filesystem persistence between runs.** Each run starts from a clean clone — anything you want to keep has to be committed back to the repo or pushed to external storage. We're skipping state for now (every run just prints fresh).
- The runtime has Node.js + chromedriver pre-installed. **Playwright + Chromium are not** — install them via a setup script (cached) or a `SessionStart` hook (every run).

### 1. Pre-flight code changes

The current script is debug-shaped. Before scheduling, fix at minimum:

- **Switch to headless.** `headless=False` ([check_moto_test.py:23](check_moto_test.py:23)) needs `headless=True` — a routine has no display.
- **Pick an output sink.** Right now it only `print`s, which means logs in the routine run history. That's enough for now — every run will re-emit the same slots since we're not tracking state, but it's the simplest path. Wire up email/Slack/a webhook later if the noise gets old.
- **Confirm the scrape actually returns slots.** The script's own fallback message — *"The site may need manual interaction (e.g. clicking a city or exam type first)"* — is a hint that the selector pass at [check_moto_test.py:39](check_moto_test.py:39) may need to be preceded by clicks (city tab, exam type, date picker). Verify locally with `headless=True` before deploying; if it falls into the "no matching slots" branch, add interaction steps first.

### 2. Push to GitHub

Routines clone from a configured GitHub repo on every run, so:

```bash
git init
git add .claude .gitignore CLAUDE.md README.md check_moto_test.py requirements.txt
git commit -m "initial commit"
gh repo create tw-moto-scrape --private --source=. --push
```

### 3. Setup script

[.claude/setup.sh](.claude/setup.sh) installs the Python deps and Chromium. It's already in the repo and marked executable. Setup scripts run once and are cached across runs (see [environment caching](https://code.claude.com/docs/en/claude-code-on-the-web.md#environment-caching)), so the ~150 MB Chromium download only happens on the first run and whenever this script changes.

If you'd rather reinstall every session, swap to a [SessionStart hook](https://code.claude.com/docs/en/claude-code-on-the-web.md#install-dependencies-with-a-sessionsstart-hook).

### 4. Schedule

Cron expression for 08:00, 11:00, 14:00, 17:00, 20:00 Taipei time:

```
0 8-20/3 * * *   # timezone: Asia/Taipei
```

Equivalent to `0 8,11,14,17,20 * * *`. If the routine runtime is fixed to UTC, shift by 8 hours: `0 0,3,6,9,12 * * *`.

### 5. Create the routine

Use the `/schedule` slash command and supply:

- the GitHub repo from step 2,
- the cron + timezone from step 4,
- a prompt like the one below.

Example prompt:

> Run `python3 check_moto_test.py` from the repo root and report what it printed.
>
> - If the script lists road-test slots, summarise them in the response (city, date, time per line).
> - If the script falls through to its "no matching slots found" branch, just say "no slots this run" and do not investigate further.
> - If the script exits non-zero or throws, paste the last 30 lines of output and stop.
>
> Do not modify any files in the repo. This is a read-only scheduled run.

## Code weirdness — walkthrough

Things I'd flag while reading [check_moto_test.py](check_moto_test.py), roughly in order of impact:

1. **Headless flag is wrong for unattended runs.** [check_moto_test.py:23](check_moto_test.py:23) — covered above.
2. **Script never interacts with the page.** The docstring and the no-results branch both acknowledge the site likely needs a click-through (city tab → exam type → date) before slots render, but the code only does `goto` + `query_selector_all`. As written, this is a one-step scrape of a multi-step UI.
3. **No "road test only" positive filter.** Despite the print at [check_moto_test.py:71](check_moto_test.py:71) labeling the output as *"road test only"*, the filter chain at [check_moto_test.py:54-67](check_moto_test.py:54) is: skip-hazard → has-target-city → has-date-or-time. Nothing requires the text to mention 路考. Any non-hazard exam type with a Taipei address and a date will pass.
4. **Selector net is overly broad and produces duplicates.** [check_moto_test.py:39](check_moto_test.py:39) selects `a, button, li, tr, .exam-item, [class*='exam'], [class*='item']`. Nested matches (a `<tr>` containing matching `<a>`s) all read overlapping `inner_text`, so the same slot text is appended to `results` multiple times. There's no dedup before printing at [check_moto_test.py:72](check_moto_test.py:72).
5. **Always-on debug dump.** [check_moto_test.py:32-35](check_moto_test.py:32) prints the first 3000 chars of body text on every run. Fine for the first few iterations, noisy in a scheduled job. Gate behind a `--debug` flag or env var.
6. **`import re` inside the loop.** [check_moto_test.py:63](check_moto_test.py:63) — works, but it's an import on every iteration. Move to module top.
7. **Arbitrary 2s sleep after `networkidle`.** [check_moto_test.py:28](check_moto_test.py:28) — if `networkidle` was sufficient this is wasted time; if it wasn't, this is papering over a missing `wait_for_selector` and may still race on slow networks. Replace with a wait for a known result-table selector once you know what to look for.
8. **No error handling.** A timeout on `goto`, a Playwright launch failure, or a parsing exception will surface as an unhandled traceback. For a routine you'll want a top-level try/except that logs and exits non-zero so the runtime can surface failures.
9. **`asyncio.run(main())` at module top level.** [check_moto_test.py:84](check_moto_test.py:84) — works, but the conventional `if __name__ == "__main__":` guard is cheap and stops the script auto-running on import.
10. **`SKIP_KEYWORDS` redundancy.** [check_moto_test.py:17](check_moto_test.py:17) — `危感` and `危險感知` don't share a substring (different chars), so both entries are needed; just noting it's intentional, not a typo.
