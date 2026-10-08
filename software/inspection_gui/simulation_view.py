"""Standalone schematic animation. No device, detection, or record writes."""
import math
from PySide6.QtCore import Qt, QTimer, QPointF
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QWidget
from .simulation_scene3d import Scene3D


class Scene(QWidget):
    def __init__(self):
        super().__init__()
        self.phase = 0.0
        self.setMinimumSize(760, 400)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor('#edf3fa'))
        p.scale(self.width() / 900, self.height() / 460)
        p.setPen(QPen(QColor('#8b9bb0'), 2))
        p.setBrush(QColor('#d6dfe9'))
        p.drawRoundedRect(30, 370, 840, 55, 8, 8)
        p.setBrush(QColor('#c2aa88'))
        p.drawRoundedRect(285, 285, 330, 80, 8, 8)
        stage = int(self.phase) % 8
        progress = self.phase % 1
        selected = stage - 3 if 3 <= stage <= 6 else -1
        for i in range(4):
            p.setBrush(QColor('#163147'))
            p.setPen(QPen(QColor('#10b981') if i < selected or stage == 7 else QColor('#64748b'), 3))
            if i == selected:
                p.setPen(QPen(QColor('#f59e0b'), 4))
            p.drawEllipse(QPointF(325 + i * 82, 321), 25, 21)
            p.setPen(QColor('#334155'))
            p.drawText(312 + i * 82, 356, f'H{i+1:02}')
        camera_x = 450
        camera_y = 205 if stage in (1, 2) else 145
        probe_x = 325 + max(0, selected) * 82 if selected >= 0 else 710
        probe_y = 275 + 25 * math.sin(math.pi * progress) if selected >= 0 else 165
        self.arm(p, 135, camera_x, camera_y, '#2563eb', 'A · 相机')
        self.arm(p, 765, probe_x, probe_y, '#7c3aed', 'B · 测针')
        if stage in (1, 2):
            p.setPen(QPen(QColor('#06b6d4'), 2, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(camera_x, camera_y), QPointF(285, 285))
            p.drawLine(QPointF(camera_x, camera_y), QPointF(615, 285))
        if selected >= 0:
            p.setPen(QPen(QColor('#f59e0b'), 3))
            p.drawLine(QPointF(probe_x, probe_y), QPointF(probe_x, 321))
        p.setPen(QColor('#475569'))
        p.drawText(35, 35, 'DOBOT CR5A × 2 · 流程示意（非真实运动轨迹）')

    @staticmethod
    def arm(p, base, x, y, color, label):
        elbow = QPointF(base + (90 if base < 450 else -90), 135)
        points = [QPointF(base, 370), QPointF(base, 250), elbow, QPointF(x, y)]
        p.setPen(QPen(QColor('#c4cdd8'), 24, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        for a, b in zip(points, points[1:]):
            p.drawLine(a, b)
        p.setPen(QPen(QColor(color), 3))
        p.setBrush(QColor('#f8fafc'))
        for point in points:
            p.drawEllipse(point, 14, 14)
        p.setPen(QColor(color))
        p.drawText(int(base)-40, 405, label)


class SimulationDialog(QDialog):
    STAGES = ['设备就绪', '机械臂 A 拍照', '识别孔位／坐标转换示意',
              '机械臂 B 测量 H01', '机械臂 B 测量 H02',
              '机械臂 B 测量 H03', '机械臂 B 测量 H04', '测量完成／生成报告示意']

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('双机械臂三维模拟测量')
        self.resize(1120, 740)
        layout = QVBoxLayout(self)
        note = QLabel('模拟演示：使用示意孔位，不连接机械臂，不下发运动，不生成真实测量数据。')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.scene = Scene3D()
        layout.addWidget(self.scene, 1)
        self.status = QLabel(self.STAGES[0])
        layout.addWidget(self.status)
        row = QHBoxLayout()
        self.play = QPushButton('开始演示')
        reset = QPushButton('重置')
        view = QPushButton('恢复视角')
        row.addWidget(self.play)
        row.addWidget(reset)
        row.addWidget(view)
        layout.addLayout(row)
        self.timer = QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self.tick)
        self.play.clicked.connect(self.toggle)
        reset.clicked.connect(self.reset)
        view.clicked.connect(self.scene.reset_view)

    def toggle(self):
        if self.timer.isActive():
            self.timer.stop()
            self.play.setText('继续演示')
        else:
            if self.scene.phase >= 8:
                self.reset()
            self.timer.start()
            self.play.setText('暂停')

    def reset(self):
        self.timer.stop()
        self.scene.phase = 0
        self.play.setText('开始演示')
        self.status.setText(self.STAGES[0])
        self.scene.update()

    def tick(self):
        self.scene.phase = min(8, self.scene.phase + 0.02)
        self.status.setText(self.STAGES[min(7, int(self.scene.phase))])
        self.scene.update()
        if self.scene.phase >= 8:
            self.timer.stop()
            self.play.setText('重新演示')

    def closeEvent(self, event):
        self.timer.stop()
        super().closeEvent(event)
