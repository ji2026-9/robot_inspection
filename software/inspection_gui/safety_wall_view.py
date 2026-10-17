"""Single global wall editor and local diagnostic preview."""
from pathlib import Path
import threading,time
from datetime import datetime
from .ui_feedback import FeedbackLabel
from PySide6.QtCore import Signal,Qt,QTimer
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,
    QComboBox,QDoubleSpinBox,QPushButton,QCheckBox,QPlainTextEdit,QScrollArea,QWidget,QSplitter,QGroupBox)
from .safety_wall import DEFAULT_WALL,load_wall,save_wall,validate_wall
from .stepper import DoubleParameter


class SafetyWallDialog(QDialog):
    wall_changed=Signal(object)
    test_ready=Signal(object,str,int)
    test_completed=Signal(object)
    test_cleared=Signal()
    def __init__(self,parent=None,config_path=None):
        super().__init__(parent)
        self.workspace=parent;self._test_token=0;self._testing=False;self._meshes=None
        self.path=Path(config_path) if config_path else Path(__file__).resolve().parents[1]/'data/probe_workspace/safety_wall.json'
        from .global_wall import wall_service
        self.service=wall_service(self.path);self._loading=True
        self.setWindowTitle('全局安全墙');self.resize(1080,760)
        root=QVBoxLayout(self);root.setContentsMargins(14,12,14,12);root.setSpacing(10)
        title=QLabel('全局安全墙');title.setStyleSheet('font-size:22px;font-weight:600');root.addWidget(title)
        self.status=QLabel();self.status.setWordWrap(True);self.status.setStyleSheet('color:#a56515;font-weight:600;');root.addWidget(self.status)
        self.service.status_changed.connect(self.refresh_status);self.refresh_status()
        info=QLabel('先测量方向与距离，再核对工具包络。坐标以测量臂B底座为准，单位 mm。')
        info.setWordWrap(True);root.addWidget(info)
        basic=QGroupBox('墙面位置与预留');form=QFormLayout(basic);root.addWidget(basic)
        self.direction=QComboBox();self.direction.addItems(['待确认墙在哪一侧','墙在 +X 侧','墙在 +Y 侧','墙在 −X 侧','墙在 −Y 侧','自定义方向'])
        form.addRow('墙的方向',self.direction);self.fields={}
        self.advanced=QGroupBox('更多参数与检查');self.advanced.setCheckable(True);self.advanced.setChecked(False)
        extra=QVBoxLayout(self.advanced);self.advanced_body=QWidget();extra.addWidget(self.advanced_body)
        advanced=QVBoxLayout(self.advanced_body);advanced.setContentsMargins(0,0,0,0);extraform=QFormLayout();advanced.addLayout(extraform)
        for key,label,lo,hi in [('yaw_deg','自定义方向角（°）',-180,180),
                              ('distance_mm','底座中心到墙面（mm）',1,10000),
                              ('margin_mm','墙内侧禁入预留（mm）',0,1000),
                              ('stop_reserve_mm','额外软件停止预留（mm）',10,1000),
                              ('width_mm','绘图宽度（mm）',1,20000),
                              ('height_mm','绘图高度（mm）',1,10000),
                              ('bottom_mm','绘图底部Z（mm）',-2000,10000)]:
            field=DoubleParameter();field.setRange(lo,hi);field.setDecimals(1);field.setSingleStep(.1);field.setValue(DEFAULT_WALL[key]);self.fields[key]=field
            (form if key in ('distance_mm','margin_mm') else extraform).addRow(label,field)
        self.fields['distance_mm'].setToolTip('330 mm只是编辑参考值，尚未测量，不能视为现场墙位置。')
        self.visible=QCheckBox('统一显示已确认方向的墙面');self.visible.hide()
        tool=QGroupBox('工具包络');toolform=QFormLayout(tool);root.addWidget(tool)
        self.tool_radius=DoubleParameter();self.tool_radius.setRange(1,500);self.tool_radius.setSingleStep(.1);self.tool_radius.setValue(50);self.tool_radius.setSuffix(' mm')
        toolform.addRow('包络半径',self.tool_radius)
        self.tool_confirm=QCheckBox('已核对墙面位置与方向，工具包络覆盖全部测针')
        self.tool_confirm.setToolTip('必须依据现场测量确认；未知时保持不勾选，软件运动入口锁定。')
        root.addWidget(self.tool_confirm)
        self.result=FeedbackLabel('现场墙面位置尚未确认');root.insertWidget(2,self.result)
        row=QHBoxLayout();self.preview_button=QPushButton('查看未应用草稿');self.save_button=QPushButton('应用到全局');self.save_button.setObjectName('primary')
        row.addWidget(self.preview_button);row.addWidget(self.save_button);root.addLayout(row)
        note=QLabel('作用于本软件的点动、定距和指定坐标：发指令前检查路径，运动中检查反馈并请求停止。\n不等同于控制器安全平面，不能保护由其他软件发起的运动。')
        note.setWordWrap(True);root.addWidget(note)
        self.test_current=QPushButton('检查当前姿态');self.test_path=QPushButton('检查测头任务路径')
        advanced.addWidget(self.test_current);advanced.addWidget(self.test_path)
        clear=QPushButton('清除检查快照');clear.clicked.connect(self.clear_test);advanced.addWidget(clear)
        self.test_detail=QPlainTextEdit();self.test_detail.setReadOnly(True);self.test_detail.setMaximumHeight(150)
        self.test_detail.setPlainText('使用显示模型和工具包络进行软件检查；模型未完成实物精度验证，不保证制动距离或采样间无碰撞。')
        advanced.addWidget(self.test_detail);root.addWidget(self.advanced)
        self.advanced.toggled.connect(self.advanced_body.setVisible);self.advanced_body.hide()
        root.addStretch()
        self.test_ready.connect(self.test_done)
        self.test_current.clicked.connect(lambda:self.start_test(False));self.test_path.clicked.connect(lambda:self.start_test(True))
        self.tool_radius.valueChanged.connect(self.geometry_changed);self.tool_confirm.toggled.connect(self.mark_dirty)
        close=QPushButton('关闭');close.clicked.connect(self.close);root.addWidget(close);self.close_button=close
        self.preview_button.clicked.connect(self.preview);self.save_button.clicked.connect(self.save)
        self.direction.currentIndexChanged.connect(self.direction_changed)
        for field in self.fields.values():field.valueChanged.connect(self.geometry_changed)
        self.visible.toggled.connect(self.mark_dirty)
        try:self.apply(self.service.snapshot())
        except (OSError,ValueError,TypeError) as error:self.result.setText('草稿读取失败，原文件保留：'+str(error));self.direction_changed(0)

    def refresh_status(self):self.status.setText(self.service.reason() or '已应用 · 所有三维视图同步，运动入口统一检查')

    def geometry_changed(self,*args):
        if self._loading:return
        self.tool_confirm.setChecked(False);self.mark_dirty()

    def apply(self,data):
        self._loading=True
        for key,field in self.fields.items():field.setValue(data[key])
        angle=data['yaw_deg'];index={0.:1,90.:2,180.:3,-180.:3,-90.:4}.get(angle,5) if data['direction_confirmed'] else 0
        self.direction.setCurrentIndex(index);self.fields['yaw_deg'].setValue(angle)
        self.visible.setChecked(data['visible']);self.direction_changed(index)
        self.tool_radius.setValue(data['tool_radius_mm']);self.tool_confirm.setChecked(data['wall_confirmed'] and data['tool_envelope_confirmed'])
        self._loading=False;self.result.setText('已载入全局设置' if self.path.exists() else '墙位置待测量；330 mm与50 mm仅为编辑参考值')

    def direction_changed(self,index):
        if index in (1,2,3,4):self.fields['yaw_deg'].setValue({1:0,2:90,3:180,4:-90}[index])
        self.fields['yaw_deg'].setEnabled(index==5)
        self.visible.setChecked(index!=0)
        self.geometry_changed()

    def mark_dirty(self,*args):
        self._test_token+=1
        self.test_cleared.emit()
        self.result.setText('有未应用修改；其他页面与运动检查继续使用已应用设置')
        if hasattr(self,'test_detail'):self.test_detail.setPlainText('参数已变化，之前的测试结果已失效，请重新测试。')

    def clear_test(self):
        self.mark_dirty();self.test_detail.setPlainText('测试快照已清除；没有向机械臂发送指令。')

    def start_test(self,path_test):
        if self._testing:return
        try:
            from .wall_collision import finite6
            wall=self.config()
            if not wall['direction_confirmed']:raise ValueError('请先选择并核对墙的方向')
            if not self.visible.isChecked():self.visible.setChecked(True);wall=self.config()
            if self.workspace is None or not hasattr(self.workspace,'backend'):raise ValueError('请从测头工作区打开测试窗口')
            if not hasattr(self.workspace.scene,'set_wall_test_result'):raise ValueError('请先关闭并重开孔检测软件，加载新的三维测试模块')
            radius=float(self.tool_radius.value()) if self.tool_confirm.isChecked() else None
            if path_test:
                task=self.workspace.task or {};frames=self.workspace.frames
                if not task.get('joint_preview_report',{}).get('complete') or not frames or not all(f.get('ik_valid') for f in frames):
                    raise ValueError('请先生成完整有效的虚拟关节预览；只有TCP路径或部分逆解不能检查整机')
                points=[finite6(f['joints'],'关节预览').tolist() for f in frames]
                offset=task.get('preview_tool_offset');actual=None
            else:
                frame=self.workspace.backend().snapshot()
                if not frame or not 0<=time.monotonic()-frame['received_monotonic']<=.2:raise ValueError('没有新鲜只读反馈，请先连接')
                if frame.get('running') or frame.get('mode') not in (4,5):raise ValueError('请保持机械臂静止后再取快照；无需为虚拟测试上使能')
                if frame.get('user_index')!=0:raise ValueError('当前工具位姿不在底座坐标系；请先核对用户坐标0')
                import numpy as np
                points=np.deg2rad(finite6(frame['joints'],'反馈关节角')).tolist()
                offset=frame.get('tool_offset');actual=frame.get('pose')
            token=self._test_token;self._testing=True;self.test_current.setEnabled(False);self.test_path.setEnabled(False)
            self.test_detail.setPlainText('正在后台检查显示模型；不向机械臂发送指令…')
            def work():
                try:
                    from .wall_collision import load_collision_meshes,check_pose,check_path
                    from .probe_workspace import atomic_json
                    if self._meshes is None:self._meshes=load_collision_meshes(Path(__file__).parent/'assets/local_dobot_cr5.npz')
                    result=check_path(self._meshes,points,wall,offset,radius,cancelled=lambda:token!=self._test_token) if path_test else check_pose(self._meshes,points,wall,offset,radius,actual)
                    result['tested_at']=datetime.now().astimezone().isoformat()
                    log=self.path.parent/'wall_tests'/(str(time.time_ns())+'.json')
                    try:atomic_json(log,result);result['log_path']=str(log)
                    except OSError as error:result['log_error']=str(error)
                    self.test_ready.emit(result,'',token)
                except Exception as error:self.test_ready.emit(None,str(error),token)
            threading.Thread(target=work,daemon=True,name='virtual-wall-check').start()
        except (ValueError,KeyError,TypeError) as error:self.test_detail.setPlainText('未测试：'+str(error));self.result.show_message('安全墙检查未完成：'+str(error),'error')

    def test_done(self,result,error,token):
        self._testing=False;self.test_current.setEnabled(True);self.test_path.setEnabled(True)
        if token!=self._test_token:self.test_detail.setPlainText('配置已变化，测试作废，请重新检查。');return
        if error:self.test_detail.setPlainText('未完成检查：'+error);self.result.show_message('安全墙检查失败：'+error,'error');return
        verdict='发现碰墙 / 进入预留禁区' if result['collision'] else '该模型在检查姿态 / 采样点未发现碰墙'
        names='、'.join(sorted({p['part'] for p in result['parts'] if p['collision']})) or '无'
        text=f"{verdict}\n最小模型间隙：{result['minimum_clearance_mm']:.2f} mm；碰撞部位：{names}"
        text+='\n工具包络已检查（按手工输入）' if result['tool_checked'] else '\n工具 / 测针包络未确认：本次仅检查机器人显示网格'
        if result['kind']=='path':text+=f"\n检查{result['samples']}个关节插值姿态，最大步长2°；不是连续碰撞检测"
        text+='\n显示模型与实物未校准；未检查自碰撞，不能据此认定实机路径安全。'
        text+='\n记录：'+result.get('log_path','保存失败：'+result.get('log_error',''))
        self.test_detail.setPlainText(text)
        self.result.show_message(verdict+f'；最小模型间隙 {result["minimum_clearance_mm"]:.2f} mm','error' if result['collision'] else 'info',hint='核对墙面和工具包络；发现侵入时不要执行该路径。' if result['collision'] else '仅为模型检查结果，仍需核验实物与控制器路径。')
        self.wall_changed.emit(result['wall'])
        self.test_completed.emit(result)

    def closeEvent(self,event):
        self._test_token+=1
        super().closeEvent(event)

    def config(self):
        data=dict(DEFAULT_WALL);data.update({key:field.value() for key,field in self.fields.items()})
        data.update(visible=self.visible.isChecked(),direction_confirmed=self.direction.currentIndex()!=0,
            wall_confirmed=self.tool_confirm.isChecked(),tool_envelope_confirmed=self.tool_confirm.isChecked(),tool_radius_mm=self.tool_radius.value())
        return validate_wall(data)

    def preview(self):
        try:self.wall_changed.emit(self.config());self.result.setText('仅此预览显示未应用草稿；全局设置尚未改变')
        except ValueError as error:self.result.show_message(str(error),'error')

    def save(self):
        try:
            data=self.service.apply(self.config());self.wall_changed.emit(self.service.display())
            self.result.setText('已应用到所有三维视图与本软件运动入口。'+('现场参数未确认，实机运动保持锁定。' if self.service.reason() else '软件路径与反馈检查已接入；控制器安全平面未部署。'))
        except (ValueError,OSError) as error:self.result.setText('未保存：'+str(error))


