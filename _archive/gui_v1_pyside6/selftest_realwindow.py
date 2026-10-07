# -*- coding: utf-8 -*-
"""
Drive the REAL GUI (real platform plugin, real fonts) end to end, with screenshots.

Run:  python app/selftest_realwindow.py
It opens the window briefly, performs the full user flow (load image, detect,
simulate, manual H03), saves screenshots and exits.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

OUT = Path(__file__).resolve().parent / "selftest"
STEPS = []


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    from gui import MainWindow
    from main import pick_cjk_font

    app = QApplication(sys.argv)
    app.setFont(pick_cjk_font())
    win = MainWindow()
    win.resize(1600, 950)
    win.show()

    def shot(tag):
        app.processEvents()
        p = OUT / "real_{}.png".format(tag)
        win.grab().save(str(p))
        STEPS.append((tag, str(p)))
        print("  截图:", p.name)

    def run():
        from config import TEST_IMAGE_DIR
        img_dir = Path(TEST_IMAGE_DIR)
        for i, p in enumerate(sorted(img_dir.glob("*.jpg")), 1):
            print("\n>>> [{}] {}".format(i, p.name))
            ok = win.load_image(str(p))
            print("    选择图片:", "成功" if ok else "失败")
            if not ok:
                print("    !! 读取失败，这是必须修的问题")
                continue
            win.rb_auto.setChecked(True)
            win.on_detect()
            app.processEvents()
            r = win.current_result
            print("    检测: {}/{}  完整={}  平均置信度={}  设备={}".format(
                r["detections"], r["expected"], r["complete"], r["avg_conf"], r["device_used"]))
            print("    任务表行数:", win.table.rowCount())
            print("    状态栏:", win.lbl_system.text())
            win.on_simulate()
            ticks = 0
            while win.exec_state.get("running") and ticks < 400:
                win.exec_step()
                app.processEvents()
                ticks += 1
                time.sleep(0.06)          # let the animation be visible on screen
            print("    模拟执行后:", win.lbl_exec.text())
            for t in win.tasks.tasks:
                print("      {} -> {}".format(t["target_id"], t["status"]))
            shot(p.stem)

        print("\n>>> 手动模式：选择 H03")
        win.load_image(str(sorted(img_dir.glob("*.jpg"))[0]))
        win.rb_auto.setChecked(True)
        win.on_detect()
        win.rb_manual.setChecked(True)
        win.on_mode_changed()
        win.cmb_target.setCurrentText("H03")
        win.on_create_tasks()
        app.processEvents()
        print("    任务表行数:", win.table.rowCount(),
              "| 任务:", [t["target_id"] for t in win.tasks.tasks])
        shot("manual_H03")
        win.close()
        app.quit()

    QTimer.singleShot(600, run)
    app.exec()
    print("\n实际窗口流程完成，共 {} 张截图".format(len(STEPS)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
