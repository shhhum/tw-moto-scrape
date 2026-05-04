# tw-moto-scrape

A Playwright async scraper that checks [mvdis.gov.tw](https://www.mvdis.gov.tw/m3-emv-trn/exm/locations#) for motorcycle road-test (路考) slot availability in Taipei (台北) and New Taipei (新北), skipping the hazard-perception exam (危險感知).

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
- Also exposes `workflow_dispatch` so you can run it on-demand from the Actions tab — useful while you're iterating on selectors.
- Sets up Python 3.12 with pip cache, installs `requirements.txt`, runs `playwright install --with-deps chromium`, then executes the script.

### Caveats

- **Schedule is best-effort.** GitHub-cron jobs can be delayed by up to ~15 min during peak load. Fine for a 3-hour cadence; not fine if you need minute-level precision.
- **Inactive-repo pause.** If you don't push for 60 days, GitHub auto-pauses scheduled workflows. Any commit reactivates them.
- **Output goes to the run log only.** Every run re-prints all matching slots since we're not tracking state — wire up a Slack/webhook step after the script if the re-prints get noisy.
- **Free-tier is plenty.** 5 runs/day × ~2 min/run ≈ 5 hours/month, against 2,000 min/month free for private repos (unlimited for public).

### Why not Claude routines?

Tried it; the routine env's outbound allowlist blocks `cdn.playwright.dev`, so `playwright install` can't fetch the Chromium-for-Testing binary that Python Playwright 1.59 expects. Hosted-browser MCPs (Browserbase et al.) would work but cost ~$10/mo and require rewriting the script as a prompt. GitHub Actions has no allowlist, runs the script as-is, and is free at this volume.

### Future enhancements (not done yet)

- `actions/upload-artifact@v4` with `if: failure()` to attach `mvdis_screenshot.png` from the no-results branch.
- A second step that greps the script's output for slot lines and POSTs them to a Slack incoming-webhook (only fires on hits, so the cadence is silent unless something matches).
- Cache the Playwright browser binaries between runs (Chromium is the bulk of the install time).

## Code weirdness — walkthrough

Things I'd flag while reading [check_moto_test.py](check_moto_test.py), roughly in order of impact:

1. **Headless flag.** [check_moto_test.py:23](check_moto_test.py:23) is `headless=True` — correct for the GH Actions runner (no display). Toggle to `False` only when running locally and you want to watch the browser.
2. **Script never interacts with the page.** The docstring and the no-results branch both acknowledge the site likely needs a click-through (city tab → exam type → date) before slots render, but the code only does `goto` + `query_selector_all`. As written, this is a one-step scrape of a multi-step UI.
3. **No "road test only" positive filter.** Despite the print at [check_moto_test.py:71](check_moto_test.py:71) labeling the output as *"road test only"*, the filter chain at [check_moto_test.py:54-67](check_moto_test.py:54) is: skip-hazard → has-target-city → has-date-or-time. Nothing requires the text to mention 路考. Any non-hazard exam type with a Taipei address and a date will pass.
4. **Selector net is overly broad and produces duplicates.** [check_moto_test.py:39](check_moto_test.py:39) selects `a, button, li, tr, .exam-item, [class*='exam'], [class*='item']`. Nested matches (a `<tr>` containing matching `<a>`s) all read overlapping `inner_text`, so the same slot text is appended to `results` multiple times. There's no dedup before printing at [check_moto_test.py:72](check_moto_test.py:72).
5. **Always-on debug dump.** [check_moto_test.py:32-35](check_moto_test.py:32) prints the first 3000 chars of body text on every run. Fine for the first few iterations, noisy in a scheduled job. Gate behind a `--debug` flag or env var.
6. **`import re` inside the loop.** [check_moto_test.py:63](check_moto_test.py:63) — works, but it's an import on every iteration. Move to module top.
7. **Arbitrary 2s sleep for content to settle.** [check_moto_test.py:27-28](check_moto_test.py:27) `goto` waits for `domcontentloaded` (was `networkidle`, which never completed on this site — analytics/long-poll keeps the network alive); the next line then sleeps 2s for JS to populate the DOM. This is a fragile heuristic. Replace with `wait_for_selector("<known result-table element>")` once we know what reliably indicates the slot list has rendered.
8. **No error handling.** A timeout on `goto`, a Playwright launch failure, or a parsing exception surfaces as an unhandled traceback. Fine for now — GH Actions marks the run failed and emails the repo admin. If you add a Slack/webhook notifier later, wrap the body in a try/except so transient failures still produce a clean message instead of a stack trace.
9. **`asyncio.run(main())` at module top level.** [check_moto_test.py:84](check_moto_test.py:84) — works, but the conventional `if __name__ == "__main__":` guard is cheap and stops the script auto-running on import.
10. **`SKIP_KEYWORDS` redundancy.** [check_moto_test.py:17](check_moto_test.py:17) — `危感` and `危險感知` don't share a substring (different chars), so both entries are needed; just noting it's intentional, not a typo.
