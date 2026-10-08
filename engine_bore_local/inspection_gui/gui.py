"""Friend's visual layout, backed by the existing production detector."""
from __future__ import annotations

from datetime import datetime
import hashlib
import time
import json
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import QObject, QThread, Qt, QTimer, Signal, Slot, QUrl
from PySide6.QtGui import QDesktopServices, QImage, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QFileDialog,
    QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QMainWindow, QDialog,
    QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea,
    QSizePolicy, QSlider, QSplitter, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from experiment_records import ExperimentRecords
from .capture_archive import save_capture, capture_information
from .measurement_readiness import ReadinessDialog, readiness_rows
from .camera_parameters import CameraParametersDialog
from .vision_workspace import ClickablePhoto, CameraPreviewWorker, pick_hole, selected_targets
from .review_view import HoleReviewDialog, review_summary
from .devices_view import show_devices
from .records_view import RecordsDialog
from .training_bridge import TrainingBridge
from .simulation_view import SimulationDialog
from .view_render import compose, holes_bbox, zoom_rect, _map_pts
from .vision import HoleDetector, _report_to_result, draw_result, imread_unicode

BASE = Path(__file__).resolve().parents[1]
LAST_BATCH = BASE / 'last_batch.json'

STYLE = """
QMainWindow, QDialog { background: #f1f5f9; color: #172b4d; }
QGroupBox { background: white; border: 1px solid #cbd5e1; border-radius: 9px;
            margin-top: 12px; padding: 14px 10px 8px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 14px; padding: 0 6px; color: #24466e; }
QPushButton { padding: 8px 13px; border: 1px solid #bdccde; border-radius: 6px;
              background: white; color: #17365c; }
QPushButton:hover { background: #e9f2ff; border-color: #6389bf; }
QPushButton:disabled { background: #edf0f4; color: #8995a5; border-color: #dce2e9; }
QPushButton#primary { background: #2160b5; color: white; border-color: #2160b5; font-weight: 600; }
QPushButton#primary:hover { background: #174f99; }
QPushButton#primary:disabled { background: #a8bdd9; border-color: #a8bdd9; }
QComboBox { padding: 5px; background: white; border: 1px solid #bdccde; border-radius: 4px; }
QTableWidget { background: white; alternate-background-color: #f1f6fc; gridline-color: #b7c7d9; }
QHeaderView::section { background: #e8eff8; padding: 6px; border: 1px solid #b7c7d9; font-weight: 600; }
QProgressBar { border: 1px solid #cbd5e1; border-radius: 5px; text-align: center; min-height: 17px; }
QProgressBar::chunk { background: #71a7e8; }
QScrollArea { border: none; background: transparent; }
"""


def bgr_to_pixmap(bgr):
    rgb = cv2.cvtColor(np.ascontiguousarray(bgr), cv2.COLOR_BGR2RGB)
    h, w, _ = rgb.shape
    return QPixmap.fromImage(QImage(rgb.data, w, h, rgb.strides[0], QImage.Format.Format_RGB888).copy())


class BatchWorker(QObject):
    result_ready = Signal(int, object)
    progress = Signal(str)
    finished = Signal()

    def __init__(self, detector, paths):
        super().__init__()
        self.detector, self.paths = detector, list(paths)

    @Slot()
    def run(self):
        try:
            for index, path in enumerate(self.paths):
                self.progress.emit(f'正在检测 {index + 1}/{len(self.paths)}：{Path(path).name}')
                try:
                    result = self.detector.detect(path)
                except Exception as error:
                    result = {'image_path': str(path), 'errors': [str(error)], 'warnings': [],
                              'detections': 0, 'center_count': 0, 'holes': [], 'detected_holes': [],
                              'fitted_holes': [], 'complete': False, 'raw_report': None}
                self.result_ready.emit(index, result)
        finally:
            self.finished.emit()


