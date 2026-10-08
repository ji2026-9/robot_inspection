# -*- coding: utf-8 -*-
"""
Headless self-test for GUI v1 (no training, read-only with respect to project data).
==================================================================================
Uses Qt's "offscreen" platform so the whole window can be constructed and driven
programmatically. It exercises exactly the same slots the buttons call, then
saves a window screenshot for visual verification.

Run:
    python app/selftest_headless.py
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtWidgets import QApplication  # noqa: E402

from config import EXPECTED_HOLES, MODEL_PATH, TEST_IMAGE_DIR  # noqa: E402
from gui import MainWindow  # noqa: E402

OUT = Path(__file__).resolve().parent / "selftest"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    app = QApplication(sys.argv)
    win = MainWindow()
    win.resize(1600, 950)
    win.show()
    app.processEvents()

    report = {"generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
              "model": str(MODEL_PATH),
              "expected_holes": EXPECTED_HOLES, "images": []}
    img_dir = Path(TEST_IMAGE_DIR)
    imgs = sorted([p for p in img_dir.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".bmp")])

    for p in imgs:
        entry = {"image": p.name}
        ok = win.load_image(str(p))
        entry["load_ok"] = ok
        if not ok:
            report["images"].append(entry)
            continue
        app.processEvents()

        # ---- AI auto detect ----
        win.rb_auto.setChecked(True)
        win.on_detect()
        app.processEvents()
        res = win.current_result
        entry["detections"] = res["detections"]
        entry["complete"] = res["complete"]
        entry["avg_conf"] = res["avg_conf"]
        entry["device_used"] = res["device_used"]
        entry["orientation_status"] = res["orientation_status"]
        entry["holes"] = [{"id": h["id"], "confidence": h["confidence"],
                           "center_px": h["center_px"]} for h in res["holes"]]
        entry["warnings"] = res.get("warnings", [])
        entry["errors"] = res.get("errors", [])
        # auto mode already created tasks inside on_detect()
        entry["tasks_created"] = [t["target_id"] for t in win.tasks.tasks]
        entry["run_dir_after_detect"] = str(win.last_run_dir)

        # ---- manual mode: try H03, then a target that may not exist ----
        win.rb_manual.setChecked(True)
        win.on_mode_changed()
        win.cmb_target.setCurrentText("H03")
        win.on_create_tasks()
        app.processEvents()
        entry["manual_H03"] = {"tasks": [t["target_id"] for t in win.tasks.tasks],
                               "table_rows": win.table.rowCount()}
        missing = [t for t in ("H01", "H02", "H03", "H04")
                   if t not in [h["id"] for h in res["holes"]]]
        if missing:
            win.cmb_target.setCurrentText(missing[0])
            win.on_create_tasks()
            app.processEvents()
            entry["manual_missing_target"] = {"target": missing[0],
                                              "tasks": [t["target_id"] for t in win.tasks.tasks]}

        # ---- simulated robot execution ----
        win.rb_auto.setChecked(True)
        win.on_create_tasks()
        app.processEvents()
        win.on_simulate()
        ticks = 0
        while win.exec_state.get("running") and ticks < 400:
            win.exec_step()
            app.processEvents()
            ticks += 1
        entry["after_simulate"] = [{"id": t["target_id"], "status": t["status"]}
                                   for t in win.tasks.tasks]
        entry["simulation_ticks"] = ticks
        entry["exec_label"] = win.lbl_exec.text()
        entry["robot_label"] = win.lbl_robot.text()
        entry["run_dir_after_simulate"] = str(win.last_run_dir)

        # ---- screenshot ----
        shot = OUT / "gui_{}.png".format(p.stem)
        win.grab().save(str(shot))
        entry["screenshot"] = str(shot)
        report["images"].append(entry)
        print("[{:<10}] 识别 {}/{}  complete={}  tasks={}  -> {}".format(
            p.name, res["detections"], EXPECTED_HOLES, res["complete"],
            entry["tasks_created"], shot.name))

    (OUT / "selftest_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n报告:", OUT / "selftest_report.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
