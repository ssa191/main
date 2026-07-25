#!/usr/bin/env bash
# Convenience runner: creates a venv on first use, installs deps, and runs the
# scraper. Pass any subcommand/flags through, e.g. ./run.sh stats
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  python3 -m venv .venv
  ./.venv/bin/pip install --quiet --upgrade pip
  ./.venv/bin/pip install --quiet -r requirements.txt
fi

exec ./.venv/bin/python -m news_scraper "$@"