class MainWindow(QMainWindow):
    def __init__(self, records=None):
        super().__init__()
        self.setWindowTitle('双机械臂孔检测系统 · 本地模型')
        self.setStyleSheet(STYLE)
        screen = QApplication.primaryScreen().availableGeometry()
        self.resize(min(1510, screen.width() - 60), min(930, screen.height() - 60))
        self.setMinimumSize(1000, 680)
        self.records = records if records is not None else ExperimentRecords()
        self.detector = HoleDetector()
        self.bridge = TrainingBridge(self)
        self.bridge.busy_changed.connect(self.management_busy_changed)
        self.bridge.model_updated.connect(self.refresh_after_update)
        self.bridge.finished.connect(self.refresh_after_update)
        self.bridge.log.connect(self.log)
        self.paths, self.results = [], []
        self.current_index = 0
        self.current_result = None
        self.camera_worker = None
        self.photo_mapping = None
        self.hole_selections = {}
        self.confirmed_task = None
        self.display_photo = None
        self.display_crop = None
        self.thread = None
        self.worker = None
        self.active_group = None
        self.completed_count = 0
        self.record_error = False
        self.records_dialog = None
        self.last_dir = str(BASE / 'data' / 'incoming_photos')
        self.batch_running = False
        self._build_ui()
        self.refresh_model_summary()
        self.log('系统就绪，检测使用当前正式模型，孔置信度保留阈值为 0.5。')
        self.set_controls()
        self.device_status_timer = QTimer(self)
        self.device_status_timer.setInterval(1000)
        self.device_status_timer.timeout.connect(self.refresh_device_status)
        self.device_status_timer.start()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 10, 16, 12)
        heading = QHBoxLayout()
        title = QLabel('双机械臂孔检测系统')
        title.setStyleSheet('font-size:24px;font-weight:700;color:#1e3a68;padding:5px;')
        heading.addWidget(title)
        heading.addStretch(1)
        self.model_label = QLabel()
        self.model_label.setStyleSheet('color:#50657f;')
        heading.addWidget(self.model_label)
        root.addLayout(heading)

        tools = QHBoxLayout()
        self.btn_select = QPushButton('离线测试 · 选择照片')
        self.btn_detect = QPushButton('开始检测')
        self.btn_detect.setObjectName('primary')
        self.btn_devices = QPushButton('设备连接')
        self.btn_records = QPushButton('实验记录')
        self.btn_dataset = QPushButton('添加训练数据 / 自动更新')
        self.btn_validation = QPushButton('训练验证结果')
        self.btn_results = QPushButton('打开结果文件夹')
        self.btn_simulation = QPushButton('模拟测量动画')
        self.btn_models = QPushButton('模型与数据管理')
        for button in (self.btn_select, self.btn_detect, self.btn_devices, self.btn_records,
                       self.btn_models, self.btn_simulation):
            tools.addWidget(button)
        self.model_dialog = QDialog(self)
        self.model_dialog.setWindowTitle('模型与数据管理')
        self.model_dialog.resize(650, 280)
        management = QVBoxLayout(self.model_dialog)
        note = QLabel('添加照片并标注 → 训练候选模型 → 查看验证结果\n正式模型仍按验证结果选择，验证通过后才启用。')
        note.setWordWrap(True)
        management.addWidget(note)
        management.addWidget(self.btn_dataset)
        management.addWidget(self.btn_validation)
        self.btn_results.setParent(self)
        self.btn_results.hide()
        root.addLayout(tools)

        split = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(split, 1)
        visual = QGroupBox('视觉检测区')
        visual_layout = QVBoxLayout(visual)
        self.image_label = ClickablePhoto('拍摄照片或选择离线照片后检测')
        self.image_label.clicked.connect(self.photo_hole_clicked)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumSize(420, 260)
        self.image_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.image_label.setStyleSheet('background:#152438;color:#acbad0;border-radius:6px;')
        frames = QSplitter(Qt.Orientation.Horizontal)
        live_box = QGroupBox('实时工业相机画面')
        live_layout = QVBoxLayout(live_box)
        self.live_label = QLabel('尚未接入工业相机驱动，实时画面不可用')
        self.live_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.live_label.setWordWrap(True)
        self.live_label.setMinimumSize(200, 220)
        self.live_label.setStyleSheet('background:#152438;color:#acbad0;')
        live_layout.addWidget(self.live_label, 1)
        self.live_note = QLabel('实时画面不会替换右侧已拍摄图片')
        self.live_note.setWordWrap(True)
        live_layout.addWidget(self.live_note)
        camera_actions = QHBoxLayout()
        self.btn_live = QPushButton('开始实时采集')
        self.btn_live_stop = QPushButton('停止采集')
        self.btn_capture = QPushButton('拍摄并留样')
        self.btn_live.clicked.connect(self.start_camera_preview)
        self.btn_live_stop.clicked.connect(self.stop_camera_preview)
        self.btn_capture.clicked.connect(self.capture_camera_photo)
        for button in (self.btn_live, self.btn_live_stop, self.btn_capture): camera_actions.addWidget(button)
        live_layout.addLayout(camera_actions)
        archive_actions = QHBoxLayout()
        parameters_button = QPushButton('相机采集参数')
        parameters_button.clicked.connect(self.show_camera_parameters)
        archive_actions.addWidget(parameters_button)
        live_layout.addLayout(archive_actions)
        self.btn_capture.setEnabled(False)
        self.btn_live_stop.setEnabled(False)
        frames.addWidget(live_box)
        frozen_box = QGroupBox('本次拍摄图片 · 点击孔选择')
        frozen_layout = QVBoxLayout(frozen_box)
        self.image_label.setMinimumSize(200, 220)
        frozen_layout.addWidget(self.image_label, 1)
        frames.addWidget(frozen_box)
        frames.setSizes([450, 450])
        visual_layout.addWidget(frames, 1)
        self.camera_timer = QTimer(self)
        self.camera_timer.setInterval(100)
        self.camera_timer.timeout.connect(self.refresh_camera_preview)
        self.camera_timer.start()
        image_tools = QHBoxLayout()
        self.chk_fit = QCheckBox('适应孔区域')
        self.chk_fit.setChecked(True)
        self.sld_zoom = QSlider(Qt.Orientation.Horizontal)
        self.sld_zoom.setRange(100, 300)
        self.sld_zoom.setValue(100)
        self.sld_zoom.setMaximumWidth(130)
        self.lbl_zoom = QLabel('100%')
        self.image_info = QLabel('尚未选择照片')
        self.image_info.setWordWrap(True)
        image_tools.addWidget(self.image_info, 1)
        image_tools.addWidget(self.chk_fit)
        image_tools.addWidget(QLabel('缩放'))
        image_tools.addWidget(self.sld_zoom)
        image_tools.addWidget(self.lbl_zoom)
        visual_layout.addLayout(image_tools)
        navigation = QHBoxLayout()
        self.previous_button = QPushButton('上一张')
        self.selector = QComboBox()
        self.next_button = QPushButton('下一张')
        self.page_label = QLabel('0/0')
        navigation.addWidget(self.previous_button)
        navigation.addWidget(self.selector, 1)
        navigation.addWidget(self.next_button)
        navigation.addWidget(self.page_label)
        visual_layout.addLayout(navigation)
        legend = QLabel('青色：孔轮廓　黄色：拟合椭圆　红色十字：图像圆心')
        legend.setStyleSheet('color:#65758b;font-size:11px;')
        visual_layout.addWidget(legend)
        split.addWidget(visual)

        sidebar = QWidget()
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(5, 0, 2, 0)
        status_box = QGroupBox('AI 检测状态')
        status_layout = QGridLayout(status_box)
        self.lbl_system = QLabel('● 系统就绪')
        self.lbl_system.setStyleSheet('font-size:16px;font-weight:600;color:#16834b;')
        status_layout.addWidget(self.lbl_system, 0, 0, 1, 2)
        self.lbl_detected = QLabel('已识别：— / 4')
        self.lbl_centers = QLabel('圆心：—')
        self.lbl_avg = QLabel('平均置信度：—')
        self.lbl_part = QLabel('part 置信度：—')
        self.lbl_constraint = QLabel('part 位置筛选：—')
        self.lbl_engine = QLabel('设备：本地 GPU / CPU')
        self.lbl_engine.setWordWrap(True)
        status_layout.addWidget(self.lbl_detected, 1, 0)
        status_layout.addWidget(self.lbl_centers, 1, 1)
        status_layout.addWidget(self.lbl_avg, 2, 0)
        status_layout.addWidget(self.lbl_constraint, 3, 0, 1, 2)
        self.review_warning = QLabel("待检测")
        self.review_warning.setWordWrap(True)
        status_layout.addWidget(self.review_warning, 4, 0, 1, 2)
        self.batch_progress = QProgressBar()
        self.batch_progress.setRange(0, 1)
        self.batch_progress.setValue(0)
        self.batch_progress.setFormat('本组进度 %v/%m')
        status_layout.addWidget(self.batch_progress, 5, 0, 1, 2)
        side_layout.addWidget(status_box)

        task_box = QGroupBox('孔位与测量准备')
        task_layout = QVBoxLayout(task_box)
        self.task_note = QLabel('孔号按当前图像位置排序；尚未建立固定物理孔身份。')
        self.task_note.setWordWrap(True)
        self.task_note.setStyleSheet('color:#8c5c18;font-size:11px;')
        task_layout.addWidget(self.task_note)
        self.measure_mode = QComboBox()
        self.measure_mode.addItems(['自动全检（四个孔）', '手动选择测孔'])
        self.measure_mode.currentIndexChanged.connect(self.sync_hole_selection)
        task_layout.addWidget(self.measure_mode)
        choices = QHBoxLayout()
        self.hole_choices = {}
        for number in range(1, 5):
            hid = f'H{number:02d}'
            checkbox = QCheckBox(hid)
            checkbox.setEnabled(False)
            checkbox.toggled.connect(lambda checked, identity=hid: self.hole_choice_changed(identity, checked))
            self.hole_choices[hid] = checkbox
            choices.addWidget(checkbox)
        task_layout.addLayout(choices)
        self.selection_note = QLabel('先识别本次图片，再按图上同名编号选择孔。')
        self.selection_note.setWordWrap(True)
        task_layout.addWidget(self.selection_note)
        self.btn_confirm_holes = QPushButton('确认本次测孔并保存清单')
        self.btn_confirm_holes.clicked.connect(self.confirm_hole_selection)
        self.btn_confirm_holes.setEnabled(False)
        task_layout.addWidget(self.btn_confirm_holes)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(['孔号', '置信度', '图像圆心 px', '定位状态', '三维坐标'])
        self.table.setShowGrid(True)
        self.table.setGridStyle(Qt.PenStyle.SolidLine)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        for column, width in enumerate((60, 80, 160, 110, 100)):
            self.table.setColumnWidth(column, width)
        self.table.setMinimumHeight(190)
        self.table.cellClicked.connect(self.review_hole)
        self.table.setToolTip("点击已有孔的一行，打开局部放大复核。孔号仅按图像位置排序。")
        task_layout.addWidget(self.table, 1)
        self.coordinate_note = QLabel('当前圆心为图像像素坐标；三维定位与测量机械臂坐标待标定。')
        self.coordinate_note.setWordWrap(True)
        self.coordinate_note.setStyleSheet('color:#687d96;font-size:11px;')
        task_layout.addWidget(self.coordinate_note)
        self.btn_send = QPushButton('发送测量任务（待设备与标定就绪）')
        self.btn_send.setEnabled(False)
        self.btn_send.setToolTip('设备连接、三维坐标、孔轴方向和标定验证完成后才能下发测量任务。')
        self.btn_readiness = QPushButton('测量就绪检查')
        self.btn_readiness.clicked.connect(self.show_readiness)
        task_layout.addWidget(self.btn_readiness)
        task_layout.addWidget(self.btn_send)
        side_layout.addWidget(task_box, 1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(sidebar)
        scroll.setMinimumWidth(420)
        split.addWidget(scroll)
        split.setSizes([900, 580])

        connection_line = QLabel('工业相机：未连接　｜　拍照机械臂 A：未连接　｜　测量机械臂 B：未连接')
        connection_line.setStyleSheet('color:#8b4b30;padding:4px;font-weight:600;')
        self.connection_line = connection_line
        self.device_states = {}
        root.addWidget(connection_line)
        self.logbox = QPlainTextEdit()
        self.logbox.setReadOnly(True)
        self.logbox.setMaximumHeight(110)
        self.logbox.setStyleSheet('background:#14243b;color:#dbe8f7;border-radius:6px;padding:5px;font-size:11px;')
        diagnostics_toggle = QPushButton('▶ 诊断信息')
        diagnostics_toggle.setCheckable(True)
        root.addWidget(diagnostics_toggle)
        self.diagnostics = QWidget()
        diagnostics_layout = QVBoxLayout(self.diagnostics)
        diagnostics_layout.setContentsMargins(0, 0, 0, 0)
        details = QHBoxLayout()
        details.addWidget(self.lbl_part)
        details.addWidget(self.lbl_engine, 1)
        diagnostics_layout.addLayout(details)
        diagnostics_layout.addWidget(self.logbox)
        self.diagnostics.hide()
        root.addWidget(self.diagnostics)
        diagnostics_toggle.toggled.connect(self.diagnostics.setVisible)
        diagnostics_toggle.toggled.connect(lambda expanded: diagnostics_toggle.setText(
            '▼ 诊断信息' if expanded else '▶ 诊断信息'))

        self.btn_select.clicked.connect(self.select_images)
        self.btn_detect.clicked.connect(self.start_batch)
        self.btn_devices.clicked.connect(self.show_device_panel)
        self.btn_records.clicked.connect(self.show_records)
        self.btn_dataset.clicked.connect(self.bridge.open_dataset)
        self.btn_validation.clicked.connect(self.bridge.open_validation)
        self.btn_results.clicked.connect(self.open_results)
        self.btn_models.clicked.connect(self.show_model_management)
        self.btn_simulation.clicked.connect(self.show_simulation)
        self.previous_button.clicked.connect(lambda: self.show_index(self.current_index - 1))
        self.next_button.clicked.connect(lambda: self.show_index(self.current_index + 1))
        self.selector.currentIndexChanged.connect(self.show_index)
        self.chk_fit.toggled.connect(self.render_view)
        self.sld_zoom.valueChanged.connect(self.render_view)
        self.table.cellDoubleClicked.connect(self.open_current_result)
        QShortcut(QKeySequence('Ctrl+O'), self, activated=self.select_images)
        QShortcut(QKeySequence('F5'), self, activated=self.start_batch)

    def log(self, message):
        self.logbox.appendPlainText(f'[{datetime.now():%H:%M:%S}] {message}')

    def set_status(self, message, color='#16834b'):
        self.lbl_system.setText('● ' + message)
        self.lbl_system.setStyleSheet(f'font-size:16px;font-weight:600;color:{color};')

    def refresh_model_summary(self):
        try:
            from dataset_update import active_models
            self.active_models = active_models()
            self.model_label.setText('正式模型 · 已通过验证')
            self.model_label.setToolTip(f"版本：{self.active_models.get('version', '')}\n孔：{self.active_models['bore']}\npart：{self.active_models['part']}")
        except (OSError, ValueError, KeyError):
            self.active_models = {'bore': str(BASE / 'models' / 'engine_part_bore_100.pt')}
            self.model_label.setText('本地模型')

    def set_controls(self):
        idle = not self.batch_running and not self.bridge.busy
        self.btn_select.setEnabled(idle)
        self.btn_detect.setEnabled(idle and bool(self.paths))
        self.btn_dataset.setEnabled(not self.batch_running)
        self.btn_validation.setEnabled(not self.batch_running)
        self.previous_button.setEnabled(bool(self.paths) and self.current_index > 0)
        self.next_button.setEnabled(bool(self.paths) and self.current_index + 1 < len(self.paths))

    def management_busy_changed(self, busy):
        if busy:
            self.detector.release()
            self.set_status('训练数据管理中，检测已暂停', '#a86613')
        else:
            self.set_status('系统就绪')
        self.set_controls()

    def refresh_after_update(self):
        self.detector.release()
        self.confirmed_task = None
        self.refresh_model_summary()
        if self.records_dialog:
            self.records_dialog.refresh()
        self.set_controls()

    @Slot()
    def select_images(self):
        if self.batch_running or self.bridge.busy:
            return
        start = self.last_dir if Path(self.last_dir).is_dir() else str(BASE)
        paths, _ = QFileDialog.getOpenFileNames(self, '选择这一组测试照片', start,
                                               '图片 (*.jpg *.jpeg *.png *.bmp)')
        if paths:
            self.set_images(paths)

    def set_images(self, paths):
        self.paths = [str(Path(path)) for path in paths]
        self.results = [None] * len(self.paths)
        self.completed_count = 0
        self.last_dir = str(Path(self.paths[0]).parent) if self.paths else self.last_dir
        self.selector.blockSignals(True)
        self.selector.clear()
        self.selector.addItems([f'{i + 1}. {Path(path).name}' for i, path in enumerate(self.paths)])
        self.selector.blockSignals(False)
        self.batch_progress.setRange(0, max(1, len(self.paths)))
        self.batch_progress.setValue(0)
        self.show_index(0)
        self.set_controls()
        self.log(f'已选择 {len(self.paths)} 张照片，点击“开始检测”处理这一组。')

    def show_index(self, index):
        if not self.paths:
            return
        self.current_index = max(0, min(int(index), len(self.paths) - 1))
        self.selector.blockSignals(True)
        self.selector.setCurrentIndex(self.current_index)
        self.selector.blockSignals(False)
        path = self.paths[self.current_index]
        self.current_result = self.results[self.current_index]
        original = imread_unicode(path)
        self.display_photo = (draw_result(original, self.current_result) if original is not None and self.current_result
                              else original)
        if self.display_photo is None and self.current_result:
            self.display_photo = imread_unicode(self.current_result.get('result_image') or '')
        self.page_label.setText(f'{self.current_index + 1}/{len(self.paths)}')
        dimensions = f' · {self.display_photo.shape[1]}×{self.display_photo.shape[0]}' if self.display_photo is not None else ''
        info = capture_information(path)
        capture_note = ''
        if info:
            capture_note = '\n留样时间：' + info.get('frame_received_at_local', info['saved_at']) + '  相机：' + (info.get('camera', {}).get('model') or '未获取')
        self.image_info.setText(Path(path).name + dimensions + capture_note)
        self.refresh_current_summary()
        self.render_view()
        self.set_controls()
        self.sync_hole_selection()

    def refresh_current_summary(self):
        result = self.current_result or {}
        detected = result.get('detected_holes', [])
        by_id = {hole['id']: hole for hole in detected}
        self.table.setRowCount(max(4, len(detected)))
        for row in range(max(4, len(detected))):
            hid = f'H{row + 1:02d}'
            hole = by_id.get(hid)
            if hole:
                center = hole.get('center_px')
                point = f'{center[0]:.2f}, {center[1]:.2f}' if center is not None else '—'
                state = '图像已定位' if hole.get('reliable_center') else ('圆心待复核' if center else '未拟合出圆心')
                values = [hid, f"{hole['confidence']:.4f}", point, state, '待标定']
            else:
                values = [hid, '—', '—', '未识别' if result else '待检测', '—']
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row, column, item)
        message, needs_review = review_summary(result)
        self.review_warning.setText(message)
        self.review_warning.setStyleSheet('color:#b45309;font-weight:600;' if needs_review else 'color:#15803d;')
        self.lbl_detected.setText(f"已识别：{result.get('detections', '—')} / 4")
        fitted = result.get('center_count')
        self.lbl_centers.setText(f"圆心：{fitted if fitted is not None else '—'}")
        avg = result.get('avg_conf')
        self.lbl_avg.setText(f'平均置信度：{avg:.4f}' if avg is not None else '平均置信度：—')
        part = result.get('part_confidence')
        self.lbl_part.setText(f'part 置信度：{part:.4f}' if part is not None else 'part 置信度：—')
        constraint = '已执行' if result.get('part_constraint_applied') else '已跳过，需复核'
        location_ok = result.get('complete') and result.get('part_constraint_applied')
        self.lbl_constraint.setText(('箱体定位：正常' if location_ok else '箱体定位：需复核') if result else '箱体定位：待检测')
        self.lbl_constraint.setToolTip('part 位置筛选：' + (constraint if result else '—'))
        device = result.get('device_name') or result.get('device_used') or '本地 GPU / CPU'
        elapsed = result.get('elapsed_s')
        self.lbl_engine.setText(f"设备：{device}" + (f' · {elapsed:.2f} 秒' if elapsed is not None else ''))
        if not self.batch_running and not self.bridge.busy:
            if result.get('errors'):
                self.set_status('当前照片检测异常', '#bf3e35')
            elif result and not result.get('complete'):
                self.set_status('当前照片需要复核', '#a86613')
            elif result:
                self.set_status('当前照片检测完成')

    def current_selected_ids(self):
        result = self.current_result or {}
        reliable = {h['id'] for h in result.get('fitted_holes', []) if h.get('reliable_center')}
        if not hasattr(self, 'measure_mode') or self.measure_mode.currentIndex() == 0:
            return reliable
        return set(self.hole_selections.get(result.get('image_path'), set())) & reliable

    def sync_hole_selection(self, *_):
        if not hasattr(self, 'hole_choices'):
            return
        result = self.current_result or {}
        reliable = {h['id'] for h in result.get('fitted_holes', []) if h.get('reliable_center')}
        selected = self.current_selected_ids()
        manual = self.measure_mode.currentIndex() == 1
        for hid, checkbox in self.hole_choices.items():
            checkbox.blockSignals(True)
            checkbox.setChecked(hid in selected)
            checkbox.setEnabled(manual and hid in reliable and not self.batch_running)
            checkbox.setToolTip('与本次图片中的同名孔对应' if hid in reliable else '本次没有该编号的可靠圆心，不能选择')
            checkbox.blockSignals(False)
        self.selection_note.setText(('自动全检：' if not manual else '手动测孔：') +
            ('、'.join(sorted(selected)) if selected else '尚未选择') +
            '\n孔号只对应当前图片。漏检时不能用编号推断具体物理孔。')
        ready = bool(selected) and (manual or (len(reliable) == 4 and result.get('detections') == 4))
        self.btn_confirm_holes.setEnabled(ready and not self.batch_running and not self.bridge.busy)
        self.render_view()

    def hole_choice_changed(self, hid, checked):
        if self.measure_mode.currentIndex() != 1:
            return
        result = self.current_result or {}
        key = result.get('image_path')
        selected = self.hole_selections.setdefault(key, set())
        if checked:
            selected.add(hid)
        else:
            selected.discard(hid)
        self.sync_hole_selection()

    def photo_hole_clicked(self, x, y):
        if self.batch_running:
            return
        if self.measure_mode.currentIndex() != 1:
            self.selection_note.setText('当前为自动全检。切换“手动选择测孔”后，可点击图片上的孔进行选择。')
            return
        result = self.current_result or {}
        hid = pick_hole(x, y, self.photo_mapping, result.get('fitted_holes', []))
        if hid and hid in self.hole_choices and self.hole_choices[hid].isEnabled():
            self.hole_choices[hid].toggle()
        elif hid:
            self.selection_note.setText(hid + ' 圆心不可靠，请点击孔位表放大复核。')

    def confirm_hole_selection(self):
        result = self.current_result or {}
        try:
            targets = selected_targets(result, self.current_selected_ids(), self.measure_mode.currentIndex() == 0)
            photo = Path(result['image_path'])
            photo_hash = hashlib.sha256(photo.read_bytes()).hexdigest()
            destination = BASE / 'results' / 'selected_tasks'
            destination.mkdir(parents=True, exist_ok=True)
            task = {'image': str(photo), 'image_sha256': photo_hash,
                    'created_at': datetime.now().isoformat(),
                    'selection_mode': 'automatic' if self.measure_mode.currentIndex() == 0 else 'manual',
                    'model': result.get('model_path'), 'coordinate_frame': 'image_pixel',
                    'robot_ready': False, 'measurement_executed': False,
                    'note': '本次图片的测孔清单，像素圆心尚未转换成机械臂坐标。',
                    'targets': [{'id': h['id'], 'confidence': h['confidence'], 'center_px': h['center_px'],
                                 'ellipse': h.get('ellipse')} for h in targets]}
            output = destination / (datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.json')
            output.write_text(json.dumps(task, ensure_ascii=False, indent=2), encoding='utf-8')
            self.selection_note.setText('已确认测孔：' + '、'.join(h['id'] for h in targets) + '\n清单已保存，尚未发送机械臂或执行测量。')
            self.confirmed_task = task
            self.log('测孔清单：' + str(output))
        except (ValueError, KeyError, OSError) as error:
            QMessageBox.warning(self, '选孔未完成', str(error))

    def start_camera_preview(self):
        if self.camera_worker and self.camera_worker.isRunning():
            return
        from .devices_view import _registered_backends, _load_settings, SETTINGS_PATH
        backend = _registered_backends.get('camera')
        if backend is None:
            QMessageBox.information(self, '相机尚未接入', '请先在设备连接中接入相机驱动并连接设备。需要相机品牌、型号与厂家SDK，当前不会用模拟画面冒充实时画面。')
            return
        if not all(callable(getattr(backend, name, None)) for name in ('start', 'stop', 'get_frame')):
            QMessageBox.warning(self, '相机驱动不完整', '驱动需提供 start、stop、get_frame 三个采集方法。')
            return
        settings, error = _load_settings(SETTINGS_PATH)
        if error:
            QMessageBox.warning(self, '相机配置读取失败', error)
            return
        self.camera_worker = CameraPreviewWorker(backend, self, settings=settings['camera'])
        self.camera_worker.failed.connect(lambda error: self.live_note.setText('采集异常：' + error))
        self.camera_worker.start()
        self.btn_live.setEnabled(False)
        self.btn_live_stop.setEnabled(True)
        self.live_note.setText('正在等待相机图像…')

    def stop_camera_preview(self):
        if self.camera_worker:
            self.camera_worker.stop()
        self.btn_capture.setEnabled(False)
        self.live_note.setText('正在停止采集…')

    def refresh_camera_preview(self):
        worker = self.camera_worker
        if not worker:
            return
        if not worker.isRunning():
            self.btn_live.setEnabled(True)
            self.btn_live_stop.setEnabled(False)
            self.btn_capture.setEnabled(False)
            self.live_label.clear()
            self.live_label.setText('采集已停止，实时画面不可用')
            return
        frame = worker.snapshot()
        self.btn_capture.setEnabled(frame is not None and not self.batch_running and not self.bridge.busy)
        if frame is None:
            self.live_label.clear()
            self.live_label.setText('等待新图像，超过2秒的旧帧不可拍摄')
            return
        size = self.live_label.size()
        canvas, _ = compose(frame, (size.width(), size.height()))
        self.live_label.setPixmap(bgr_to_pixmap(canvas))
        self.live_note.setText('实时采集正常。右侧图片独立冻结，拍摄暂未绑定机械臂位姿。')

    def capture_camera_photo(self):
        if self.batch_running or self.bridge.busy:
            return
        packet = self.camera_worker.snapshot_packet() if self.camera_worker and self.camera_worker.isRunning() else None
        if packet is None:
            QMessageBox.warning(self, '没有有效图像', '请先启动实时采集，确认相机正在提供新图像。')
            return
        from .devices_view import _registered_backends, _load_settings, SETTINGS_PATH
        settings, _ = _load_settings(SETTINGS_PATH)
        metadata = {'camera': settings.get('camera', {}),
                    'camera_driver': getattr(self.camera_worker.backend, 'name', type(self.camera_worker.backend).__name__),
                    'camera_identity_note': '相机名称型号来自连接配置，未取得厂家设备身份读回时不视为验证。',
                    'frame_received_at_local': datetime.fromtimestamp(packet['frame_received_at']).astimezone().isoformat(),
                    'camera_parameters_actual': packet.get('camera_parameters_actual'),
                    'robot_a_pose': None, 'robot_a_pose_note': '未取得有效拍照机械臂位姿',
                    'model_version': self.active_models.get('version'),
                    'camera_parameters_note': '仅记录设备实际读回值，未获取时保持空值，不用期望配置替代。'}
        camera = self.camera_worker.backend
        metadata['camera_identity_actual'] = {key: getattr(camera, key, None) for key in ('device_name', 'device_serial', 'device_uid', 'profile')}
        backend = _registered_backends.get('robot_a')
        latest = getattr(backend, 'latest', None)
        if isinstance(latest, dict) and latest.get('received_at') and 0 <= time.time()-latest['received_at'] < 2:
            metadata['robot_a_pose'] = {k: latest.get(k) for k in ('pose','joints','received_at','user_index','tool_index')}
            metadata['robot_a_pose_note'] = '附近时刻的机械臂反馈，不是硬件同步曝光位姿。'
        try:
            photo, sidecar, info = save_capture(BASE / 'data' / 'camera_captures', packet['frame'], metadata)
        except (OSError, ValueError, TypeError, cv2.error) as error:
            QMessageBox.warning(self, '留样未完成，暂停检测', str(error))
            return
        self.confirmed_task = None
        self.set_images([str(photo)])
        self.measure_mode.setCurrentIndex(0)
        self.selection_note.setText('已冻结本次相机照片。点击“开始检测”，再按图上编号选择要测的孔。')
        self.log('相机原图已留样：' + str(photo) + '；拍摄信息：' + str(sidecar))
        if self.records_dialog:
            self.records_dialog.refresh()

    def show_camera_parameters(self):
        from .devices_view import _registered_backends
        self.camera_parameters_dialog = CameraParametersDialog(_registered_backends.get('camera'), self)
        self.camera_parameters_dialog.show()

    def open_capture_archive(self):
        folder = BASE / 'data' / 'camera_captures'
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def show_readiness(self):
        from .devices_view import _registered_backends
        result = self.current_result or {}
        photo = result.get('image_path')
        info = capture_information(photo) if photo else None
        archived = False
        if info:
            try: archived = hashlib.sha256(Path(photo).read_bytes()).hexdigest() == info.get('image_sha256')
            except OSError: pass
        task = self.confirmed_task or {}
        confirmed = bool(photo and task.get('image') == photo and
                         task.get('selection_mode') == ('automatic' if self.measure_mode.currentIndex() == 0 else 'manual') and
                         task.get('model') == self.active_models.get('bore') and
                         {t['id'] for t in task.get('targets', [])} == self.current_selected_ids())
        if confirmed:
            try: confirmed = hashlib.sha256(Path(photo).read_bytes()).hexdigest() == task.get('image_sha256')
            except OSError: confirmed = False
        rows = readiness_rows(_registered_backends, archived, confirmed)
        self.btn_send.setEnabled(False)
        self.readiness_dialog = ReadinessDialog(rows, self)
        self.readiness_dialog.show()

    def review_hole(self, row, column=0):
        result = self.current_result or {}
        hid = self.table.item(row, 0).text() if self.table.item(row, 0) else ''
        hole = next((h for h in result.get('fitted_holes', []) + result.get('detected_holes', []) if h['id'] == hid), None)
        if hole is None:
            self.review_warning.setText('该行暂无检测结果，不能推定漏检孔的实际位置。请复核整张原图。')
            return
        original = imread_unicode(result.get('image_path') or self.paths[self.current_index])
        if original is None:
            QMessageBox.warning(self, '照片无法读取', '请重新选择原始照片后复核。')
            return
        self.hole_review_dialog = HoleReviewDialog(original, hole, self)
        self.hole_review_dialog.show()

    def render_view(self, *_):
        self.lbl_zoom.setText(f'{self.sld_zoom.value()}%')
        if self.display_photo is None:
            self.photo_mapping = None
            self.image_label.clear()
            self.image_label.setText('照片未能读取，请重新选择本机照片。' if self.paths else '请选择一组测试照片')
            return
        size = self.image_label.size()
        if min(size.width(), size.height()) < 60:
            return
        display_result = dict(self.current_result or {})
        display_result['holes'] = display_result.get('fitted_holes', [])
        crop = holes_bbox(display_result, self.display_photo.shape) if self.chk_fit.isChecked() else None
        if crop is None:
            crop = (0, 0, self.display_photo.shape[1], self.display_photo.shape[0])
        crop = zoom_rect(crop, self.sld_zoom.value() / 100.0, self.display_photo.shape)
        canvas, mapping = compose(self.display_photo, (size.width(), size.height()), crop_rect=crop)
        if mapping:
            for hole in display_result.get('fitted_holes', []):
                cx, cy = _map_pts([hole['center_px']], mapping)[0]
                selected = hole['id'] in self.current_selected_ids()
                text = f"{hole['id']} {'SELECT' if selected else 'SKIP'} {hole['confidence']:.2f}"
                fs = 0.62
                (width, height), baseline = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, fs, 1)
                if not (mapping['ox'] <= cx <= mapping['ox'] + mapping['tw'] and mapping['oy'] <= cy <= mapping['oy'] + mapping['th']):
                    continue
                tx = int(np.clip(cx + 10, mapping['ox'] + 3, max(mapping['ox'] + 3, mapping['ox'] + mapping['tw'] - width - 8)))
                ty = int(np.clip(cy - 14, mapping['oy'] + height + 5, mapping['oy'] + mapping['th'] - 5))
                cv2.rectangle(canvas, (tx - 4, ty - height - 4), (tx + width + 4, ty + baseline + 4), (20, 35, 56), -1)
                color = ((130, 255, 150) if selected else (185, 185, 185)) if hole.get('reliable_center') else (50, 160, 255)
                cv2.putText(canvas, text, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, fs, color, 1, cv2.LINE_AA)
        self.photo_mapping = mapping
        self.image_label.setPixmap(bgr_to_pixmap(canvas))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'image_label'):
            self.render_view()

    @Slot()
    def start_batch(self):
        if self.batch_running or self.bridge.busy or not self.paths:
            return
        self.refresh_model_summary()
        try:
            self.active_group = self.records.begin(self.paths, self.active_models['bore'])
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, '实验记录未能保存', str(error))
            return
        self.hole_selections.clear()
        self.confirmed_task = None
        self.batch_running = True
        self.completed_count = 0
        self.record_error = False
        self.results = [None] * len(self.paths)
        self.batch_progress.setValue(0)
        self.detector.output_dir = BASE / 'results' / 'gui_batches' / datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        self.show_index(0)
        self.set_status('正在检测这一组照片', '#a86613')
        self.set_controls()
        self.thread = QThread(self)
        self.worker = BatchWorker(self.detector, self.paths)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.log)
        self.worker.result_ready.connect(self.receive_result)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.finish_batch)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    @Slot(int, object)
    def receive_result(self, index, result):
        self.results[index] = result
        self.completed_count += 1
        self.batch_progress.setValue(self.completed_count)
        report = result.get('raw_report')
        if report is None:
            report = {'image': self.paths[index], 'model': self.active_models['bore'],
                      'selected_bores': [], 'centers': [], 'bore_selected_count': 0,
                      'part_max_confidence': 0, 'warnings': result.get('errors', []),
                      'errors': result.get('errors', []), 'result_image': ''}
        capture_info = capture_information(self.paths[index])
        if capture_info:
            report['capture_archive'] = capture_info
        result['record_report'] = report
        try:
            self.records.update(self.active_group, report=report)
            self.save_batch()
        except OSError as error:
            self.record_error = True
            self.log(f'实验记录写入失败：{error}')
        for warning in result.get('warnings', []):
            self.log(f"{Path(self.paths[index]).name}：{warning}")
        for error in result.get('errors', []):
            self.log(f"{Path(self.paths[index]).name}：检测异常，{error}")
        self.log(f"{Path(self.paths[index]).name}：识别 {result.get('detections', 0)} 个孔，拟合 {result.get('center_count', 0)} 个圆心。")
        if index == self.current_index:
            self.show_index(index)
        if self.records_dialog:
            self.records_dialog.refresh()

    def save_batch(self):
        reports = [result.get('record_report') or result['raw_report'] for result in self.results
                   if result and (result.get('record_report') or result.get('raw_report'))]
        temporary = LAST_BATCH.with_suffix('.tmp')
        temporary.write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(LAST_BATCH)

    @Slot()
    def finish_batch(self):
        self.batch_running = False
        self.thread = None
        self.worker = None
        failures = sum(bool(result and result.get('errors')) for result in self.results)
        complete = self.completed_count == len(self.paths)
        status = '未完成，请复核' if not complete or self.record_error else ('已完成（含异常）' if failures else '已完成')
        try:
            self.records.update(self.active_group, status=status)
        except OSError as error:
            self.record_error = True
            self.log(f'实验记录写入失败：{error}')
        self.set_controls()
        self.show_index(self.current_index)
        if self.record_error:
            self.set_status('结果已生成，实验记录保存失败', '#bf3e35')
        else:
            self.set_status(f'本组完成 {self.completed_count}/{len(self.paths)} 张' + (f'，{failures} 张异常' if failures else ''), '#a86613' if failures else '#16834b')
        self.log('本组结果已追加到实验记录；可用上一张、下一张查看每张结果。'
                 if not self.record_error else '检测结果已生成，实验记录写入问题需要处理。')
        if self.records_dialog:
            self.records_dialog.refresh()

    def restore_last_batch(self):
        try:
            reports = json.loads(LAST_BATCH.read_text(encoding='utf-8'))
            reports = [report for report in reports if isinstance(report, dict) and report.get('image')]
            if not reports:
                return
            self.paths = [report['image'] for report in reports]
            self.results = [_report_to_result(report) for report in reports]
            self.selector.blockSignals(True)
            self.selector.addItems([f'{index + 1}. {Path(path).name}' for index, path in enumerate(self.paths)])
            self.selector.blockSignals(False)
            self.completed_count = len(reports)
            self.batch_progress.setRange(0, len(reports))
            self.batch_progress.setValue(len(reports))
            self.show_index(0)
            self.log(f'已恢复上次 {len(reports)} 张检测结果，未新增实验记录。')
        except (OSError, ValueError, KeyError, TypeError):
            pass

    @Slot()
    def show_records(self):
        if self.records_dialog is None:
            self.records_dialog = RecordsDialog(self, records=self.records)
        self.records_dialog.refresh()
        self.records_dialog.show()
        self.records_dialog.raise_()
        self.records_dialog.activateWindow()

    def show_simulation(self):
        if not hasattr(self, 'simulation_dialog'):
            self.simulation_dialog = SimulationDialog(self)
        self.simulation_dialog.show()
        self.simulation_dialog.raise_()
        self.simulation_dialog.activateWindow()

    def show_model_management(self):
        self.model_dialog.show()
        self.model_dialog.raise_()
        self.model_dialog.activateWindow()

    def show_device_panel(self):
        dialog = show_devices(self)
        if not getattr(dialog, '_main_status_bound', False):
            dialog.connection_status_changed.connect(self.device_status_changed)
            dialog._main_status_bound = True

    def device_status_changed(self, device, connected, note):
        self.device_states[device] = connected
        if not hasattr(self, 'device_notes'):
            self.device_notes = {}
        self.device_notes[device] = note
        names = {'camera':'工业相机', 'robot_a':'拍照机械臂 A', 'robot_b':'测量机械臂 B'}
        self.connection_line.setText('　｜　'.join(
            names[key]+('：只读反馈已连接' if key == 'robot_b' and self.device_states.get(key)
                        else '：已连接' if self.device_states.get(key) else '：反馈过期／已断开' if '过期' in self.device_notes.get(key, '') else '：未连接')
            for key in names))
        self.log(names[device]+'：'+note)

    def refresh_device_status(self):
        from .devices_view import _registered_backends
        names = {'camera':'工业相机', 'robot_a':'拍照机械臂 A', 'robot_b':'测量机械臂 B'}
        descriptions = []
        for key, name in names.items():
            backend = _registered_backends.get(key)
            connected = bool(backend and backend.is_connected())
            self.device_states[key] = connected
            detail = '只读反馈已连接' if key == 'robot_b' and connected else '设备已打开' if key == 'camera' and connected else '已连接' if connected else '未连接'
            if key == 'camera' and connected and getattr(backend, 'device_name', ''):
                detail += '（' + backend.device_name + '）'
            descriptions.append(name + '：' + detail)
        self.connection_line.setText('　｜　'.join(descriptions))

    @Slot()
    def open_results(self):
        folder = BASE / 'results'
        folder.mkdir(exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    @Slot()
    def open_current_result(self, *_):
        path = (self.current_result or {}).get('result_image')
        if path and Path(path).is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def closeEvent(self, event):
        if self.batch_running:
            self.log('当前这组照片仍在检测，完成后即可关闭。')
            event.ignore()
            return
        if self.bridge.busy:
            self.log('训练数据管理窗口仍在运行，请先在任务栏返回并关闭管理窗口，再退出软件。')
            event.ignore()
            return
        if self.camera_worker and self.camera_worker.isRunning():
            self.camera_worker.stop()
            self.log('正在停止相机采集，采集结束后可关闭。')
            event.ignore()
            return
        self.bridge.detach()
        from .devices_view import _registered_backends
        for backend in _registered_backends.values():
            backend.disconnect()
        self.detector.release()
        event.accept()

