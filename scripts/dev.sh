#!/usr/bin/env bash
# Start the backend for development.
#
#   ./scripts/dev.sh              # listen on all interfaces so the phone can reach it
#   ./scripts/dev.sh --local      # localhost only
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PYTHON="${PYTHON:-$REPO_ROOT/.venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
  echo "Creating virtualenv..."
  python3 -m venv .venv
  PYTHON="$REPO_ROOT/.venv/bin/python"
  "$PYTHON" -m pip install --quiet --upgrade pip
  "$PYTHON" -m pip install --quiet -r backend/requirements.txt
fi

HOST="0.0.0.0"
[[ "${1:-}" == "--local" ]] && HOST="127.0.0.1"
PORT="${PORT:-8787}"

if [[ ! -f .env ]]; then
  echo "No .env found; copying .env.example (offline mock provider, manual publishing)."
  cp .env.example .env
fi

echo "Backend on http://${HOST}:${PORT}  (API docs at /docs)"
echo "Pair a phone with:  $PYTHON scripts/pair.py"
PYTHONPATH="$REPO_ROOT/backend" exec "$PYTHON" -m uvicorn app.main:app --host "$HOST" --port "$PORT"
