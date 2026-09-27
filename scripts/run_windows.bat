@echo off
rem Sparta Gen — run from source on Windows (needs Python 3.9+ from python.org).
rem First run creates a virtual environment and installs everything, including ffmpeg (imageio-ffmpeg).
cd /d "%~dp0\.."
if not exist .venv (
  echo Creating virtual environment...
  py -3 -m venv .venv || python -m venv .venv
  .venv\Scripts\python -m pip install --upgrade pip
  .venv\Scripts\python -m pip install -e ".[all]"
)
.venv\Scripts\python -m spartagen gui %*
