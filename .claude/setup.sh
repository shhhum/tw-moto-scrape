#!/usr/bin/env bash
# Canonical setup commands for the Claude routine cloud environment.
# Paste the body below into the cloud env's Setup script field — see README step 3.
set -euo pipefail

pip install -r requirements.txt
playwright install chromium
