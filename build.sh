#!/usr/bin/env bash
# ============================================================
#  TextSpeak Pro - macOS / Linux one-click build script
#  Produces dist/TextSpeakPro (the single-file app binary).
#  (C) 2026 JojoLapin Inc.
# ============================================================
set -eu

cd "$(dirname "$0")"

VENV="${VENV:-.venv-build}"

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
  echo "Creating build virtual environment ($PY)..."
  "$PY" -m venv "$VENV"
fi

VPY="$VENV/bin/python"

echo "Installing runtime + build dependencies..."
"$VPY" -m pip install --upgrade --quiet pip wheel
"$VPY" -m pip install --quiet -r requirements.txt -r requirements-build.txt

echo
echo "Building single-file executable (this takes 1-3 minutes)..."
echo
"$VPY" build_exe.py

echo
echo "Done. Artifacts in dist/:"
ls -lh dist/ 2>/dev/null || true
