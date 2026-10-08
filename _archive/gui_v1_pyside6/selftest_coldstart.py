# -*- coding: utf-8 -*-
"""
Cold-start regression test.

Reproduces the REAL user flow that the main self-test missed:
    1. start the GUI,
    2. pick a photo        <-- image is read HERE, before YOLO is loaded,
    3. only then run detection.

Historically step 2 failed for every non-ASCII path because cv2.imread behaves
differently before/after ultralytics is imported. This test must pass WITHOUT
importing ultralytics first.
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent))

FAILS = []


def check(name, cond, detail=""):
    print("[{}] {}{}".format("PASS" if cond else "FAIL", name,
                             ("  -> " + str(detail)[:160]) if detail else ""))
    if not cond:
        FAILS.append(name)
    return bool(cond)


def main() -> int:
    import cv2  # noqa: F401

    # Guard: this test only means something if ultralytics has NOT been imported.
    if "ultralytics" in sys.modules or "torch" in sys.modules:
        print("[WARN] ultralytics/torch already imported - cold-start guarantee weakened")

    from PySide6.QtWidgets import QApplication
    from gui import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()          # detector is lazy: model NOT loaded yet
    win.show()
    app.processEvents()

    check("C0 detector not loaded yet", win.detector._model is None)

    from config import TEST_IMAGE_DIR
    test_dir = Path(TEST_IMAGE_DIR)
    ok = 0
    total = 0
    for p in sorted(test_dir.glob("*.jpg")):
        total += 1
        if win.load_image(str(p)):
            ok += 1
        else:
            print("      failed:", p)
    check("C1 cold-start load all test images", ok == total, "{}/{}".format(ok, total))

    tmp = Path(tempfile.mkdtemp(prefix="cold_"))
    cn_dir = tmp / "中文目录"
    cn_dir.mkdir(parents=True, exist_ok=True)
    jpg = cn_dir / "照片副本.jpg"
    png = cn_dir / "截图.png"
    shutil.copy2(sorted(test_dir.glob("*.jpg"))[0], jpg)
    frame = win.camera.get_frame()
    from imageio_util import imwrite_unicode
    imwrite_unicode(png, frame)
    check("C2 cold-start load chinese-dir jpg", win.load_image(str(jpg)))
    check("C3 cold-start load chinese-dir png", win.load_image(str(png)))

    ascii_dir = tmp / "ascii"
    ascii_dir.mkdir(exist_ok=True)
    a = ascii_dir / "plain.jpg"
    shutil.copy2(sorted(test_dir.glob("*.jpg"))[0], a)
    check("C4 cold-start load ascii path", win.load_image(str(a)))

    check("C5 camera layer used", win.camera.source_path == str(a), win.camera.source_path)

    # now detection still works after all that
    win.on_detect()
    app.processEvents()
    check("C6 detect after cold loads",
          win.current_result is not None and win.current_result["detections"] == 4,
          "det=%s" % (win.current_result or {}).get("detections"))

    win.close()
    shutil.rmtree(tmp, ignore_errors=True)
    print()
    print("COLD-START: {}".format("PASS" if not FAILS else "FAIL -> " + ", ".join(FAILS)))
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
