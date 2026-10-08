"""工业相机实时预览窗口（配合 ``orbbec_camera.py`` 使用）。

取流线程直接复用朋友分支的 ``vision_workspace.CameraPreviewWorker``：
后台线程持续取帧，界面线程只负责显示，互不阻塞。

边界（和整套软件保持一致）：

* 本窗口只做「看」和「抓拍」；不连接、不使能、不发送任何机械臂运动；
* 抓拍走 ``capture_archive.save_capture``：无损 PNG + 同批 JSON，**绝不覆盖**；
* 抓拍后照片进入主窗口工作区，点「② 开始检测」才开始检测。
"""
from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout

from .capture_archive import save_capture
from .vision_workspace import CameraPreviewWorker


def capture_root() -> Path:
    """留样目录：软件目录下的 ``captures``（与主窗口「用工业相机拍照」一致）。"""
    return Path(__file__).resolve().parents[1] / 'captures'


def bgr_to_pixmap(bgr):
    rgb = cv2.cvtColor(np.ascontiguousarray(bgr), cv2.COLOR_BGR2RGB)
    height, width, _ = rgb.shape
    return QPixmap.fromImage(
        QImage(rgb.data, width, height, rgb.strides[0], QImage.Format.Format_RGB888).copy())


_STYLE = """
QDialog#cameraPreview { background: #eef2f7; }
QDialog#cameraPreview QLabel { color: #22324a; }
QDialog#cameraPreview QLabel#previewCanvas {
    background: #f7f9fc; border: 1px solid #dde5ee; border-radius: 8px; color: #8a97a8; }
QDialog#cameraPreview QLabel#previewStatus { color: #35618f; font-size: 13px; }
QDialog#cameraPreview QPushButton {
    background: #ffffff; border: 1px solid #c7d5e5; border-radius: 8px;
    padding: 8px 14px; color: #16324f; font-weight: 600; }
QDialog#cameraPreview QPushButton:hover { background: #eef5ff; border-color: #7ba7dd; }
QDialog#cameraPreview QPushButton:disabled { background: #f3f6fa; color: #9aa8ba; border-color: #e3e9f1; }
QDialog#cameraPreview QPushButton#previewPrimary {
    background: #1256a8; border-color: #1256a8; color: #ffffff; }
"""


