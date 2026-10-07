@echo off
chcp 65001 >nul
cd /d E:\robot_project\robot_inspection
"E:\robot_project\robot_inspection\.venv\Scripts\python.exe" "E:\robot_project\robot_inspection\scripts\check_dataset.py" %*
pause
