#!/usr/bin/env bash
# Sparta Gen — run from source on Linux / macOS (double-click run_macos.command on a Mac).
# First run creates a virtual environment and installs everything, including ffmpeg (imageio-ffmpeg)
# when no system ffmpeg is present.
set -e
cd "$(dirname "$0")/.."
PY="${PYTHON:-python3}"
if [ ! -d .venv ]; then
  echo "Creating virtual environment…"
  "$PY" -m venv .venv
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -e ".[all]"
fi
exec .venv/bin/python -m spartagen gui "$@"
