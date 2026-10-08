"""Select bundled standalone Python when installed, or development venv."""
from pathlib import Path

BASE = Path(__file__).resolve().parent

def python_executable(labelme=False, windowless=False):
    environment = BASE / ('.labelme_env' if labelme else '.venv')
    name = 'pythonw.exe' if windowless else 'python.exe'
    standalone = environment / name
    return standalone if standalone.exists() else environment / 'Scripts' / name
