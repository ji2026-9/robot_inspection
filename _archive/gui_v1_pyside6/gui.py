# -*- coding: utf-8 -*-
"""
GUI layer (PySide6).
====================
Contains no YOLO code and no robot code - it only talks to:
    vision.HoleDetector        (detection)
    task_manager.TaskManager   (task creation / saving)
    robot_interface.MockRobot  (simulated execution)

This separation keeps the GUI replaceable when a camera / real robot arrives.
"""

from pathlib import Path

import cv2
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog,
                               QCheckBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
                               QDialog, QMainWindow, QPlainTextEdit, QPushButton, QSlider,
                               QProgressBar, QRadioButton, QSizePolicy, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)
from PySide6.QtGui import QKeySequence, QShortcut

from camera_interface import create_camera
from config import (APP_VERSION, CONF, EXPECTED_HOLES, IMGSZ, MODEL_PATH,
                    RESULTS_ROOT, TEST_IMAGE_DIR, WINDOW_TITLE)
from robot_interface import create_robot
from task_manager import TaskManager
from view_render import compose, holes_bbox, overlay_annotations, overlay_execution, zoom_rect
from vision import HoleDetector, draw_result, imread_unicode


def bgr_to_pixmap(bgr):
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    h, w, ch = rgb.shape
    img = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888)
    return QPixmap.fromImage(img.copy())


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("{} {}".format(WINDOW_TITLE, APP_VERSION))
        self.resize(1500, 900)

        self.detector = HoleDetector()
        self.tasks = TaskManager()
        self.robot = create_robot()
        self.camera = create_camera()          # swap here for an industrial camera
        self.last_dir = str(TEST_IMAGE_DIR)

        self.current_image_path = None
        self.current_bgr = None
        self.current_result = None
        self.annotated = None
        self.display_photo = None
        self.display_crop = None
        self.last_run_dir = None
        self.task_signature_done = None      # what mode+result produced the current tasks
        self.detection_seq = 0               # increments on every detection run
        # simulated-robot animation state
        self.exec_state = {"active": False, "order": [], "done": [], "current": None,
                           "probe": None, "phase": "idle", "tick": 0, "idx": 0, "from": None}
        self.exec_timer = QTimer(self)
        self.exec_timer.setInterval(320)
        self.exec_timer.timeout.connect(self.exec_step)

        self._build_ui()
        self.log("系统启动完成。模型: {}".format(MODEL_PATH))
        self.log("机器人：未连接（当前版本只有模拟接口）")
        self.log("工作模式：AI 自动检测（默认）")
        self.set_status("系统就绪", "#16a34a")

    # ------------------------------------------------------------- UI build
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        title = QLabel(WINDOW_TITLE)
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size:24px;font-weight:700;padding:10px;color:#1e3a8a;")
        root.addWidget(title)

        mid = QHBoxLayout()
        root.addLayout(mid, stretch=1)

        # ---------------- left: image ----------------
        left = QGroupBox("视觉检测区")
        lv = QVBoxLayout(left)
        self.image_label = QLabel("请选择图片（默认目录：test_images）")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setMinimumSize(640, 480)
        self.image_label.setStyleSheet(
            "background:transparent;color:#9ca3af;border-radius:10px;")
        self.image_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        lv.addWidget(self.image_label)
        info_row = QHBoxLayout()
        self.image_info = QLabel("未选择图片")
        self.image_info.setStyleSheet("color:#6b7280;font-size:12px;")
        self.chk_fit = QCheckBox("适应工件（检测后自动放大到孔区域）")
        self.chk_fit.setChecked(True)
        self.chk_fit.setStyleSheet("font-size:12px;")
        self.chk_fit.toggled.connect(self.on_fit_toggled)
        self.sld_zoom = QSlider(Qt.Horizontal)
        self.sld_zoom.setMinimum(100)
        self.sld_zoom.setMaximum(400)
        self.sld_zoom.setValue(130)
        self.sld_zoom.setFixedWidth(150)
        self.sld_zoom.setToolTip("画面缩放 100%~400%")
        self.sld_zoom.valueChanged.connect(self.on_zoom_changed)
        self.lbl_zoom = QLabel("130%")
        self.lbl_zoom.setStyleSheet("font-size:12px;color:#6b7280;")
        info_row.addWidget(self.image_info)
        info_row.addStretch(1)
        info_row.addWidget(self.chk_fit)
        info_row.addWidget(QLabel("缩放"))
        info_row.addWidget(self.sld_zoom)
        info_row.addWidget(self.lbl_zoom)
        lv.addLayout(info_row)
        mid.addWidget(left, stretch=3)

        # ---------------- right: panel ----------------
        right = QWidget()
        rv = QVBoxLayout(right)

        g_status = QGroupBox("AI 检测状态")
        gs = QGridLayout(g_status)
        self.lbl_system = QLabel("● 系统就绪")
        self.lbl_system.setStyleSheet("font-size:15px;font-weight:600;color:#16a34a;")
        gs.addWidget(self.lbl_system, 0, 0, 1, 2)
        self.lbl_expected = QLabel("检测目标：{}".format(EXPECTED_HOLES))
        self.lbl_detected = QLabel("已识别：-")
        self.lbl_avg = QLabel("平均置信度：-")
        gs.addWidget(self.lbl_expected, 1, 0)
        gs.addWidget(self.lbl_detected, 1, 1)
        gs.addWidget(self.lbl_avg, 2, 0, 1, 2)
        self.lbl_holes = QLabel("H01 -   H02 -   H03 -   H04 -")
        self.lbl_holes.setStyleSheet("font-size:15px;font-weight:600;")
        gs.addWidget(self.lbl_holes, 3, 0, 1, 2)
        self.lbl_engine = QLabel("设备：-    耗时：-")
        self.lbl_engine.setStyleSheet("color:#6b7280;font-size:12px;")
        gs.addWidget(self.lbl_engine, 4, 0, 1, 2)
        self.lbl_numbering = QLabel("当前编号：基于当前图像几何排序（PCA）｜orientation_status = uncertain")
        self.lbl_numbering.setWordWrap(True)
        self.lbl_numbering.setStyleSheet("color:#b45309;font-size:12px;")
        gs.addWidget(self.lbl_numbering, 5, 0, 1, 2)
        rv.addWidget(g_status)

        g_mode = QGroupBox("工作模式")
        gm = QHBoxLayout(g_mode)
        self.rb_auto = QRadioButton("AI 自动检测")
        self.rb_manual = QRadioButton("手动指定检测")
        self.rb_auto.setChecked(True)
        gm.addWidget(self.rb_auto)
        gm.addWidget(self.rb_manual)
        rv.addWidget(g_mode)

        g_manual = QGroupBox("手动指定（模式 B）")
        gma = QHBoxLayout(g_manual)
        gma.addWidget(QLabel("目标孔："))
        self.cmb_target = QComboBox()
        self.cmb_target.addItems(["H01", "H02", "H03", "H04"])
        self.cmb_target.setCurrentText("H03")
        self.cmb_target.setEnabled(False)
        gma.addWidget(self.cmb_target)
        gma.addStretch(1)
        rv.addWidget(g_manual)

        g_tasks = QGroupBox("检测任务")
        gt = QVBoxLayout(g_tasks)
        self.lbl_taskinfo = QLabel("任务：0 个")
        self.lbl_taskinfo.setStyleSheet("color:#6b7280;font-size:12px;")
        gt.addWidget(self.lbl_taskinfo)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["目标", "状态", "置信度", "中心坐标"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setMinimumHeight(170)
        gt.addWidget(self.table)
        rv.addWidget(g_tasks, stretch=1)
        mid.addWidget(right, stretch=2)

        # ---------------- bottom: buttons ----------------
        btns = QHBoxLayout()
        self.btn_select = QPushButton("选择图片")
        self.btn_detect = QPushButton("开始 AI 检测")
        self.btn_create = QPushButton("生成检测任务")
        self.btn_execute = QPushButton("执行检测")
        self.btn_simulate = QPushButton("模拟执行")
        self.btn_save = QPushButton("保存结果")
        self.btn_open = QPushButton("打开结果目录")
        self.btn_csv = QPushButton("导出任务CSV")
        for b in (self.btn_select, self.btn_detect, self.btn_create,
                  self.btn_execute, self.btn_simulate, self.btn_save,
                  self.btn_open, self.btn_csv):
            b.setMinimumHeight(38)
            btns.addWidget(b)
        root.addLayout(btns)

        # ---------------- robot status ----------------
        robot_line = QHBoxLayout()
        self.lbl_robot = QLabel("机器人：未连接")
        self.lbl_robot.setStyleSheet("font-size:14px;font-weight:600;color:#b91c1c;")
        self.lbl_exec = QLabel("执行状态：等待机器人连接")
        self.lbl_exec.setStyleSheet("font-size:14px;color:#6b7280;")
        self.prog_exec = QProgressBar()
        self.prog_exec.setRange(0, 1)
        self.prog_exec.setValue(0)
        self.prog_exec.setFixedWidth(220)
        self.prog_exec.setFormat("模拟进度 %v/%m")
        robot_line.addWidget(self.lbl_robot)
        robot_line.addSpacing(24)
        robot_line.addWidget(self.lbl_exec)
        robot_line.addSpacing(12)
        robot_line.addWidget(self.prog_exec)
        robot_line.addStretch(1)
        root.addLayout(robot_line)

        # ---------------- log ----------------
        self.logbox = QPlainTextEdit()
        self.logbox.setReadOnly(True)
        self.logbox.setMaximumHeight(160)
        self.logbox.setStyleSheet("font-family:Consolas,monospace;font-size:12px;"
                                  "background:#0f172a;color:#e2e8f0;")
        root.addWidget(self.logbox)

        # ---------------- signals ----------------
        self.btn_select.clicked.connect(self.on_select_image)
        self.btn_detect.clicked.connect(self.on_detect)
        self.btn_create.clicked.connect(self.on_create_tasks)
        self.btn_execute.clicked.connect(self.on_execute)
        self.btn_simulate.clicked.connect(self.on_simulate)
        self.btn_save.clicked.connect(self.on_save)
        self.btn_open.clicked.connect(self.on_open_results)
        self.btn_csv.clicked.connect(self.on_export_csv)
        self.table.cellDoubleClicked.connect(self.on_task_dblclick)
        self.rb_auto.toggled.connect(self.on_mode_changed)
        self.cmb_target.currentTextChanged.connect(lambda _t: self.update_task_button())
        QShortcut(QKeySequence("Ctrl+O"), self, activated=self.on_select_image)
        QShortcut(QKeySequence("F5"), self, activated=self.on_detect)
        QShortcut(QKeySequence("Ctrl+S"), self, activated=self.on_save)
        self.update_task_button()      # initial button visibility / label

    # ------------------------------------------------------------- helpers
    def log(self, msg):
        from datetime import datetime
        self.logbox.appendPlainText("[{}] {}".format(datetime.now().strftime("%H:%M:%S"), msg))

    def set_status(self, text, color):
        self.lbl_system.setText("● " + text)
        self.lbl_system.setStyleSheet("font-size:15px;font-weight:600;color:{};".format(color))

    def set_display_photo(self, bgr, crop_rect=None):
        """Store the photo to show and (optionally) the region to zoom into."""
        self.display_photo = bgr
        self.display_crop = crop_rect
        self.render_view()

    def render_view(self):
        """Re-render the styled canvas at the label's current size."""
        if self.display_photo is None:
            return
        size = self.image_label.size()
        if size.width() < 60 or size.height() < 60:
            return
        crop = self.display_crop if self.chk_fit.isChecked() else None
        if crop is None and self.display_photo is not None:
            crop = (0, 0, self.display_photo.shape[1], self.display_photo.shape[0])
        z = self.sld_zoom.value() / 100.0
        if z > 1.0 and crop is not None:
            crop = zoom_rect(crop, z, self.display_photo.shape)
        canvas, mapping = compose(self.display_photo, (size.width(), size.height()), crop_rect=crop)
        if self.current_result:
            # draw the run overlay first so the H0x labels stay readable on top
            canvas = overlay_execution(canvas, self.current_result, mapping, self.exec_state)
            canvas = overlay_annotations(canvas, self.current_result, mapping)
        self.image_label.setPixmap(bgr_to_pixmap(canvas))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.render_view()

    def on_fit_toggled(self, checked):
        if checked and self.current_result:
            self.display_crop = holes_bbox(self.current_result, self.display_photo.shape) \
                if self.display_photo is not None else None
        elif not checked:
            self.display_crop = None
        self.render_view()
        self.log("图像显示：{}".format("适应工件" if checked else "整图"))

    def on_zoom_changed(self, value):
        self.lbl_zoom.setText("{}%".format(value))
        self.render_view()

    def refresh_task_table(self):
        self.table.setRowCount(len(self.tasks.tasks))
        for r, t in enumerate(self.tasks.tasks):
            st = {"pending": "待检测", "simulated_done": "模拟完成"}.get(t["status"], t["status"])
            if t.get("simulated") is False:
                st = "未执行（机器人未连接）"
            vals = [t["target_id"], st,
                    "{:.3f}".format(t.get("confidence", 0.0)),
                    "({:.0f}, {:.0f})".format(t["center_px"][0], t["center_px"][1])]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(v)
                if c > 0:
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(r, c, item)
        self.update_task_button()

    def refresh_hole_checklist(self):
        res = self.current_result
        present = {h["id"] for h in (res or {}).get("holes", [])}
        parts = []
        for hid in ("H01", "H02", "H03", "H04"):
            parts.append("{} {}".format(hid, "✓" if hid in present else "-"))
        self.lbl_holes.setText("   ".join(parts))

    # -------------------------------------------------------------- actions
    def on_select_image(self):
        start = self.last_dir if Path(self.last_dir).is_dir() else str(Path.home())
        path, _ = QFileDialog.getOpenFileName(
            self, "选择图片", start, "Images (*.jpg *.jpeg *.png *.bmp)")
        if not path:
            return
        self.load_image(path)

    def load_image(self, path):
        p = Path(path)
        if not p.is_file():
            self.log("图片不存在：{}".format(path))
            self.set_status("检测异常", "#dc2626")
            return False
        # Go through the camera abstraction so a real camera can be swapped in.
        self.camera.set_source(p)
        if not self.camera.start():
            self.log("图片读取失败（相机接口）：{}".format(path))
            self.set_status("检测异常", "#dc2626")
            return False
        img = self.camera.get_frame()
        if img is None:
            self.log("相机未返回图像：{}".format(path))
            self.set_status("检测异常", "#dc2626")
            return False
        self.last_dir = str(p.parent)
        self.current_image_path = str(p)
        self.current_bgr = img
        self.current_result = None
        self.annotated = None
        self.tasks.tasks = []
        self.task_signature_done = None
        self.stop_simulation(silent=True)
        # a new image means the previous run is irrelevant -> reset the status row
        self.lbl_exec.setText("执行状态：等待机器人连接")
        self.prog_exec.setRange(0, 1)
        self.prog_exec.setValue(0)
        self.refresh_task_table()
        self.set_display_photo(img, None)
        self.image_info.setText("{}   {}x{}".format(p.name, img.shape[1], img.shape[0]))
        self.lbl_detected.setText("已识别：-")
        self.lbl_avg.setText("平均置信度：-")
        self.refresh_hole_checklist()
        self.set_status("系统就绪", "#16a34a")
        self.log("已选择图片：{}".format(p.name))
        return True

    def on_detect(self):
        if not self.current_image_path:
            self.log("尚未选择图片，无法检测。")
            self.set_status("检测异常", "#dc2626")
            return
        self.set_status("正在检测", "#d97706")
        QApplication.processEvents()
        self.log("开始 AI 检测（imgsz={} conf={}）...".format(IMGSZ, CONF))
        res = self.detector.detect(self.current_image_path)
        self.current_result = res
        self.detection_seq += 1
        self.task_signature_done = None          # new result -> tasks may be rebuilt
        self.stop_simulation(silent=True)        # clear any previous run overlay

        for w in res.get("warnings", []):
            self.log("提示：" + w)
        for e in res.get("errors", []):
            self.log("错误：" + e)

        if res.get("errors"):
            self.set_status("检测异常", "#dc2626")
            self.lbl_detected.setText("已识别：0")
            self.lbl_avg.setText("平均置信度：-")
            self.refresh_hole_checklist()
            return

        self.annotated = draw_result(self.current_bgr, res)
        # Screen view uses the CLEAN photo; annotations are drawn in display
        # space (crisp text at any zoom). self.annotated (with baked-in marks)
        # is still what gets written to disk.
        crop = holes_bbox(res, self.current_bgr.shape) if self.chk_fit.isChecked() else None
        self.set_display_photo(self.current_bgr, crop)
        self.lbl_detected.setText("已识别：{}".format(res["detections"]))
        self.lbl_avg.setText("平均置信度：{:.3f}".format(res["avg_conf"] or 0.0))
        self.lbl_engine.setText("设备：{}    耗时：{:.2f} s".format(
            "GPU" if res["device_used"] not in (None, "cpu") else "CPU",
            res.get("elapsed_s") or 0.0))
        self.refresh_hole_checklist()
        self.log("检测完成：识别 {}/{}，平均置信度 {:.3f}，设备 {}".format(
            res["detections"], EXPECTED_HOLES, res["avg_conf"] or 0.0, res["device_used"]))
        if res["complete"]:
            self.set_status("检测完成", "#16a34a")
        else:
            self.set_status("检测不完整（{}/{}）".format(res["detections"], EXPECTED_HOLES), "#d97706")
            self.log("检测不完整，请重新采集图像或调整检测参数。")

        run_dir, _ = self.tasks.save_run(res, self.annotated)
        self.last_run_dir = run_dir
        self.log("检测结果已保存：{}".format(run_dir))

        if self.rb_auto.isChecked():
            self.on_create_tasks()

    def on_mode_changed(self):
        manual = self.rb_manual.isChecked()
        self.cmb_target.setEnabled(manual)
        self.log("切换工作模式：{}".format("手动指定检测" if manual else "AI 自动检测"))
        if not manual and self.tasks.tasks:
            self.log("提示：AI 自动模式下任务由【开始 AI 检测】自动生成；"
                     "如需重新生成，直接重新检测即可。")
        self.update_task_button()

    def task_signature(self):
        """Identifies the tasks that the current mode + current result would produce."""
        if self.current_result is None:
            return None
        return (bool(self.rb_manual.isChecked()),
                self.cmb_target.currentText() if self.rb_manual.isChecked() else None,
                self.detection_seq)

    def update_task_button(self):
        """Make the button label say exactly what a click will do."""
        n = len(self.tasks.tasks)
        manual = self.rb_manual.isChecked()
        # In AI-auto mode the tasks are generated by 开始 AI 检测 itself, so the
        # separate button would be a duplicate -> hide it (cleaner UX).
        self.btn_create.setVisible(manual)
        if manual:
            self.btn_create.setText("生成任务：{}".format(self.cmb_target.currentText()))
            self.btn_create.setToolTip("只生成下拉框中选中的那一个孔（不重新推理）；"
                                       "AI 自动模式下此按钮由【开始 AI 检测】自动完成")
        else:
            self.btn_create.setText("重新生成任务（4 孔）" if n else "生成检测任务（4 孔）")
            self.btn_create.setToolTip(
                "按最近的检测结果生成 4 个任务；AI 自动检测在结束时已经自动生成过一次")
        mode = "手动指定" if manual else "AI 自动"
        self.lbl_taskinfo.setText("任务：{} 个{}".format(n, "" if n == 0 else "（{}）".format(mode)))

    def on_create_tasks(self):
        if self.current_result is None:
            self.log("尚未检测，无法生成任务。请先点击【开始 AI 检测】。")
            return
        sig = self.task_signature()
        if self.tasks.tasks and sig == self.task_signature_done:
            self.log("任务未变化：当前已是 {} 个任务，未重复生成（避免清空执行状态）。".format(
                len(self.tasks.tasks)))
            self.refresh_task_table()
            return
        if self.rb_manual.isChecked():
            target = self.cmb_target.currentText()
            r = self.tasks.create_manual_task(self.current_result, target)
        else:
            r = self.tasks.create_auto_tasks(self.current_result)
        self.log(r["message"])
        if r["ok"]:
            self.task_signature_done = sig
        # NOTE: do NOT overwrite the detection status here. When the detection
        # itself was incomplete, "检测不完整" is the correct state to show;
        # "检测异常" is reserved for real failures (read/model/inference).
        self.refresh_task_table()

    def on_execute(self):
        if not self.tasks.tasks:
            self.log("当前没有检测任务，请先检测并生成任务。")
            return
        r = self.tasks.mark_executed(self.robot, simulate=False)
        self.lbl_robot.setText("机器人：未连接")
        self.lbl_exec.setText("执行状态：{}".format(r["message"]))
        self.log(r["message"])
        self.refresh_task_table()

    def on_simulate(self):
        if not self.tasks.tasks:
            self.log("当前没有检测任务，请先检测并生成任务。")
            return
        if self.exec_state["active"]:
            self.stop_simulation()
            return
        order = [t["target_id"] for t in self.tasks.tasks]
        self.exec_state = {"active": True, "order": order, "done": [], "current": order[0],
                           "probe": None, "phase": "approach", "tick": 0, "idx": 0,
                           "from": None, "running": True}
        self.btn_simulate.setText("停止模拟")
        self.lbl_robot.setText("机器人：未连接")
        self.lbl_exec.setText("执行状态：模拟执行中（未连接真实机器人）")
        self.prog_exec.setRange(0, len(order))
        self.prog_exec.setValue(0)
        self.log("=" * 46)
        self.log("开始模拟执行：{} 个目标，路径 {}".format(len(order), " -> ".join(order)))
        self.log("注意：这是软件仿真，机器人状态仍为“未连接”，不会驱动任何真实设备。")
        for t in self.tasks.tasks:
            t["status"] = "pending"
            t["simulated"] = None
        self.refresh_task_table()
        self.render_view()
        self.exec_timer.start()

    def exec_step(self):
        """Advance the simulated probe by one tick (called by the QTimer)."""
        st = self.exec_state
        if not st.get("running"):
            self.exec_timer.stop()
            return
        order = st["order"]
        if st["idx"] >= len(order):
            self.finish_simulation()
            return
        hid = order[st["idx"]]
        task = next((t for t in self.tasks.tasks if t["target_id"] == hid), None)
        if task is None:
            st["idx"] += 1
            return
        target_xy = tuple(task["center_px"])
        st["current"] = hid
        if st["phase"] == "approach":
            start = st["from"] or target_xy
            n = 3
            t = min(1.0, (st["tick"] + 1) / float(n))
            st["probe"] = (start[0] + (target_xy[0] - start[0]) * t,
                           start[1] + (target_xy[1] - start[1]) * t)
            st["tick"] += 1
            if st["tick"] >= n:
                st["phase"] = "measure"
                st["tick"] = 0
            self.lbl_exec.setText("执行状态：探头接近 {}（{:.0f}, {:.0f}）".format(
                hid, st["probe"][0], st["probe"][1]))
        else:
            st["probe"] = target_xy
            st["done"].append(hid)
            task["status"] = "simulated_done"
            task["simulated"] = True
            st["idx"] += 1
            st["phase"] = "approach"
            st["tick"] = 0
            st["from"] = target_xy
            self.prog_exec.setValue(len(st["done"]))
            self.log("  {} 移动到 ({:.0f}, {:.0f}) -> 下探测量 -> 完成 [{}/{}]".format(
                hid, target_xy[0], target_xy[1], len(st["done"]), len(order)))
            self.refresh_task_table()
        self.render_view()
        if st["idx"] >= len(order) and st["phase"] == "approach" and len(st["done"]) == len(order):
            self.finish_simulation()

    def finish_simulation(self):
        st = self.exec_state
        if not st.get("running"):
            return
        self.exec_timer.stop()
        st["running"] = False          # timer stops, but keep the overlay visible
        st["current"] = None
        self.btn_simulate.setText("模拟执行")
        self.lbl_exec.setText("执行状态：模拟执行完成 {}/{}（未连接真实机器人）".format(
            len(st["done"]), len(st["order"])))
        self.log("模拟执行结束：{}/{} 个目标完成（软件仿真，未驱动真实设备）。".format(
            len(st["done"]), len(st["order"])))
        self.log("=" * 46)
        self.render_view()
        if self.current_result:
            robot_result = self.robot.simulate_execute(
                [{"target_id": t, "center_px": next(
                    (x["center_px"] for x in self.tasks.tasks if x["target_id"] == t), None)}
                 for t in st["order"]], delay=0.0)
            run_dir, _ = self.tasks.save_run(
                self.current_result, self.annotated,
                extra={"execution": "simulated",
                       "execution_order": st["order"],
                       "execution_done": st["done"],
                       "robot_layer_result": robot_result,
                       "execution_note": "software simulation only - no real robot connected"})
            self.last_run_dir = run_dir
            self.log("模拟执行记录已保存：{}".format(run_dir))

    def stop_simulation(self, silent=False):
        st = self.exec_state
        was = st.get("running")
        self.exec_timer.stop()
        self.exec_state = {"active": False, "order": [], "done": [], "current": None,
                           "probe": None, "phase": "idle", "tick": 0, "idx": 0, "from": None}
        if hasattr(self, "btn_simulate"):
            self.btn_simulate.setText("模拟执行")
        if was and not silent:
            self.lbl_exec.setText("执行状态：模拟已停止")
            self.log("模拟执行已手动停止。")

    def on_save(self):
        if not self.current_result:
            self.log("尚未检测，无可保存的结果。")
            return
        run_dir, _ = self.tasks.save_run(self.current_result, self.annotated)
        self.last_run_dir = run_dir
        self.log("结果已保存：{}".format(run_dir))

    # ------------------------------------------------- extra conveniences
    def on_open_results(self):
        import os
        root = Path(RESULTS_ROOT)
        target = Path(self.last_run_dir) if self.last_run_dir else None
        if target is None or not Path(target).is_dir():
            if root.is_dir():
                dirs = sorted([d for d in root.iterdir() if d.is_dir()], key=lambda d: d.name)
                target = dirs[-1] if dirs else None
        if target is None or not Path(target).is_dir():
            self.log("还没有任何结果目录：{}".format(root))
            return
        try:
            os.startfile(str(target))
            self.log("已打开结果目录：{}".format(target))
        except Exception as exc:
            self.log("打开目录失败：{}".format(exc))

    def on_export_csv(self):
        import csv
        if not self.tasks.tasks:
            self.log("当前没有检测任务，无法导出 CSV。")
            return
        base = Path(self.last_run_dir) if self.last_run_dir else (Path(RESULTS_ROOT))
        try:
            base.mkdir(parents=True, exist_ok=True)
            out = Path(base) / "tasks.csv"
            k = 2
            while out.exists():                    # never overwrite an earlier export
                out = Path(base) / "tasks_{:02d}.csv".format(k)
                k += 1
            with out.open("w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(["target_id", "status", "confidence", "center_x", "center_y",
                            "simulated", "source_image"])
                for t in self.tasks.tasks:
                    w.writerow([t["target_id"], t.get("status"), t.get("confidence"),
                                t["center_px"][0], t["center_px"][1], t.get("simulated"),
                                self.current_image_path])
            self.log("任务已导出：{}".format(out))
        except Exception as exc:
            self.log("导出 CSV 失败：{}".format(exc))

    def on_task_dblclick(self, row, _col):
        """Double-click a task row -> zoomed viewer for that hole."""
        if row < 0 or row >= len(self.tasks.tasks):
            return
        if self.current_result is None or self.display_photo is None:
            return
        tid = self.tasks.tasks[row]["target_id"]
        hit = next((h for h in self.current_result["holes"] if h["id"] == tid), None)
        if hit is None:
            self.log("{} 在本次检测结果中不存在，无法放大。".format(tid))
            return
        img = self.display_photo
        e = hit["ellipse"]
        cx, cy = e["center"]
        R = int(max(e["major"], e["minor"]) * 1.15) + 30
        x0, y0 = max(0, int(cx - R)), max(0, int(cy - R))
        x1, y1 = min(img.shape[1], int(cx + R)), min(img.shape[0], int(cy + R))
        crop = img[y0:y1, x0:x1].copy()
        if crop.size == 0:
            return
        cv2.ellipse(crop, ((cx - x0, cy - y0), (e["width"], e["height"]), e["angle"]),
                    (0, 255, 0), 3)
        cv2.circle(crop, (int(cx - x0), int(cy - y0)), 6, (0, 0, 255), -1)
        cv2.putText(crop, "{}  conf {:.3f}".format(tid, hit["confidence"]), (12, 34),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 5, cv2.LINE_AA)
        cv2.putText(crop, "{}  conf {:.3f}".format(tid, hit["confidence"]), (12, 34),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 255), 2, cv2.LINE_AA)
        dlg = QDialog(self)
        dlg.setWindowTitle("孔 {} 放大查看".format(tid))
        lay = QVBoxLayout(dlg)
        lab = QLabel()
        lab.setPixmap(bgr_to_pixmap(crop).scaled(760, 760, Qt.KeepAspectRatio,
                                                 Qt.SmoothTransformation))
        lay.addWidget(lab)
        info = QLabel("中心 ({:.1f}, {:.1f})   宽 {:.1f}   高 {:.1f}   角度 {:.1f}°   "
                      "长短轴比 {:.3f}".format(cx, cy, e["width"], e["height"],
                                              e["angle"], e.get("aspect", 0)))
        info.setStyleSheet("font-size:12px;color:#374151;")
        lay.addWidget(info)
        dlg.exec()
