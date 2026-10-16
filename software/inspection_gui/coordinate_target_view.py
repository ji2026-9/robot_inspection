"""Coordinate entry, wall-aware preview and locked real execution request."""
import copy,threading,time
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
        self.setWindowTitle('坐标到点 · 安全墙预演');self.resize(1250,820)
        root=QVBoxLayout(self);split=QSplitter(Qt.Horizontal);root.addWidget(split,1)
        controls=QWidget();left=QVBoxLayout(controls);scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(controls);scroll.setMinimumWidth(370);split.addWidget(scroll)
        title=QLabel('输入目标 → 检查 → 带墙预演');title.setStyleSheet('font-size:18px;font-weight:600');left.addWidget(title)
        note=QLabel('目标为测量臂底座B / 用户0坐标，XYZ为mm、姿态为度。默认保持当前姿态；先完成预演，绝不直接按输入坐标发送运动。')
        note.setWordWrap(True);left.addWidget(note)
        self.hold_orientation=QCheckBox('保持采样时的当前工具姿态');self.hold_orientation.setChecked(True);left.addWidget(self.hold_orientation)
        form=QFormLayout();self.fields=[];left.addLayout(form)
        for name in ('X','Y','Z','Rx','Ry','Rz'):
            field=QDoubleSpinBox();field.setRange(-2500,2500) if len(self.fields)<3 else field.setRange(-360,360)
            field.setDecimals(3);field.setSuffix(' mm' if len(self.fields)<3 else ' °');form.addRow(name,field);self.fields.append(field)
        read=QPushButton('读取当前位置作为目标初值');read.clicked.connect(self.read_current);left.addWidget(read)
        self.radius=QDoubleSpinBox();self.radius.setRange(0,500);self.radius.setSuffix(' mm');form.addRow('工具包络半径（需实测）',self.radius)
        self.tool_confirm=QCheckBox('已核对包络覆盖全部工具与测针');left.addWidget(self.tool_confirm)
        self.build=QPushButton('生成姿态路径并检查安全墙');self.build.clicked.connect(self.generate);left.addWidget(self.build)
        self.play=QPushButton('播放预演');self.play.clicked.connect(self.toggle_play);self.play.setEnabled(False);left.addWidget(self.play)
        self.reset=QPushButton('回到预演起点');self.reset.clicked.connect(lambda:self.slider.setValue(0));left.addWidget(self.reset)
        self.collision_pose=QPushButton('查看碰墙姿态');self.collision_pose.clicked.connect(self.show_collision);self.collision_pose.setEnabled(False);left.addWidget(self.collision_pose)
        self.execute=QPushButton('实机执行 · 先解锁手动控制');self.execute.setEnabled(False);self.execute.clicked.connect(self.try_execute);left.addWidget(self.execute)
        row=QHBoxLayout();row.addWidget(QLabel('执行速度'));self.execute_speed=QDoubleSpinBox()
        self.execute_speed.setRange(1,10);self.execute_speed.setDecimals(0);self.execute_speed.setValue(5);self.execute_speed.setSuffix(' mm/s')
        row.addWidget(self.execute_speed);row.addStretch(1);left.addLayout(row)
        self.detail=QPlainTextEdit();self.detail.setReadOnly(True);self.detail.setMinimumHeight(190);left.addWidget(self.detail)
        self.detail.setPlainText('尚未生成。实机执行锁定：实物几何、连续碰撞与控制器实际插补轨迹尚未验证。原有手动点动不受本预演检查保护。')
        self.scene=Scene3D();self.scene.probe_only=True;self.scene.distance=2200;split.addWidget(self.scene);split.setSizes([400,820]);split.setStretchFactor(1,1)
        self.slider=QSlider(Qt.Horizontal);self.slider.setRange(0,0);self.slider.valueChanged.connect(self.seek);root.addWidget(self.slider)
        self.progress=QLabel('预演尚未生成 · 不控制实机');root.addWidget(self.progress)
        self.timer=QTimer(self);self.timer.setInterval(33);self.timer.timeout.connect(self.advance)
        self.ready.connect(self._preview_finished)
        for field in (*self.fields,self.radius):field.valueChanged.connect(self.invalidate)
        self.hold_orientation.toggled.connect(self.orientation_changed);self.tool_confirm.toggled.connect(self.invalidate)
        self.orientation_changed()
        try:self.show_wall(load_wall(self.workspace.storage_path.parent/'safety_wall.json'))
        except (ValueError,OSError,TypeError) as error:self.detail.setPlainText('安全墙读取失败：'+str(error))

    def orientation_changed(self,*args):
        for field in self.fields[3:]:field.setEnabled(not self.hold_orientation.isChecked())
        self.invalidate()

    def invalidate(self,*args):
        self.revision+=1;self.plan=None;self.timer.stop();self.play.setText('播放预演');self.play.setEnabled(False)
        self.execute.setEnabled(False);self.collision_pose.setEnabled(False)
        self.scene.set_wall_test_result(None);self.scene.set_manual_preview(None,[],None);self.slider.setRange(0,0)
        self.detail.setPlainText('输入已变化，旧结果作废；请重新生成并检查。实机执行保持锁定。')

    def show_wall(self,wall):
        displayed=dict(wall);displayed['visible']=bool(wall['direction_confirmed']);self.scene.set_safety_wall(displayed)

    def read_current(self):
        try:
            frame=validate_start(self.workspace.backend().snapshot())
            for field,value in zip(self.fields,frame['pose']):field.setValue(value)
            self.detail.setPlainText('已读取目标初值；可修改XYZ，再生成带墙预演。')
        except (ValueError,TypeError,KeyError) as error:self.detail.setPlainText(str(error))

    def generate(self):
        if self.busy:return
        try:
            backend=self.workspace.backend();frame=copy.deepcopy(validate_start(backend.snapshot()))
            wall=load_wall(self.workspace.storage_path.parent/'safety_wall.json')
            if not self.tool_confirm.isChecked() or self.radius.value()<=0:raise ValueError('请先实测并填写工具包络半径，确认覆盖全部工具和测针')
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
        verdict='检查不通过，禁止执行：'+'；'.join(plan['problems']) if plan['problems'] else '显示模型采样路径未发现碰墙；不等于实机路径已验证安全'
        text=f"{verdict}\n目标：{plan['target_pose']}\n完成逆解：{len(plan['frames'])} 帧\n采样最小间隙：{plan['collision']['minimum_clearance_mm']:.2f} mm\n起点显示模型/反馈差：{plan['start_model_error_mm']:.2f} mm，{plan['start_model_error_deg']:.2f}°"
        clearance=plan['collision']['minimum_clearance_mm']
        clearance_ok=(not plan['problems'] and clearance>=EXECUTION_MIN_CLEARANCE_MM)
        text+=(f'\n执行门槛：采样间隙需 ≥ {EXECUTION_MIN_CLEARANCE_MM:.0f} mm（当前{"达标" if clearance_ok else "未达标"}）')
        text+='\n仍需人工确认：'+'；'.join(plan['execution_blockers'])
        if clearance_ok:
            text+='\n可执行：需先在“实机控制”界面连接并启用本轮控制（核对工具、负载与现场），再点击实机执行。'
        else:
            text+='\n实机执行保持禁止。'
        self.detail.setPlainText(text);self.execute.setEnabled(clearance_ok)
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
            if not self.plan:raise ValueError('没有有效预演')
            backend=self.workspace.backend()
            approval=request_execution(self.plan,backend.snapshot(),
                load_wall(self.workspace.storage_path.parent/'safety_wall.json'),backend.generation)
            control=getattr(backend,'manual_control',None)
            if control is None:raise ValueError('实机控制通道不可用，请先打开“实机控制”界面')
            state=control.snapshot()
            if not state.get('connected'):raise ValueError('请先在“实机控制”界面连接控制通道')
            if not state.get('unlocked') or state.get('phase')!='ready':
                raise ValueError('请先在“实机控制”界面勾选现场确认、填写负载并启用本轮控制')
            speed=int(self.execute_speed.value())
            move=control.preview_target(approval['target_pose'],speed)
            control.execute(move['id'])
            self.detail.setPlainText('已发送目标移动指令；DI_1 触发、偏离路径、超时或按下停止都会中断。')
        except (ValueError,PermissionError,OSError,RuntimeError) as error:
            self.detail.setPlainText('未执行：'+str(error))

    def hideEvent(self,event):self.timer.stop();super().hideEvent(event)
    def closeEvent(self,event):self.revision+=1;self.timer.stop();super().closeEvent(event)
