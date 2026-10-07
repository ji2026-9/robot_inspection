@echo off
chcp 65001 >nul
cd /d E:\robot_project\robot_inspection
echo ==========================================
echo   孔位检测 + 椭圆拟合 + PCA 编号
echo ==========================================
"E:\robot_project\robot_inspection\.venv\Scripts\python.exe" "E:\robot_project\robot_inspection\scripts\predict_holes.py" %*
echo.
echo 检测流程结束，返回码 %ERRORLEVEL%
pause
