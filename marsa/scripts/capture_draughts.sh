#!/usr/bin/env bash
# Phase 0 — daily live draught capture. Schedule this (cron / Routine).
# Every day it does not run is a day of Delta-draught that can never be recovered.
#
#   export DATALASTIC_API_KEY="..."   # or put it in ../.env
#   ./scripts/capture_draughts.sh                 # the six grain ports
#   ./scripts/capture_draughts.sh --max-pro 40    # cap the credit spend
#
# Example crontab (07:00 UTC daily), from the repo root:
#   0 7 * * *  cd /path/to/marsa && ./scripts/capture_draughts.sh >> out/capture.log 2>&1
set -euo pipefail
cd "$(dirname "$0")/.."
python -m marsa.draught_capture --ports mine "$@"
