#!/bin/bash
set -euo pipefail

# Prepares a Claude Code on the web container to run the Playwright scraper.
# Local machines manage their own .venv, so this is a no-op outside the web env.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR"

# Idempotent: venv creation and pip/playwright installs are all safe to re-run.
python3 -m venv .venv
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r requirements.txt

# Chromium for Playwright. Needs outbound access to cdn.playwright.dev; if the
# environment's network policy blocks it this step fails and the scraper will
# report {"ok": false} at runtime — see README.md.
.venv/bin/playwright install --with-deps chromium
