# -*- coding: utf-8 -*-
"""
Full functional self-test for GUI v1 (offline, read-only w.r.t. project data).
=============================================================================
Covers: vision / camera / robot / task_manager / GUI slots + error paths.
Writes app/selftest/full_report.json and screenshots.
"""

import json
import os
import shutil
import sys
import tempfile
import traceback
from datetime import datetime
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

RES = []

IMG_PROBE = None


def probe(tag):
    """Diagnostic: is plain cv2.imread able to read the Chinese-path image here?"""
    global IMG_PROBE
    if IMG_PROBE is None:
        from config import TEST_IMAGE_DIR
        _l = sorted(Path(TEST_IMAGE_DIR).glob("*.jpg"))
        IMG_PROBE = _l[0] if _l else Path("missing.jpg")
    try:
        ok = cv2.imread(str(IMG_PROBE)) is not None
    except Exception as exc:
        ok = "ERR:{}".format(exc)
    print("   [probe] cv2.imread(中文路径) @ {:<22} -> {}".format(tag, ok))
    return ok


def check(name, cond, detail=""):
    RES.append({"test": name, "pass": bool(cond), "detail": str(detail)[:300]})
    print("[{}] {}{}".format("PASS" if cond else "FAIL", name,
                             ("  -> " + str(detail)[:160]) if detail else ""))
    return bool(cond)


def section(t):
    print("\n" + "=" * 72 + "\n" + t + "\n" + "=" * 72)


