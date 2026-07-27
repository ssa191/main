#!/usr/bin/env bash
# Phase 1 — historical backfill, current year first then working backwards.
# Resumable: every 7-day report ZIP is cached under out/raw/ and every call
# UPSERTs into SQLite, so re-running skips finished work and never duplicates.
#
#   export DATALASTIC_API_KEY="..."   # or put it in ../.env
#   ./scripts/run_backfill.sh                 # all years, newest -> oldest
#   ./scripts/run_backfill.sh 2026 2024       # only 2026, 2025, 2024
#
# Stop anytime (Ctrl-C or when you hit the monthly credit cap) and re-run — it
# continues where it left off. Run --estimate first; it spends nothing.
set -euo pipefail
cd "$(dirname "$0")/.."

START_YEAR="${1:-$(date +%Y)}"   # newest year to run (default: this year)
END_YEAR="${2:-2021}"            # oldest year to run (data floor is 2021-08-10)

echo "Estimating full scope first (no credits spent):"
python -m marsa.arrivals_pipeline --ports mine --from 2021-08-10 --to "$(date +%F)" --estimate

for (( y=START_YEAR; y>=END_YEAR; y-- )); do
  echo ""
  echo "================ YEAR $y ================"
  python -m marsa.arrivals_pipeline --ports mine --year "$y"
done

echo ""
echo "All requested years complete. Store: out/marsa.db  (CSV: out/ksa_arrivals.csv)"
