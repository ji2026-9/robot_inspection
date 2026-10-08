"""Friend's visual layout, backed by the existing production detector."""
from __future__ import annotations

from datetime import datetime
import threading
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import QObject, QSize, QThread, Qt, QTimer, Signal, Slot, QUrl
from PySide6.QtGui import QDesktopServices, QImage, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QFileDialog,
    QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QMainWindow, QDialog,
    QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea,
    QFrame, QSizePolicy, QSlider, QSplitter, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from experiment_records import ExperimentRecords
from .devices_view import show_devices
from .records_view import RecordsDialog
from .training_bridge import TrainingBridge
from .simulation_view import SimulationDialog
from .view_render import compose, holes_bbox, zoom_rect, _map_pts
from .vision_workspace import CameraPreviewWorker, ClickablePhoto   # [canvas-live]
from .vision import HoleDetector, _report_to_result, draw_result, imread_unicode

BASE = Path(__file__).resolve().parents[1]
# [merge-history] 历史批次原来单独归档在 last_batch.json / batches/index.jsonl，
# 内容和「实验记录」重复。现在只保留实验记录这一份历史：不再写这些归档文件，
# 磁盘上已有的旧文件也不会删除。

STYLE = r"""
QMainWindow, QDialog { background: #eef2f7; color: #22324a; }
QLabel { color: #22324a; }
#topBar { background: #0f3d78; }
#appTitle { color: #ffffff; font-size: 21px; font-weight: 700; }
#appSub { color: #aecbf0; font-size: 12px; }
#modelChip { color: #d9e8ff; font-size: 12px; }
QGroupBox { background: #ffffff; border: 1px solid #dde5ee; border-radius: 10px;
            margin-top: 14px; padding: 12px 12px 10px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; color: #17457f; }
QPushButton { background: #ffffff; border: 1px solid #c7d5e5; border-radius: 8px;
              padding: 8px 12px; color: #16324f; font-weight: 600; }
QPushButton:hover { background: #eef5ff; border-color: #7ba7dd; }
QPushButton:pressed { background: #deeafa; }
QPushButton:disabled { background: #f3f6fa; color: #9aa8ba; border-color: #e3e9f1; }
QPushButton#primary { background: #1256a8; border-color: #1256a8; color: #ffffff;
                      padding: 11px 12px; font-size: 14px; }
QPushButton#primary:hover { background: #0e4a93; }
QPushButton#primary:disabled { background: #b9cbe4; border-color: #b9cbe4; }
QPushButton#flat { background: transparent; border: none; color: #35618f; padding: 4px 8px; }
QPushButton#flat:hover { color: #1256a8; }
QComboBox { background: #ffffff; color: #16324f; border: 1px solid #c7d5e5;
            border-radius: 7px; padding: 5px 8px; }
QComboBox QAbstractItemView { background: #ffffff; color: #16324f; selection-background-color: #dbeafe; }
QCheckBox, QRadioButton { color: #22324a; }
QLabel#bigCount { font-size: 15px; font-weight: 700; color: #17457f; }
QLabel#systemState { font-size: 15px; font-weight: 700; color: #12805a; }
QLabel#warnNote { color: #9a6212; font-size: 11px; }
QLabel#hintNote, QLabel#legend { color: #6d7f96; font-size: 11px; }
QLabel#canvas { background: #f7f9fc; border: 1px solid #dde5ee; border-radius: 8px; color: #8a97a8; }
QLabel#paneCaption { color: #5a6b82; font-size: 11px; font-weight: 600; }
QSplitter#visualSplit::handle { background: #cfdae8; }
QSplitter#visualSplit::handle:hover { background: #9fb6d1; }
QTableWidget { background: #ffffff; color: #22324a; alternate-background-color: #f5f8fc;
               border: none; gridline-color: #e6ecf3; }
QTableWidget::item { color: #22324a; padding: 4px; }
QHeaderView::section { background: #eef3fa; color: #17457f; padding: 7px;
                       border: none; border-bottom: 1px solid #d8e2ee; font-weight: 600; }
QProgressBar { border: 1px solid #d8e2ee; border-radius: 7px; background: #f4f7fb;
               text-align: center; color: #17457f; min-height: 18px; }
QProgressBar::chunk { background: #2f7fd6; border-radius: 6px; }
QScrollArea { border: none; background: transparent; }
#diagPanel { background: #ffffff; border: 1px solid #dde5ee; border-radius: 10px; }
QLabel#diagTitle { color: #17457f; font-weight: 600; }
QPlainTextEdit#log { background: #f8fafd; color: #33415a;
                     border: 1px solid #e4eaf2; border-radius: 8px;
                     padding: 8px; font-size: 11px;
                     font-family: 'Consolas', 'Microsoft YaHei UI'; }
QFrame#statusBar { background: #f3f6fa; border-top: 1px solid #dde5ee; }
QLabel#deviceLine { color: #8b4b30; font-weight: 600; }
"""


def bgr_to_pixmap(bgr):
    rgb = cv2.cvtColor(np.ascontiguousarray(bgr), cv2.COLOR_BGR2RGB)
    h, w, _ = rgb.shape
    return QPixmap.fromImage(QImage(rgb.data, w, h, rgb.strides[0], QImage.Format.Format_RGB888).copy())


class PanePhoto(ClickablePhoto):
    """[split-view] 画布尺寸一变就通知重画。

    拖动分隔条、隐藏实时格、缩放窗口都会改变这一格的尺寸；如果不重画，
    点击时用的坐标映射还是旧的，点孔就会点偏。

    """

    resized = Signal()

    def sizeHint(self):
        # 交给分隔条决定大小；否则 QLabel 会拿 pixmap 尺寸当期望值，拖起来又卡又跳。
        return QSize(160, 160)

    def minimumSizeHint(self):
        return QSize(120, 120)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.resized.emit()


