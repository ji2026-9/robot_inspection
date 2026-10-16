"""Probe records and previews, with a separately locked manual controller."""
from pathlib import Path
from datetime import datetime
import copy,json,threading,time
import numpy as np
from scipy.spatial.transform import Rotation
from PySide6.QtCore import Qt,QTimer,QObject,Signal
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QGridLayout,QLabel,QPushButton,
    QWidget,QFrame,QSplitter,QTabWidget,QScrollArea,QLineEdit,QTableWidget,QTableWidgetItem,
    QHeaderView,QAbstractItemView,QCheckBox,QDoubleSpinBox,QSlider,QFileDialog,QInputDialog,QPlainTextEdit)
from .probe_workspace import PositionLibrary,capture_position,manual_task,cartesian_frames,atomic_json,vector6
from .readonly_kinematics import audit_snapshot
from .simulation_scene3d import Scene3D
from .devices_view import _registered_backends,current_settings,remember_settings,_validate_address
from .simulated_vision import example_data,build_preview,load_json,DEMO_START
from .joint_preview import compile_joint_preview
from .offline_planning import robot_frames
from .probe_trigger import TriggerJournal,di1_state


STYLE='''QDialog,QWidget{background:#f7f9fc;color:#263b51;}
QLabel{background:transparent;} QLabel#muted{color:#7b8da0;font-size:11px;}
QLabel#sectionTitle{font-weight:600;font-size:13px;color:#24415f;}
QFrame#card{background:white;border:1px solid #e1e8f0;border-radius:10px;}
QPushButton{background:white;border:1px solid #cfdae7;border-radius:6px;padding:7px 10px;color:#245583;}
QPushButton:hover{background:#eaf2ff;} QPushButton:disabled{color:#a8b5c4;}
QPushButton#primary{background:#245fa6;color:white;border-color:#245fa6;}
QPushButton#primary:disabled{background:#afc1d8;border-color:#afc1d8;}
QLineEdit,QDoubleSpinBox{background:white;border:1px solid #d8e2ed;border-radius:5px;padding:5px;}
QTabWidget::pane{border:0;} QTabBar::tab{background:#eef3fa;color:#6a7f95;padding:9px 12px;border:0;}
QTabBar::tab:selected{background:#e4eeff;color:#225eaf;}
QScrollArea{border:0;} QScrollBar:vertical{width:8px;background:transparent;}
QScrollBar::handle:vertical{background:#ced9e5;border-radius:4px;min-height:30px;}
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}
QTableWidget{background:white;gridline-color:#eef2f7;border:1px solid #e1e8f0;}
QHeaderView::section{background:#edf3fa;color:#506984;padding:6px;border:0;}
'''


class WorkspaceSignals(QObject):
    connected=Signal(bool,str)
    audited=Signal(int,object,str)
    joints_ready=Signal(int,object,object,str)
    joints_progress=Signal(int,int,int)


