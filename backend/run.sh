#!/usr/bin/env bash
# One-command launcher: creates a virtualenv, installs deps, and starts the app.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

echo "Installing dependencies..."
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

echo "Starting Acme ERP on http://127.0.0.1:8000 ..."
echo "Open that URL in your browser. Log in with admin@acme.test / admin123"
exec uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
