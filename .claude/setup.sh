#!/usr/bin/env bash
# Setup script for Claude routine runs.
# Cached across runs (see https://code.claude.com/docs/en/claude-code-on-the-web.md#environment-caching),
# so heavy installs (Chromium ~150 MB) only happen on the first run or when this script changes.
set -euo pipefail

pip install -r requirements.txt
playwright install chromium
