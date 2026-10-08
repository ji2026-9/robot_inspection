@echo off
chcp 65001 >nul
cd /d E:\robot_project\robot_inspection
echo ============================================================
echo   Robot Vision Inspection System  (GUI v1)
echo   Model : E:\robot_project\robot_inspection\weights\best.pt
echo ============================================================
"E:\robot_project\robot_inspection\.venv\Scripts\python.exe" "E:\robot_project\robot_inspection\app\main.py" %*
echo.
echo GUI exited with code %ERRORLEVEL%
pause
