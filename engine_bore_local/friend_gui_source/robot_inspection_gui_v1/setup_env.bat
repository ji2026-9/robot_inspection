@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo   Robot Vision Inspection GUI - environment setup
echo   (creates a local .venv and installs dependencies)
echo ============================================================
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python not found in PATH.
  echo         Please install Python 3.11 first: https://www.python.org/downloads/release/python-3119/
  echo         Remember to tick "Add python.exe to PATH" during installation.
  pause
  exit /b 1
)
python -c "import sys;print('Python',sys.version.split()[0])"

if not exist ".venv\Scripts\python.exe" (
  echo [1/3] Creating virtual environment .venv ...
  python -m venv .venv
  if errorlevel 1 ( echo [ERROR] failed to create .venv & pause & exit /b 1 )
) else (
  echo [1/3] .venv already exists, reusing it
)
set "PY=.venv\Scripts\python.exe"

echo [2/3] Upgrading pip ...
"%PY%" -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple --disable-pip-version-check

echo [3/3] Installing PyTorch and the rest ...
where nvidia-smi >nul 2>nul
if errorlevel 1 (
  echo   - No NVIDIA GPU detected: installing CPU build of PyTorch
  "%PY%" -m pip install torch torchvision -i https://pypi.tuna.tsinghua.edu.cn/simple
) else (
  echo   - NVIDIA GPU detected: installing CUDA 12.1 build of PyTorch
  "%PY%" -m pip install torch==2.5.1+cu121 torchvision==0.20.1+cu121 --index-url https://download.pytorch.org/whl/cu121
  if errorlevel 1 (
    echo   - CUDA build failed, falling back to CPU build
    "%PY%" -m pip install torch torchvision -i https://pypi.tuna.tsinghua.edu.cn/simple
  )
)
"%PY%" -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple --disable-pip-version-check
if errorlevel 1 ( echo [ERROR] dependency installation failed & pause & exit /b 1 )

echo.
echo [DONE] Environment ready.
echo        Double-click run_gui.bat to start the software.
echo        Run  verify\verify_app.py  to check everything.
pause
