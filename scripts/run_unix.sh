#!/usr/bin/env bash
# Sparta Gen — run from source on Linux / macOS (double-click run_macos.command on a Mac).
# First run creates a virtual environment and installs the engine, including ffmpeg (imageio-ffmpeg) when no
# system ffmpeg is present.  With Flutter installed (https://docs.flutter.dev/get-started/install) it starts
# the Sparta Gen app itself; without it, the classic web app opens in your browser.
set -e
cd "$(dirname "$0")/.."
PY="${PYTHON:-python3}"
if [ ! -d .venv ]; then
  echo "Creating virtual environment…"
  "$PY" -m venv .venv
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -e ".[all]"
fi
if command -v flutter >/dev/null 2>&1 && [ "${SPARTAGEN_WEB:-0}" != 1 ]; then
  device=linux
  [ "$(uname -s)" = Darwin ] && device=macos
  cd app
  SPARTAGEN_ENGINE="\"$(cd .. && pwd)/.venv/bin/python\" -m spartagen" exec flutter run -d "$device" --release "$@"
fi
echo "(Flutter is not installed: opening the classic web app in your browser instead.)"
exec .venv/bin/python -m spartagen gui "$@"
