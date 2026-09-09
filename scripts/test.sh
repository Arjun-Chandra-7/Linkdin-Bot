#!/usr/bin/env bash
# Run the backend test suite.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
PYTHON="${PYTHON:-$REPO_ROOT/.venv/bin/python}"
exec "$PYTHON" -m pytest "$@"
