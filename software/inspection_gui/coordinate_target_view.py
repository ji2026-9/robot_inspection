"""Coordinate entry, wall-aware preview and locked real execution request."""
import copy,math,threading,time
from pathlib import Path
import numpy as np
from PySide6.QtCore import Qt,QTimer,Signal
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,QPushButton,
    QDoubleSpinBox,QCheckBox,QSplitter,QWidget,QPlainTextEdit,QSlider,QScrollArea)
from .coordinate_target import build_target_preview,request_execution,validate_start,EXECUTION_MIN_CLEARANCE_MM
from .safety_wall import load_wall
from .simulation_scene3d import Scene3D

class CoordinateTargetDialog(QDialog):
    ready=Signal(object,str,int)
    def __init__(self,workspace):
        super().__init__(workspace);self.workspace=workspace;self.plan=None;self.revision=0;self.busy=False;self.meshes=None
        self.seed=None;self.seed_placeholder=False
        self.execute_ready=False;self.enabled_here=False
        self.setWindowTitle('坐标到点 · 安全墙预演');self.resize(1250,820)
        root=QVBoxLayout(self);split=QSplitter(Qt.Horizontal);root.addWidget(split,1)
        controls=QWidget();left=QVBoxLayout(controls);scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(controls);scroll.setMinimumWidth(370);split.addWidget(scroll)
        title=QLabel('输入目标 → 预演 → 执行');title.setStyleSheet('font-size:18px;font-weight:600');left.addWidget(title)
        note=QLabel('目标为测量臂底座B / 用户0坐标，XYZ为mm、姿态为度。默认保持当前姿态；安全墙没设置时只解算路径，不做碰墙检查。')
        note.setWordWrap(True);left.addWidget(note)
        self.hold_orientation=QCheckBox('保持采样时的当前工具姿态');self.hold_orientation.setChecked(True);left.addWidget(self.hold_orientation)
        form=QFormLayout();self.fields=[];left.addLayout(form)
        for name in ('X','Y','Z','Rx','Ry','Rz'):
            field=QDoubleSpinBox();field.setRange(-2500,2500) if len(self.fields)<3 else field.setRange(-360,360)
            field.setDecimals(3);field.setSuffix(' mm' if len(self.fields)<3 else ' °');form.addRow(name,field);self.fields.append(field)
        read=QPushButton('读取当前位置作为目标初值');read.clicked.connect(self.read_current);left.addWidget(read)
        self.radius=QDoubleSpinBox();self.radius.setRange(0,500);self.radius.setValue(120);self.radius.setSuffix(' mm')
        form.addRow('工具包络半径（设墙时才需要）',self.radius)
        self.tool_confirm=QCheckBox('已核对包络覆盖全部工具与测针（设墙时才需要）');left.addWidget(self.tool_confirm)
        self.build=QPushButton('生成路径预演');self.build.clicked.connect(self.generate);left.addWidget(self.build)
        self.play=QPushButton('播放预演');self.play.clicked.connect(self.toggle_play);self.play.setEnabled(False);left.addWidget(self.play)
        self.reset=QPushButton('回到预演起点');self.reset.clicked.connect(lambda:self.slider.setValue(0));left.addWidget(self.reset)
        self.collision_pose=QPushButton('查看碰墙姿态');self.collision_pose.clicked.connect(self.show_collision);self.collision_pose.setEnabled(False);left.addWidget(self.collision_pose)
        row=QHBoxLayout();row.addWidget(QLabel('执行速度'));self.execute_speed=QDoubleSpinBox()
        self.execute_speed.setRange(1,10);self.execute_speed.setDecimals(0);self.execute_speed.setValue(5);self.execute_speed.setSuffix(' mm/s')
        row.addWidget(self.execute_speed);row.addStretch(1);left.addLayout(row)
        section=QLabel('本轮实机授权');section.setStyleSheet('font-weight:600;color:#24415f');left.addWidget(section)
        self.control_state=QLabel('实机控制：未连接');self.control_state.setWordWrap(True);left.addWidget(self.control_state)
        self.session_confirm=QCheckBox('本次工具与现场已核对');left.addWidget(self.session_confirm)
        session_note=QLabel('包含负载与重心、工具坐标及实体急停；人员已离开运动范围。');session_note.setWordWrap(True);left.addWidget(session_note)
        row=QHBoxLayout();row.addWidget(QLabel('工具总重量'));self.payload=QDoubleSpinBox()
        self.payload.setRange(0,5);self.payload.setDecimals(3);self.payload.setValue(1.0);self.payload.setSuffix(' kg');row.addWidget(self.payload);row.addStretch(1);left.addLayout(row)
        row=QHBoxLayout();self.connect_control=QPushButton('连接实机控制');self.connect_control.clicked.connect(self.connect_control_channel)
        row.addWidget(self.connect_control);self.enable_control=QPushButton('启用本轮控制');self.enable_control.clicked.connect(self.enable_control_session)
        row.addWidget(self.enable_control);left.addLayout(row)
        self.execute=QPushButton('实机执行');self.execute.setEnabled(False);self.execute.clicked.connect(self.try_execute);left.addWidget(self.execute)
        self.detail=QPlainTextEdit();self.detail.setReadOnly(True);self.detail.setMinimumHeight(190);left.addWidget(self.detail)
        self.detail.setPlainText('流程：勾选现场确认并启用本轮控制 → 填坐标和包络半径 → 生成带墙预演 → 实机执行。实机执行只检查显示模型采样路径，不等于实物几何已验证。')
        self.scene=Scene3D();self.scene.probe_only=True;self.scene.distance=2200;split.addWidget(self.scene);split.setSizes([400,820]);split.setStretchFactor(1,1)
        self.slider=QSlider(Qt.Horizontal);self.slider.setRange(0,0);self.slider.valueChanged.connect(self.seek);root.addWidget(self.slider)
        self.progress=QLabel('预演尚未生成 · 不控制实机');root.addWidget(self.progress)
        self.timer=QTimer(self);self.timer.setInterval(33);self.timer.timeout.connect(self.advance)
        self.pose_timer=QTimer(self);self.pose_timer.setInterval(300);self.pose_timer.timeout.connect(self.refresh_pose)
        self.ready.connect(self._preview_finished)
        for field in (*self.fields,self.radius):field.valueChanged.connect(self.invalidate)
        self.hold_orientation.toggled.connect(self.orientation_changed);self.tool_confirm.toggled.connect(self.invalidate)
        self.session_confirm.toggled.connect(self.session_changed);self.payload.valueChanged.connect(self.session_changed)
        self.seed_from_feedback();self.orientation_changed()
        try:self.show_wall(load_wall(self.workspace.storage_path.parent/'safety_wall.json'))
        except (ValueError,OSError,TypeError) as error:self.detail.setPlainText('安全墙读取失败：'+str(error))
        self.refresh_control_state()
        self.auto_connect()

    def orientation_changed(self,*args):
        for field in self.fields[3:]:field.setEnabled(not self.hold_orientation.isChecked())
        self.invalidate()

    def invalidate(self,*args):
        self.revision+=1;self.plan=None;self.timer.stop();self.play.setText('播放预演');self.play.setEnabled(False)
        self.execute_ready=False;self.execute.setEnabled(False);self.collision_pose.setEnabled(False)
        self.scene.set_wall_test_result(None);self.scene.set_manual_preview(None,[],self.seed);self.slider.setRange(0,0)
        note='（未收到新鲜只读反馈，机械臂按示意姿态显示，不代表实机当前位姿）' if self.seed_placeholder else ''
        self.detail.setPlainText('输入已变化，旧结果作废；请重新生成并检查。实机执行保持锁定。'+note)

    def _current_joints(self):
        frame=self.workspace.backend().snapshot()
        joints=frame.get('joints') if isinstance(frame,dict) else None
        if (not isinstance(joints,(list,tuple)) or len(joints)!=6
            or not all(type(v) in (int,float) and math.isfinite(v) for v in joints)):return None
        return [float(v) for v in joints]

    def seed_from_feedback(self):
        joints=self._current_joints()
        self.seed_placeholder=joints is None
        self.seed={'joints_deg':joints if joints is not None else [130.,-50.,100.,40.,90.,0.]}
        self.scene.set_manual_preview(None,[],self.seed)

    def refresh_pose(self):
        self.refresh_control_state()
        if self.plan is not None:return
        self.seed_from_feedback()

    def backend_control(self):
        backend=self.workspace.backend()
        if getattr(backend,'manual_control',None) is None:
            from .manual_control import ManualControl
            backend.manual_control=ManualControl(self.workspace.storage_path.parent/'manual_control_logs')
        return backend,backend.manual_control

    def refresh_control_state(self):
        state=None
        try:
            control=getattr(self.workspace.backend(),'manual_control',None);state=control.snapshot() if control is not None else None
        except (AttributeError,TypeError):state=None
        connected=bool(state['connected']) if state else False
        unlocked=bool(state['unlocked']) if state and connected else False
        unconfirmed=bool(state and state['safety']['stop_state']=='unconfirmed')
        if state is None:text='实机控制：未连接 · 点“连接实机控制”'
        else:
            text=('实机控制：已连接' if connected else '实机控制：未连接')+(' · 本轮已启用' if unlocked else ' · 本轮未启用')
            text+=' · '+state['reason']
            if unconfirmed:text+=' · 无法确认停止，请使用实体急停'
        self.control_state.setText(text)
        self.control_state.setStyleSheet('color:'+('#b42318' if unconfirmed else '#214f7d')+';font-weight:600;')
        self.connect_control.setEnabled(not connected)
        self.enable_control.setEnabled(connected and not unlocked)
        self.enable_control.setText('本轮已启用' if unlocked else '启用本轮控制')
        for widget in (self.session_confirm,self.payload):widget.setEnabled(not unlocked)
        self.execute.setEnabled(bool(self.execute_ready and unlocked))

    def connect_control_channel(self):
        try:
            backend,control=self.backend_control();frame=backend.snapshot()
            if not frame or not backend.address:raise ValueError('请先在设备连接页连上只读反馈')
            control.observe(frame,backend.generation);control.connect(backend.address,backend.generation)
            self.detail.setPlainText('正在检查 TCP 控制模式（不使能、不运动）。连接成功后勾选现场确认并启用本轮控制。')
        except (ValueError,OSError,RuntimeError) as error:self.detail.setPlainText('未连接：'+str(error))
        self.refresh_control_state()

    def auto_connect(self):
        """Non-motion convenience: grab the control channel as soon as the window opens."""
        try:
            backend,control=self.backend_control()
            if control.snapshot()['connected']:return
            frame=backend.snapshot()
            if not frame or not backend.address:return
            control.observe(frame,backend.generation);control.connect(backend.address,backend.generation)
        except (ValueError,OSError,RuntimeError,AttributeError):pass

    def ensure_session(self):
        """Enable this round's motion permit if it is not already unlocked."""
        backend,control=self.backend_control()
        state=control.snapshot()
        if not state.get('connected'):
            self.auto_connect();state=control.snapshot()
            if not state.get('connected'):raise ValueError('实机控制未连接：请先连上只读反馈，再点“连接实机控制”')
        if state.get('unlocked') and state.get('phase')=='ready':return control
        if not self.session_confirm.isChecked():raise ValueError('请先勾选“本次工具与现场已核对”')
        frame=backend.snapshot()
        if frame:control.observe(frame,backend.generation)
        control.unlock(True,self.payload.value(),interactive=True);self.enabled_here=True
        state=control.snapshot()
        if not state.get('unlocked') or state.get('phase')!='ready':
            raise ValueError('无法启用本轮控制：'+str(state.get('reason') or state.get('phase')))
        return control

    def enable_control_session(self):
        try:
            backend,control=self.backend_control()
            if not self.session_confirm.isChecked():raise ValueError('请先勾选本轮工具与现场确认')
            frame=backend.snapshot()
            if frame:control.observe(frame,backend.generation)
            control.unlock(True,self.payload.value(),interactive=True);self.enabled_here=True
            self.detail.setPlainText('本轮控制已启用；生成带墙预演后点“实机执行”即可到点。')
        except (ValueError,OSError) as error:self.detail.setPlainText('未启用：'+str(error))
        self.refresh_control_state()

    def session_changed(self,*args):
        control=getattr(self.workspace.backend(),'manual_control',None)
        if control is not None:
            state=control.snapshot()
            if state['unlocked'] or state['resumable']:
                control.request_stop('现场确认或工具重量发生变化');self.enabled_here=False
        self.refresh_control_state()

    def show_wall(self,wall):
        displayed=dict(wall);displayed['visible']=bool(wall['direction_confirmed']);self.scene.set_safety_wall(displayed)

    def read_current(self):
        try:
            frame=validate_start(self.workspace.backend().snapshot())
            for field,value in zip(self.fields,frame['pose']):field.setValue(value)
            self.seed_from_feedback()
            self.detail.setPlainText('已读取目标初值；可修改XYZ，再生成带墙预演。')
        except (ValueError,TypeError,KeyError) as error:self.detail.setPlainText(str(error))

    def generate(self):
        if self.busy:return
        try:
            backend=self.workspace.backend();frame=copy.deepcopy(validate_start(backend.snapshot()))
            wall=load_wall(self.workspace.storage_path.parent/'safety_wall.json')
            if wall['direction_confirmed'] and (not self.tool_confirm.isChecked() or self.radius.value()<=0):
                raise ValueError('已设置安全墙：请先填写工具包络半径并勾选覆盖确认')
            target=[field.value() for field in self.fields]
            if self.hold_orientation.isChecked():target[3:]=frame['pose'][3:]
            radius=self.radius.value();generation=backend.generation;token=self.revision
            self.plan=None;self.busy=True;self.build.setEnabled(False);self.play.setEnabled(False);self.execute.setEnabled(False);self.timer.stop()
            self.show_wall(wall);self.detail.setPlainText('正在后台求解整段机械臂姿态并检查安全墙…没有发送运动指令。')
            def work():
                try:
                    from .wall_collision import load_collision_meshes
                    if self.meshes is None:self.meshes=load_collision_meshes(Path(__file__).parent/'assets/local_dobot_cr5.npz')
                    result=build_target_preview(frame,target,wall,radius,self.meshes,generation=generation,cancelled=lambda:token!=self.revision)
                    self.ready.emit(result,'',token)
                except Exception as error:self.ready.emit(None,str(error),token)
            threading.Thread(target=work,daemon=True,name='coordinate-target-preview').start()
        except (ValueError,OSError,TypeError,KeyError) as error:self.detail.setPlainText('未生成：'+str(error))

    def _preview_finished(self,plan,error,token):
        self.busy=False;self.build.setEnabled(True)
        if token!=self.revision:self.detail.setPlainText('目标已变化，旧预演已取消。');return
        if error:self.detail.setPlainText('预演失败，禁止执行：'+error);return
        self.plan=plan;self.show_wall(plan['wall'])
        seed=dict(joints_deg=plan['start']['joints']);self.scene.set_manual_preview(plan['task'],plan['frames'],seed)
        self.slider.setRange(0,max(0,len(plan['frames'])-1));self.seek(0);self.play.setEnabled(bool(plan['frames']))
        self.collision_pose.setEnabled(plan['collision']['collision'])
        wall_checked=bool(plan.get('wall_checked'))
        if plan['problems']:verdict='检查不通过，禁止执行：'+'；'.join(plan['problems'])
        elif wall_checked:verdict='显示模型采样路径未发现碰墙；不等于实机路径已验证安全'
        else:verdict='逆解完整；未设置安全墙，本次没有做碰墙检查'
        text=f"{verdict}\n目标：{plan['target_pose']}\n完成逆解：{len(plan['frames'])} 帧\n起点显示模型/反馈差：{plan['start_model_error_mm']:.2f} mm，{plan['start_model_error_deg']:.2f}°"
        if wall_checked:
            clearance=plan['collision']['minimum_clearance_mm']
            clearance_ok=(not plan['problems'] and clearance>=EXECUTION_MIN_CLEARANCE_MM)
            text+=f"\n采样最小间隙：{clearance:.2f} mm"
            text+=f'\n执行门槛：采样间隙需 ≥ {EXECUTION_MIN_CLEARANCE_MM:.0f} mm（当前{"达标" if clearance_ok else "未达标"}）'
        else:
            clearance_ok=not plan['problems']
            text+='\n未设置安全墙：间隙门槛不适用，执行前请自行确认运动范围内没有障碍。'
        text+='\n仍需人工确认：'+'；'.join(plan['execution_blockers'])
        if clearance_ok:
            text+='\n可执行：勾选“本次工具与现场已核对”，再点“实机执行”。'
        else:
            text+='\n实机执行保持禁止。'
        self.detail.setPlainText(text);self.execute_ready=clearance_ok;self.refresh_control_state()
        if plan['collision']['collision']:self.show_collision()

    def show_collision(self):
        if self.plan and self.plan['collision']['collision']:
            self.timer.stop();self.play.setText('播放预演');self.scene.set_wall_test_result(self.plan['collision'])

    def seek(self,value):
        if self.plan and self.plan['frames']:
            self.scene.set_wall_test_result(None);self.scene.manual_index=value;self.scene.update()
            self.progress.setText(f'预演 {value+1}/{len(self.plan["frames"])} · 播放速率仅用于显示，不是实机速度')

    def toggle_play(self):
        if self.timer.isActive():self.timer.stop();self.play.setText('继续预演')
        elif self.plan and self.plan['frames']:
            if self.slider.value()==self.slider.maximum():self.slider.setValue(0)
            self.scene.set_wall_test_result(None);self.timer.start();self.play.setText('暂停预演')

    def advance(self):
        if self.slider.value()>=self.slider.maximum():self.timer.stop();self.play.setText('重播预演')
        else:self.slider.setValue(self.slider.value()+1)

    def try_execute(self):
        try:
            if not self.plan:raise ValueError('没有有效预演，请先点“生成姿态路径并检查安全墙”')
            backend=self.workspace.backend()
            approval=request_execution(self.plan,backend.snapshot(),
                load_wall(self.workspace.storage_path.parent/'safety_wall.json'),backend.generation)
            control=getattr(backend,'manual_control',None)
            if control is None:raise ValueError('请先点“连接实机控制”')
            control=self.ensure_session()
            speed=int(self.execute_speed.value())
            move=control.preview_target(approval['target_pose'],speed)
            control.execute(move['id'])
            self.detail.setPlainText('已发送目标移动指令；DI_1 触发、偏离路径、超时或按下停止都会中断。')
        except (ValueError,PermissionError,OSError,RuntimeError) as error:
            self.detail.setPlainText('未执行：'+str(error))
        self.refresh_control_state()

    def showEvent(self,event):
        super().showEvent(event);self.refresh_pose();self.pose_timer.start()

    def hideEvent(self,event):
        self.timer.stop();self.pose_timer.stop();super().hideEvent(event)

    def closeEvent(self,event):
        self.revision+=1;self.timer.stop();self.pose_timer.stop()
        if self.enabled_here:
            try:
                control=getattr(self.workspace.backend(),'manual_control',None)
                if control is not None and control.snapshot()['unlocked']:control.request_stop('关闭坐标到点窗口')
            except (AttributeError,TypeError,OSError):pass
            self.enabled_here=False
        super().closeEvent(event)