class PaneLabel(QLabel):
    """[split-view] 只显示画面的格子（实时那一格），尺寸完全由分隔条决定。"""

    def sizeHint(self):
        return QSize(160, 160)

    def minimumSizeHint(self):
        return QSize(120, 120)


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
        self.display_photo = None
        self.display_crop = None
        self.thread = None
        self.worker = None
        self.active_group = None
        self.completed_count = 0
        self.record_error = False
        self.records_dialog = None
        # [local patch] remember the last used photo folder across restarts
        _marker = BASE / 'last_photo_dir.txt'
        try:
            _saved = Path(_marker.read_text(encoding='utf-8').strip()) if _marker.is_file() else None
        except OSError:
            _saved = None
        if _saved is not None and _saved.is_dir():
            self.last_dir = str(_saved)
        else:
            _pictures = Path.home() / 'Pictures'
            self.last_dir = str(_pictures) if _pictures.is_dir() else str(BASE)
        self.batch_running = False
        self._build_ui()
        self.refresh_model_summary()
        # [local patch] start with a CLEAN workspace. History is only shown
        # when the user opens 实验记录 and loads a group back into the workspace.
        self.log('系统就绪，检测使用当前正式模型，孔置信度保留阈值为 0.5。')
        self.log('工作区为空。如需查看以前的检测结果，请点「实验记录」，'
                 '选中一组后「载入到工作区」。')
        self.log('设备信息不再保存到本机：相机插上即自动识别，机械臂按当前电脑实际 IP 填写。')
        self.set_controls()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- 顶部标题栏 ----
        top = QFrame()
        top.setObjectName('topBar')
        top.setFixedHeight(70)   # [local patch]
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(20, 8, 20, 8)
        titles = QVBoxLayout()
        titles.setSpacing(3)      # [local patch]
        app_title = QLabel('双机械臂孔检测系统')
        app_title.setObjectName('appTitle')
        app_sub = QLabel('工业箱体孔位识别 · 椭圆拟合 · 孔心定位')
        app_sub.setObjectName('appSub')
        titles.addWidget(app_title)
        titles.addWidget(app_sub)
        top_layout.addLayout(titles)
        top_layout.addStretch(1)
        self.model_label = QLabel()
        self.model_label.setObjectName('modelChip')
        self.model_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        top_layout.addWidget(self.model_label)
        root.addWidget(top)

        # ---- 主体：左操作 / 中图像 / 右结果 ----
        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(14, 12, 14, 10)
        body_layout.setSpacing(12)
        root.addWidget(body, 1)

        left_inner = QWidget()
        left_layout = QVBoxLayout(left_inner)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)

        actions = QGroupBox('操作')
        actions_layout = QVBoxLayout(actions)
        actions_layout.setSpacing(8)
        self.btn_select = QPushButton('① 选择照片')
        self.btn_select.setObjectName('primary')
        # [camera-sync] 直接从工业相机拍一张
        self.btn_capture = QPushButton('用工业相机拍照')
        self.btn_capture.setToolTip('从 Orbbec Gemini 335Le 取一帧彩色图，无损留样后直接放进工作区。')
        self.btn_detect = QPushButton('② 开始检测')
        self.btn_detect.setObjectName('primary')
        self.btn_send = QPushButton('③ 发送测量任务')
        self.btn_send.setEnabled(False)
        self.btn_send.setToolTip('先点「测量就绪检查」：标定、手眼坐标转换、测针 TCP 等未完成项全部满足后才会开放下发。')
        # [camera-sync] 拍照按钮排在“选择照片”后面
        for _button in (self.btn_select, self.btn_capture, self.btn_detect, self.btn_send):
            actions_layout.addWidget(_button)
        left_layout.addWidget(actions)

        photos = QGroupBox('本组照片')
        photos_layout = QVBoxLayout(photos)
        photos_layout.setSpacing(5)
        photos_layout.setContentsMargins(10, 6, 10, 8)   # [compact-left]
        self.page_label = QLabel('未选择照片')
        self.page_label.setObjectName('bigCount')
        self.selector = QComboBox()
        self.selector.setMinimumHeight(28)
        navigation = QHBoxLayout()
        navigation.setSpacing(5)
        self.previous_button = QPushButton('上一张')
        self.next_button = QPushButton('下一张')
        for _nav_button in (self.previous_button, self.next_button):
            _nav_button.setFixedHeight(30)
        navigation.addWidget(self.previous_button)
        navigation.addWidget(self.next_button)
        self.batch_progress = QProgressBar()
        self.batch_progress.setRange(0, 1)
        self.batch_progress.setValue(0)
        self.batch_progress.setFormat('本组进度 %v/%m')
        self.batch_progress.setMaximumHeight(22)   # [compact-left]
        photos_layout.addWidget(self.page_label)
        photos_layout.addWidget(self.selector)
        photos_layout.addLayout(navigation)
        photos_layout.addWidget(self.batch_progress)
        left_layout.addWidget(photos)

        others = QGroupBox('其他功能')
        others_layout = QGridLayout(others)          # 两列   # [compact-left]
        others_layout.setSpacing(6)
        others_layout.setContentsMargins(10, 6, 10, 8)   # [compact-left]
        self.btn_devices = QPushButton('设备连接')
        self.btn_records = QPushButton('实验记录')
        self.btn_models = QPushButton('模型与数据管理')
        self.btn_simulation = QPushButton('模拟测量动画')
        self.btn_results = QPushButton('打开结果文件夹')
        # [fusion-sync] 来自朋友分支的“测量就绪检查”
        self.btn_readiness = QPushButton('测量就绪检查')
        self.btn_readiness.setToolTip('列出相机 / 机械臂 / 标定 / 测孔清单的完成情况，未完成的项不会隐藏。')
        # [merge-history] 「打开历史批次」已并入「实验记录」；
        # 「相机实时预览」已并入视觉检测区的「相机实时画面 / 抓拍」。
        for _index, _button in enumerate((self.btn_devices, self.btn_records,
                                          self.btn_models, self.btn_simulation,
                                          self.btn_results,
                                          self.btn_readiness)):
            _button.setMinimumHeight(32)
            others_layout.addWidget(_button, _index // 2, _index % 2)
        left_layout.addWidget(others)
        # 每张卡片给一个真实最小高度：诊断信息展开时左栏改为滚动，
        # 而不是把卡片压成一条看不清的细缝。   # [compact-left]
        actions.setMinimumHeight(222)
        photos.setMinimumHeight(158)
        others.setMinimumHeight(184)
        left_layout.addStretch(1)
        # [local patch] keep the left column reachable when 诊断信息 expands
        left = QScrollArea()
        left.setWidgetResizable(True)
        left.setWidget(left_inner)
        left.setFrameShape(QFrame.Shape.NoFrame)
        left.setFixedWidth(266)   # [compact-left]
        left.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        left.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        body_layout.addWidget(left)

        visual = QGroupBox('视觉检测区')
        visual_layout = QVBoxLayout(visual)
        visual_layout.setSpacing(8)
        # [split-view] 视觉检测区拆成左右两格：左边相机实时画面（只看），右边检测结果
        # （标定/识别后的孔图，点孔选本次要测的孔）。中间分隔条可拖，关掉实时时结果图占满。
        self.visual_split = QSplitter(Qt.Orientation.Horizontal)
        self.visual_split.setObjectName('visualSplit')
        # [split-view] 不允许把某一格拖成 0（拖没了就找不回来），分隔条加宽一点好抓
        self.visual_split.setChildrenCollapsible(False)
        self.visual_split.setHandleWidth(8)

        self.live_column = QWidget()
        live_layout = QVBoxLayout(self.live_column)
        live_layout.setContentsMargins(0, 0, 0, 0)
        live_layout.setSpacing(4)
        self.live_caption = QLabel('实时画面（未开启）')
        self.live_caption.setObjectName('paneCaption')
        self.live_view = PaneLabel('勾选下方「相机实时画面」\n在这里看相机实时画面（只看，不点选）')
        self.live_view.setObjectName('canvas')
        self.live_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.live_view.setMinimumSize(150, 200)
        self.live_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        live_layout.addWidget(self.live_caption)
        live_layout.addWidget(self.live_view, 1)
        self.live_column.setMinimumWidth(160)

        self.result_column = QWidget()
        result_layout = QVBoxLayout(self.result_column)
        result_layout.setContentsMargins(0, 0, 0, 0)
        result_layout.setSpacing(4)
        self.result_caption = QLabel('检测结果（标定好的孔）')
        self.result_caption.setObjectName('paneCaption')
        self._result_caption_base = '检测结果（标定好的孔）'
        self.result_view = PanePhoto('请选择一组测试照片')
        self.result_view.setObjectName('canvas')
        self.result_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.result_view.clicked.connect(self.canvas_clicked)     # [split-view]
        self.result_view.resized.connect(self.render_view)        # [split-view] 尺寸变了就重算坐标映射
        self.result_view.setMinimumSize(150, 200)
        self.result_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        result_layout.addWidget(self.result_caption)
        result_layout.addWidget(self.result_view, 1)
        self.result_column.setMinimumWidth(220)

        self.visual_split.addWidget(self.live_column)
        self.visual_split.addWidget(self.result_column)
        self.visual_split.setStretchFactor(0, 4)
        self.visual_split.setStretchFactor(1, 6)
        self.visual_split.splitterMoved.connect(self.render_view)  # [split-view] 拖动分隔条也跟着重画
        self.live_column.hide()          # [split-view] 默认不显示实时，结果图先占满整格
        visual_layout.addWidget(self.visual_split, 1)
        self.image_label = self.result_view      # [split-view] 兼容旧调用，指向结果格
        image_tools = QHBoxLayout()
        self.image_info = QLabel('尚未选择照片')
        # [canvas-live] 视觉检测区里直接看实时、直接抓拍
        self.chk_live = QCheckBox('相机实时画面')
        self.chk_live.setToolTip('勾选后左边这一格显示工业相机实时画面；预览本身不写文件。')
        self.chk_live.toggled.connect(self.toggle_live_preview)
        self.btn_snap = QPushButton('抓拍')
        self.btn_snap.setToolTip('把当前实时画面无损留样，放进工作区并在右格显示（不自动检测）。')
        self.btn_snap.clicked.connect(self.snap_from_camera)
        self.chk_fit = QCheckBox('适应孔区域')
        self.chk_fit.setChecked(True)
        self.sld_zoom = QSlider(Qt.Orientation.Horizontal)
        self.sld_zoom.setRange(100, 300)
        self.sld_zoom.setValue(100)
        self.sld_zoom.setMaximumWidth(150)
        self.lbl_zoom = QLabel('100%')
        image_tools.addWidget(self.image_info, 1)
        image_tools.addWidget(self.chk_live)
        image_tools.addWidget(self.btn_snap)
        image_tools.addWidget(self.chk_fit)
        image_tools.addWidget(QLabel('缩放'))
        image_tools.addWidget(self.sld_zoom)
        image_tools.addWidget(self.lbl_zoom)
        visual_layout.addLayout(image_tools)
        legend = QLabel('左格：相机实时画面（只看）　｜　右格：检测结果——青色孔轮廓、黄色拟合椭圆、'
                        '红色十字圆心；点右格的孔即可选中/取消，选中的孔椭圆变绿、圆心打勾（要测量的孔）')
        legend.setObjectName('legend')
        visual_layout.addWidget(legend)
        body_layout.addWidget(visual, 1)

        right = QWidget()
        right.setFixedWidth(424)  # [local patch] table needs room
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(10)

        status_box = QGroupBox('AI 检测状态')
        status_layout = QVBoxLayout(status_box)
        status_layout.setSpacing(6)
        self.lbl_system = QLabel('● 系统就绪')
        self.lbl_system.setObjectName('systemState')
        self.lbl_detected = QLabel('已识别：— / 4')
        self.lbl_centers = QLabel('圆心：—')
        self.lbl_avg = QLabel('平均置信度：—')
        self.lbl_part = QLabel('part 置信度：—')
        self.lbl_constraint = QLabel('part 位置筛选：—')
        self.lbl_engine = QLabel('设备：本地 GPU / CPU')
        self.lbl_engine.setWordWrap(True)
        status_grid = QGridLayout()
        status_grid.addWidget(self.lbl_detected, 0, 0)
        status_grid.addWidget(self.lbl_centers, 0, 1)
        status_grid.addWidget(self.lbl_avg, 1, 0)
        status_grid.addWidget(self.lbl_constraint, 1, 1)
        status_layout.addWidget(self.lbl_system)
        status_layout.addLayout(status_grid)
        right_layout.addWidget(status_box)

        task_box = QGroupBox('孔位与测量准备')
        task_layout = QVBoxLayout(task_box)
        task_layout.setSpacing(6)
        self.task_note = QLabel('孔号按当前图像位置排序，不是永久物理孔号；勾选孔号表示“本次要测量这个孔”。')
        self.task_note.setObjectName('warnNote')
        self.task_note.setWordWrap(True)
        self.measure_targets = set()      # [fusion-sync] 本次要测量的孔
        self._filling_table = False       # [fusion-sync] 防止程序填表误触发勾选回调
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(['孔号 ☑', '置信度', '图像圆心 px', '定位状态', '三维坐标'])
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(30)
        _header = self.table.horizontalHeader()
        _header.setStretchLastSection(False)
        for _column in (0, 1, 3, 4):
            _header.setSectionResizeMode(_column, QHeaderView.ResizeMode.ResizeToContents)
        _header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        task_layout.addWidget(self.task_note)
        task_layout.addWidget(self.table, 1)
        self.coordinate_note = QLabel('当前圆心为图像像素坐标；三维定位与测量机械臂坐标待标定。')
        self.coordinate_note.setObjectName('hintNote')
        self.coordinate_note.setWordWrap(True)
        task_layout.addWidget(self.coordinate_note)
        right_layout.addWidget(task_box, 1)
        body_layout.addWidget(right)

        # ---- 模型与数据管理弹窗（保留原功能）----
        self.model_dialog = QDialog(self)
        self.model_dialog.setWindowTitle('模型与数据管理')
        self.model_dialog.resize(560, 230)
        management = QVBoxLayout(self.model_dialog)
        note = QLabel('添加照片并标注 → 训练候选模型 → 查看验证结果\n'
                      '正式模型仍按验证结果选择，验证通过后才启用。')
        note.setWordWrap(True)
        management.addWidget(note)
        self.btn_dataset = QPushButton('添加训练数据 / 自动更新')
        self.btn_validation = QPushButton('训练验证结果')
        management.addWidget(self.btn_dataset)
        management.addWidget(self.btn_validation)

        # ---- 底部状态栏 ----
        bottom = QFrame()
        bottom.setObjectName('statusBar')
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(16, 6, 16, 8)
        bottom_layout.setSpacing(4)
        bar = QHBoxLayout()
        self.connection_line = QLabel('工业相机：未连接　｜　拍照机械臂 A：未连接　｜　测量机械臂 B：未连接')
        self.connection_line.setObjectName('deviceLine')
        diagnostics_toggle = QPushButton('▶ 诊断信息')
        diagnostics_toggle.setObjectName('flat')
        diagnostics_toggle.setCheckable(True)
        bar.addWidget(self.connection_line, 1)
        bar.addWidget(diagnostics_toggle)
        bottom_layout.addLayout(bar)
        self.diagnostics = QWidget()
        self.diagnostics.setObjectName('diagPanel')   # [local patch] light card
        # 横向紧凑布局：左边是标题与运行信息，右边是日志。   # [compact-diag]
        diagnostics_layout = QHBoxLayout(self.diagnostics)
        diagnostics_layout.setContentsMargins(12, 8, 12, 8)
        diagnostics_layout.setSpacing(14)
        diag_side = QWidget()
        diag_side.setObjectName('diagSide')
        diag_side.setFixedWidth(268)
        side_layout = QVBoxLayout(diag_side)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(4)
        diag_title = QLabel('运行日志与诊断')
        diag_title.setObjectName('diagTitle')
        self.lbl_part.setWordWrap(True)
        self.lbl_engine.setWordWrap(True)
        side_layout.addWidget(diag_title)
        side_layout.addWidget(self.lbl_part)
        side_layout.addWidget(self.lbl_engine)
        side_layout.addStretch(1)
        diagnostics_layout.addWidget(diag_side)
        self.logbox = QPlainTextEdit()
        self.logbox.setObjectName('log')
        self.logbox.setReadOnly(True)
        self.logbox.setFixedHeight(92)   # [compact-diag]
        diagnostics_layout.addWidget(self.logbox, 1)
        self.diagnostics.hide()
        bottom_layout.addWidget(self.diagnostics)
        root.addWidget(bottom)

        self.device_states = {}

        # ---- 信号 ----
        self.btn_select.clicked.connect(self.select_images)
        self.btn_capture.clicked.connect(self.capture_from_camera)   # [camera-sync]
        self.btn_detect.clicked.connect(self.start_batch)
        self.btn_devices.clicked.connect(self.show_device_panel)
        self.btn_records.clicked.connect(self.show_records)
        self.btn_dataset.clicked.connect(self.bridge.open_dataset)
        self.btn_validation.clicked.connect(self.bridge.open_validation)
        self.btn_results.clicked.connect(self.open_results)
        self.btn_models.clicked.connect(self.show_model_management)
        self.btn_simulation.clicked.connect(self.show_simulation)
        self.btn_readiness.clicked.connect(self.show_readiness)   # [fusion-sync]
        self.previous_button.clicked.connect(lambda: self.show_index(self.current_index - 1))
        self.next_button.clicked.connect(lambda: self.show_index(self.current_index + 1))
        self.selector.currentIndexChanged.connect(self.show_index)
        self.chk_fit.toggled.connect(self.render_view)
        self.sld_zoom.valueChanged.connect(self.render_view)
        self.table.cellDoubleClicked.connect(self.open_current_result)
        self.table.itemChanged.connect(self.measure_target_changed)   # [fusion-sync]
        diagnostics_toggle.toggled.connect(self.diagnostics.setVisible)
        diagnostics_toggle.toggled.connect(lambda expanded: diagnostics_toggle.setText(
            '▼ 诊断信息' if expanded else '▶ 诊断信息'))
        # [device-state] 定时用驱动真值刷新状态栏，不再依赖“上一次点击”
        self.device_timer = QTimer(self)
        self.device_timer.setInterval(1500)
        self.device_timer.timeout.connect(self.refresh_device_states)
        self.device_timer.start()
        self.refresh_device_states()
        # [camera-sync] 启动后延迟一点在后台自动连一次相机（不阻塞界面）
        self._auto_connect_state = {'done': False, 'ok': False, 'error': ''}
        self._auto_connect_checks = 0
        QTimer.singleShot(1200, self.auto_connect_camera)
        # [canvas-live] 视觉检测区实时画面的刷新定时器
        self.live_worker = None
        self.live_frame = None
        self.live_timer = QTimer(self)
        self.live_timer.setInterval(40)
        self.live_timer.timeout.connect(self.update_live_frame)
        QShortcut(QKeySequence('Ctrl+O'), self, activated=self.select_images)
        QShortcut(QKeySequence('F5'), self, activated=self.start_batch)

    def measure_target_changed(self, item):
        """[fusion-sync] 勾选孔号 = 本次要测量这个孔。"""
        if self._filling_table or item.column() != 0:
            return
        hid = f'H{item.row() + 1:02d}'
        if item.checkState() == Qt.CheckState.Checked:
            self.measure_targets.add(hid)
        else:
            self.measure_targets.discard(hid)
        chosen = '、'.join(sorted(self.measure_targets)) if self.measure_targets else '（空）'
        self.log(f'本次测量清单：{chosen}')
        self.render_view()      # [select-mark] 勾表格也要在图上显示出来

    def confirmed_targets(self):
        """[fusion-sync] 勾选且圆心可靠的孔（对齐朋友分支 selected_targets 的校验口径）。"""
        result = self.current_result or {}
        reliable = {hole['id'] for hole in result.get('fitted_holes', [])
                    if hole.get('reliable_center')}
        return sorted(self.measure_targets & reliable)

    @Slot()
    def show_readiness(self):
        """[fusion-sync] 测量就绪检查：如实列出未完成项，不因连接成功就放行。"""
        try:
            from .measurement_readiness import readiness_rows, ReadinessDialog
            from .devices_view import _registered_backends
        except ImportError as error:
            QMessageBox.warning(self, '测量就绪检查不可用', str(error))
            return
        # [camera-sync] “本次原图留样”以真实留样为准（capture_archive 写的无损原图 + 同批 JSON）
        has_capture = bool(getattr(self, 'last_capture', None))
        rows = readiness_rows(_registered_backends, has_capture,
                              bool(self.confirmed_targets()))
        self.log('打开测量就绪检查：未完成的标定项不会被隐藏，发送测量任务保持禁用。')
        ReadinessDialog(rows, self).exec()

    def camera_settings(self):
        """[camera-sync] 取「设备连接 → 工业相机」本次运行填写的配置。

        [no-local-config] 配置不再从本机文件读取，只取本次运行内存里的内容；
        没有填写时返回空字典，相机按实际接入的设备自动识别。
        """
        try:
            from .devices_view import current_settings
            return current_settings().get('camera', {})
        except (ImportError, OSError, ValueError, KeyError):
            return {}

    @Slot()
    def capture_from_camera(self):
        """[camera-sync] 用工业相机拍一张：交给视觉检测区同一套「抓拍」逻辑。

        [merge-capture] 以前这里和「抓拍」各写了一份取流代码，实时画面开着
        的时候两边抢同一台相机。现在统一走 snap_from_camera：实时画面开着
        就直接冻结当前帧，没开才临时取流。
        """
        self.snap_from_camera(source='用工业相机拍照')

    def auto_connect_camera(self):
        """[camera-sync] 后台连一次相机；连不上只记录原因，不改任何显示状态。"""
        backend = self._device_backends().get('camera')
        if backend is None:
            self.log('未发现 Orbbec 相机驱动（未安装 OrbbecSDK），相机保持未连接。')
            return
        try:
            if backend.is_connected():
                self.refresh_device_states()
                return
        except Exception:      # noqa: BLE001 - 驱动异常不能影响启动
            pass
        state = self._auto_connect_state
        settings = self.camera_settings()

        def worker():
            try:
                state['ok'] = bool(backend.connect(settings)) and bool(backend.is_connected())
                state['error'] = '' if state['ok'] else (getattr(backend, 'last_error', '') or '未知原因')
            except Exception as error:      # noqa: BLE001
                state['ok'], state['error'] = False, str(error)
            state['done'] = True

        threading.Thread(target=worker, daemon=True, name='camera-auto-connect').start()
        QTimer.singleShot(3000, self.report_auto_connect)

    def report_auto_connect(self):
        """[camera-sync] 把自动连接的结果如实写进运行日志。"""
        state = getattr(self, '_auto_connect_state', None)
        if state is None:
            return
        if not state.get('done'):
            self._auto_connect_checks = getattr(self, '_auto_connect_checks', 0) + 1
            if self._auto_connect_checks <= 5:
                QTimer.singleShot(3000, self.report_auto_connect)
            else:
                self.log('相机自动连接仍在等待设备响应，可勾选检测区的「相机实时画面」重试。')
            return
        backend = self._device_backends().get('camera')
        if state['ok']:
            name = (getattr(backend, 'device_name', '') or '相机') if backend is not None else '相机'
            serial = getattr(backend, 'device_serial', '') if backend is not None else ''
            self.log('相机已自动连接：' + name + (f'（序列号 {serial}）' if serial else ''))
        else:
            self.log('相机自动连接未成功：' + (state['error'] or '未知原因')
                     + '；可点检测区的「相机实时画面」或「设备连接 → 连接设备」重试。'
                     + '若提示连接超时，请先确认电脑与相机在同一网段（相机默认 192.168.1.10）。')
        self.refresh_device_states()

    @Slot(bool)
    def toggle_live_preview(self, on):
        """[split-view] 左侧那一格显示/关闭工业相机实时画面（右格结果图不受影响）。"""
        if on:
            if self.batch_running or self.bridge.busy:
                self.chk_live.setChecked(False)
                QMessageBox.information(self, '正在忙', '检测或训练正在进行，先等它结束再开实时画面。')
                return
            backend = self._device_backends().get('camera')
            if backend is None:
                self.chk_live.setChecked(False)
                QMessageBox.information(self, '相机未接入',
                                        '本机没有可用的 Orbbec 相机驱动。\n'
                                        '请确认已安装 OrbbecSDK，并且相机 USB 已插好。')
                return
            self.set_status('正在连接相机…', '#a86613')
            QApplication.processEvents()
            try:
                if not backend.is_connected() and not backend.connect(self.camera_settings()):
                    raise RuntimeError(backend.last_error or '相机连接失败。')
            except Exception as error:      # noqa: BLE001 - 如实报出
                self.chk_live.setChecked(False)
                self.set_status('相机连接失败', '#bf3e35')
                self.log('实时画面启动失败：' + str(error))
                QMessageBox.warning(self, '实时画面启动失败', str(error))
                return
            from .vision_workspace import CameraPreviewWorker
            self.live_worker = CameraPreviewWorker(backend, self)
            self.live_worker.failed.connect(self.live_preview_failed)
            self.live_worker.start()
            self.live_timer.start()
            self._show_live_column()
            self.set_status('相机实时画面中', '#a86613')      # [canvas-live]
            self.log('左侧已切到相机实时画面（只看、不点选；预览不写文件，点「抓拍」才留样）。')
        else:
            self.live_timer.stop()
            worker, self.live_worker = getattr(self, 'live_worker', None), None
            if worker is not None:
                worker.stop()
                worker.wait(5000)
            self.live_frame = None
            self._live_placeholder()
            if getattr(self, 'live_column', None) is not None:
                self.live_column.hide()      # [split-view] 关掉实时后，结果图占满整格
            self.log('实时画面已关闭。')
            self.refresh_current_summary()

    def _live_placeholder(self):
        """[split-view] 实时那一格的占位提示（不写文件，也不冒充已经有画面）。"""
        label = getattr(self, 'live_view', None)
        if label is None:
            return
        label.clear()
        label.setText('勾选下方「相机实时画面」\n在这里看相机实时画面（只看，不点选）')
        self.live_caption.setText('实时画面（未开启）')

    def _show_live_column(self):
        """[split-view] 打开实时格，按 45:55 摆分隔条（两边都留够最小宽度，之后可以自己拖）。"""
        if getattr(self, 'live_column', None) is None:
            return
        self.live_column.show()
        total = max(self.visual_split.width(), 420)
        live_width = max(160, min(int(total * 0.45), total - 220))
        self.visual_split.setSizes([live_width, max(220, total - live_width)])

    def _paint_live_frame(self):
        """[split-view] 把最近一帧按实时格当前大小重画（保持长宽比）。"""
        frame = getattr(self, 'live_frame', None)
        label = getattr(self, 'live_view', None)
        if frame is None or label is None:
            return
        height, width = frame.shape[:2]
        size = label.size()
        scale = min(size.width() / max(width, 1), size.height() / max(height, 1), 1.0)
        canvas = frame
        if scale < 0.999:
            canvas = cv2.resize(frame, (max(1, int(width * scale)), max(1, int(height * scale))),
                                interpolation=cv2.INTER_AREA)
        label.setPixmap(bgr_to_pixmap(canvas))

    def update_live_frame(self):
        """[canvas-live] 把最新一帧画到左侧实时格。"""
        worker = getattr(self, 'live_worker', None)
        if worker is None:
            return
        packet = worker.snapshot_packet() if hasattr(worker, 'snapshot_packet') else None
        if not packet:
            self.live_caption.setText('实时画面（相机）· 等待图像…'
                                      '（若一直没有画面，检查相机网段是否为 192.168.1.100）')
            return
        frame = packet.get('frame')
        if frame is None:
            return
        self.live_frame = frame
        self._paint_live_frame()
        size_text = f'{frame.shape[1]}×{frame.shape[0]}（未写文件）'
        # [split-view] 格子窄的时候只留短标题，别把字挤到隔壁那格去
        self.live_caption.setText('实时画面（相机）· ' + size_text
                                  if self.live_column.width() >= 330 else '实时画面（相机）')
        self.live_caption.setToolTip('实时画面（相机）· ' + size_text)

    def live_preview_failed(self, message):
        self.log('实时画面中断：' + message)
        if getattr(self, 'chk_live', None) is not None and self.chk_live.isChecked():
            self.chk_live.setChecked(False)

    @Slot()
    def snap_from_camera(self, *_args, source='视觉检测区抓拍'):
        """[canvas-live] 抓拍：无损留样后放进工作区（实时画面会被冻结成照片）。

        ``*_args`` 用来吸收按钮 clicked 信号带过来的布尔值；``source``
        只影响留样说明，不影响保存内容。
        """
        from .capture_archive import save_capture      # [canvas-live]
        live_on = getattr(self, 'chk_live', None) is not None and self.chk_live.isChecked()
        frame = getattr(self, 'live_frame', None)
        frame = frame.copy() if (live_on and frame is not None) else None
        backend = self._device_backends().get('camera')
        if frame is None:
            if backend is None:
                QMessageBox.information(self, '相机未接入', '本机没有可用的 Orbbec 相机驱动。')
                return
            self.set_status('正在从相机拍照…', '#a86613')
            QApplication.processEvents()
            try:
                if not backend.is_connected() and not backend.connect(self.camera_settings()):
                    raise RuntimeError(backend.last_error or '相机连接失败。')
                if not backend.start():
                    raise RuntimeError(backend.last_error or '相机取流失败。')
                for _attempt in range(30):
                    frame = backend.get_frame()
                    if frame is not None:
                        break
                if frame is None:
                    raise RuntimeError('相机没有返回图像。')
            except Exception as error:      # noqa: BLE001
                self.set_status('相机拍照失败', '#bf3e35')
                self.log('相机拍照失败：' + str(error))
                QMessageBox.warning(self, '相机拍照失败', str(error))
                return
            finally:
                try:
                    backend.stop()
                except Exception:
                    pass
        try:
            photo, info, data = save_capture(BASE / 'captures', frame, metadata={
                'source': f'Orbbec Gemini 335Le（工业相机 · {source}）',
                'device_serial': getattr(backend, 'device_serial', '')
                                 or getattr(backend, 'device_uid', ''),
                'profile': getattr(backend, 'profile', ''),
                'note': f'{source}；原图无损保存，不覆盖。',
            })
        except OSError as error:
            self.set_status('原图留样失败', '#bf3e35')
            self.log('原图留样失败：' + str(error))
            QMessageBox.warning(self, '原图留样失败', str(error))
            return
        self.last_capture = {'photo': str(photo), 'info': str(info)}
        self.set_images([str(photo)])
        self.set_status('相机拍照完成')
        self.log(f'相机抓拍：{photo.name}（{data["width_px"]}×{data["height_px"]}，'
                 f'SHA256 {data["image_sha256"][:12]}…）已放入工作区，可点「② 开始检测」。')

    def canvas_clicked(self, x, y):
        """[split-view] 在右格结果图上点一下 = 选中/取消这个孔（本次要测量的孔）。"""
        if self.display_photo is None:
            return
        holes = (self.current_result or {}).get('fitted_holes', [])
        if not holes:
            self.log('这张图还没有检测结果，先点「② 开始检测」，再点孔来选。')
            return
        from .vision_workspace import pick_hole
        hole_id = pick_hole(x, y, getattr(self, 'display_mapping', None), holes)
        if not hole_id:
            mapping = getattr(self, 'display_mapping', None)
            if mapping:
                px = (x - mapping['ox']) / mapping['scale'] + mapping['crop'][0]
                py = (y - mapping['oy']) / mapping['scale'] + mapping['crop'][1]
                self.log(f'点击（画布 {int(x)},{int(y)} → 图像 {int(px)},{int(py)}）没有落在孔上；'
                         '直接点孔中心即可选中。')
            else:
                self.log('点击位置没有落在孔上（当前画面没有映射信息）。')
            return
        if hole_id in self.measure_targets:
            self.measure_targets.discard(hole_id)
        else:
            self.measure_targets.add(hole_id)
        """点孔后立刻把表格里的勾选状态同步过来"""
        self.refresh_current_summary()
        self.render_view()      # [select-mark] 图上立刻出现/去掉绿色圈和白勾
        chosen = '、'.join(sorted(self.measure_targets)) if self.measure_targets else '（空）'
        self.log(f'点选 {hole_id} → 本次测量清单：{chosen}')

    def load_reports(self, reports):
        """[canvas-live] 把一组已保存的检测结果载入工作区（不重新检测、不新增记录）。"""
        reports = [report for report in reports
                   if isinstance(report, dict) and report.get('image')]
        if not reports:
            QMessageBox.information(self, '没有可载入的记录', '这一组里没有可显示的照片记录。')
            return
        self.paths = [report['image'] for report in reports]
        self.results = [_report_to_result(report) for report in reports]
        self.selector.blockSignals(True)
        self.selector.clear()
        self.selector.addItems([f'{index + 1}. {Path(path).name}'
                                for index, path in enumerate(self.paths)])
        self.selector.blockSignals(False)
        self.completed_count = len(reports)
        self.batch_progress.setRange(0, len(reports))
        self.batch_progress.setValue(len(reports))
        self.show_index(0)
        self.set_controls()

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
        try:   # [local patch] remember it for next launch
            (BASE / 'last_photo_dir.txt').write_text(self.last_dir, encoding='utf-8')
        except OSError:
            pass
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
        self.image_info.setText(Path(path).name + dimensions)
        self._result_caption_base = f'检测结果（标定好的孔）· {Path(path).name}'
        self.result_caption.setText(self._result_caption_base)
        self.refresh_current_summary()
        self.render_view()
        self.set_controls()

    def refresh_current_summary(self):
        result = self.current_result or {}
        detected = result.get('detected_holes', [])
        by_id = {hole['id']: hole for hole in detected}
        self.table.setRowCount(4)
        self._filling_table = True        # [fusion-sync]
        try:
            for row in range(4):
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
                    if column == 0:   # [fusion-sync] 勾选＝本次要测的孔
                        item.setToolTip('勾选表示“本次要测量这个孔”；只有圆心可靠的孔才允许勾选。')
                        if hole and hole.get('reliable_center'):
                            item.setFlags(Qt.ItemFlag.ItemIsUserCheckable
                                          | Qt.ItemFlag.ItemIsEnabled
                                          | Qt.ItemFlag.ItemIsSelectable)
                            item.setCheckState(Qt.CheckState.Checked if hid in self.measure_targets
                                               else Qt.CheckState.Unchecked)
                    self.table.setItem(row, column, item)
        finally:
            self._filling_table = False
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
        live_on = getattr(self, 'chk_live', None) is not None and self.chk_live.isChecked()
        if not self.batch_running and not self.bridge.busy and not live_on:
            # [split-view] 实时画面开着时不要把状态栏改回"当前照片…"
            if result.get('errors'):
                self.set_status('当前照片检测异常', '#bf3e35')
            elif result and not result.get('complete'):
                self.set_status('当前照片需要复核', '#a86613')
            elif result:
                self.set_status('当前照片检测完成')

    def render_view(self, *_):
        """[split-view] 只画右格（检测结果）；左格实时画面由定时器单独刷新。"""
        self.lbl_zoom.setText(f'{self.sld_zoom.value()}%')
        if self.display_photo is None:
            self.result_caption.setText(getattr(self, '_result_caption_base', '检测结果（标定好的孔）'))
            self.result_view.clear()
            self.result_view.setText('照片未能读取，请重新选择本机照片。' if self.paths else '请选择一组测试照片')
            return
        size = self.result_view.size()
        if min(size.width(), size.height()) < 60:
            return
        display_result = dict(self.current_result or {})
        display_result['holes'] = display_result.get('fitted_holes', [])
        crop = holes_bbox(display_result, self.display_photo.shape) if self.chk_fit.isChecked() else None
        if crop is None:
            crop = (0, 0, self.display_photo.shape[1], self.display_photo.shape[0])
        crop = zoom_rect(crop, self.sld_zoom.value() / 100.0, self.display_photo.shape)
        canvas, mapping = compose(self.display_photo, (size.width(), size.height()), crop_rect=crop)
        # [canvas-live] compose 已算好裁剪框/缩放，点击换算直接用它，不要覆盖 crop。
        self.display_mapping = dict(mapping) if mapping else None
        chosen = sorted(self.measure_targets)
        # [select-mark] 角标写清"本次要测哪几个孔"，配合图上绿色圈 + 白勾
        caption_base = getattr(self, '_result_caption_base', '检测结果（标定好的孔）')
        caption_note = '本次要测：' + ('、'.join(chosen) if chosen else '（未选中，点图上的孔即可选中）')
        # [split-view] 格子窄的时候优先留"本次要测"，完整信息进提示
        self.result_caption.setText(caption_note if self.result_column.width() < 430
                                    else caption_base + '　｜　' + caption_note)
        self.result_caption.setToolTip(caption_base + '　｜　' + caption_note)
        if mapping:
            for hole in display_result.get('fitted_holes', []):
                cx, cy = _map_pts([hole['center_px']], mapping)[0]
                selected = hole['id'] in self.measure_targets
                text = (f">> {hole['id']}  {hole['confidence']:.2f}" if selected
                        else f"{hole['id']}  {hole['confidence']:.2f}")
                fs = 0.62
                (width, height), baseline = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, fs, 1)
                if not (mapping['ox'] <= cx <= mapping['ox'] + mapping['tw'] and mapping['oy'] <= cy <= mapping['oy'] + mapping['th']):
                    continue
                _dx = 26 if selected else 10     # [select-mark] 选中的孔留出绿点的位置
                tx = int(np.clip(cx + _dx, mapping['ox'] + 3, max(mapping['ox'] + 3, mapping['ox'] + mapping['tw'] - width - 8)))
                ty = int(np.clip(cy - 14, mapping['oy'] + height + 5, mapping['oy'] + mapping['th'] - 5))
                cv2.rectangle(canvas, (tx - 4, ty - height - 4), (tx + width + 4, ty + baseline + 4),
                              (55, 170, 75) if selected else (20, 35, 56), -1)
                color = ((255, 255, 255) if selected else
                         ((170, 235, 255) if hole.get('reliable_center') else (50, 160, 255)))
                cv2.putText(canvas, text, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, fs, color, 1, cv2.LINE_AA)
        self._draw_selection_marks(canvas, mapping, display_result)
        self.result_view.setPixmap(bgr_to_pixmap(canvas))

    def _draw_selection_marks(self, canvas, mapping, display_result):
        """[select-mark] 给"本次要测的孔"套绿环 + 圆心打白勾，让别人一眼看出选没选上。

        单独一个方法：不同版本的标注循环写法不一样，这里只依赖圆心和椭圆参数。
        """
        if canvas is None or not mapping or not display_result:
            return canvas
        for hole in display_result.get('fitted_holes', []):
            if hole.get('id') not in self.measure_targets:
                continue
            centre_px = hole.get('center_px')
            if not centre_px:
                continue
            cx, cy = _map_pts([centre_px], mapping)[0]
            if not (mapping['ox'] - 40 <= cx <= mapping['ox'] + mapping['tw'] + 40
                    and mapping['oy'] - 40 <= cy <= mapping['oy'] + mapping['th'] + 40):
                continue
            ellipse = hole.get('ellipse')
            if ellipse:
                ec = _map_pts([ellipse['center']], mapping)[0]
                # cv2.ellipse 的 axes 是"半径"，这里用拟合椭圆的半轴——圈就正好贴着孔口，
                # 再往里收 10%，画成细环：不往外扩、也不盖住黄色的拟合椭圆。
                axes = (max(3, int(ellipse['width'] * mapping['scale'] * 0.45)),
                        max(3, int(ellipse['height'] * mapping['scale'] * 0.45)))
                cv2.ellipse(canvas, tuple(np.round(ec).astype(int)), axes,
                            ellipse['angle'], 0, 360, (80, 215, 95), 2, cv2.LINE_AA)
            centre = (int(round(cx)), int(round(cy)))
            cv2.circle(canvas, centre, 8, (80, 215, 95), -1)
            cv2.circle(canvas, centre, 8, (255, 255, 255), 2, cv2.LINE_AA)
            cv2.polylines(canvas, [np.array([[centre[0] - 4, centre[1] - 1],
                                             [centre[0] - 1, centre[1] + 3],
                                             [centre[0] + 5, centre[1] - 5]], np.int32)],
                          False, (255, 255, 255), 2, cv2.LINE_AA)
        return canvas

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'result_view'):
            self.render_view()
        self._paint_live_frame()

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
        result['record_report'] = report
        try:
            # [merge-history] 实验记录就是唯一的历史来源，不再另存批次归档。
            if not self.records.update(self.active_group, report=report):
                self.record_error = True
                self.log('这一组已经在「实验记录」里被删除，本次结果不再写回实验记录'
                         '（结果图与检测报告仍在结果文件夹里）。')
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

    @Slot()
    def finish_batch(self):
        self.batch_running = False
        self.thread = None
        self.worker = None
        failures = sum(bool(result and result.get('errors')) for result in self.results)
        complete = self.completed_count == len(self.paths)
        status = '未完成，请复核' if not complete or self.record_error else ('已完成（含异常）' if failures else '已完成')
        try:
            if not self.records.update(self.active_group, status=status):
                self.record_error = True
                self.log('这一组已在「实验记录」里被删除，本组状态不再写回记录。')
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
        # [device-state] 打开时按驱动真值对齐，避免窗口里和状态栏说法不一致
        self.refresh_device_states()
        for _key in ('camera', 'robot_a', 'robot_b'):
            self.sync_device_dialog(_key, bool(self.device_states.get(_key)))

    def device_status_changed(self, device, connected, note):
        self.device_states[device] = connected
        self.update_connection_line()
        names = {'camera':'工业相机', 'robot_a':'拍照机械臂 A', 'robot_b':'测量机械臂 B'}
        self.log(names[device]+'：'+note)

    def _device_backends(self):
        """[device-state] 当前注册的设备驱动。"""
        try:
            from .devices_view import _registered_backends
        except ImportError:
            return {}
        return _registered_backends

    def update_connection_line(self):
        """[device-state] 状态栏只反映实际连接状态，显示真实型号。"""
        names = {'camera': '工业相机', 'robot_a': '拍照机械臂 A', 'robot_b': '测量机械臂 B'}
        backends = self._device_backends()
        parts = []
        for key, title in names.items():
            connected = bool(self.device_states.get(key))
            suffix = ''
            if connected:
                backend = backends.get(key)
                model = (getattr(backend, 'device_name', '') or
                         getattr(backend, 'device_serial', '')) if backend is not None else ''
                if model:
                    suffix = f'（{model}）'
            state = '只读反馈已连接' if (key == 'robot_b' and connected) else ('已连接' if connected else '未连接')
            parts.append(f'{title}：{state}{suffix}')
        self.connection_line.setText('　｜　'.join(parts))

    def refresh_device_states(self):
        """[device-state] 按驱动真实状态刷新状态栏与设备窗口（谁连上就显示谁）。"""
        backends = self._device_backends()
        if not backends:
            return
        changed = False
        for key in ('camera', 'robot_a', 'robot_b'):
            backend = backends.get(key)
            try:
                connected = bool(backend is not None and backend.is_connected())
            except Exception:      # noqa: BLE001 - 驱动异常不能把界面弄崩
                connected = False
            if bool(self.device_states.get(key, False)) != connected:
                self.device_states[key] = connected
                changed = True
                self.sync_device_dialog(key, connected)
        if changed:
            self.update_connection_line()

    def sync_device_dialog(self, device, connected):
        """[device-state] 设备窗口那一页的状态跟着变，避免两处显示矛盾。"""
        dialog = getattr(self, '_inspection_devices_dialog', None)
        if dialog is None:
            return
        try:
            page = dialog.pages.get(device)
            if page is None:
                return
            if connected and hasattr(page, 'adopt_runtime_identity'):
                # 换电脑也能用：把探测到的真实型号/序列号填进界面
                page.adopt_runtime_identity(self._device_backends().get(device))
            if ('已连接' in page.status.text()) == bool(connected):
                return
            page._set_status(bool(connected),
                             '连接已建立。' if connected else '连接已断开。')
        except (RuntimeError, AttributeError):
            pass

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
        worker = getattr(self, 'live_worker', None)      # [canvas-live] 先停实时画面
        if worker is not None:
            try:
                self.live_timer.stop()
                worker.stop()
                worker.wait(5000)
            except RuntimeError:
                pass
        self.bridge.detach()
        from .devices_view import _registered_backends
        for backend in _registered_backends.values():
            backend.disconnect()
        self.detector.release()
        event.accept()

