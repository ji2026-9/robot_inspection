@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] .venv not found. Please run setup_env.bat first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" "verify\verify_app.py"
pause
