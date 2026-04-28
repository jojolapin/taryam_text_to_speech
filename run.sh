#!/usr/bin/env bash
# ============================================================
#  TextSpeak Pro - macOS / Linux developer launcher
#  (C) 2026 JojoLapin Inc.
# ============================================================
set -eu

cd "$(dirname "$0")"

VENV="${VENV:-.venv}"

# Pick the best Python available
PY=""
for cand in python3.13 python3.12 python3.11 python3 python; do
  if command -v "$cand" >/dev/null 2>&1; then
    PY="$cand"; break
  fi
done
if [[ -z "${PY:-}" ]]; then
  echo "Python 3.11+ is required but was not found on PATH." >&2
  exit 1
fi

if [[ ! -x "$VENV/bin/python" ]]; then
  echo "Creating virtual environment ($PY)..."
  "$PY" -m venv "$VENV"
fi

VPY="$VENV/bin/python"

"$VPY" -m pip install --upgrade --quiet pip wheel
"$VPY" -m pip install --quiet -r requirements.txt

echo "Launching TextSpeak Pro..."
exec "$VPY" main.py "$@"