class SafetyWallWorkbench(QWidget):
    """Dedicated mainline work page; never opens robot control connections."""
    def __init__(self,workspace,parent=None):
        super().__init__(parent);self.workspace=workspace
        from .simulation_scene3d import Scene3D
        layout=QVBoxLayout(self);split=QSplitter(Qt.Horizontal);layout.addWidget(split)
        self.editor=SafetyWallDialog(workspace,workspace.storage_path.parent/'safety_wall.json')
        self.editor.setWindowFlags(Qt.Widget);self.editor.setMinimumWidth(400)
        self.editor.close_button.hide()
        self.scene=Scene3D();self.scene.probe_only=True;self.scene.distance=2200
        split.addWidget(self.editor);split.addWidget(self.scene);split.setSizes([430,800]);split.setStretchFactor(1,1)
        self.editor.wall_changed.connect(self.scene.set_safety_wall)
        self.editor.service.attach_scene(self.scene)
        self.editor.test_completed.connect(self.scene.set_wall_test_result)
        self.editor.test_cleared.connect(lambda:self.scene.set_wall_test_result(None))
        self.editor.service.attach_scene(workspace.scene)
        self.timer=QTimer(self);self.timer.setInterval(200);self.timer.timeout.connect(self.refresh)
    def refresh(self):
        if self.isVisible():self.scene.set_live_frame(self.workspace.backend().snapshot(),True)
    def showEvent(self,event):
        super().showEvent(event);self.timer.start();self.refresh()
    def hideEvent(self,event):
        self.timer.stop();super().hideEvent(event)
    def closeEvent(self,event):
        self.timer.stop();self.editor.close();super().closeEvent(event)
