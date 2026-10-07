# -*- coding: utf-8 -*-
"""
Global configuration: paths / detection params / constants.
All paths live here so camera and robot backends can be swapped later.
This module only defines constants and never touches project data.
"""

from pathlib import Path


def _resolve_project_root() -> Path:
    """Works both on the dev machine and on a friend's machine.

    If this app/ folder sits next to weights/, test_images/ and dataset/
    (i.e. inside a delivery package), use that folder as the project root.
    Otherwise fall back to the original development path.
    """
    here = Path(__file__).resolve().parent          # .../app
    candidate = here.parent                          # .../package root
    if (candidate / "weights" / "best.pt").is_file():
        return candidate
    if (candidate / "test_images").is_dir():
        return candidate
    return Path(r"E:\robot_inspection")


# ---------- project paths ----------
PROJ = _resolve_project_root()
MODEL_PATH = PROJ / "weights" / "best.pt"
TEST_IMAGE_DIR = PROJ / "test_images"
RESULTS_ROOT = PROJ / "results" / "gui_runs"
APP_DIR = PROJ / "app"
DATASET_YAML = PROJ / "dataset" / "box_yolo" / "data.yaml"

# ---------- model / detection ----------
CLASS_NAME = "cylinder_bore"
EXPECTED_HOLES = 4
IMGSZ = 640
CONF = 0.50
IOU = 0.70
DEVICE_PREFERENCE = ["0", "cpu"]

# ---------- numbering ----------
ORIENTATION_STATUS = "uncertain"
ORIENTATION_METHOD = "pca_current_image"
ORIENTATION_NOTE = ("当前编号：基于当前图像几何排序（PCA），非永久物理身份；"
                    "180 度旋转下 H01/H04 可能对调。")

# ---------- robot ----------
ROBOT_MODE = "mock"

# ---------- misc ----------
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".bmp")
WINDOW_TITLE = "机械臂智能视觉检测系统"
APP_VERSION = "v1.0"