class ProbeWorkspaceDialog(QDialog):
    def __init__(self,parent=None,storage_path=None):
        super().__init__(parent);self.setWindowTitle('测头臂工作区 · 记录、预览与实机控制');self.setStyleSheet(STYLE)
        area=self.screen().availableGeometry();self.resize(min(1250,area.width()-40),min(840,area.height()-40));self.setMinimumSize(800,540)
        self.storage_path=Path(storage_path) if storage_path else Path(__file__).resolve().parents[1]/'data'/'probe_workspace'/'positions.json'
        self.library=None;self.storage_error=''
        try:self.library=PositionLibrary(self.storage_path)
        except (OSError,ValueError,KeyError,TypeError) as exc:self.storage_error='位置库未能读取，原文件保留：'+str(exc)
        self.visible_ids=[];self.start_record=None;self.task=None;self.frames=[];self.audit=None;self.preview_seed=None
        self.connecting=False;self.auditing=False;self.audit_generation=0;self.closed=False;self.auto_attempted=False
        self.shutdown_event=threading.Event()
        self.feedback_configuration=None;self.feedback_was_valid=False
        self.preview_focused=False
        self.joint_generation=0;self.joint_cancel=threading.Event();self.joint_busy=False
        self.position=0.;self.last_tick=0.;self.loading_fields=False
        self.signals=WorkspaceSignals(self);self.signals.connected.connect(self.connection_finished);self.signals.audited.connect(self.audit_finished)
        self.signals.joints_ready.connect(self.joints_finished);self.signals.joints_progress.connect(self.joints_progress)
        self.trigger_cursor=0;self.trigger_missed=0;self.trigger_save_error=''
        self.trigger_journal=TriggerJournal(self.storage_path.parent/'probe_triggers')
        root=QVBoxLayout(self);root.setContentsMargins(14,12,14,12);root.setSpacing(10)
        heading=QHBoxLayout();label=QLabel('测头臂工作区');label.setStyleSheet('font-size:20px;font-weight:600;color:#19446b;');heading.addWidget(label)
        heading.addStretch();label=QLabel('轨迹仅预览 · 实机控制需独立解锁');label.setObjectName('muted');heading.addWidget(label);root.addLayout(heading)
        connection=QHBoxLayout();self.address=QLineEdit(current_settings()['robot_b'].get('address') or '192.168.5.1');self.address.setMaximumWidth(150)
        self.connect_button=QPushButton('连接只读反馈');self.connect_button.clicked.connect(self.connect_feedback)
        self.connection_state=QLabel('等待反馈');self.connection_state.setWordWrap(True)
        connection.addWidget(self.address);connection.addWidget(self.connect_button);connection.addWidget(self.connection_state,1)
        control=QPushButton('实机控制 · 默认锁定');control.clicked.connect(self.open_manual_control);connection.addWidget(control);root.addLayout(connection)
        split=QSplitter(Qt.Orientation.Horizontal);split.setChildrenCollapsible(False);root.addWidget(split,1)
        self.tabs=QTabWidget();self.tabs.setMinimumWidth(360);self.tabs.setMaximumWidth(450);split.addWidget(self.tabs)
        self._build_positions();self._build_manual();self._build_audit();self._build_simulated_vision();self._build_probe_trigger()
        self.scene=Scene3D();self.scene.probe_only=True;self.scene.distance=2200
        self.scene.setToolTip('左键旋转 · 右键平移 · 滚轮缩放\n虚拟关节跟随仅使用显示模型；未验证实物工具和碰撞，不控制实机。')
        split.addWidget(self.scene);split.setSizes([400,820]);split.setStretchFactor(1,1)
        self.tabs.currentChanged.connect(self.tab_changed)
        self.progress=QSlider(Qt.Orientation.Horizontal);self.progress.setRange(0,0);self.progress.valueChanged.connect(self.seek);root.addWidget(self.progress)
        self.joint_status=QLabel('生成路径后自动计算虚拟机械臂跟随');self.joint_status.setWordWrap(True);root.addWidget(self.joint_status)
        playback=QHBoxLayout();self.play_button=QPushButton('播放 TCP 轨迹');self.play_button.clicked.connect(self.toggle_preview);playback.addWidget(self.play_button)
        reset=QPushButton('回到起点');self.reset_button=reset;reset.clicked.connect(self.reset_preview);playback.addWidget(reset)
        self.focus_button=QPushButton('聚焦路径');self.focus_button.clicked.connect(self.focus_preview);playback.addWidget(self.focus_button);playback.addStretch()
        view=QPushButton('恢复斜视');view.clicked.connect(self.scene.reset_view);playback.addWidget(view);root.addLayout(playback)
        self.message_label=QLabel(self.storage_error or '记录当前配置下的 TCP；测球 TCP 尚未标定，任务不可执行于实机。');self.message_label.setWordWrap(True);self.message_label.setObjectName('muted');root.addWidget(self.message_label)
        self.timer=QTimer(self);self.timer.setInterval(33);self.timer.timeout.connect(self.tick)
        self.refresh_timer=QTimer(self);self.refresh_timer.setInterval(200);self.refresh_timer.timeout.connect(self.refresh_feedback)
        self.refresh_positions();self.invalidate_preview();self.tab_changed(0)

    def _build_probe_trigger(self):
        layout=self.page('测头采点');card,box=self.card('RMP60 · DI_1 只读监测')
        self.probe_state=QLabel('反馈未连接');self.probe_state.setWordWrap(True);box.addWidget(self.probe_state)
        self.probe_io=QLabel('DI_1：—    DO_1：—（只读）');box.addWidget(self.probe_io)
        box.addWidget(self.note('按 DI_1 高电平触发配置，每个低→高边沿自动保存一帧。停止联锁需独立启用；未启用时仅记录，不改变机械臂状态。'))
        self.stop_summary=QLabel('停止联锁：未启用');self.stop_summary.setWordWrap(True);box.addWidget(self.stop_summary)
        stop_button=QPushButton('测头触发停止 · 设置与隔离演练');stop_button.clicked.connect(self.open_stop_monitor);box.addWidget(stop_button)
        layout.addWidget(card)
        self.probe_count=QLabel();self.probe_count.setWordWrap(True);layout.addWidget(self.probe_count)
        self.probe_table=QTableWidget(0,3);self.probe_table.setHorizontalHeaderLabels(['接收时间','X / Y / Z mm','用户 / 工具'])
        self.probe_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.probe_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.probe_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.probe_table.verticalHeader().hide();self.probe_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.probe_table.setMinimumHeight(190);self.probe_table.itemSelectionChanged.connect(self.probe_selected);layout.addWidget(self.probe_table)
        self.probe_detail=QLabel('选择一条记录查看六维位姿和采样说明');self.probe_detail.setWordWrap(True);layout.addWidget(self.probe_detail)
        export=QPushButton('导出触发采点记录');export.clicked.connect(self.export_probe_triggers);layout.addWidget(export)
        analysis=QPushButton('白球采集与重复性分析');analysis.clicked.connect(self.open_sphere_analysis);layout.addWidget(analysis)
        layout.addWidget(self.note('记录的是输入变化后收到的第一帧位姿，不是控制器触发锁存坐标。网络延迟和反馈周期可能带来误差，也可能漏掉过短脉冲；不能直接当作已验证的标定或测量数据。'))
        layout.addStretch();self.refresh_probe_table()

    def open_sphere_analysis(self):
        from .sphere_analysis_view import SphereAnalysisDialog
        dialog=getattr(self,'_sphere_analysis_dialog',None)
        if dialog is None:self._sphere_analysis_dialog=dialog=SphereAnalysisDialog(self)
        dialog.show();dialog.raise_();dialog.activateWindow();return dialog

    def open_stop_monitor(self):
        control=getattr(self.backend(),'manual_control',None)
        if control is not None and control.snapshot()['connected']:
            self.message('请先在实机控制界面断开控制，再开启独立停止测试，避免控制端口冲突。',True);return
        from .probe_stop_view import ProbeStopDialog
        dialog=getattr(self,'_probe_stop_dialog',None)
        if dialog is None:self._probe_stop_dialog=dialog=ProbeStopDialog(self)
        dialog.show();dialog.raise_();dialog.activateWindow();return dialog

    def open_manual_control(self):
        from .manual_control_view import ManualControlDialog
        dialog=getattr(self,'_manual_control_dialog',None)
        if dialog is None:self._manual_control_dialog=dialog=ManualControlDialog(self)
        dialog.show();dialog.raise_();dialog.activateWindow();return dialog

    def refresh_probe_table(self):
        records=self.trigger_journal.records[-100:][::-1];self.visible_triggers=records
        self.probe_table.setRowCount(len(records))
        for row,record in enumerate(records):
            stamp=datetime.fromtimestamp(record['feedback_received_at']).strftime('%H:%M:%S.%f')[:-3]
            values=[stamp,' / '.join(f'{x:.2f}' for x in record['tcp_pose'][:3]),f"U{record['user_index']} / T{record['tool_index']}"]
            for col,value in enumerate(values):self.probe_table.setItem(row,col,QTableWidgetItem(value))
        self.update_probe_count()

    def update_probe_count(self):
        text=f'已保存 {len(self.trigger_journal.records)} 条触发记录（列表显示最近 100 条）'
        if self.trigger_missed:text+=f'\n接收队列溢出，至少 {self.trigger_missed} 条事件未保存。'
        if self.trigger_journal.load_errors:text+='\n部分历史文件读取失败，原文件保留。'
        if self.trigger_save_error:text+='\n保存失败，将重试：'+self.trigger_save_error
        self.probe_count.setText(text)
        self.probe_count.setStyleSheet('color:#b45309;' if self.trigger_missed or self.trigger_save_error or self.trigger_journal.load_errors else '')

    def refresh_probe_feedback(self,frame):
        monitor=getattr(self.backend(),'stop_monitor',None)
        report=monitor.snapshot() if monitor else {'reason':'当前驱动不支持停止联锁'}
        self.stop_summary.setText('停止联锁：'+report['reason'])
        state=di1_state(frame)
        self.probe_state.setText('反馈不可用 · 无法判断测头状态' if state is None else
            ('DI_1 高电平 · 按配置视为测头触发' if state else 'DI_1 低电平 · 按配置视为测头未触发'))
        self.probe_state.setStyleSheet('color:'+('#b45309' if state is None else '#c2413b' if state else '#15805e')+';font-weight:600;')
        outputs=frame.get('digital_outputs') if frame else None
        output='—' if type(outputs) is not int else 'ON' if outputs&1 else 'OFF'
        inputs='—' if state is None else str(int(state))
        self.probe_io.setText(f'DI_1：{inputs}    DO_1：{output}（只读）')
        reader=getattr(self.backend(),'probe_events_since',None)
        if reader is None:return
        batch=reader(self.trigger_cursor);changed=False
        self.trigger_missed=max(self.trigger_missed,batch['missed_events'])
        for record in batch['events'][:32]:
            try:self.trigger_journal.save(record)
            except (OSError,ValueError,TypeError) as exc:self.trigger_save_error=str(exc);break
            self.trigger_cursor=record['event_sequence'];self.trigger_save_error='';changed=True
        if changed:self.refresh_probe_table()
        else:self.update_probe_count()

    def probe_selected(self):
        row=self.probe_table.currentRow()
        if not 0<=row<len(self.visible_triggers):return
        record=self.visible_triggers[row]
        self.probe_detail.setText('TCP：'+' / '.join(f'{x:.4f}' for x in record['tcp_pose'])+'\n关节：'+
            ' / '.join(f'{x:.4f}' for x in record['joints_deg'])+
            f"\n反馈间隔：{record['feedback_interval_ms']:.2f} ms；控制器时间戳：{record.get('controller_timestamp_ms')}"+
            '\n接收帧采样，非硬件锁存；未验证测球 TCP，不用于实机执行。')

    def export_probe_triggers(self):
        path,_=QFileDialog.getSaveFileName(self,'导出触发采点记录','probe_triggers.json','JSON (*.json)')
        if path:
            try:self.trigger_journal.export(path);self.message('已导出接收帧触发记录，未标记为标定有效。')
            except (OSError,ValueError) as exc:self.message('导出失败：'+str(exc),True)

    def page(self,title):
        content=QWidget();layout=QVBoxLayout(content);layout.setContentsMargins(8,12,8,8);layout.setSpacing(12)
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(content);self.tabs.addTab(scroll,title)
        return layout

    def note(self,text):
        label=QLabel(text);label.setWordWrap(True);label.setObjectName('muted');return label

    def card(self,heading):
        frame=QFrame();frame.setObjectName('card');layout=QVBoxLayout(frame);layout.setContentsMargins(12,12,12,12);layout.setSpacing(9)
        label=QLabel(heading);label.setObjectName('sectionTitle');layout.addWidget(label);return frame,layout

    def _build_positions(self):
        layout=self.page('位置记录');card,box=self.card('当前位置 · TCP')
        self.current_pose=QLabel('未连接');self.current_pose.setWordWrap(True);box.addWidget(self.current_pose);layout.addWidget(card)
        self.position_name=QLineEdit();self.position_name.setPlaceholderText('位置名称，如待机位置、工件上方');self.position_name.setMaxLength(64);layout.addWidget(self.position_name)
        self.record_button=QPushButton('记录当前位置');self.record_button.setObjectName('primary');self.record_button.clicked.connect(self.save_current);layout.addWidget(self.record_button)
        self.positions_table=QTableWidget(0,3);self.positions_table.setHorizontalHeaderLabels(['名称','坐标 / 工具','时间'])
        self.positions_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.positions_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.positions_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection);self.positions_table.verticalHeader().hide()
        self.positions_table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.Stretch)
        for i in (1,2):self.positions_table.horizontalHeader().setSectionResizeMode(i,QHeaderView.ResizeMode.ResizeToContents)
        self.positions_table.setMinimumHeight(180);self.positions_table.itemSelectionChanged.connect(self.position_selected);layout.addWidget(self.positions_table)
        self.saved_detail=QLabel('选择记录查看原始坐标');self.saved_detail.setWordWrap(True);self.saved_detail.setMinimumHeight(100);layout.addWidget(self.saved_detail)
        actions=QGridLayout()
        for i,(text,callback) in enumerate([('作为预览起点',self.use_selected_start),('作为预览目标',self.use_selected_target),('重命名',self.rename_selected),('归档 / 恢复',self.archive_selected),('导出位置库',self.export_positions),('导入位置库',self.import_positions)]):
            button=QPushButton(text);button.clicked.connect(callback);actions.addWidget(button,i//2,i%2)
        layout.addLayout(actions);self.show_archived=QCheckBox('显示已归档位置');self.show_archived.toggled.connect(self.refresh_positions);layout.addWidget(self.show_archived)
        layout.addWidget(self.note('坐标按记录时的用户和工具配置保存。位置记录不会使机械臂运动；未标定的 TCP 不能当作测球中心。'));layout.addStretch()

    def _build_manual(self):
        layout=self.page('手动任务');card,box=self.card('起点')
        self.start_label=QLabel('尚未设置');self.start_label.setWordWrap(True);box.addWidget(self.start_label)
        button=QPushButton('以当前位置为起点');button.clicked.connect(self.use_current_start);box.addWidget(button);layout.addWidget(card)
        card,box=self.card('目标位姿 · B 基座坐标');self.target_fields={};grid=QGridLayout();grid.setSpacing(8)
        for i,axis in enumerate(('X','Y','Z','Rx','Ry','Rz')):
            field=QDoubleSpinBox();field.setDecimals(2);field.setRange(-5000 if i<3 else -360,5000 if i<3 else 360)
            field.setSuffix(' mm' if i<3 else ' °');field.valueChanged.connect(self.target_changed)
            cell=QVBoxLayout();cell.addWidget(self.note(axis));cell.addWidget(field);grid.addLayout(cell,i//2,i%2);self.target_fields[axis]=field
        box.addLayout(grid);layout.addWidget(card)
        self.clearance=QDoubleSpinBox();self.clearance.setRange(1,1000);self.clearance.setValue(50);self.clearance.setSuffix(' mm');self.clearance.valueChanged.connect(self.target_changed)
        row=QHBoxLayout();row.addWidget(QLabel('预览退让距离'));row.addWidget(self.clearance);layout.addLayout(row)
        self.task_name=QLineEdit('手动任务');self.task_name.setMaxLength(64);self.task_name.textChanged.connect(self.target_changed);layout.addWidget(self.task_name)
        self.preview_button=QPushButton('生成 TCP 轨迹预览');self.preview_button.setObjectName('primary');self.preview_button.clicked.connect(self.build_manual);layout.addWidget(self.preview_button)
        self.manual_summary=QLabel('需先设置起点');self.manual_summary.setWordWrap(True);layout.addWidget(self.manual_summary)
        row=QHBoxLayout();self.export_task_button=QPushButton('导出预览任务');self.export_task_button.clicked.connect(self.export_task);row.addWidget(self.export_task_button)
        load=QPushButton('导入预览任务');load.clicked.connect(self.import_task);row.addWidget(load);layout.addLayout(row)
        layout.addWidget(self.note('接近候选点沿目标工具 +Z 的反方向构造。生成后计算显示模型的虚拟关节跟随；未验证实物 TCP、控制器限位和碰撞。'));layout.addStretch()

    def _build_audit(self):
        layout=self.page('姿态核对');card,box=self.card('显示模型与控制器反馈')
        box.addWidget(self.note('使用同一帧的关节角、TCP 和工具偏移反算法兰。模型法兰轴已按厂家工具轴定义转换；剩余偏差仍保留。'))
        self.audit_button=QPushButton('核对当前姿态');self.audit_button.clicked.connect(self.start_audit);box.addWidget(self.audit_button)
        optional=QPushButton('尝试控制器只读正解');optional.clicked.connect(lambda:self.start_audit(query_controller=True));box.addWidget(optional);layout.addWidget(card)
        self.audit_summary=QLabel('尚未核对');self.audit_summary.setWordWrap(True);layout.addWidget(self.audit_summary)
        self.export_audit_button=QPushButton('导出核对报告');self.export_audit_button.clicked.connect(self.export_audit);self.export_audit_button.setEnabled(False);layout.addWidget(self.export_audit_button)
        layout.addWidget(self.note('青色点：按反馈工具配置反算的法兰。橙色点：显示模型法兰。核对为单个静态样本，不代表整条运动学或实物测球标定已验证。'))
        layout.addWidget(self.note('可选查询只发送 PositiveKin，不切换模式、不使能、不下发运动。控制器不响应时保留反馈核对结果。'));layout.addStretch()

    def backend(self):return _registered_backends['robot_b']

    def _build_simulated_vision(self):
        self.vision_start_record=None;self.loading_vision=False
        layout=self.page('模拟视觉');card,box=self.card('模拟视觉 → 测头臂路径')
        box.addWidget(self.note('没有相机也可测试坐标处理流程。此处所有转换参数均为模拟，任务仅预览。'))
        self.vision_example_button=QPushButton('载入四孔示例');self.vision_example_button.clicked.connect(self.load_vision_example);box.addWidget(self.vision_example_button)
        row=QHBoxLayout()
        for text,callback in [('导入模拟孔坐标',self.import_vision_input),('导入模拟转换',self.import_vision_transform)]:
            button=QPushButton(text);button.clicked.connect(callback);row.addWidget(button)
        box.addLayout(row);layout.addWidget(card)
        self.vision_start_label=QLabel('起点：示例位置（非实机）· 示例工具 0');self.vision_start_label.setWordWrap(True);layout.addWidget(self.vision_start_label)
        self.vision_current_button=QPushButton('使用实机当前位姿作为起点');self.vision_current_button.clicked.connect(self.use_vision_current);layout.addWidget(self.vision_current_button)
        self.vision_clearance=QDoubleSpinBox();self.vision_clearance.setRange(1,500);self.vision_clearance.setValue(50);self.vision_clearance.setSuffix(' mm');self.vision_clearance.valueChanged.connect(self.vision_changed)
        row=QHBoxLayout();row.addWidget(QLabel('接近 / 退回距离'));row.addWidget(self.vision_clearance);layout.addLayout(row)
        self.vision_build_button=QPushButton('生成模拟视觉路径');self.vision_build_button.setObjectName('primary');self.vision_build_button.clicked.connect(self.build_vision);layout.addWidget(self.vision_build_button)
        self.vision_summary=QLabel('请先载入四孔示例，或导入模拟孔坐标及转换参数。');self.vision_summary.setWordWrap(True);layout.addWidget(self.vision_summary)
        self.vision_table=QTableWidget(0,4);self.vision_table.setHorizontalHeaderLabels(['孔号','B 基座 X','Y','Z'])
        self.vision_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.vision_table.verticalHeader().hide()
        self.vision_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch);self.vision_table.setMinimumHeight(150);layout.addWidget(self.vision_table)
        self.vision_export_button=QPushButton('导出当前仅预览任务');self.vision_export_button.clicked.connect(self.export_task);layout.addWidget(self.vision_export_button)
        self.vision_advanced=QCheckBox('展开模拟坐标与转换参数');layout.addWidget(self.vision_advanced)
        self.vision_editor_container=QWidget();edit_layout=QVBoxLayout(self.vision_editor_container);edit_layout.setContentsMargins(0,0,0,0)
        self.vision_input=QPlainTextEdit();self.vision_input.setPlaceholderText('模拟孔坐标 JSON，必须注明来源坐标系和 mm 单位');self.vision_input.setMinimumHeight(160)
        self.vision_transform=QPlainTextEdit();self.vision_transform.setPlaceholderText('模拟坐标转换 JSON，必须明确标记未标定');self.vision_transform.setMinimumHeight(160)
        edit_layout.addWidget(self.note('孔坐标 / 接近方向'));edit_layout.addWidget(self.vision_input);edit_layout.addWidget(self.note('模拟来源坐标 → B 基座转换'));edit_layout.addWidget(self.vision_transform)
        self.vision_input.textChanged.connect(self.vision_changed);self.vision_transform.textChanged.connect(self.vision_changed)
        layout.addWidget(self.vision_editor_container);self.vision_editor_container.hide();self.vision_advanced.toggled.connect(self.vision_editor_container.setVisible)
        layout.addWidget(self.note('孔中心仅作为 TCP 候选点；工具方向、测球接触补偿、孔间避障和实际关节路径均未验证。生成新任务会替换工作区的上一条预览。'));layout.addStretch()

    def vision_changed(self,*_):
        if self.loading_vision:return
        self.invalidate_preview();self.vision_table.setRowCount(0)
        self.vision_summary.setText('模拟输入已更新，请重新生成；旧任务已失效。')

    def load_vision_example(self):
        data,transform=example_data();self.loading_vision=True
        try:
            self.vision_input.setPlainText(json.dumps(data,ensure_ascii=False,indent=2))
            self.vision_transform.setPlainText(json.dumps(transform,ensure_ascii=False,indent=2))
            self.vision_start_record=None;self.vision_start_label.setText('起点：示例位置（非实机）· 示例工具 0')
        finally:self.loading_vision=False
        self.vision_changed();self.vision_summary.setText('已载入四孔示例与模拟转换。没有使用真实视觉标定；点击生成即可预览。')

    def import_vision_input(self):self.import_vision_json(self.vision_input,'导入模拟孔坐标')
    def import_vision_transform(self):self.import_vision_json(self.vision_transform,'导入模拟转换参数')

    def import_vision_json(self,editor,title):
        path,_=QFileDialog.getOpenFileName(self,title,'','JSON (*.json)')
        if not path:return
        self.vision_changed()
        try:
            data=load_json(path);editor.setPlainText(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False))
            self.vision_summary.setText('已载入模拟输入；生成时会检查坐标、单位和转换参数。')
        except (OSError,ValueError,TypeError) as exc:editor.clear();self.vision_summary.setText('导入失败：'+str(exc));self.message(str(exc),True)

    def use_vision_current(self):
        try:
            record=self.current_record('模拟任务起点')
            if record['user_index']!=0:raise ValueError('实机起点需要用户坐标 0，不能混用其他用户坐标')
            self.vision_start_record=record;self.vision_start_label.setText(f"起点：实机反馈 · 工具 {record['tool_index']}（生成时重新取样）")
            self.vision_changed()
        except (ValueError,KeyError,OSError) as exc:self.message(str(exc),True)

    def build_vision(self):
        self.invalidate_preview();self.vision_table.setRowCount(0)
        try:
            raw=self.vision_input.toPlainText();conversion=self.vision_transform.toPlainText()
            if len(raw)>1024*1024 or len(conversion)>1024*1024:raise ValueError('模拟输入过大，最大 1 MB')
            if not raw.strip():raise ValueError('缺少模拟孔坐标，请先载入示例或导入坐标')
            if not conversion.strip():raise ValueError('缺少坐标转换参数；没有标定不能直接混用两套坐标')
            seed=None;source='example';start=DEMO_START;tool=0
            if self.vision_start_record is not None:
                seed=self.current_record('模拟任务起点')
                if seed['user_index']!=0:raise ValueError('实机用户坐标已变化，请重新读取基座坐标起点')
                if seed['tool_index']!=self.vision_start_record['tool_index'] or seed['tool_offset']!=self.vision_start_record['tool_offset']:raise ValueError('实机工具配置已变化，请重新读取起点')
                source='fresh_controller_feedback';start=seed['tcp_pose'];tool=seed['tool_index']
            task=build_preview(json.loads(raw),json.loads(conversion),start,tool,self.vision_clearance.value(),start_source=source)
            self.apply_task(task,seed)
            if seed is None:self.focus_preview()
            holes=task['holes_in_b_base'];self.vision_table.setRowCount(len(holes))
            for i,hole in enumerate(holes):
                for j,value in enumerate([hole['id']]+[f'{x:.2f}' for x in hole['position_mm']]):self.vision_table.setItem(i,j,QTableWidgetItem(value))
            self.vision_summary.setText(f"模拟任务 · {len(holes)} 个孔 · {len(task['waypoints'])} 个候选点\n模拟转换 → B 基座坐标 → 接近 / 测量候选点 / 退回\n未标定、未验证避障与可达性；不可下发实机。")
        except (ValueError,KeyError,TypeError,OSError) as exc:
            self.invalidate_preview();self.vision_summary.setText('未生成：'+str(exc));self.message(str(exc),True)

    def message(self,text,error=False):
        self.message_label.setText(text);self.message_label.setStyleSheet('color:#b45309;' if error else '')

    def connect_feedback(self):
        if self.connecting:return
        backend=self.backend()
        if backend.is_connected():self.address.setText(backend.address);self.refresh_feedback();return
        address=self.address.text().strip()
        if not address or not _validate_address(address):self.message('请填写有效的机械臂 IP 地址',True);return
        settings=current_settings();settings['robot_b'].update(address=address,port=30004,transport='网口');remember_settings(settings)
        self.connecting=True;self.connect_button.setEnabled(False);signals=self.signals
        def work():
            if self.shutdown_event.is_set():return
            try:ok=bool(backend.connect(settings['robot_b']));error=''
            except Exception as exc:ok=False;error=str(exc)
            if self.shutdown_event.is_set():backend.disconnect();return
            try:signals.connected.emit(ok,error)
            except RuntimeError:pass
        threading.Thread(target=work,daemon=True,name='probe-readonly-connect').start()

    def connection_finished(self,ok,error):
        self.connecting=False
        if not ok:self.message('只读反馈连接失败：'+error,True)
        self.refresh_feedback()

    def refresh_feedback(self):
        backend=self.backend();frame=backend.snapshot()
        self.refresh_probe_feedback(frame)
        if frame:
            configuration=(frame['user_index'],frame['tool_index'],tuple(frame.get('tool_offset',[])),tuple(frame.get('user_offset',[])))
            if self.feedback_configuration is not None and configuration!=self.feedback_configuration:
                self.audit_generation+=1;self.auditing=False;self.audit=None;self.scene.pose_audit=None
                self.export_audit_button.setEnabled(False);self.audit_summary.setText('用户 / 工具配置已变化，请重新核对。')
                if self.preview_seed is not None:
                    self.vision_changed();self.message('用户 / 工具配置已变化，旧预览已失效。',True)
            self.feedback_configuration=configuration
        elif self.feedback_was_valid:
            self.audit_generation+=1;self.auditing=False;self.audit=None;self.scene.pose_audit=None
            self.export_audit_button.setEnabled(False);self.audit_summary.setText('反馈不可用，旧核对结果已失效，请重连后重新核对。')
        self.feedback_was_valid=frame is not None
        self.connect_button.setEnabled(frame is None and not self.connecting)
        self.record_button.setEnabled(frame is not None and self.library is not None);self.audit_button.setEnabled(frame is not None and not self.auditing)
        self.vision_current_button.setEnabled(frame is not None)
        if frame:
            self.connection_state.setText('● 只读反馈已连接 · '+str(backend.address))
            pose=frame['pose'];self.current_pose.setText(f'X {pose[0]:.2f}   Y {pose[1]:.2f}   Z {pose[2]:.2f} mm\n'
                f'Rx {pose[3]:.2f}   Ry {pose[4]:.2f}   Rz {pose[5]:.2f} °\n用户 {frame["user_index"]}  ·  工具 {frame["tool_index"]}')
        else:
            self.connection_state.setText('等待只读反馈' if not self.connecting else '正在连接…');self.current_pose.setText('反馈不可用；旧实时位姿已失效')
        if self.tabs.currentIndex() not in (1,3):self.scene.set_live_frame(frame,True)

    def metadata(self):
        backend=self.backend();identity=backend.identity or {};responses=identity.get('responses',{})
        return {'address':backend.address,'model':responses.get('/properties/controllerType',{}).get('name','未获取'),
                'version':responses.get('/settings/version',{}).get('control','未获取')}

    def current_record(self,name='预览起点'):
        return capture_position(name,self.backend().snapshot(),self.metadata())

    def save_current(self):
        try:
            if self.library is None:raise ValueError(self.storage_error)
            record=self.current_record(self.position_name.text());self.library.add(record);self.refresh_positions(record['id'])
            self.position_name.clear();self.message('位置已保存：'+record['name']+'；未执行运动。')
        except (OSError,ValueError,KeyError,TypeError) as exc:self.message(str(exc),True)

    def refresh_positions(self,selected=None):
        if isinstance(selected,bool):selected=None
        if self.library is None:return
        records=[r for r in self.library.records if not r['archived'] or self.show_archived.isChecked()]
        self.visible_ids=[r['id'] for r in records];self.positions_table.setRowCount(len(records))
        for i,r in enumerate(records):
            stamp=datetime.fromisoformat(r['recorded_at']).astimezone().strftime('%m-%d %H:%M')
            for j,value in enumerate([r['name']+('（归档）' if r['archived'] else ''),f"U{r['user_index']} / T{r['tool_index']}",stamp]):self.positions_table.setItem(i,j,QTableWidgetItem(value))
            if r['id']==selected:self.positions_table.selectRow(i)

    def selected_record(self):
        row=self.positions_table.currentRow()
        if row<0 or row>=len(self.visible_ids) or self.library is None:raise ValueError('请先选择一条位置记录')
        return copy.deepcopy(next(r for r in self.library.records if r['id']==self.visible_ids[row]))

    def position_selected(self):
        try:
            r=self.selected_record();p=r['tcp_pose'];q=r['joints_deg']
            self.saved_detail.setText(f"{r['name']}\nTCP："+' / '.join(f'{x:.2f}' for x in p)+'\n关节：'+' / '.join(f'{x:.2f}' for x in q)+'\n单位：mm / °；工具配置未验证为实际测球中心。')
            self.saved_detail.setToolTip(json.dumps(r,ensure_ascii=False,indent=2))
        except ValueError:self.saved_detail.setText('选择记录查看原始坐标')

    def rename_selected(self):
        try:
            r=self.selected_record();name,ok=QInputDialog.getText(self,'重命名位置','名称',text=r['name'])
            if ok:self.library.change(r['id'],name=name);self.refresh_positions(r['id'])
        except (OSError,ValueError) as exc:self.message(str(exc),True)

    def archive_selected(self):
        try:
            r=self.selected_record();self.library.change(r['id'],archived=not r['archived']);self.refresh_positions()
            self.message('位置已恢复。' if r['archived'] else '位置已归档，可勾选“显示已归档位置”后恢复。')
        except (OSError,ValueError) as exc:self.message(str(exc),True)

    def export_positions(self):
        if self.library is None:return
        path,_=QFileDialog.getSaveFileName(self,'导出位置库','probe_positions.json','JSON (*.json)')
        if path:
            try:self.library.export(path);self.message('位置库已导出。')
            except (OSError,ValueError) as exc:self.message(str(exc),True)

    def import_positions(self):
        if self.library is None:return
        path,_=QFileDialog.getOpenFileName(self,'导入位置库','','JSON (*.json)')
        if path:
            try:count=self.library.import_file(path);self.refresh_positions();self.message(f'导入 {count} 条新记录；没有修改原始坐标。')
            except (OSError,ValueError,KeyError,TypeError) as exc:self.message(str(exc),True)

    def set_start(self,record):
        if record['user_index']!=0:raise ValueError('起点必须是用户坐标 0；目前没有其他用户坐标到基座的转换标定')
        self.start_record=copy.deepcopy(record);self.start_label.setText(record['name']+f" · 工具 {record['tool_index']}\n"+' / '.join(f'{v:.2f}' for v in record['tcp_pose']))
        self.invalidate_preview()

    def use_current_start(self):
        try:self.set_start(self.current_record());self.message('已采样预览起点；后续实机移动不会改变该样本。')
        except (ValueError,OSError,KeyError) as exc:self.message(str(exc),True)

    def use_selected_start(self):
        try:self.set_start(self.selected_record());self.tabs.setCurrentIndex(1)
        except (ValueError,KeyError) as exc:self.message(str(exc),True)

    def use_selected_target(self):
        try:
            record=self.selected_record()
            if record['user_index']!=0:raise ValueError('目标记录不是基座坐标，不能直接载入')
            if self.start_record is None:self.set_start(record)
            if record['tool_index']!=self.start_record['tool_index']:raise ValueError('目标与起点的工具编号不一致，不能直接混用')
            if record.get('tool_offset')!=self.start_record.get('tool_offset'):raise ValueError('目标与起点的工具偏移不同，不能直接混用')
            self.loading_fields=True
            for field,value in zip(self.target_fields.values(),record['tcp_pose']):
                if not field.minimum()<=value<=field.maximum():raise ValueError('该记录超出当前手动编辑范围')
                field.setValue(value)
            self.target_source={'type':'recorded_position','position_id':record['id']};self.tabs.setCurrentIndex(1)
        except (ValueError,KeyError) as exc:self.message(str(exc),True)
        finally:self.loading_fields=False;self.invalidate_preview()

    def target_changed(self,*_):
        if self.loading_fields:return
        self.target_source={'type':'manual_input'};self.invalidate_preview()

    def invalidate_preview(self):
        self.joint_generation+=1;self.joint_cancel.set();self.joint_busy=False
        self.task=None;self.frames=[];self.preview_seed=None
        if hasattr(self,'joint_status'):self.joint_status.setText('生成路径后自动计算虚拟机械臂跟随')
        if hasattr(self,'timer'):self.timer.stop()
        if hasattr(self,'scene'):
            self.scene.set_manual_preview(None,[],None)
            if self.preview_focused:self.scene.reset_view();self.preview_focused=False
        if hasattr(self,'progress'):self.progress.setRange(0,0);self.progress.setEnabled(False)
        if hasattr(self,'play_button'):self.play_button.setEnabled(False);self.play_button.setText('播放 TCP 轨迹')
        if hasattr(self,'focus_button'):self.focus_button.setEnabled(False)
        self.export_task_button.setEnabled(False)
        if hasattr(self,'vision_export_button'):self.vision_export_button.setEnabled(False)
        self.manual_summary.setText('参数已更新，请重新生成预览。' if self.start_record else '需先设置起点')

    def build_manual(self):
        self.invalidate_preview()
        try:
            if self.start_record is None:raise ValueError('先读取当前位置或载入一条记录作为起点')
            target=[field.value() for field in self.target_fields.values()]
            task=manual_task(self.start_record['tcp_pose'],target,self.start_record['tool_index'],self.clearance.value(),self.task_name.text(),
                {'start_position_id':self.start_record['id'],'target':getattr(self,'target_source',{'type':'manual_input'})})
            self.apply_task(task,self.start_record)
        except (ValueError,KeyError) as exc:self.message(str(exc),True)

    def apply_task(self,task,seed=None):
        self.joint_generation+=1;generation=self.joint_generation;self.joint_cancel.set()
        self.joint_cancel=threading.Event();cancel=self.joint_cancel
        frames=cartesian_frames(task);task=copy.deepcopy(task)
        for flag in ('hardware_executable','kinematics_verified','collision_verified','tool_calibration_verified','calibration_verified'):task[flag]=False
        # Imported files must never supply trusted precomputed joint trajectories.
        task.pop('joint_preview',None);task.pop('joint_preview_report',None)
        task['preview_only']=True;self.task=task;self.frames=[];self.preview_seed=copy.deepcopy(seed)
        self.scene.set_manual_preview(task,frames,seed);self.progress.setRange(0,len(frames)-1);self.progress.setEnabled(True)
        self.timer.stop();self.play_button.setEnabled(False);self.progress.setEnabled(False)
        self.export_task_button.setEnabled(False)
        self.focus_button.setEnabled(True)
        self.vision_export_button.setEnabled(False)
        mode='模拟视觉任务' if task.get('simulation_only') else '手动任务'
        self.manual_summary.setText(f"{mode} · 工具 {task['tool_index']} · {len(frames)} 帧\n{len(task['waypoints'])} 个候选点\n未验证逆解、碰撞和实物工具；不可执行。")
        self.joint_busy=True;self.joint_status.setText('正在后台计算虚拟关节跟随…')
        self.message('仅计算显示模型，不连接运动接口。')
        signals=self.signals
        def work():
            try:
                offset=seed.get('tool_offset') if seed else task.get('preview_tool_offset')
                if offset is None:
                    if task['tool_index']!=0:raise ValueError('缺少该工具的偏移配置，不能计算关节跟随')
                    offset=[0.,0.,0.,0.,0.,0.]
                offset=vector6(offset,'预览工具偏移')
                joints=seed['joints_deg'] if seed else None
                solved,report=compile_joint_preview(frames,offset,joints,cancel.is_set,
                    lambda done,total:signals.joints_progress.emit(generation,done,total))
                report['tool_offset']=offset;error=''
            except InterruptedError:return
            except Exception as exc:solved=[];report={};error=str(exc)
            if not cancel.is_set():
                try:signals.joints_ready.emit(generation,solved,report,error)
                except RuntimeError:pass
        threading.Thread(target=work,daemon=True,name='offline-joint-preview').start()

    def joints_progress(self,generation,done,total):
        if generation==self.joint_generation and not self.closed:
            self.joint_status.setText(f'正在后台计算虚拟关节跟随：{done} / {total}')

    def joints_finished(self,generation,frames,report,error):
        if generation!=self.joint_generation or self.closed or self.task is None:return
        self.joint_busy=False
        if error:
            self.joint_status.setText('关节跟随未生成：'+error);self.message(error,True);return
        self.task['joint_preview_report']=report
        self.task['preview_tool_offset']=report['tool_offset']
        self.task['joint_preview']=[{'joints_deg':np.rad2deg(f['joints']).tolist(),
            'tcp_pose':np.r_[f['tip'],Rotation.from_matrix(f['rotation']).as_euler('xyz',degrees=True)].tolist(),
            'stage':f['stage']} for f in frames]
        self.frames=frames;self.scene.set_manual_preview(self.task,frames,self.preview_seed)
        if self.tabs.currentIndex() not in (1,3):
            self.scene.set_manual_preview(None,[],None);self.refresh_feedback()
        self.progress.setRange(0,max(0,len(frames)-1));self.progress.setEnabled(bool(frames))
        self.play_button.setEnabled(bool(frames));self.play_button.setText('播放虚拟机械臂')
        self.export_task_button.setEnabled(True);self.vision_export_button.setEnabled(True)
        text=f"虚拟关节跟随：{len(frames)} / {report['total_frames']} 帧"
        if report['failure']:
            fail=report['failure'];text+=f"；在第 {fail['frame_index']+1} 帧停止：{fail['reason']}"
        else:text+=' · 全部求解完成'
        if report['near_singular_frames']:text+=' · 部分姿态接近模型奇异位置'
        self.joint_status.setText(text+'\n仅显示模型；±360° 为软件预览范围，控制器限位、避障及实物 TCP 未验证。')
        if frames:self.seek(0)
        else:self.message('没有可连续播放的有效关节样本；红点为失败目标。',True)

    def export_task(self):
        if self.task is None:return
        path,_=QFileDialog.getSaveFileName(self,'导出仅预览的手动任务','manual_preview.json','JSON (*.json)')
        if path:
            try:atomic_json(path,self.task);self.message('已导出预览任务；hardware_executable=false。')
            except (ValueError,OSError) as exc:self.message(str(exc),True)

    def import_task(self):
        path,_=QFileDialog.getOpenFileName(self,'导入仅预览的手动任务','','JSON (*.json)')
        if not path:return
        self.invalidate_preview()
        try:
            if Path(path).stat().st_size>1024*1024:raise ValueError('任务文件过大')
            task=json.loads(Path(path).read_text(encoding='utf-8-sig'))
            if task.get('schema_version')!=1 or task.get('units')!={'position':'mm','angle':'deg'}:raise ValueError('任务格式或单位无效')
            if not isinstance(task.get('waypoints'),list) or not 2<=len(task['waypoints'])<=100:raise ValueError('任务点数量无效')
            if type(task.get('tool_index')) is not int or not 0<=task['tool_index']<=255:raise ValueError('工具编号无效')
            self.apply_task(task);self.tabs.setCurrentIndex(1)
        except (OSError,ValueError,KeyError,TypeError,AttributeError) as exc:self.invalidate_preview();self.message(str(exc),True)

    def seek(self,value):
        if not self.frames:return
        value=max(0,min(int(value),len(self.frames)-1));self.scene.manual_index=value;self.scene.update()
        frame=self.frames[value];self.message('TCP 预览 · '+frame['stage']+' · '+' / '.join(f'{v:.2f}' for v in frame['tip'])+' mm')

    def toggle_preview(self):
        if self.joint_busy:return
        if self.timer.isActive():self.timer.stop();self.play_button.setText('继续预览');return
        if not self.frames:return
        if self.progress.value()==self.progress.maximum():self.progress.setValue(0)
        self.position=float(self.progress.value());self.last_tick=time.monotonic();self.timer.start();self.play_button.setText('暂停预览')

    def tick(self):
        now=time.monotonic();self.position+=(now-self.last_tick)/.06;self.last_tick=now
        value=min(int(self.position),self.progress.maximum());self.progress.setValue(value)
        if value==self.progress.maximum():
            self.timer.stop();self.play_button.setText('重新预览')
            if self.task.get('joint_preview_report',{}).get('failure'):self.message('已停在最后有效姿态；后续目标逆解失败，未继续播放。',True)

    def reset_preview(self):self.timer.stop();self.progress.setValue(0);self.seek(0);self.play_button.setText('播放 TCP 轨迹')

    def focus_preview(self):
        if self.task is None:return
        points=np.array([p['tcp_pose'][:3] for p in self.task['waypoints']],float)
        # Fit the whole moving arm, not just its TCP path; otherwise the elbow
        # leaves the viewport as the arm changes posture during playback.
        if self.frames and 'joints' in self.frames[0]:
            extent=[]
            for frame in self.frames[::max(1,len(self.frames)//40)]+self.frames[-1:]:
                extent.extend(t[:3,3] for t in robot_frames(frame['joints'],(0,0,0)).values())
            points=np.vstack([points,np.asarray(extent)])
        center=(points.min(axis=0)+points.max(axis=0))/2
        radius=float(np.max(np.linalg.norm(points-center,axis=1)))+120
        aspect=max(.4,min(1.,self.scene.width()/max(1,self.scene.height())))
        self.scene.pan[:]=center-[0,0,450];self.scene.distance=max(600.,radius/(np.sin(np.deg2rad(18.5))*aspect)*1.1)
        self.preview_focused=True;self.scene.update()

    def tab_changed(self,tab):
        if hasattr(self,'timer'):self.timer.stop()
        if not hasattr(self,'scene'):return
        if hasattr(self,'play_button'):
            self.play_button.setVisible(tab in (1,3));self.reset_button.setVisible(tab in (1,3));self.progress.setVisible(tab in (1,3));self.focus_button.setVisible(tab in (1,3))
            self.play_button.setText('播放 TCP 轨迹')
        if tab in (1,3):
            self.scene.set_manual_preview(self.task,self.frames,self.preview_seed)
            if self.frames:self.seek(self.progress.value())
        else:
            self.scene.set_manual_preview(None,[],None)
            if self.preview_focused:self.scene.reset_view();self.preview_focused=False
            self.refresh_feedback()

    def start_audit(self,*_,query_controller=False):
        if self.auditing:return
        frame=self.backend().snapshot()
        if frame is None:self.message('未收到有效反馈，不能核对',True);return
        self.auditing=True;self.audit=None;self.export_audit_button.setEnabled(False);self.audit_button.setEnabled(False)
        self.audit_generation+=1;generation=self.audit_generation;address=self.backend().address;signals=self.signals
        self.audit_summary.setText('正在只读核对…')
        def work():
            try:report=audit_snapshot(address,frame,query_controller);error=''
            except Exception as exc:report=None;error=str(exc)
            try:signals.audited.emit(generation,report,error)
            except RuntimeError:pass
        threading.Thread(target=work,daemon=True,name='probe-pose-audit').start()

    def audit_finished(self,generation,report,error):
        if generation!=self.audit_generation or self.closed:return
        self.auditing=False;self.audit_button.setEnabled(self.backend().is_connected())
        if error:self.audit_summary.setText('无法核对：'+error);return
        self.audit=report;self.scene.pose_audit=report;self.scene.update();self.export_audit_button.setEnabled(True)
        delta=report['visual_vs_controller'];source='控制器正解查询' if report['reference_source']=='controller_positive_kinematics' else '反馈工具配置反算'
        result='该样本一致' if report['display_chain_matches_sample'] else '显示模型需要进一步核对'
        text=f"{result}\n法兰位置差：{delta['position_mm']:.3f} mm\n法兰坐标轴角差：{delta['orientation_deg']:.3f}°\n已应用厂家末端轴定义转换\n参考来源：{source}\n工具 {report['tool_index']}；实物测球 TCP 未验证。"
        if report['reference_source']=='controller_positive_kinematics':
            error=report['feedback_vs_controller'];text+=f"\n正解 / 反馈：{error['position_mm']:.3f} mm，{error['orientation_deg']:.3f}°"
        if report['controller_query_error']:text+='\n正解查询未响应或被拒绝，已使用反馈核对；未切换控制模式。'
        self.audit_summary.setText(text)

    def export_audit(self):
        if self.audit is None:return
        path,_=QFileDialog.getSaveFileName(self,'导出静态核对报告','pose_audit.json','JSON (*.json)')
        if path:
            try:atomic_json(path,self.audit)
            except (ValueError,OSError) as exc:self.message(str(exc),True)

    def showEvent(self,event):
        super().showEvent(event);self.closed=False;self.refresh_timer.start();self.refresh_feedback()
        if not self.auto_attempted and not self.backend().is_connected():self.auto_attempted=True;QTimer.singleShot(0,self.connect_feedback)

    def closeEvent(self,event):
        if hasattr(self,'_manual_control_dialog'):self._manual_control_dialog.close()
        if hasattr(self,'_probe_stop_dialog'):self._probe_stop_dialog.close()
        if hasattr(self,'_sphere_analysis_dialog'):self._sphere_analysis_dialog.close()
        if self.joint_busy:self.invalidate_preview()
        self.joint_generation+=1;self.joint_cancel.set();self.joint_busy=False
        self.closed=True;self.timer.stop();self.refresh_timer.stop();self.audit_generation+=1;self.auditing=False;super().closeEvent(event)

    def shutdown(self):self.shutdown_event.set();self.close()


def show_probe_workspace(parent=None):
    dialog=getattr(parent,'_probe_workspace_dialog',None) if parent is not None else getattr(show_probe_workspace,'dialog',None)
    if dialog is None:
        dialog=ProbeWorkspaceDialog(parent)
        if parent is not None:parent._probe_workspace_dialog=dialog
        else:show_probe_workspace.dialog=dialog
    dialog.show();dialog.raise_();dialog.activateWindow();return dialog
