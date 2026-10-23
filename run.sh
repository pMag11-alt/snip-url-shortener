#!/usr/bin/env bash
# One-command local setup: creates a virtualenv, installs dependencies,
# loads demo data and starts the server on http://localhost:8000
set -euo pipefail
cd "$(dirname "$0")"

PYTHON=${PYTHON:-python3}
"$PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 11))' \
  || { echo "Snip needs Python 3.11 or newer (found $("$PYTHON" --version))." >&2; exit 1; }

[ -d .venv ] || "$PYTHON" -m venv .venv
.venv/bin/pip install --quiet --disable-pip-version-check -r requirements.txt
.venv/bin/python -m app.seed

echo "Snip running at http://localhost:${PORT:-8000}  (API docs at /docs)"
exec .venv/bin/uvicorn app.main:app --reload --port "${PORT:-8000}"
