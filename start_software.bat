@echo off
cd /d "%~dp0"
if not exist "software\.venv\Scripts\python.exe" (
  echo Python environment missing. See docs\GETTING_STARTED_20261016.md
  pause
  exit /b 1
)
"software\.venv\Scripts\python.exe" "software\app.py"
if errorlevel 1 pause
