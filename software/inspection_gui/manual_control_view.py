"""Compact real controller panel. Opening the panel never connects or moves."""
import time
from PySide6.QtCore import QEvent,QTimer,Qt
from .stepper import DoubleParameter
from PySide6.QtGui import QShortcut,QKeySequence
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QGridLayout,QLabel,
    QPushButton,QCheckBox,QDoubleSpinBox,QComboBox,QFrame,QWidget,QToolButton,QLineEdit)
from .manual_control import ManualControl
from .numeric_parameter import NumericParameter


class ManualControlDialog(QDialog):
    def __init__(self, workspace):
        super().__init__(workspace)
        self.workspace=workspace
        self.setWindowTitle('测头机械臂 · 实机控制')
        self.resize(940,690);self.setMinimumSize(840,650)
        self.setStyleSheet("""
            QDialog{background:#f3f6fa;color:#263b51;}
            QLabel{background:transparent;color:#263b51;}
            QFrame#controlCard{background:white;border:1px solid #dde5ef;border-radius:12px;}
            QLabel#section{font-size:15px;font-weight:600;color:#214567;}
            QLabel#muted{font-size:11px;color:#708298;}
            QPushButton{background:white;border:1px solid #cbd7e6;border-radius:7px;padding:9px 12px;color:#285580;}
            QPushButton:hover{background:#edf4ff;border-color:#8eafd8;}
            QPushButton:disabled{color:#a1afc0;background:#f7f9fc;border-color:#e0e6ee;}
            QPushButton#primary{background:#2563ad;color:white;border-color:#2563ad;font-weight:600;}
            QPushButton#primary:disabled{background:#b4c7df;border-color:#b4c7df;color:white;}
            QComboBox,QDoubleSpinBox{background:white;border:1px solid #ccd8e6;border-radius:5px;padding:5px;color:#263b51;}
            QToolButton{border:0;color:#436d99;background:transparent;}
            QCheckBox{background:transparent;color:#263b51;}
            QCheckBox::indicator{width:15px;height:15px;border:1px solid #9badc3;border-radius:3px;background:white;}
            QCheckBox::indicator:checked{background:#2563ad;border-color:#2563ad;}
        """)
        root=QVBoxLayout(self);root.setContentsMargins(18,16,18,16);root.setSpacing(12)
        heading=QHBoxLayout()
        title=QLabel('测头机械臂');title.setStyleSheet('font-size:23px;font-weight:600');heading.addWidget(title)
        subtitle=QLabel('实机控制');subtitle.setObjectName('muted');heading.addWidget(subtitle);heading.addStretch()
        backend=workspace.backend()
        address=backend.address or (workspace.address.text() if hasattr(workspace,'address') else '192.168.5.1')
        self.address=QLineEdit(address);self.address.setMaximumWidth(140);self.address.setPlaceholderText('机械臂 IP');heading.addWidget(self.address)
        self.connect_button=QPushButton('连接控制');self.connect_button.clicked.connect(self.connect_control);heading.addWidget(self.connect_button)
        self.disconnect_button=QPushButton('断开');self.disconnect_button.clicked.connect(self.disconnect_control);heading.addWidget(self.disconnect_button)
        root.addLayout(heading)
        columns=QHBoxLayout();columns.setSpacing(14);root.addLayout(columns,1)
        left_pane=QWidget();left_pane.setMinimumWidth(310);left_pane.setMaximumWidth(360)
        left=QVBoxLayout(left_pane);left.setContentsMargins(0,0,0,0);left.setSpacing(12);columns.addWidget(left_pane,2)
        right_card=QFrame();right_card.setObjectName('controlCard');right=QVBoxLayout(right_card)
        right.setContentsMargins(18,16,18,16);right.setSpacing(12);columns.addWidget(right_card,3)
        pose_card=QFrame();pose_card.setObjectName('controlCard');pose_layout=QVBoxLayout(pose_card)
        pose_layout.setContentsMargins(16,14,16,14)
        label=QLabel('实时位姿');label.setObjectName('section');pose_layout.addWidget(label)
        self.pose=QLabel('等待只读反馈');self.pose.setWordWrap(True);self.pose.setMinimumHeight(104)
        self.pose.setStyleSheet('font-size:14px;line-height:1.5');self.pose.setTextInteractionFlags(Qt.TextSelectableByMouse)
        pose_layout.addWidget(self.pose)
        self.io_status=QLabel('测头 —  ·  控制器 —');self.io_status.setObjectName('muted');pose_layout.addWidget(self.io_status)
        left.addWidget(pose_card)
        session_card=QFrame();session_card.setObjectName('controlCard');session=QVBoxLayout(session_card)
        session.setContentsMargins(16,14,16,14);session.setSpacing(10)
        label=QLabel('本轮控制');label.setObjectName('section');session.addWidget(label)
        self.checks=[QCheckBox('本次工具与现场已核对')];session.addWidget(self.checks[0])
        note=QLabel('包含负载与重心、工具坐标及实体急停；人员已离开运动范围。')
        note.setObjectName('muted');note.setWordWrap(True);session.addWidget(note)
        row=QHBoxLayout();row.addWidget(QLabel('工具总重量'))
        self.payload=DoubleParameter();self.payload.setRange(0,5);self.payload.setSingleStep(.1);self.payload.setDecimals(3);self.payload.setSuffix(' kg')
        self.payload.setMaximumWidth(175);row.addWidget(self.payload);session.addLayout(row)
        self.unlock_button=QPushButton('启用本轮控制');self.unlock_button.setObjectName('primary')
        self.unlock_button.clicked.connect(self.unlock);session.addWidget(self.unlock_button)
        self.session_budget=QLabel('60 秒 / 累计 5 mm；普通停止不重置额度。')
        self.session_budget.setWordWrap(True);self.session_budget.setObjectName('muted');session.addWidget(self.session_budget)
        left.addWidget(session_card);left.addStretch(1)
        explanation=QToolButton();explanation.setText('查看控制说明');explanation.setCheckable(True)
        self.explanation=QLabel('连接控制只检查 TCP 状态。重量仅作人工确认记录，不会写入控制器。工具与负载需已正确配置、已使能。软件停止有延迟，实体急停须可用。')
        self.explanation.setObjectName('muted');self.explanation.setWordWrap(True);self.explanation.hide()
        explanation.toggled.connect(self.explanation.setVisible);left.addWidget(explanation);left.addWidget(self.explanation)
        label=QLabel('手动移动');label.setObjectName('section');right.addWidget(label)
        self.motion_mode=QComboBox();self.motion_mode.addItems(['连续点动 · 按住移动','定距移动 · 精细调整']);right.addWidget(self.motion_mode)
        self.motion_hint=QLabel();self.motion_hint.setObjectName('muted');self.motion_hint.setWordWrap(True);right.addWidget(self.motion_hint)
        row=QHBoxLayout();self.step_label=QLabel('距离（mm）');row.addWidget(self.step_label);self.step=NumericParameter();row.addWidget(self.step)
        row.addSpacing(8);self.speed_label=QLabel('倍率（%）');row.addWidget(self.speed_label);self.speed=NumericParameter();row.addWidget(self.speed);right.addLayout(row)
        grid=QGridLayout();grid.setHorizontalSpacing(10);grid.setVerticalSpacing(8);self.directions=[]
        for row,axis in enumerate(('X','Y','Z')):
            for col,sign in enumerate((-1,1)):
                button=QPushButton(axis+(' −' if sign<0 else ' +'));button.setMinimumHeight(43)
                button.setAutoRepeat(False)
                button.setStyleSheet('font-size:18px;font-weight:600')
                button.clicked.connect(lambda checked=False,a=axis,s=sign:self.preview(a,s))
                button.pressed.connect(lambda a=axis,s=sign:self.direction_press(a,s))
                button.released.connect(lambda a=axis,s=sign:self.direction_release(a,s))
                grid.addWidget(button,row,col);self.directions.append(button)
        right.addLayout(grid)
        self.target=QLabel('尚未选择目标\n选择 X / Y / Z 方向后在这里核对。')
        self.target.setWordWrap(True);self.target.setMinimumHeight(74)
        self.target.setStyleSheet('background:#f2f6fc;border-radius:8px;padding:10px;color:#3d5d80;');right.addWidget(self.target)
        self.execute_button=QPushButton('按住执行 · 松开停止');self.execute_button.setObjectName('primary');self.execute_button.setMinimumHeight(47)
        self.execute_button.setAutoRepeat(False);self.execute_button.pressed.connect(self.execute);self.execute_button.released.connect(self.release)
        right.addWidget(self.execute_button)
        self.inline_stop=QPushButton('停止运动（Esc）');self.inline_stop.setMinimumHeight(48)
        self.inline_stop.setStyleSheet('background:#b73b32;color:white;border-color:#b73b32;font-size:17px;font-weight:600')
        self.inline_stop.pressed.connect(self.stop_motion);right.addWidget(self.inline_stop)
        self.stop_shortcut=QShortcut(QKeySequence('Esc'),self)
        self.stop_shortcut.setContext(Qt.WindowShortcut);self.stop_shortcut.setAutoRepeat(False)
        self.stop_shortcut.activated.connect(self.stop_motion)
        right.addStretch(1)
        self.status=QLabel('未连接控制');self.status.setWordWrap(True);root.addWidget(self.status)
        self.detail=QLabel();self.detail.setWordWrap(True);self.detail.setStyleSheet('color:#b42318');self.detail.hide();root.addWidget(self.detail)
        self.safety_status=QLabel();self.safety_status.setObjectName('muted');self.safety_status.setWordWrap(True);root.addWidget(self.safety_status)
        actions=QHBoxLayout();actions.setSpacing(10)
        self.stop_button=QPushButton('停止移动');self.stop_button.setMinimumHeight(45)
        self.stop_button.setStyleSheet('background:#b73b32;color:white;border-color:#b73b32;font-size:16px;font-weight:600')
        self.stop_button.pressed.connect(self.stop_motion);actions.addWidget(self.stop_button,2)
        self.reset_button=QPushButton('继续控制');self.reset_button.setObjectName('primary');self.reset_button.setMinimumHeight(45)
        self.reset_button.clicked.connect(self.reset_safety);actions.addWidget(self.reset_button,2)
        self.end_button=QPushButton('结束本轮并锁定');self.end_button.setMinimumHeight(45)
        self.end_button.clicked.connect(self.end_session);actions.addWidget(self.end_button,1);root.addLayout(actions)
        backend=workspace.backend()
        if getattr(backend,'manual_control',None) is None:
            backend.manual_control=ManualControl(workspace.storage_path.parent/'manual_control_logs')
        self.controller=backend.manual_control;self.plan_id=None;self.held_direction=None
        self.waiting_feedback=False;self.feedback_deadline=0
        self.mode_parameters={0:(100,1),1:(.1,1)};self.previous_mode=None
        self.motion_mode.currentIndexChanged.connect(self.mode_changed);self.mode_changed()
        self.step.currentTextChanged.connect(self.invalidate_plan);self.speed.currentTextChanged.connect(self.invalidate_plan)
        self.checks[0].toggled.connect(self.confirmation_changed);self.payload.valueChanged.connect(self.confirmation_changed)
        self.timer=QTimer(self);self.timer.setInterval(50);self.timer.timeout.connect(self.refresh);self.refresh()

    def confirmation_changed(self):
        state=self.controller.snapshot()
        if state['unlocked'] or state['resumable']:
            self.controller.request_stop('现场确认或工具重量发生变化')
        self.plan_id=None

    def error(self,exc):
        self.detail.setText(str(exc));self.detail.show()

    def clear_error(self):self.detail.clear();self.detail.hide()

    def connect_control(self):
        try:
            backend=self.workspace.backend();frame=backend.snapshot()
            if frame and backend.address and self.address.text().strip()!=backend.address:
                raise ValueError('当前反馈来自 '+backend.address+'，请先在设备页连接所填地址，避免控制错误的机械臂')
            if not frame or not backend.address:
                if hasattr(self.workspace,'connect_feedback'):
                    self.waiting_feedback=True;self.feedback_deadline=time.monotonic()+8
                    self.workspace.address.setText(self.address.text().strip());self.workspace.connect_feedback()
                    self.error('正在连接反馈并等待静止状态，随后检查 TCP 控制。');return
                raise ValueError('请先连接只读反馈')
            external=backend.stop_monitor.snapshot()['state'] in ('armed','pending','acknowledged')
            self.controller.observe(frame,backend.generation,external)
            self.controller.connect(backend.address,backend.generation);self.clear_error()
        except (ValueError,OSError,RuntimeError) as exc:self.error(exc)
        self.refresh()

    def disconnect_control(self):
        self.waiting_feedback=False
        self.controller.close();self.clear_checks();self.plan_id=None;self.refresh()

    def clear_checks(self):
        for check in self.checks:check.setChecked(False)

    def unlock(self):
        if not all(check.isChecked() for check in self.checks):
            self.error('请先核对工具与现场，并勾选本轮确认。');return
        try:self.controller.unlock(True,self.payload.value(),interactive=True);self.clear_error()
        except (ValueError,OSError) as exc:self.error(exc)
        self.refresh()

    def stop_motion(self):
        self.controller.request_stop('人工停止',recoverable=True);self.plan_id=None;self.refresh()

    def end_session(self):
        self.controller.request_stop('结束本轮并锁定');self.clear_checks();self.plan_id=None;self.refresh()

    def reset_safety(self):
        try:
            state=self.controller.snapshot()
            if state['safety']['can_resume']:
                self.controller.resume_control()
            else:
                self.controller.reset_safety();self.clear_checks()
            self.plan_id=None;self.target.setText('请选择新的目标\n不会继续执行停止前的移动。');self.clear_error()
        except (ValueError,OSError) as exc:self.error(exc)
        self.refresh()

    def invalidate_plan(self):
        self.plan_id=None;self.target.setText('参数已变化，请重新选择方向。');self.refresh()

    def mode_changed(self):
        jogging=self.motion_mode.currentIndex()==0
        if self.previous_mode is not None:
            try:self.mode_parameters[self.previous_mode]=(self.step.value(),self.speed.value())
            except ValueError:pass
        mode=self.motion_mode.currentIndex();distance,speed=self.mode_parameters[mode];self.previous_mode=mode
        self.step_label.setText('上限（mm）' if jogging else '距离（mm）')
        self.step.configure([.01,.05,.1,.5,1,2,5,10,20,50,100],.01,100,distance)
        self.speed_label.setText('倍率（%）' if jogging else '速度（mm/s）')
        self.speed.configure([1,2,3,5,8,10] if jogging else [1,2,3,5,10,15,20],1,10 if jogging else 20,speed,integer=True)
        self.execute_button.setVisible(not jogging)
        self.motion_hint.setText('按住方向持续移动，松开即请求停止；可反复点动。' if jogging else '选方向核对目标，再按住执行；松手后可继续下一次。')
        self.plan_id=None;self.target.setText('控制器点动速度 × 所选倍率\n可输入自定义行程上限；单次最长30秒。' if jogging else '距离0.01–100 mm，目标速度1–20 mm/s\n可选择常用值，也可直接输入。')
        if hasattr(self,'timer'):self.refresh()

    def direction_press(self,axis,sign):
        if self.motion_mode.currentIndex()!=0:return
        if self.held_direction is not None:return
        self.held_direction=(axis,sign)
        try:
            ratio=self.speed.value();limit=self.step.value()
            self.controller.start_jog(axis,sign,ratio,limit);self.clear_error()
            self.target.setText(f"{axis}{'+' if sign>0 else '−'} 连续点动 · {ratio}% · 上限{limit:g} mm\n松开停止；不缓存下一次按键。")
        except (ValueError,OSError,RuntimeError) as exc:self.held_direction=None;self.error(exc)

    def direction_release(self,axis,sign):
        if self.held_direction==(axis,sign):
            self.held_direction=None;self.release()

    def preview(self,axis,sign):
        if self.motion_mode.currentIndex()==0:return
        try:
            step=self.step.value()*sign;speed=self.speed.value()
            plan=self.controller.preview(axis,step,speed);self.plan_id=plan['id']
            xyz=' / '.join(f'{v:.3f}' for v in plan['target'][:3])
            self.target.setText(f"{axis} {step:+g} mm · {speed} mm/s\n目标 XYZ：{xyz} mm\n保持姿态 · 用户0 / 工具{plan['tool']} · 10秒内有效")
            self.clear_error()
        except (ValueError,OSError) as exc:self.plan_id=None;self.error(exc)
        self.refresh()

    def execute(self):
        try:self.controller.execute(self.plan_id);self.clear_error()
        except (ValueError,OSError,RuntimeError) as exc:self.plan_id=None;self.error(exc)

    def release(self):
        if self.controller.snapshot()['phase'] in ('queued','moving'):
            self.controller.request_stop('松开移动按钮',recoverable=True,auto_rearm=True)
        self.plan_id=None;self.refresh()

    def refresh(self):
        state=self.controller.snapshot();frame=self.workspace.backend().snapshot();safety=state['safety']
        if self.waiting_feedback:
            if frame and frame.get('pose_stable') is True:
                self.waiting_feedback=False;self.connect_control();return
            if time.monotonic()>self.feedback_deadline:
                self.waiting_feedback=False;self.error('连接未完成：请检查 IP、反馈、使能状态及工具配置。')
        if self.plan_id and state['plan'] and self.controller.clock()-state['plan']['created']>10:
            self.plan_id=None;self.target.setText('目标预览已过期，请重新选择方向。')
        if frame:
            p=frame['pose']
            self.pose.setText(f'X   {p[0]:.3f} mm\nY   {p[1]:.3f} mm\nZ   {p[2]:.3f} mm\nRx {p[3]:.2f}°   Ry {p[4]:.2f}°   Rz {p[5]:.2f}°')
            self.io_status.setText(f"用户 {frame['user_index']} / 工具 {frame['tool_index']} · 测头 "+('触发' if frame['digital_inputs']&1 else '松开')+' · '+('有报警' if frame['error'] else '无报警'))
        else:self.pose.setText('反馈不可用');self.io_status.setText('等待只读反馈连接')
        age=safety['feedback_age_ms'];freshness='暂无反馈' if age is None else f'{age:.0f} ms'
        jogging=self.motion_mode.currentIndex()==0
        self.safety_status.setText('反馈 '+freshness+' · '+safety['feedback_reason']+(' · 点动倍率1%–10%' if jogging else ' · 目标速度受控制器设置和全局倍率影响'))
        if state['phase']=='moving' and state['motion_kind']=='jog':
            self.safety_status.setText('点动中 · 反馈 '+freshness+' · 松开方向按钮即请求停止')
        self.session_budget.setText(f"本次剩余 {safety['remaining_seconds']:.0f} 秒，可多次点动" if state['unlocked'] or state['resumable'] else '启用一次可反复点动，10分钟到期；异常会锁定。')
        text=state['reason']
        if state['phase']=='latched':
            if safety['can_resume']:text='已停止 · 点击“继续控制”，再选择新的目标'
            elif safety['can_reset']:text='本轮已锁定 · 点击“解除锁定”，再启用新一轮'
        if safety['stop_state']=='unconfirmed':text='无法确认停止 · 请使用实体急停，并检查连接及控制器状态'
        color='#b42318' if safety['stop_state']=='unconfirmed' else '#214f7d'
        self.status.setText(text);self.status.setStyleSheet(f'color:{color};background:#e8eff8;padding:9px;border-radius:7px;font-weight:600')
        self.connect_button.setEnabled(not state['connected'] and not self.waiting_feedback);self.disconnect_button.setEnabled(state['connected'] or self.waiting_feedback)
        self.address.setEnabled(not state['connected'] and not self.waiting_feedback)
        self.stop_button.setEnabled(state['connected']);self.inline_stop.setEnabled(state['connected']);self.end_button.setEnabled(state['connected'])
        self.reset_button.setText('继续控制' if state['resumable'] and safety['can_resume'] else '解除锁定' if safety['can_reset'] else '等待停止反馈' if state['phase'] in ('stopping','verifying_stop') else '继续控制')
        self.reset_button.setEnabled(safety['can_resume'] or safety['can_reset'])
        self.unlock_button.setEnabled(state['can_unlock']);self.unlock_button.setText('本轮已启用' if state['unlocked'] else '启用本轮控制')
        direction_held=False
        for index,button in enumerate(self.directions):
            axis=('X','Y','Z')[index//2];sign=(-1,1)[index%2]
            held=button.isDown() and self.held_direction==(axis,sign) and state['phase'] in ('queued','moving')
            direction_held=direction_held or held
            button.setEnabled((state['phase']=='ready' and safety['feedback_ok']) or held)
        holding=self.execute_button.isDown() and state['phase'] in ('queued','moving')
        self.execute_button.setEnabled(bool(self.plan_id and state['phase']=='ready' and safety['feedback_ok']) or holding)
        if (holding or direction_held) and self.isActiveWindow():self.controller.maintain_hold()
        if not state['unlocked'] and not state['resumable'] and state['phase'] in ('stopping','verifying_stop','latched','fault'):
            self.clear_checks();self.plan_id=None
        if not state['unlocked'] and state['phase'] in ('stopping','verifying_stop','latched','fault'):
            self.plan_id=None;self.target.setText('正在停止并核对反馈\n松手后自动恢复点动输入；异常需解除锁定。' if state['resumable'] and self.controller.auto_rearm else '本次目标已取消\n恢复控制后，请重新选择方向。')
        for control in (self.motion_mode,self.step,self.speed,self.payload,*self.checks):
            control.setEnabled(state['phase'] not in ('queued','moving','stopping','verifying_stop'))

    def event(self,event):
        if event.type() in (QEvent.Type.WindowDeactivate,QEvent.Type.Hide) and hasattr(self,'controller'):
            state=self.controller.snapshot()
            if state['unlocked'] or state['resumable']:
                self.controller.request_stop('控制窗口失去焦点或隐藏',recoverable=True)
        return super().event(event)

    def showEvent(self,event):
        super().showEvent(event);self.timer.start();self.refresh()

    def hideEvent(self,event):
        self.waiting_feedback=False;self.timer.stop();super().hideEvent(event)

    def closeEvent(self,event):
        self.timer.stop();self.controller.close();self.clear_checks();self.plan_id=None;super().closeEvent(event)

    def reject(self):self.close()
