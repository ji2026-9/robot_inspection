"""Explicit opt-in stop-only UI; never starts physical motion."""
from pathlib import Path
import time
from .ui_feedback import FeedbackLabel
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog,QVBoxLayout,QLabel,QPushButton,QCheckBox,QPlainTextEdit
from .probe_stop import run_simulation


class ProbeStopDialog(QDialog):
    def __init__(self, workspace):
        super().__init__(workspace)
        self.workspace = workspace
        self.setWindowTitle('测头触发停止 · 实验功能')
        self.resize(720, 720)
        layout = QVBoxLayout(self)
        title = QLabel('测头触发停止（默认关闭）')
        title.setStyleSheet('font-size:20px;font-weight:600')
        layout.addWidget(title)
        note = QLabel('DI_1 触发后仅发送停止点动和停止队列请求，不使能、不启动运动、不改负载。\n'
            '电脑与网络有延迟，不能保证零过冲，不替代硬件保护或急停。\n'
            '实机兼容性和停止距离尚未验证；未验证前不得靠本功能向白球运动。\n'
            '每次监控有效 30 秒，触发后不自动恢复；断线 / 配置变化也会请求停止。')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.simulate = QPushButton('运行隔离演练（不连接控制端口）')
        self.simulate.clicked.connect(self.run_demo)
        layout.addWidget(self.simulate)
        self.static_ready = QCheckBox('机械臂已静止、无运动程序；本次只轻触测针，不点动、不移动白球')
        self.static_ready.toggled.connect(self.controls)
        layout.addWidget(self.static_ready)
        self.static_test = QPushButton('开始静止触发通信测试（30 秒；不启动运动）')
        self.static_test.clicked.connect(self.arm_static)
        layout.addWidget(self.static_test)
        label = QLabel('以下是运动监控设置，静止通信测试无需勾选：')
        layout.addWidget(label)
        self.checks = []
        for text in ('现场已确认整套工具负载、重心及安装配置',
                     '测针远离白球与障碍物，人员在运动范围外，急停可用',
                     '已安排不接触工件的停止测试；不使用此功能作为接触保护',
                     '理解请求可能失败；不保证官方点动兼容性，需单独实测'):
            check = QCheckBox(text)
            check.toggled.connect(self.controls)
            layout.addWidget(check)
            self.checks.append(check)
        self.enable = QPushButton('开始实机停止监控（30 秒；不启动运动）')
        self.enable.clicked.connect(self.arm)
        layout.addWidget(self.enable)
        self.disable = QPushButton('结束监控（实机监控期间先请求停止）')
        self.disable.clicked.connect(self.disarm)
        layout.addWidget(self.disable)
        self.status = FeedbackLabel('实机停止监控未启用')
        self.status.setWordWrap(True)
        layout.insertWidget(1,self.status)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        layout.addWidget(self.detail, 1)
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.refresh)
        self.controls()

    def monitor(self):
        return getattr(self.workspace.backend(), 'stop_monitor', None)

    def controls(self):
        m = self.monitor()
        active = bool(m and m.snapshot()['state'] in ('armed','pending','acknowledged'))
        control=getattr(self.workspace.backend(),'manual_control',None)
        conflict=bool(control and control.snapshot()['connected'])
        self.enable.setEnabled(bool(m) and not active and not conflict and all(c.isChecked() for c in self.checks))
        self.static_test.setEnabled(bool(m) and not active and not conflict and self.static_ready.isChecked())
        tip='请先在实机控制窗口断开 TCP 控制，避免端口冲突' if conflict else '需连接有效反馈并确认现场条件'
        self.enable.setToolTip(tip);self.static_test.setToolTip(tip)
        self.static_ready.setEnabled(not active)
        self.disable.setEnabled(active)
        self.simulate.setEnabled(not active)
        for c in self.checks:
            c.setEnabled(not active)

    def run_demo(self):
        r = run_simulation()
        self.detail.setPlainText(r['reason']+'\n实机监控保持关闭；这是合成信号，不是实测停止结果。')

    def arm_static(self):
        self.arm(static_only=True)

    def arm(self, checked=False, *, static_only=False):
        try:
            self.status.clear()
            backend = self.workspace.backend()
            control=getattr(backend,'manual_control',None)
            if control and control.snapshot()['connected']:
                raise ValueError('实机控制已连接，请先断开，避免两个功能争用控制端口')
            ready = self.static_ready.isChecked() if static_only else all(c.isChecked() for c in self.checks)
            if not ready:
                raise ValueError('现场条件尚未确认')
            path = self.workspace.storage_path.parent/'stop_monitor_logs'/(str(time.time_ns())+'.json')
            backend.stop_monitor.arm(backend.snapshot(), backend.address, backend.generation,
                live=True, confirmations=True, audit_path=path, static_only=static_only)
            self.detail.setPlainText('本次报告：'+str(path)+'\n未发送运动、使能或接管控制指令。')
            if static_only:
                self.detail.appendPlainText('等待轻触测针一次后松开；不要点动或接触白球。\n本测试不验证运动中可停止。')
        except (ValueError, OSError, AttributeError, KeyError) as exc:
            self.detail.setPlainText('未启用：'+str(exc))
            self.status.show_message('未启用：'+str(exc),'error')
        self.refresh()

    def disarm(self):
        self.status.clear()
        m = self.monitor()
        if m:
            m.disarm()
        self.refresh()

    def refresh(self):
        m = self.monitor()
        if m:
            r = m.snapshot()
            self.status.set_status(r['state']+' · '+r['reason']+
                ('\n日志异常：'+r['save_error'] if r.get('save_error') else ''))
            if r['state']=='failed' or r.get('save_error'):self.status.show_message(r['reason']+('；日志异常：'+r['save_error'] if r.get('save_error') else ''),'error')
        self.controls()
        control=getattr(self.workspace.backend(),'manual_control',None)
        if control and control.snapshot()['connected']:
            self.status.setText('独立测试已锁定：请先在实机控制窗口断开 TCP 控制，再返回本窗口')

    def showEvent(self, event):
        super().showEvent(event)
        self.timer.start()
        self.refresh()

    def closeEvent(self, event):
        self.disarm()
        self.timer.stop()
        for c in self.checks:
            c.setChecked(False)
        self.static_ready.setChecked(False)
        super().closeEvent(event)

    def reject(self):self.close()
