"""Separate opt-in real controller UI; constructing/showing never opens TCP29999."""
from PySide6.QtCore import QEvent,QTimer,Qt
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QGridLayout,QLabel,
    QPushButton,QCheckBox,QDoubleSpinBox,QComboBox,QFrame,QMessageBox,QScrollArea,QWidget)
from .manual_control import ManualControl


class ManualControlDialog(QDialog):
    def __init__(self, workspace):
        super().__init__(workspace)
        self.workspace=workspace;self.setWindowTitle('实机控制 · 保护状态与定距移动');self.resize(710,850)
        root=QVBoxLayout(self);scroll=QScrollArea();scroll.setWidgetResizable(True);root.addWidget(scroll)
        body=QWidget();scroll.setWidget(body);layout=QVBoxLayout(body)
        title=QLabel('测头机械臂 · 实机控制');title.setStyleSheet('font-size:21px;font-weight:600');layout.addWidget(title)
        text=QLabel('控制器需处于 TCP 模式并已正确配置负载、重心及工具。\n'
            '本界面不自动使能、清报警或切换模式；路径预览不执行于实机。\n'
            '测头触发后请求软件停止，有网络和制动延迟，不能当作急停或自动接触保护。')
        text.setWordWrap(True);layout.addWidget(text)
        self.pose=QLabel('等待只读反馈');self.pose.setWordWrap(True);layout.addWidget(self.pose)
        row=QHBoxLayout();self.connect_button=QPushButton('连接 TCP 控制（不移动）')
        self.connect_button.clicked.connect(self.connect_control);row.addWidget(self.connect_button)
        self.disconnect_button=QPushButton('断开控制');self.disconnect_button.clicked.connect(self.disconnect_control);row.addWidget(self.disconnect_button);layout.addLayout(row)
        self.status=QLabel('运动锁定');self.status.setWordWrap(True);root.addWidget(self.status)
        self.safety_status=QLabel();self.safety_status.setWordWrap(True);root.addWidget(self.safety_status)
        self.reset_button=QPushButton('确认现场并复位锁定（不移动）')
        self.reset_button.clicked.connect(self.reset_safety);root.addWidget(self.reset_button)
        self.checks=[]
        for label in ('整套工具重量、重心已核对，控制器负载已生效',
                      '已核对工具坐标、用户坐标系0及移动方向',
                      '测试物固定、人员退出运动范围，实体急停可操作',
                      '静止触发通信已验证；运动停止距离尚未验证'):
            check=QCheckBox(label);check.setChecked(False);layout.addWidget(check);self.checks.append(check)
        row=QHBoxLayout();row.addWidget(QLabel('已核对的整套工具重量'))
        self.payload=QDoubleSpinBox();self.payload.setRange(0,5);self.payload.setDecimals(3);self.payload.setSuffix(' kg');row.addWidget(self.payload);layout.addLayout(row)
        note=QLabel('负载、重心和 TCP：人工确认，未自动核验。输入重量不会修改控制器配置。');note.setWordWrap(True);layout.addWidget(note)
        self.unlock_button=QPushButton('确认并解锁本次定距移动（60 秒）');self.unlock_button.clicked.connect(self.unlock);layout.addWidget(self.unlock_button)
        row=QHBoxLayout();row.addWidget(QLabel('步长'))
        self.step=QComboBox();self.step.addItems(['0.1 mm','0.5 mm','1.0 mm']);row.addWidget(self.step)
        row.addWidget(QLabel('目标速度'));self.speed=QComboBox();self.speed.addItems(['1 mm/s','2 mm/s','5 mm/s']);row.addWidget(self.speed);layout.addLayout(row)
        label=QLabel('① 选择方向生成目标预览（保持姿态）');layout.addWidget(label)
        grid=QGridLayout();self.directions=[]
        for row,axis in enumerate(('X','Y','Z')):
            for col,sign in enumerate((-1,1)):
                button=QPushButton(axis+('−' if sign<0 else '+')+' · 预览')
                button.clicked.connect(lambda checked=False,a=axis,s=sign:self.preview(a,s));grid.addWidget(button,row,col);self.directions.append(button)
        layout.addLayout(grid)
        self.target=QLabel('尚未生成目标。每次最多1 mm，每次解锁累计最多5 mm。');self.target.setWordWrap(True);layout.addWidget(self.target)
        self.execute_button=QPushButton('② 按住执行本次移动 · 松开请求停止');self.execute_button.setAutoRepeat(False)
        self.execute_button.pressed.connect(self.execute);self.execute_button.released.connect(self.release);layout.addWidget(self.execute_button)
        self.stop_button=QPushButton('软件停止 · 立即锁定');self.stop_button.setStyleSheet('background:#b42318;color:white;font-size:18px;padding:12px')
        self.stop_button.clicked.connect(lambda:self.controller.request_stop('人工停止'));root.addWidget(self.stop_button)
        self.detail=QLabel('');self.detail.setWordWrap(True);self.detail.setStyleSheet('color:#b42318')
        root.insertWidget(root.indexOf(self.safety_status)+1,self.detail)
        backend=workspace.backend()
        existing=getattr(backend,'manual_control',None)
        if existing is None:
            backend.manual_control=ManualControl(workspace.storage_path.parent/'manual_control_logs')
        self.controller=backend.manual_control;self.plan_id=None
        self.step.currentIndexChanged.connect(self.invalidate_plan);self.speed.currentIndexChanged.connect(self.invalidate_plan)
        for check in self.checks:check.toggled.connect(self.confirmation_changed)
        self.payload.valueChanged.connect(self.confirmation_changed)
        self.timer=QTimer(self);self.timer.setInterval(50);self.timer.timeout.connect(self.refresh);self.refresh()

    def confirmation_changed(self):
        if self.controller.snapshot()['unlocked']:
            self.controller.request_stop('现场确认或工具重量发生变化')
        self.plan_id=None

    def reset_safety(self):
        answer=QMessageBox.question(self,'确认现场后复位',
            '请确认机械臂已停止、测针已松开、现场无干涉。\n复位只解除本次停止锁定，继续运动还需要重新确认和解锁。',
            QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)
        if answer!=QMessageBox.StandardButton.Yes:return
        try:self.controller.reset_safety();self.clear_checks();self.plan_id=None
        except (ValueError,OSError) as exc:self.error(exc)
        self.refresh()

    def invalidate_plan(self):
        self.plan_id=None;self.target.setText('参数已变化，请重新预览');self.refresh()

    def error(self, exc):self.detail.setText(str(exc))

    def connect_control(self):
        try:
            backend=self.workspace.backend();frame=backend.snapshot()
            if not frame or not backend.address:raise ValueError('请先连接工作区只读反馈')
            external=backend.stop_monitor.snapshot()['state'] in ('armed','pending','acknowledged')
            self.controller.observe(frame,backend.generation,external)
            self.controller.connect(backend.address,backend.generation)
        except (ValueError,OSError,RuntimeError) as exc:self.error(exc)
        self.refresh()

    def disconnect_control(self):
        self.controller.close();self.clear_checks();self.plan_id=None;self.refresh()

    def clear_checks(self):
        for check in self.checks:check.setChecked(False)

    def unlock(self):
        if not all(check.isChecked() for check in self.checks):
            self.error('请逐项确认现场条件；不能用勾选替代实际核对。');return
        answer=QMessageBox.question(self,'确认实机移动入口',
            '解锁后，按住执行按钮会发送真实移动指令。\n请确认人员已离开运动范围，负载和重心配置已核对。',
            QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)
        if answer!=QMessageBox.StandardButton.Yes:return
        try:self.controller.unlock(True,self.payload.value());self.detail.setText('已解锁；选择方向后核对目标。')
        except (ValueError,OSError) as exc:self.error(exc)
        self.refresh()

    def preview(self, axis, sign):
        try:
            step=(.1,.5,1)[self.step.currentIndex()]*sign;speed=(1,2,5)[self.speed.currentIndex()]
            plan=self.controller.preview(axis,step,speed);self.plan_id=plan['id']
            xyz=' / '.join(f'{v:.3f}' for v in plan['target'][:3])
            self.target.setText(f"{axis} {step:+.1f} mm · {speed} mm/s\n目标 X / Y / Z：{xyz} mm\n姿态保持；用户0 / 工具{plan['tool']}。预览10秒内有效。")
        except (ValueError,OSError) as exc:self.plan_id=None;self.error(exc)
        self.refresh()

    def execute(self):
        try:self.controller.execute(self.plan_id)
        except (ValueError,OSError,RuntimeError) as exc:self.plan_id=None;self.error(exc)

    def release(self):
        if self.controller.snapshot()['phase'] in ('queued','moving'):
            self.controller.request_stop('松开执行按钮')
        self.plan_id=None;self.refresh()

    def refresh(self):
        state=self.controller.snapshot();frame=self.workspace.backend().snapshot()
        if self.plan_id and state['plan'] and self.controller.clock()-state['plan']['created']>10:
            self.plan_id=None;self.target.setText('目标预览已过期，请重新选择方向生成预览。')
        if frame:
            self.pose.setText('当前 XYZ：'+' / '.join(f'{v:.3f}' for v in frame['pose'][:3])+
                ' mm\nRx / Ry / Rz：'+' / '.join(f'{v:.3f}' for v in frame['pose'][3:])+
                f" °\n用户{frame['user_index']} / 工具{frame['tool_index']} · DI_1={frame['digital_inputs']&1} · "+('报警' if frame['error'] else '无报警'))
        else:self.pose.setText('反馈不可用；禁止移动')
        safety=state['safety'];age=safety['feedback_age_ms']
        age_text='未收到有效反馈' if age is None else f'反馈年龄 {age:.0f} ms'
        self.safety_status.setText(age_text+' · '+safety['feedback_reason']+
            f"\n单次≤1 mm · 目标速度≤5 mm/s · 授权累计≤5 mm\n剩余授权 {safety['remaining_seconds']:.0f} 秒 / {safety['remaining_distance_mm']:.1f} mm"+
            ('\n无法确认停止，请使用实体急停；断开后重新检查连接。' if safety['stop_state']=='unconfirmed' else ''))
        color='#b42318' if safety['stop_state']=='unconfirmed' else '#855400' if state['phase']!='ready' else '#245583'
        self.status.setStyleSheet(f'color:{color};background:#edf2f7;padding:10px;font-weight:600')
        self.status.setText(state['reason']);self.connect_button.setEnabled(not state['connected'])
        self.disconnect_button.setEnabled(state['connected']);self.stop_button.setEnabled(state['connected'])
        self.reset_button.setEnabled(safety['can_reset'])
        self.unlock_button.setEnabled(state['can_unlock'])
        self.unlock_button.setToolTip('连接 TCP 并满足反馈检查后才能解锁；具体原因见下方状态。' if not state['can_unlock'] else '重新核对四项现场条件后解锁60秒')
        for button in self.directions:button.setEnabled(state['phase']=='ready' and safety['feedback_ok'])
        # Keep the held button enabled during execution so Qt can deliver release.
        holding=self.execute_button.isDown() and state['phase'] in ('queued','moving')
        self.execute_button.setEnabled(bool(self.plan_id and state['phase']=='ready' and safety['feedback_ok']) or holding)
        if holding and self.isActiveWindow():self.controller.maintain_hold()
        if not state['unlocked'] and state['phase'] in ('stopping','verifying_stop','latched','fault'):
            self.clear_checks();self.plan_id=None
        for control in (self.step,self.speed,self.payload,*self.checks):
            control.setEnabled(state['phase'] not in ('queued','moving','stopping','verifying_stop'))

    def event(self, event):
        if event.type() in (QEvent.Type.WindowDeactivate,QEvent.Type.Hide) and hasattr(self,'controller'):
            if self.controller.snapshot()['unlocked']:self.controller.request_stop('控制窗口失去焦点或隐藏')
        return super().event(event)

    def showEvent(self,event):
        super().showEvent(event);self.timer.start();self.refresh()

    def closeEvent(self,event):
        self.timer.stop();self.controller.close();self.clear_checks();self.plan_id=None;super().closeEvent(event)

    def reject(self):self.close()