def main() -> int:
    HERE = Path(__file__).resolve().parent
    OUT = HERE / "selftest"
    OUT.mkdir(parents=True, exist_ok=True)
    probe("main() 开始")
    TMP = Path(tempfile.mkdtemp(prefix="gui_selftest_"))
    from config import TEST_IMAGE_DIR
    _imgs = sorted(Path(TEST_IMAGE_DIR).glob("*.jpg"))
    if len(_imgs) < 3:
        print("[错误] test_images 里至少有 3 张 jpg 才能跑这个自测")
        return 2
    IMG1, IMG3 = _imgs[0], _imgs[2]

    # ------------------------------------------------------------------ A) vision
    section("A) vision layer")
    import vision
    probe("import vision 之后")
    det = vision.HoleDetector()
    probe("HoleDetector() 之后")
    check("A1 model loads", det.load(), det.load_error or str(det.weights))
    probe("det.load() 之后")

    r1 = det.detect(IMG1)
    probe("det.detect(测试1) 之后")
    check("A2 detect 测试1 -> 4 holes", r1["detections"] == 4 and r1["complete"],
          "det=%s complete=%s avg=%s" % (r1["detections"], r1["complete"], r1["avg_conf"]))
    check("A3 holes have ids H01..H04", [h["id"] for h in r1["holes"]] == ["H01", "H02", "H03", "H04"])
    check("A4 device resolved", r1["device_used"] in ("0", "cpu"), r1["device_used"])

    r3 = det.detect(IMG3)
    # NOTE: how many holes 测试3 yields depends on the model. With fusion_v1 it is
    # 4/4; with the previous best.pt it was 3/4. Assert consistency, not a number.
    check("A5 detect 测试3 -> count/flags consistent",
          (r3["detections"] == 4 and r3["complete"]) or
          (r3["detections"] == 3 and not r3["complete"]),
          "det=%s complete=%s" % (r3["detections"], r3["complete"]))
    if r3["complete"]:
        check("A6 complete result: 4 holes, no 'incomplete' warning",
              len(r3["holes"]) == 4 and
              not any("检测不完整" in w for w in r3["warnings"]),
              r3["warnings"])
    else:
        check("A6 incomplete raises warning, no fake hole",
              any("检测不完整" in w for w in r3["warnings"]) and len(r3["holes"]) == 3,
              r3["warnings"])

    bad = det.detect(Path(TMP) / "nope.jpg")
    check("A7 missing file -> error, no exception", bool(bad["errors"]) and bad["detections"] == 0,
          bad["errors"])

    junk = Path(TMP) / "junk.jpg"
    junk.write_bytes(b"not an image at all")
    jr = det.detect(junk)
    check("A8 corrupt image -> error, no exception", bool(jr["errors"]), jr["errors"])

    det2 = vision.HoleDetector(Path(TMP) / "missing_model.pt")
    mr = det2.detect(IMG1)
    check("A9 missing model -> error, no exception", bool(mr["errors"]), mr["errors"])

    ann = vision.draw_result(cv2.imread(str(IMG1)), r1)
    check("A10 draw_result output shape", ann.shape[:2] == (4608, 2592), ann.shape)

    # regression: the reported ellipse triple must draw the fitted ellipse and the
    # reported fields must agree with each other.
    # NOTE: with ELLIPSE_FIT_MODE="robust_edge" the ellipse deliberately follows the
    # image aperture edge instead of the YOLO mask contour, so its residual against
    # the contour is larger than it used to be (measured worst 6.86%). The threshold
    # below therefore only catches a grossly wrong drawing - the historical bug was
    # swapping major/minor without rotating the angle (that measured 24% on 测试1 H04).
    worst_paired = worst_swapped = worst_field = 0.0
    modes_seen = set()

    def _draw_rms(e, pts, w, hgt, ang):
        t = np.linspace(0, 2 * np.pi, 720)
        a, b = w / 2.0, hgt / 2.0
        th = np.deg2rad(ang)
        px = e["center"][0] + a * np.cos(t) * np.cos(th) - b * np.sin(t) * np.sin(th)
        py = e["center"][1] + a * np.cos(t) * np.sin(th) + b * np.sin(t) * np.cos(th)
        poly = np.stack([px, py], axis=1)
        d = np.array([np.min(np.linalg.norm(poly - p, axis=1)) for p in pts])
        return float(np.sqrt((d ** 2).mean()) / max(1.0, min(a, b)) * 100)

    for img in sorted(Path(TEST_IMAGE_DIR).glob("*.jpg")):
        rr = det.detect(img)
        for h in rr["holes"]:
            e = h["ellipse"]
            pts = h["_contour"].reshape(-1, 2).astype(np.float64)
            modes_seen.add((h.get("ellipse_fit") or {}).get("used", "current"))
            worst_paired = max(worst_paired, _draw_rms(e, pts, e["width"], e["height"], e["angle"]))
            worst_swapped = max(worst_swapped, _draw_rms(e, pts, e["height"], e["width"], e["angle"]))
            lo, hi = min(e["width"], e["height"]), max(e["width"], e["height"])
            worst_field = max(worst_field,
                              abs(e["major"] - hi), abs(e["minor"] - lo),
                              abs(e["aspect"] - lo / hi),
                              abs(e["center"][0] - h["center_px"][0]),
                              abs(e["center"][1] - h["center_px"][1]))
    check("A11 ellipse geometry regression (draw RMS < 10%, fields consistent)",
          worst_paired < 10.0 and worst_field < 0.02,
          "paired=%.2f%% swapped=%.2f%% field_err=%.4f mode=%s" % (
              worst_paired, worst_swapped, worst_field, sorted(modes_seen)))

    # ------------------------------------------------------------------ B) camera
    section("B) camera layer")
    import camera_interface as cam
    c1 = cam.ImageFileCamera(IMG1)
    check("B1 file camera start", c1.start() and c1.get_frame() is not None)
    check("B2 file camera reports not connected (honest)", c1.is_connected() is False)
    c1.stop()
    check("B3 file camera stop -> no frame", c1.get_frame() is None)
    c2 = cam.ImageFileCamera(Path(TMP) / "missing.jpg")
    check("B4 file camera bad path -> start False", c2.start() is False and c2.get_frame() is None)
    c3 = cam.MockCamera()
    check("B5 mock camera", c3.start() and c3.get_frame() is not None and c3.is_connected() is False)
    check("B6 factory", isinstance(cam.create_camera(IMG1), cam.ImageFileCamera)
          and isinstance(cam.create_camera(prefer="mock"), cam.MockCamera))

    # ------------------------------------------------------------------ C) robot
    section("C) robot layer")
    import robot_interface as rb
    rob = rb.create_robot()
    check("C1 never claims connected", rob.is_connected() is False)
    check("C2 connect() refuses", rob.connect() is False)
    check("C3 move_to_target refuses", rob.move_to_target({"target_id": "H01"})["ok"] is False)
    check("C4 execute_measurement refuses",
          rob.execute_measurement({"target_id": "H01"})["ok"] is False)
    sim = rob.simulate_execute([{"target_id": "H%02d" % i} for i in (1, 2, 3)], delay=0.0)
    check("C5 simulate returns simulated_done", all(x["status"] == "simulated_done" for x in sim)
          and all(x["simulated"] for x in sim), len(sim))
    rob.stop()
    sim2 = rob.simulate_execute([{"target_id": "H01"}], delay=0.0)
    check("C6 stop() honoured", sim2[0]["status"] == "stopped")

    # ------------------------------------------------------------------ D) tasks
    section("D) task manager")
    import task_manager as tm
    tm.RESULTS_ROOT = TMP / "runs"          # keep the real results dir clean
    T = tm.TaskManager()
    a = T.create_auto_tasks(r1)
    check("D1 auto tasks (complete) -> 4 pending",
          a["ok"] and len(T.tasks) == 4 and all(t["status"] == "pending" for t in T.tasks))
    b = T.create_auto_tasks(r3)
    if r3["complete"]:
        check("D2 auto tasks (测试3 complete) -> 4 pending",
              b["ok"] and len(T.tasks) == 4, b["message"])
    else:
        check("D2 auto tasks (incomplete) refused", b["ok"] is False and T.tasks == [], b["message"])
    c = T.create_auto_tasks(None)
    check("D3 auto tasks (no result) refused", c["ok"] is False)
    T.create_auto_tasks(r1)
    d = T.create_manual_task(r1, "H03")
    check("D4 manual H03 found", d["ok"] and T.tasks[0]["target_id"] == "H03", d["message"])
    e = T.create_manual_task(r3, "H04" if not r3["complete"] else "H99")
    check("D5 manual missing target refused", e["ok"] is False and T.tasks == [], e["message"])
    f = T.create_manual_task(None, "H01")
    check("D6 manual without detection refused", f["ok"] is False)
    T.tasks = []
    check("D7 execute without tasks refused", T.mark_executed(rob)["ok"] is False)
    T.create_auto_tasks(r1)
    g = T.mark_executed(rob, simulate=False)
    check("D8 real execute refused (no robot)", g["ok"] is False and
          all(t["status"] == "pending" for t in T.tasks))
    h = T.mark_executed(rob, simulate=True)
    check("D9 simulate marks all done", h["ok"] and
          all(t["status"] == "simulated_done" for t in T.tasks))
    d1, p1 = T.save_run(r1, ann)
    d2, p2 = T.save_run(r1, ann)
    check("D10 save_run writes json+image", (d1 / "detection.json").is_file() and
          p1["result_image"] and Path(p1["result_image"]).is_file())
    check("D11 save_run never overwrites", d1 != d2 and d1.is_dir() and d2.is_dir(),
          "{} vs {}".format(d1.name, d2.name))
    j = json.loads((d1 / "detection.json").read_text(encoding="utf-8"))
    check("D12 saved json has required keys",
          all(k in j for k in ("source_image", "holes", "orientation_status", "tasks")))
    check("D13 saved json has no private keys",
          all(not k.startswith("_") for h in j["holes"] for k in h))

    # ------------------------------------------------------------------ E) GUI
    section("E) GUI slots")
    from PySide6.QtWidgets import QApplication
    probe("import PySide6 之后")
    from gui import MainWindow
    app = QApplication.instance() or QApplication(sys.argv)
    probe("QApplication 之后")
    win = MainWindow()
    win.resize(1600, 950)
    win.show()
    app.processEvents()
    check("E1 window title", "机械臂智能视觉检测系统" in win.windowTitle(), win.windowTitle())
    check("E2 initial table empty & robot unconnected",
          win.table.rowCount() == 0 and "未连接" in win.lbl_robot.text())

    win.on_detect()
    check("E3 detect without image -> no crash", True)
    check("E4 load bad path returns False", win.load_image(str(Path(TMP) / "x.jpg")) is False)
    check("E5 load 测试1 ok", win.load_image(str(IMG1)) is True)
    check("E6 image info updated", "测试1" in win.image_info.text(), win.image_info.text())

    win.rb_auto.setChecked(True)
    win.on_detect()
    app.processEvents()
    check("E7 detect 测试1 -> 4 holes shown", win.current_result["detections"] == 4)
    check("E8 auto tasks created", win.table.rowCount() == 4 and len(win.tasks.tasks) == 4)
    check("E9 status shows 检测完成", "检测完成" in win.lbl_system.text(), win.lbl_system.text())
    check("E10 hole checklist all ticked", win.lbl_holes.text().count("✓") == 4, win.lbl_holes.text())
    win.grab().save(str(OUT / "full_gui_测试1.png"))

    win.rb_manual.setChecked(True)
    win.on_mode_changed()
    check("E11 manual mode enables combo", win.cmb_target.isEnabled() is True)
    win.cmb_target.setCurrentText("H03")
    win.on_create_tasks()
    check("E12 manual H03 -> 1 task", win.table.rowCount() == 1 and
          win.tasks.tasks[0]["target_id"] == "H03")
    check("E12b button label names the manual target", "H03" in win.btn_create.text(),
          win.btn_create.text())
    check("E12c create-task button visible in manual mode", win.btn_create.isVisible() is True)
    win.on_execute()
    check("E13 execute refused -> status text", "未连接" in win.lbl_exec.text(), win.lbl_exec.text())
    win.on_simulate()
    steps = 0
    while win.exec_state.get("running") and steps < 400:
        win.exec_step()
        app.processEvents()
        steps += 1
    check("E14 simulate -> completed rows",
          all(t["status"] == "simulated_done" for t in win.tasks.tasks) and
          "模拟执行完成" in win.lbl_exec.text(),
          "ticks=%d exec=%s" % (steps, win.lbl_exec.text()))
    check("E14b simulation drew a visible overlay (order/done kept)",
          win.exec_state["active"] is True and len(win.exec_state["done"]) == len(win.tasks.tasks)
          and win.exec_state["probe"] is not None,
          "done=%s probe=%s" % (win.exec_state["done"], win.exec_state["probe"]))
    check("E14c progress bar reached the end",
          win.prog_exec.value() == win.prog_exec.maximum(), win.prog_exec.value())
    check("E15 robot label still 未连接", "未连接" in win.lbl_robot.text())
    before = [t["status"] for t in win.tasks.tasks]
    win.on_create_tasks()
    check("E15b re-generating tasks does not wipe execution status",
          [t["status"] for t in win.tasks.tasks] == before, before)
    win.rb_auto.setChecked(True)
    win.on_mode_changed()
    check("E15c button label reflects auto mode", "4 孔" in win.btn_create.text(),
          win.btn_create.text())
    check("E15d create-task button hidden in auto mode", win.btn_create.isVisible() is False,
          "visible=%s" % win.btn_create.isVisible())

    win.load_image(str(IMG3))
    win.rb_auto.setChecked(True)
    win.on_detect()
    app.processEvents()
    n3 = win.current_result["detections"]
    check("E16 测试3 -> hole count matches completeness flag",
          (n3 == 4) == bool(win.current_result["complete"]), "det=%s" % n3)
    if n3 == 4:
        check("E17 auto mode -> 4 tasks",
              win.table.rowCount() == 4 and len(win.tasks.tasks) == 4,
              "rows=%s tasks=%s" % (win.table.rowCount(), len(win.tasks.tasks)))
        check("E18 status shows complete",
              "不完整" not in win.lbl_system.text(), win.lbl_system.text())
    else:
        check("E17 no tasks for incomplete", win.table.rowCount() == 0 and win.tasks.tasks == [])
        check("E18 status shows incomplete", "不完整" in win.lbl_system.text(), win.lbl_system.text())
    check("E18b previous run status cleared on new image",
          "等待机器人连接" in win.lbl_exec.text() and win.prog_exec.value() == 0,
          "exec=%s prog=%s" % (win.lbl_exec.text(), win.prog_exec.value()))
    win.grab().save(str(OUT / "full_gui_测试3.png"))

    win.rb_manual.setChecked(True)
    win.on_mode_changed()
    win.cmb_target.setCurrentText("H04")
    win.on_create_tasks()
    if n3 == 4:
        check("E19 manual existing H04 -> 1 row",
              win.table.rowCount() == 1 and win.tasks.tasks[0]["target_id"] == "H04")
    else:
        check("E19 manual missing H04 -> empty", win.table.rowCount() == 0)

    win.chk_fit.setChecked(False)
    win.chk_fit.setChecked(True)
    for z in (100, 200, 400, 130):
        win.sld_zoom.setValue(z)
        app.processEvents()
    check("E20 zoom slider all values ok", win.sld_zoom.value() == 130, win.lbl_zoom.text())
    win.resize(1200, 800)
    app.processEvents()
    check("E21 resize re-render ok", True)
    # re-create tasks on a complete detection before exporting
    win.load_image(str(IMG1))
    win.rb_auto.setChecked(True)
    win.on_detect()
    app.processEvents()
    check("E21b engine label shows GPU/CPU + time",
          ("GPU" in win.lbl_engine.text() or "CPU" in win.lbl_engine.text())
          and "耗时" in win.lbl_engine.text(), win.lbl_engine.text())
    win.on_save()
    check("E22 save button ok", True)
    win.on_export_csv()
    csvs = sorted(Path(win.last_run_dir).glob("tasks*.csv")) if win.last_run_dir else []
    check("E22b export tasks csv", bool(csvs), csvs[0] if csvs else "-")
    win.on_export_csv()
    csvs2 = sorted(Path(win.last_run_dir).glob("tasks*.csv")) if win.last_run_dir else []
    check("E22b2 second export does not overwrite", len(csvs2) == len(csvs) + 1,
          [c.name for c in csvs2])
    # camera abstraction actually used by the GUI
    check("E22c GUI uses camera layer",
          getattr(win, "camera", None) is not None and win.camera.source_path is not None,
          getattr(getattr(win, "camera", None), "source_path", None))
    logs = win.logbox.toPlainText()
    check("E23 log has content", len(logs.splitlines()) > 5, "%d lines" % len(logs.splitlines()))
    win.close()
    check("E24 window closes cleanly", True)

    # ------------------------------------------------------------------ report
    # ---- cold-start regression (must run in a FRESH process: the GUI has to
    #      read a photo before ultralytics is ever imported) ----
    section("F) cold-start regression (fresh process)")
    import subprocess
    cold = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parent / "selftest_coldstart.py")],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=dict(os.environ, QT_QPA_PLATFORM="offscreen"))
    tail = "\n".join([l for l in (cold.stdout or "").splitlines() if l.strip()][-7:])
    check("F1 cold-start test passes", cold.returncode == 0, tail.replace("\n", " | "))

    npass = sum(1 for r in RES if r["pass"])
    summary = {"generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
               "total": len(RES), "passed": npass,
               "failed": [r for r in RES if not r["pass"]], "results": RES}
    (OUT / "full_report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
    print("\n" + "=" * 72)
    print("TOTAL {} / {} passed".format(npass, len(RES)))
    if summary["failed"]:
        print("FAILED:")
        for f in summary["failed"]:
            print("  - {}  {}".format(f["test"], f["detail"]))
    print("report:", OUT / "full_report.json")
    shutil.rmtree(TMP, ignore_errors=True)
    return 0 if npass == len(RES) else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(2)