class CameraPreviewDialog(QDialog):
    """实时预览窗口；由主窗口持有唯一实例。"""

    def __init__(self, main_window):
        super().__init__(main_window)
        self.main = main_window
        self.worker = None
        self.last_frame = None
        self._stamps: list[float] = []
        self.setObjectName('cameraPreview')
        self.setWindowTitle('工业相机 · 实时预览')
        self.resize(1020, 700)
        self.setMinimumSize(640, 480)
        self.setModal(False)
        self.setStyleSheet(_STYLE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        heading = QLabel('实时预览 · Orbbec Gemini 335Le')
        heading.setStyleSheet('font-size: 19px; font-weight: 700; color: #183b65;')
        layout.addWidget(heading)
        note = QLabel('只取彩色图；预览本身不写文件，点「抓拍」才做无损留样（PNG + 同批 JSON，不覆盖）。')
        note.setObjectName('previewStatus')
        note.setWordWrap(True)
        layout.addWidget(note)

        self.image_label = QLabel('点「开始预览」显示相机画面')
        self.image_label.setObjectName('previewCanvas')
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumSize(560, 360)
        layout.addWidget(self.image_label, 1)

        self.status = QLabel('相机未开始预览。')
        self.status.setObjectName('previewStatus')
        layout.addWidget(self.status)

        buttons = QHBoxLayout()
        self.start_button = QPushButton('开始预览')
        self.start_button.setObjectName('previewPrimary')
        self.stop_button = QPushButton('停止预览')
        self.stop_button.setEnabled(False)
        self.grab_button = QPushButton('抓拍并放入工作区')
        self.grab_button.setEnabled(False)
        self.grab_detect_button = QPushButton('抓拍并直接检测')
        self.grab_detect_button.setEnabled(False)
        close_button = QPushButton('关闭')
        for widget in (self.start_button, self.stop_button):
            buttons.addWidget(widget)
        buttons.addStretch(1)
        for widget in (self.grab_button, self.grab_detect_button, close_button):
            buttons.addWidget(widget)
        layout.addLayout(buttons)

        self.start_button.clicked.connect(self.start_preview)
        self.stop_button.clicked.connect(self.stop_preview)
        self.grab_button.clicked.connect(lambda: self.grab(False))
        self.grab_detect_button.clicked.connect(lambda: self.grab(True))
        close_button.clicked.connect(self.close)

        self.timer = QTimer(self)
        self.timer.setInterval(40)          # 界面按 25 帧/秒刷新
        self.timer.timeout.connect(self.refresh)

    # ------------------------------------------------------------ 相机与线程
    def camera(self):
        try:
            from .devices_view import _registered_backends
        except ImportError:
            return None
        return _registered_backends.get('camera')

    def start_preview(self):
        if self.worker is not None:
            return
        camera = self.camera()
        if camera is None:
            QMessageBox.information(self, '相机未接入',
                                    '本机没有可用的 Orbbec 相机驱动。\n'
                                    '请确认已安装 OrbbecSDK，并且相机 USB 已插好。')
            return
        self.status.setText('正在连接相机…')
        self.start_button.setEnabled(False)
        try:
            settings = self.main.camera_settings() if hasattr(self.main, 'camera_settings') else {}
            if not camera.is_connected() and not camera.connect(settings):
                raise RuntimeError(camera.last_error or '相机连接失败。')
        except Exception as error:                      # noqa: BLE001 - 如实报出，不吞异常
            self.status.setText('相机连接失败。')
            self.start_button.setEnabled(True)
            QMessageBox.warning(self, '相机连接失败', str(error))
            return
        self.worker = CameraPreviewWorker(camera, self)
        self.worker.failed.connect(self.preview_failed)
        self.worker.start()
        self.timer.start()
        self.stop_button.setEnabled(True)
        self.grab_button.setEnabled(True)
        self.grab_detect_button.setEnabled(True)
        self._stamps.clear()
        self.status.setText('正在等待第一帧…')
        if hasattr(self.main, 'log'):
            self.main.log('已开始工业相机实时预览。')

    def stop_preview(self):
        self.timer.stop()
        worker, self.worker = self.worker, None
        if worker is not None:
            worker.stop()
            worker.wait(5000)
        self.last_frame = None
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.grab_button.setEnabled(False)
        self.grab_detect_button.setEnabled(False)
        self.status.setText('预览已停止（相机保持连接）。')

    def preview_failed(self, message):
        self.status.setText('预览中断：' + message)
        if hasattr(self.main, 'log'):
            self.main.log('相机预览中断：' + message)
        self.stop_preview()

    # ---------------------------------------------------------------- 画面刷新
    def refresh(self):
        worker = self.worker
        if worker is None:
            return
        packet = worker.snapshot_packet() if hasattr(worker, 'snapshot_packet') else None
        if not packet:
            self.status.setText('等待相机图像…（若一直无画面，请检查相机网段是否为 192.168.1.100）')
            return
        frame = packet.get('frame')
        if frame is None:
            return
        self.last_frame = frame
        size = self.image_label.size()
        height, width = frame.shape[:2]
        scale = min(size.width() / width, size.height() / height, 1.0)
        canvas = frame
        if scale < 0.999:
            canvas = cv2.resize(frame, (max(1, int(width * scale)), max(1, int(height * scale))),
                                interpolation=cv2.INTER_AREA)
        self.image_label.setPixmap(bgr_to_pixmap(canvas))
        now = time.monotonic()
        self._stamps.append(now)
        self._stamps = [stamp for stamp in self._stamps if now - stamp <= 1.0]
        self.status.setText(f'实时预览中：{width}×{height}　约 {len(self._stamps)} 帧/秒　'
                            '（预览不写文件）')

    # ------------------------------------------------------------------ 抓拍
    def grab(self, then_detect):
        if self.last_frame is None:
            QMessageBox.information(self, '还没有画面', '请先点「开始预览」，等出现画面再抓拍。')
            return
        frame = self.last_frame.copy()
        camera = self.camera()
        try:
            photo, info, data = save_capture(capture_root(), frame, metadata={
                'source': 'Orbbec Gemini 335Le（工业相机 · 实时预览抓拍）',
                'device_serial': getattr(camera, 'device_serial', '')
                                 or getattr(camera, 'device_uid', ''),
                'profile': getattr(camera, 'profile', ''),
                'note': '实时预览窗口抓拍；原图无损保存，不覆盖。',
            })
        except OSError as error:
            QMessageBox.warning(self, '原图留样失败', str(error))
            return
        self.main.set_images([str(photo)])
        self.main.log(f'相机抓拍：{photo.name}（{data["width_px"]}×{data["height_px"]}，'
                      f'SHA256 {data["image_sha256"][:12]}…）已放入工作区。')
        self.status.setText(f'已抓拍并留样：{photo.name}')
        if then_detect:
            self.main.start_batch()

    def closeEvent(self, event):
        self.stop_preview()
        super().closeEvent(event)
