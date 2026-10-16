"""Safety-wall draft editor; deliberately cannot enable a motion permit."""
from pathlib import Path
import threading,time
from datetime import datetime
from PySide6.QtCore import Signal,Qt,QTimer
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,
    QComboBox,QDoubleSpinBox,QPushButton,QCheckBox,QPlainTextEdit,QScrollArea,QWidget,QSplitter)
from .safety_wall import DEFAULT_WALL,load_wall,save_wall,validate_wall


class SafetyWallDialog(QDialog):
    wall_changed=Signal(object)
    test_ready=Signal(object,str,int)
    test_completed=Signal(object)
    test_cleared=Signal()
    def __init__(self,parent=None,config_path=None):
        super().__init__(parent)
        self.workspace=parent;self._test_token=0;self._testing=False;self._meshes=None
        self.path=Path(config_path) if config_path else Path(__file__).resolve().parents[1]/'data/probe_workspace/safety_wall.json'
        self.setWindowTitle('玻璃安全墙 · 设置与虚拟碰撞测试');self.resize(690,800)
        outer=QVBoxLayout(self);scroll=QScrollArea();scroll.setWidgetResizable(True)
        content=QWidget();root=QVBoxLayout(content);scroll.setWidget(content);outer.addWidget(scroll)
        title=QLabel('玻璃安全墙设置');title.setStyleSheet('font-size:20px;font-weight:600');root.addWidget(title)
        status=QLabel('显示模型虚拟测试 · 尚未接入运动指令拦截')
        status.setWordWrap(True);status.setStyleSheet('color:#b42318;font-weight:600');root.addWidget(status)
        info=QLabel('坐标系：测量机械臂 B 底座，长度单位 mm。\n你口述的中心距离为约330 mm；已保存的设置会原样载入，请核对下方数值。\n橙色为玻璃，虚线为预留边界；测试按无限半空间检查。')
        info.setWordWrap(True);root.addWidget(info)
        form=QFormLayout();root.addLayout(form)
        self.direction=QComboBox();self.direction.addItems(['未确认方向','玻璃在 +X 侧','玻璃在 +Y 侧','玻璃在 −X 侧','玻璃在 −Y 侧','自定义水平方向'])
        form.addRow('朝向玻璃的方向',self.direction)
        self.fields={}
        for key,label,lo,hi in [('yaw_deg','方向角（°，+X=0，+Y=90）',-180,180),
                              ('distance_mm','底座中心至玻璃的垂直距离（mm）',1,10000),
                              ('margin_mm','向机械臂侧预留距离（mm，待确定）',0,1000),
                              ('width_mm','三维显示宽度（mm）',1,20000),
                              ('height_mm','三维显示高度（mm）',1,10000),
                              ('bottom_mm','显示底边高度 Z（mm）',-2000,10000)]:
            field=QDoubleSpinBox();field.setRange(lo,hi);field.setDecimals(1);field.setValue(DEFAULT_WALL[key]);self.fields[key]=field
            form.addRow(label,field)
        self.visible=QCheckBox('在测头工作区的三维预览中显示草稿');root.addWidget(self.visible)
        note=QLabel('计划禁止进入玻璃平面及其背后整个半空间；这里的宽高仅用于绘图，不是允许从边缘绕过去。\n此窗口仅配置和显示，不会向机械臂发送设置、停止或运动指令。')
        note.setWordWrap(True);root.addWidget(note)
        self.result=QLabel('尚未保存');self.result.setWordWrap(True);root.addWidget(self.result)
        row=QHBoxLayout();self.preview_button=QPushButton('更新三维草稿');self.save_button=QPushButton('保存草稿');row.addWidget(self.preview_button);row.addWidget(self.save_button);root.addLayout(row)
        unavailable=QPushButton('启用整机路径拦截（待开发、待实测）');unavailable.setEnabled(False);root.addWidget(unavailable)
        self.tool_radius=QDoubleSpinBox();self.tool_radius.setRange(1,500);self.tool_radius.setValue(50);self.tool_radius.setSuffix(' mm')
        self.tool_confirm=QCheckBox('已实测：法兰至TCP的胶囊包络能覆盖全部工具和测针')
        root.addWidget(QLabel('工具包络半径（50 mm仅为编辑初值，未确认前不用于检查）'));root.addWidget(self.tool_radius);root.addWidget(self.tool_confirm)
        self.test_current=QPushButton('虚拟检查当前姿态（只读反馈）')
        self.test_path=QPushButton('虚拟检查已生成的关节预览路径')
        root.addWidget(self.test_current);root.addWidget(self.test_path)
        clear=QPushButton('清除测试快照，恢复原预览');clear.clicked.connect(self.clear_test);root.addWidget(clear)
        self.test_detail=QPlainTextEdit();self.test_detail.setReadOnly(True);self.test_detail.setMaximumHeight(170)
        self.test_detail.setPlainText('尚未测试。检查机器人显示网格和可选工具包络，不检查自碰撞；路径使用关节插值采样，不能保证采样间无碰撞。结果不会授权实机运动。')
        root.addWidget(self.test_detail)
        self.test_ready.connect(self.test_done)
        self.test_current.clicked.connect(lambda:self.start_test(False));self.test_path.clicked.connect(lambda:self.start_test(True))
        self.tool_radius.valueChanged.connect(self.mark_dirty);self.tool_confirm.toggled.connect(self.mark_dirty)
        close=QPushButton('关闭');close.clicked.connect(self.close);root.addWidget(close);self.close_button=close
        self.preview_button.clicked.connect(self.preview);self.save_button.clicked.connect(self.save)
        self.direction.currentIndexChanged.connect(self.direction_changed)
        for field in self.fields.values():field.valueChanged.connect(self.mark_dirty)
        self.visible.toggled.connect(self.mark_dirty)
        try:self.apply(load_wall(self.path))
        except (OSError,ValueError,TypeError) as error:self.result.setText('草稿读取失败，原文件保留：'+str(error));self.direction_changed(0)

    def apply(self,data):
        for key,field in self.fields.items():field.setValue(data[key])
        angle=data['yaw_deg'];index={0.:1,90.:2,180.:3,-180.:3,-90.:4}.get(angle,5) if data['direction_confirmed'] else 0
        self.direction.setCurrentIndex(index);self.fields['yaw_deg'].setValue(angle)
        self.visible.setChecked(data['visible']);self.direction_changed(index)
        self.result.setText('已载入未验证草稿' if self.path.exists() else '尚未保存；请先核对方向和底座中心距离')

    def direction_changed(self,index):
        if index in (1,2,3,4):self.fields['yaw_deg'].setValue({1:0,2:90,3:180,4:-90}[index])
        self.fields['yaw_deg'].setEnabled(index==5);self.mark_dirty()

    def mark_dirty(self,*args):
        self._test_token+=1
        self.test_cleared.emit()
        self.result.setText('参数已更改，尚未应用或保存；保护仍未启用')
        if hasattr(self,'test_detail'):self.test_detail.setPlainText('参数已变化，之前的测试结果已失效，请重新测试。')
        if self.workspace is not None and hasattr(self.workspace,'scene'):
            if hasattr(self.workspace.scene,'set_wall_test_result'):self.workspace.scene.set_wall_test_result(None)

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
        except (ValueError,KeyError,TypeError) as error:self.test_detail.setPlainText('未测试：'+str(error))

    def test_done(self,result,error,token):
        self._testing=False;self.test_current.setEnabled(True);self.test_path.setEnabled(True)
        if token!=self._test_token:self.test_detail.setPlainText('配置已变化，测试作废，请重新检查。');return
        if error:self.test_detail.setPlainText('未完成检查：'+error);return
        verdict='发现碰墙 / 进入预留禁区' if result['collision'] else '该模型在检查姿态 / 采样点未发现碰墙'
        names='、'.join(sorted({p['part'] for p in result['parts'] if p['collision']})) or '无'
        text=f"{verdict}\n最小模型间隙：{result['minimum_clearance_mm']:.2f} mm；碰撞部位：{names}"
        text+='\n工具包络已检查（按手工输入）' if result['tool_checked'] else '\n工具 / 测针包络未确认：本次仅检查机器人显示网格'
        if result['kind']=='path':text+=f"\n检查{result['samples']}个关节插值姿态，最大步长2°；不是连续碰撞检测"
        text+='\n显示模型与实物未校准；未检查自碰撞，不能据此认定实机路径安全。'
        text+='\n记录：'+result.get('log_path','保存失败：'+result.get('log_error',''))
        self.test_detail.setPlainText(text)
        self.wall_changed.emit(result['wall']);self.workspace.scene.set_wall_test_result(result)
        self.test_completed.emit(result)

    def closeEvent(self,event):
        self._test_token+=1
        super().closeEvent(event)

    def config(self):
        data=dict(DEFAULT_WALL);data.update({key:field.value() for key,field in self.fields.items()})
        data.update(visible=self.visible.isChecked(),direction_confirmed=self.direction.currentIndex()!=0)
        return validate_wall(data)

    def preview(self):
        try:self.wall_changed.emit(self.config());self.result.setText('三维草稿已更新；没有启用运动保护')
        except ValueError as error:self.result.setText(str(error))

    def save(self):
        try:
            data=save_wall(self.path,self.config());self.wall_changed.emit(data)
            self.result.setText('草稿已保存：'+str(self.path)+'\n尚未验证，运动拦截未启用')
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
        self.editor.wall_changed.connect(workspace.scene.set_safety_wall)
        self.editor.test_completed.connect(self.scene.set_wall_test_result)
        self.editor.test_cleared.connect(lambda:self.scene.set_wall_test_result(None))
        try:self.scene.set_safety_wall(load_wall(self.editor.path))
        except (ValueError,OSError,TypeError):pass  # Editor shows the original error.
        self.timer=QTimer(self);self.timer.setInterval(200);self.timer.timeout.connect(self.refresh)
    def refresh(self):
        if self.isVisible():self.scene.set_live_frame(self.workspace.backend().snapshot(),True)
    def showEvent(self,event):
        super().showEvent(event);self.timer.start();self.refresh()
    def closeEvent(self,event):
        self.timer.stop();self.editor.close();super().closeEvent(event)
