# -*- coding: utf-8 -*-
"""Check that this GUI package is complete and runnable. No training."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FAIL = []


def check(name, cond, detail=""):
    print("[{}] {}{}".format("PASS" if cond else "FAIL", name,
                             ("  -> " + str(detail)[:150]) if detail else ""))
    if not cond:
        FAIL.append(name)


def main() -> int:
    print("package root:", ROOT)
    app = ROOT / "app"
    check("1. app/ exists", app.is_dir())
    for f in ("main.py", "gui.py", "vision.py", "task_manager.py",
              "robot_interface.py", "camera_interface.py", "config.py",
              "view_render.py", "imageio_util.py"):
        check("1b. app/{}".format(f), (app / f).is_file())

    model = ROOT / "weights" / "best.pt"
    check("2. weights/best.pt", model.is_file(),
          "{:,} bytes".format(model.stat().st_size) if model.is_file() else "missing")
    check("3. test_images", (ROOT / "test_images").is_dir(),
          len(list((ROOT / "test_images").glob("*.jpg"))))
    check("4. dataset/box_yolo/data.yaml", (ROOT / "dataset" / "box_yolo" / "data.yaml").is_file())
    check("5. requirements.txt", (ROOT / "requirements.txt").is_file())
    # NOTE: a local .venv is created by setup_env.bat, so on a fresh machine it
    # is legitimately missing. That is information, NOT a failure.
    venv_py = ROOT / ".venv" / "Scripts" / "python.exe"
    if venv_py.is_file():
        check("6. local .venv", True, str(venv_py))
    else:
        print("[INFO] 6. local .venv not created yet - run setup_env.bat "
              "first (expected on a fresh machine)")

    # imports
    try:
        import numpy, cv2  # noqa: F401
        check("7. numpy + opencv import", True,
              "numpy {}, cv2 {}".format(numpy.__version__, cv2.__version__))
    except Exception as exc:
        check("7. numpy + opencv import", False, exc)
    try:
        import PySide6  # noqa: F401
        from PySide6.QtWidgets import QApplication  # noqa: F401
        check("8. PySide6 import", True, PySide6.__version__)
    except Exception as exc:
        check("8. PySide6 import", False, exc)

    # model load (load only - never trains)
    try:
        from ultralytics import YOLO
        import torch
        m = YOLO(str(model))
        check("9. MODEL LOAD", True, "task={} names={} | cuda={}".format(
            getattr(m, "task", "?"), getattr(m, "names", "?"), torch.cuda.is_available()))
    except Exception as exc:
        check("9. MODEL LOAD", False, "{}: {}".format(type(exc).__name__, exc))

    print()
    print("VERIFY: {}".format("PASS" if not FAIL else "FAIL -> " + ", ".join(FAIL)))
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
