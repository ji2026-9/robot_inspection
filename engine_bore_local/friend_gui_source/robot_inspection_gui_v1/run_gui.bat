@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] .venv not found. Please run setup_env.bat first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" "app\main.py"
if errorlevel 1 (
  echo.
  echo [ERROR] the GUI exited with an error. See the messages above.
  pause
)
