@echo off
rem Sparta Gen — run from source on Windows (needs Python 3.9+ from python.org).
rem First run creates a virtual environment and installs the engine, including ffmpeg (imageio-ffmpeg).
rem With Flutter installed (https://docs.flutter.dev/get-started/install) it starts the Sparta Gen app itself;
rem without it, the classic web app opens in your browser.
cd /d "%~dp0\.."
if not exist .venv (
  echo Creating virtual environment...
  py -3 -m venv .venv || python -m venv .venv
  .venv\Scripts\python -m pip install --upgrade pip
  .venv\Scripts\python -m pip install -e ".[all]"
)
where flutter >nul 2>nul
if %errorlevel%==0 if not "%SPARTAGEN_WEB%"=="1" (
  set SPARTAGEN_ENGINE="%CD%\.venv\Scripts\python.exe" -m spartagen
  cd app
  flutter run -d windows --release %*
  exit /b
)
echo (Flutter is not installed: opening the classic web app in your browser instead.)
.venv\Scripts\python -m spartagen gui %*
