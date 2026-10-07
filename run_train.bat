@echo off
chcp 65001 >nul
cd /d E:\robot_inspection
echo ==========================================
echo   YOLO11n-Seg 训练 (RTX 3050 Ti, 4GB)
echo ==========================================
"E:\robot_inspection\.venv\Scripts\python.exe" "E:\robot_inspection\scripts\train_seg.py" %*
echo.
echo 训练流程结束，返回码 %ERRORLEVEL%
pause
