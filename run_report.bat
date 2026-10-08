@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d E:\robot_project\robot_inspection
set "PYTHONIOENCODING=utf-8"

set "VENV=E:\robot_project\robot_inspection\.venv\Scripts\activate.bat"
set "SCRIPT1=E:\robot_project\robot_inspection\scripts\make_training_report.py"
set "SCRIPT2=E:\robot_project\robot_inspection\scripts\make_detection_report.py"
set "TR=E:\robot_project\robot_inspection\results\training_report.html"
set "DE=E:\robot_project\robot_inspection\results\detection_report.html"

echo ============================================================
echo   Generate visual reports  (NO training, NO model change)
echo   Training report  -^> %TR%
echo   Detection report -^> %DE%
echo ============================================================
echo.

if not exist "%VENV%" (
  echo [ERROR] Virtual env not found: %VENV%
  echo         Please create the .venv first.
  goto :fail
)
call "%VENV%"

echo [1/2] Building training report ...
python "%SCRIPT1%"
if errorlevel 1 (
  echo.
  echo [FAILED] Training report generation failed. See the error above.
  goto :fail
)
echo.

echo [2/2] Building detection report ...
python "%SCRIPT2%"
if errorlevel 1 (
  echo.
  echo [FAILED] Detection report generation failed. See the error above.
  goto :fail
)
echo.

echo ============================================================
echo   Done. Opening reports in your default browser ...
echo ============================================================
if exist "%TR%" (
  start "" "%TR%"
) else (
  echo [WARN] Not found: %TR%
)
if exist "%DE%" (
  start "" "%DE%"
) else (
  echo [WARN] Not found: %DE%
)
echo.
echo Training  report: %TR%
echo Detection report: %DE%
echo.
pause
exit /b 0

:fail
echo.
echo Report generation stopped. Nothing was trained and no model file was modified.
echo.
pause
exit /b 1
