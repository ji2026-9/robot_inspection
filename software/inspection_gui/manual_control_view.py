"""Compact real controller panel. Opening the panel never connects or moves."""
import time,math
from shiboken6 import isValid
from pathlib import Path
from .ui_feedback import FeedbackLabel
from PySide6.QtCore import QEvent,QTimer,Qt
from .stepper import DoubleParameter
from PySide6.QtGui import QShortcut,QKeySequence
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QGridLayout,QLabel,
    QPushButton,QCheckBox,QDoubleSpinBox,QComboBox,QFrame,QWidget,QToolButton,QLineEdit,QScrollArea,QListWidget,QListWidgetItem,QSplitter,QMessageBox,QTableWidgetItem,QFileDialog)
from .manual_control import ManualControl
from .numeric_parameter import NumericParameter
from .manual_preview import ManualPreview,validate_preview
from .safety_wall import load_wall


class ManualControlDialog(QDialog):
    def __init__(self, workspace):
        super().__init__(workspace)
        self.workspace=workspace
        self.setWindowTitle('测头机械臂 · 实机控制')
        self.resize(1180,820);self.setMinimumSize(840,600)
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
            QListWidget,QLineEdit{background:white;color:#263b51;border:1px solid #ccd8e6;border-radius:5px;padding:5px;}
            QComboBox,QDoubleSpinBox{background:white;border:1px solid #ccd8e6;border-radius:5px;padding:5px;color:#263b51;}
            QToolButton{border:0;color:#436d99;background:transparent;}
            QCheckBox{background:transparent;color:#263b51;}
            QCheckBox::indicator{width:15px;height:15px;border:1px solid #9badc3;border-radius:3px;background:white;}
            QCheckBox::indicator:checked{background:#2563ad;border-color:#2563ad;}
        """)
        root=QVBoxLayout(self);root.setContentsMargins(12,8,12,8);root.setSpacing(6)
        heading=QHBoxLayout()
        title=QLabel('测头机械臂');title.setStyleSheet('font-size:23px;font-weight:600');heading.addWidget(title)
        subtitle=QLabel('实机控制');subtitle.setObjectName('muted');heading.addWidget(subtitle);heading.addStretch()
        backend=workspace.backend()
        address=backend.address or (workspace.address.text() if hasattr(workspace,'address') else '192.168.5.1')
        self.address=QLineEdit(address);self.address.setMaximumWidth(140);self.address.setPlaceholderText('机械臂 IP');heading.addWidget(self.address)
        self.connect_button=QPushButton('连接控制');self.connect_button.clicked.connect(self.connect_control);heading.addWidget(self.connect_button)
        self.disconnect_button=QPushButton('断开');self.disconnect_button.clicked.connect(self.disconnect_control);heading.addWidget(self.disconnect_button)
        self.header_widgets=(title,subtitle,self.address,self.connect_button,self.disconnect_button)
        root.addLayout(heading)
        columns=QHBoxLayout();columns.setSpacing(14);root.addLayout(columns,1)
        left_pane=QWidget();left_pane.setMinimumWidth(310);left_pane.setMaximumWidth(360)
        left=QVBoxLayout(left_pane);left.setContentsMargins(0,0,0,0);left.setSpacing(12);columns.addWidget(left_pane,2)
        right_card=QFrame();right_card.setObjectName('controlCard');right=QVBoxLayout(right_card)
        right.setContentsMargins(18,16,18,16);right.setSpacing(12);columns.addWidget(right_card,3)
        pose_card=QFrame();pose_card.setObjectName('controlCard');pose_layout=QHBoxLayout(pose_card)
        pose_layout.setContentsMargins(12,8,12,8)
        label=QLabel('实时位姿');label.setObjectName('section');pose_layout.addWidget(label)
        self.pose=QLabel('等待只读反馈');self.pose.setWordWrap(True);self.pose.setMinimumHeight(104)
        self.pose.setStyleSheet('font-size:14px;line-height:1.5');self.pose.setTextInteractionFlags(Qt.TextSelectableByMouse)
        pose_layout.addWidget(self.pose,1)
        self.io_status=QLabel('测头 —  ·  控制器 —');self.io_status.setObjectName('muted');pose_layout.addWidget(self.io_status)
        left.addWidget(pose_card)
        session_card=QFrame();session_card.setObjectName('controlCard');session=QVBoxLayout(session_card)
        session.setContentsMargins(12,8,12,8);session.setSpacing(8)
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
        self.session_budget.setWordWrap(True);self.session_budget.setObjectName('muted');session.addWidget(self.session_budget,1)
        label.hide();note.hide();self.checks[0].setToolTip(note.text())
        root.addWidget(session_card)
        self.coordinate_button=QPushButton('输入目标坐标 · 带安全墙预演');self.coordinate_button.clicked.connect(self.open_coordinate_target)
        self.coordinate_button.hide()
        explanation=QToolButton();explanation.setText('查看控制说明');explanation.setCheckable(True)
        self.explanation=QLabel('连接控制只检查 TCP 状态。重量仅作人工确认记录，不会写入控制器。工具与负载需已正确配置、已使能。软件停止有延迟，实体急停须可用。')
        self.explanation.setObjectName('muted');self.explanation.setWordWrap(True);self.explanation.hide()
        explanation.toggled.connect(self.explanation.setVisible);left.addWidget(explanation);left.addWidget(self.explanation)
        label=QLabel('手动移动');label.setObjectName('section');right.addWidget(label)
        self.motion_mode=QComboBox();self.motion_mode.addItems(['连续点动 · 按住移动','定距移动 · 精细调整','位置与路径']);right.addWidget(self.motion_mode)
        self.motion_hint=QLabel();self.motion_hint.setObjectName('muted');self.motion_hint.setStyleSheet('color:#365b84;font-size:13px;');self.motion_hint.setWordWrap(True);right.addWidget(self.motion_hint)
        row=QHBoxLayout();self.step_label=QLabel('距离（mm）');row.addWidget(self.step_label);self.step=NumericParameter();row.addWidget(self.step)
        right.addLayout(row)
        row=QHBoxLayout();self.speed_label=QLabel('倍率（%）');row.addWidget(self.speed_label);self.speed=NumericParameter();row.addWidget(self.speed);right.addLayout(row)
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
        self.direction_panel=QWidget();self.direction_panel.setLayout(grid);right.addWidget(self.direction_panel)
        self.point_panel=QWidget();points=QGridLayout(self.point_panel);points.setContentsMargins(0,0,0,0)
        points.setVerticalSpacing(8)
        self.xyz=[]
        for i,axis in enumerate('XYZ'):
            points.addWidget(QLabel(axis),i,0)
            value=DoubleParameter();value.setRange(-2500,2500);value.setDecimals(3);value.setSingleStep(.1);value.setSuffix(' mm')
            points.addWidget(value,i,1);self.xyz.append(value)
            points.setRowMinimumHeight(i,38)
            value.valueChanged.connect(self.invalidate_plan)
        self.waypoints=[];self.waypoint_enabled=[]
        self.read_position=QPushButton('读取当前位置');self.read_position.clicked.connect(self.copy_position);points.addWidget(self.read_position,3,0,1,2)
        points.setRowMinimumHeight(3,40);self.point_panel.setMinimumHeight(178)
        from .target_table import TargetTable
        self.route_list=TargetTable();self.route_list.setMaximumHeight(175);self.route_list.setWordWrap(True);self.route_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.route_list.itemChanged.connect(self.waypoint_checked)
        self.route_list.setAccessibleName('目标位置列表');self.route_list.setToolTip('勾选要执行的目标，按列表顺序执行；取消勾选的目标不会经过。保持当前工具姿态，不自动绕过未知障碍。')
        points.addWidget(self.route_list,4,0,1,2)
        route_actions=QHBoxLayout();self.route_buttons=[]
        for text,callback in [('添加目标',self.add_waypoint),('删除',self.remove_waypoint),('上移',self.move_waypoint),('清空',self.clear_waypoints)]:
            button=QPushButton(text);button.setStyleSheet("padding:6px 5px;");button.clicked.connect(callback);route_actions.addWidget(button);self.route_buttons.append(button)
        points.addLayout(route_actions,5,0,1,2)
        self.route_summary=QLabel('尚未添加目标；可直接预览输入坐标');self.route_summary.setWordWrap(True);self.route_summary.setObjectName('muted')
        points.addWidget(self.route_summary,6,0,1,2)
        row=QHBoxLayout()
        for text,checked in [('全选',True),('全不选',False)]:
            button=QPushButton(text);button.clicked.connect(lambda _=False,v=checked:self.select_waypoints(v));row.addWidget(button);self.route_buttons.append(button)
        points.addLayout(row,7,0,1,2)
        origin_title=QLabel('返回位置 · XYZ');origin_title.setObjectName('section');points.addWidget(origin_title,8,0,1,2)
        self.origin_label=QLabel('尚未设置原点');self.origin_label.setWordWrap(True);points.addWidget(self.origin_label,9,0,1,2)
        row=QHBoxLayout();self.origin_buttons=[]
        for text,callback in [('保存当前位置',self.set_origin_current),('保存输入位置',self.set_origin_input)]:
            button=QPushButton(text);button.setStyleSheet('padding:6px 5px;');button.clicked.connect(callback);row.addWidget(button);self.origin_buttons.append(button)
        points.addLayout(row,10,0,1,2)
        self.return_origin_button=QPushButton('预览返回路径');self.return_origin_button.clicked.connect(self.preview_origin);points.addWidget(self.return_origin_button,11,0,1,2)
        note=QLabel('返回位置自动保存；保持当前工具姿态，不是机械零点，不更改控制器坐标系。预览后点击底部“确认预览并执行”。');note.setWordWrap(True);note.setObjectName('muted');points.addWidget(note,12,0,1,2)
        self.origin_path=workspace.storage_path.parent/'manual_origin.json';self.origin=None
        from .manual_origin import load_origin
        try:self.origin=load_origin(self.origin_path)
        except (OSError,ValueError,TypeError,KeyError) as exc:self.origin_label.setText('原点记录不可用：'+str(exc))
        self.update_origin_label()
        source_row=QHBoxLayout();source_row.addWidget(QLabel('目标类型'))
        self.preview_source=QComboBox();self.preview_source.addItems(['多点路径','返回保存位置','单个坐标']);source_row.addWidget(self.preview_source,1)
        self.preview_source_panel=QWidget();self.preview_source_panel.setLayout(source_row);right.addWidget(self.preview_source_panel)
        self.preview_source.currentIndexChanged.connect(self.invalidate_plan)
        self.preview_source.currentIndexChanged.connect(self.update_target_fields)
        self.path_source_summary=QLabel('尚未预览');self.path_source_summary.setWordWrap(True);self.path_source_summary.setStyleSheet('color:#365b84;font-size:12px;');right.addWidget(self.path_source_summary)
        task_row=QHBoxLayout()
        for text,callback in [('下移',self.move_waypoint_down),('插入',self.insert_waypoint),('保存任务',self.save_target_task),('打开任务',self.open_target_task)]:
            button=QPushButton(text);button.setStyleSheet('padding:6px 5px;');button.clicked.connect(callback);task_row.addWidget(button);self.route_buttons.append(button)
        points.addLayout(task_row,13,0,1,2)
        self.target_grid=points
        self.save_return_input=QPushButton('将输入坐标保存为返回位置')
        self.save_return_input.clicked.connect(self.set_origin_input);self.origin_buttons.append(self.save_return_input)
        points.addWidget(self.save_return_input,14,0,1,2)
        single_tasks=QHBoxLayout()
        for text,callback in [('保存目标任务',self.save_target_task),('打开任务',self.open_target_task)]:
            button=QPushButton(text);button.clicked.connect(callback);single_tasks.addWidget(button);self.route_buttons.append(button)
        points.addLayout(single_tasks,15,0,1,2)
        self.return_origin_button.hide()
        self.preview_source.blockSignals(True);self.preview_source.setCurrentIndex(2);self.preview_source.blockSignals(False)
        right.addWidget(self.point_panel)
        self.update_target_fields()
        self.build_target_button=QPushButton('规划并预览路径');self.build_target_button.clicked.connect(self.generate_target_preview)
        self.preview_view=ManualPreview(workspace)
        # Two main panes: controls on the left, an embedded preview on the right.
        columns.removeWidget(left_pane);columns.removeWidget(right_card)
        left.removeWidget(pose_card);right.addWidget(pose_card)
        pose_layout.setContentsMargins(10,4,10,4);self.pose.setMinimumHeight(36)
        self.pose.setStyleSheet('font-size:12px;');self.io_status.setWordWrap(True)
        root.removeWidget(session_card);right.insertWidget(0,session_card)
        left.removeWidget(explanation);left.removeWidget(self.explanation);right.addWidget(explanation);right.addWidget(self.explanation)
        right_card.setMinimumWidth(300)
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(right_card);scroll.setMinimumWidth(320);scroll.setMaximumWidth(390)
        self.control_scroll=scroll;self.session_card=session_card;self.pose_card=pose_card;self.parameter_layout=right;self.root_layout=root
        splitter=QSplitter(Qt.Horizontal);splitter.addWidget(scroll);splitter.addWidget(self.preview_view)
        splitter.setStretchFactor(0,0);splitter.setStretchFactor(1,1);splitter.setSizes([350,900]);splitter.setChildrenCollapsible(False);self.columns_splitter=splitter
        columns.addWidget(splitter,1);self.preview_view.expand_requested.connect(self.expand_preview)
        left_pane.hide()
        # Put current feedback, target and workflow beside the path, above the viewport.
        right.removeWidget(pose_card);self.preview_view.layout().insertWidget(1,pose_card)
        self.overview=QFrame();self.overview.setObjectName('controlCard');overview_layout=QVBoxLayout(self.overview);overview_layout.setContentsMargins(10,7,10,7);overview_layout.setSpacing(3)
        self.workflow_label=QLabel();self.workflow_label.setWordWrap(True);overview_layout.addWidget(self.workflow_label)
        self.overview_target=QLabel();self.overview_target.setWordWrap(True);self.overview_target.setTextInteractionFlags(Qt.TextSelectableByMouse);overview_layout.addWidget(self.overview_target)
        self.preview_view.layout().insertWidget(2,self.overview);self.submitted_target=None
        self.point_seeded=False
        self.target=QLabel('尚未选择目标\n选择 X / Y / Z 方向后在这里核对。')
        self.target.setWordWrap(True);self.target.setMinimumHeight(44)
        self.target.setStyleSheet('background:#f2f6fc;border-radius:8px;padding:10px;color:#3d5d80;');right.addWidget(self.target)
        self.execute_button=QPushButton('按住执行 · 松开停止');self.execute_button.setObjectName('primary');self.execute_button.setMinimumHeight(47)
        self.execute_button.setAutoRepeat(False);self.execute_button.pressed.connect(self.execute);self.execute_button.released.connect(self.release)
        self.stop_shortcut=QShortcut(QKeySequence('Esc'),self)
        self.stop_shortcut.setContext(Qt.WindowShortcut);self.stop_shortcut.setAutoRepeat(False)
        self.stop_shortcut.activated.connect(self.stop_motion)
        right.addStretch(1)
        self.status=FeedbackLabel('未连接控制');self.status.setWordWrap(True);root.addWidget(self.status)
        self.detail=FeedbackLabel();self.detail.hide();root.insertWidget(1,self.detail)
        self._fault_box=None;self._fault_key=None
        self.safety_status=QLabel();self.safety_status.setObjectName('muted');self.safety_status.setWordWrap(True);right.addWidget(self.safety_status)
        actions=QHBoxLayout();actions.setSpacing(10)
        actions.addWidget(self.build_target_button,2);actions.addWidget(self.execute_button,2)
        self.stop_button=QPushButton('停止运动（Esc）');self.stop_button.setMinimumHeight(45)
        self.stop_button.setStyleSheet('background:#b73b32;color:white;border-color:#b73b32;font-size:16px;font-weight:600')
        self.stop_button.pressed.connect(self.stop_motion);actions.addWidget(self.stop_button,2)
        self.reset_button=QPushButton('继续控制');self.reset_button.setObjectName('primary');self.reset_button.setMinimumHeight(45)
        self.reset_button.clicked.connect(self.reset_safety);actions.addWidget(self.reset_button,2)
        self.end_button=QPushButton('结束本轮并锁定');self.end_button.setMinimumHeight(45)
        self.end_button.clicked.connect(self.end_session);actions.addWidget(self.end_button,1);root.addLayout(actions)
        self.inline_stop=self.stop_button
        backend=workspace.backend()
        if getattr(backend,'manual_control',None) is None:
            from .global_wall import wall_service
            from .wall_guard import WallGuard
            service=wall_service(workspace.storage_path.parent/'safety_wall.json')
            backend.manual_control=ManualControl(workspace.storage_path.parent/'manual_control_logs',wall_guard=WallGuard(service))
        self.controller=backend.manual_control;self.plan_id=None;self.held_direction=None
        self.waiting_feedback=False;self.feedback_deadline=0
        self.mode_parameters={0:(100,1),1:(.1,1),2:(100,5)};self.previous_mode=None
        self.motion_mode.currentIndexChanged.connect(self.mode_changed);self.mode_changed()
        self.step.currentTextChanged.connect(self.invalidate_plan);self.speed.currentTextChanged.connect(self.invalidate_plan)
        self.checks[0].toggled.connect(self.confirmation_changed);self.payload.valueChanged.connect(self.confirmation_changed)
        self.preview_view.feedback.connect(self.preview_feedback)
        self.timer=QTimer(self);self.timer.setInterval(50);self.timer.timeout.connect(self.refresh);self.preview_view.changed.connect(self.preview_changed);self.refresh()

    def update_target_fields(self):
        if not hasattr(self,'target_grid'):return
        mode=self.preview_source.currentIndex()
        for row in range(self.target_grid.rowCount()):
            visible=(row<=3 and mode!=1) or (row in (4,5,6,7,13) and mode==0) or (row in (8,9,10,12) and mode==1) or (row in (14,15) and mode==2)
            for col in range(self.target_grid.columnCount()):
                item=self.target_grid.itemAtPosition(row,col)
                if item:self._show_target_item(item,visible)
            self.target_grid.setRowMinimumHeight(row,38 if visible and row<=3 else 0)
        self.return_origin_button.hide()

    def _show_target_item(self,item,visible):
        if item.widget():item.widget().setVisible(visible)
        if item.layout():
            for index in range(item.layout().count()):self._show_target_item(item.layout().itemAt(index),visible)

    def expand_preview(self,expanded):
        for widget in self.header_widgets:widget.setVisible(not expanded)
        self.overview.setVisible(not expanded)
        self.control_scroll.setVisible(not expanded);self.session_card.setVisible(not expanded);self.pose_card.setVisible(not expanded)
        self.preview_view.expand_button.setText('还原布局' if expanded else '放大预览')
        QTimer.singleShot(0,self.preview_view.fit_view)

    def update_origin_label(self):
        if not self.origin:self.origin_label.setText('尚未设置原点；请保存当前或输入XYZ位置。')
        if self.origin:
            x,y,z=self.origin['xyz'];self.origin_label.setText(f'X {x:.3f}   Y {y:.3f}   Z {z:.3f} mm')
            self.origin_label.setToolTip('原点来源：'+str(self.origin_path)+'\n只保存XYZ返回位置，不是机械零点。')

    def save_user_origin(self,xyz):
        try:
            if self.controller.snapshot()['phase'] in ('queued','moving','stopping','verifying_stop'):raise ValueError('请等待运动和停止核对结束后再设置原点')
            from .manual_origin import save_origin
            backend=self.workspace.backend()
            self.origin=save_origin(self.origin_path,xyz,backend.snapshot(),backend.address)
            self.update_origin_label();self.invalidate_plan();self.clear_error()
            self.target.setText('自定义原点已保存；只保存位置，没有发送运动。')
            self.pin_notice(False);self.detail.show_message('自定义原点已保存。','success',hint='需要返回时，点击“回到原点 · 先预览”。');self.detail.show()
        except (ValueError,OSError,TypeError,KeyError) as exc:self.error(exc)

    def set_origin_current(self):
        frame=self.workspace.backend().snapshot()
        if not frame:self.error('请先连接只读反馈');return
        self.save_user_origin(frame['pose'][:3])

    def set_origin_input(self):self.save_user_origin([v.value() for v in self.xyz])

    def preview_origin(self):
        self.preview_source.setCurrentIndex(1);self.generate_target_preview()

    def origin_target(self):
        from .manual_origin import load_origin,origin_position
        backend=self.workspace.backend();frame=backend.snapshot()
        # Another running window may have updated the same origin file.
        latest=load_origin(self.origin_path)
        if latest is None:raise ValueError('没有保存的原点，请先设置；原点文件：'+str(self.origin_path))
        xyz=origin_position(latest,frame,backend.address);self.origin=latest;self.update_origin_label()
        return frame,xyz

    def update_route_summary(self):
        selected=[str(i+1) for i,v in enumerate(self.waypoint_enabled) if v]
        self.route_summary.setText(f'已勾选 {len(selected)} / {len(self.waypoints)} 个目标 · 顺序：'+(' → '.join(selected) if selected else '未选择，请勾选目标') if self.waypoints else '尚未添加目标；可直接预览输入坐标')

    def update_waypoints(self):
        self.route_list.blockSignals(True);self.route_list.setRowCount(len(self.waypoints))
        for i,xyz in enumerate(self.waypoints):
            item=QTableWidgetItem(f'{i+1:02d}');item.setFlags((item.flags()|Qt.ItemIsUserCheckable)&~Qt.ItemIsEditable)
            item.setCheckState(Qt.Checked if self.waypoint_enabled[i] else Qt.Unchecked);self.route_list.setItem(i,0,item)
            for column,v in enumerate(xyz,1):self.route_list.setItem(i,column,QTableWidgetItem(f'{v:.3f}'))
        self.route_list.blockSignals(False);self.update_route_summary();self.invalidate_plan()

    def waypoint_checked(self,item):
        index=self.route_list.row(item);column=item.column()
        if 0<=index<len(self.waypoint_enabled):
            if column==0:self.waypoint_enabled[index]=item.checkState()==Qt.Checked
            else:
                try:
                    value=float(item.text())
                    if not math.isfinite(value) or abs(value)>2500:raise ValueError('XYZ需为−2500至2500 mm内的有限数值')
                    self.waypoints[index][column-1]=round(value,3)
                except ValueError as exc:self.error('目标坐标未修改：'+str(exc));self.update_waypoints();return
            self.update_route_summary();self.invalidate_plan()

    def select_waypoints(self,checked):
        self.waypoint_enabled=[checked]*len(self.waypoints);self.update_waypoints()

    def add_waypoint(self):
        if len(self.waypoints)>=20:self.error('最多20个目标位置');return
        self.preview_source.setCurrentIndex(0);self.waypoints.append([v.value() for v in self.xyz]);self.waypoint_enabled.append(True);self.update_waypoints()
    def remove_waypoint(self):
        index=self.route_list.currentRow()
        if index>=0:self.waypoints.pop(index);self.waypoint_enabled.pop(index);self.update_waypoints()
    def move_waypoint(self):
        index=self.route_list.currentRow()
        if index>0:
            self.waypoints[index-1],self.waypoints[index]=self.waypoints[index],self.waypoints[index-1]
            self.waypoint_enabled[index-1],self.waypoint_enabled[index]=self.waypoint_enabled[index],self.waypoint_enabled[index-1]
            self.update_waypoints();self.route_list.setCurrentRow(index-1)
    def clear_waypoints(self):self.waypoints.clear();self.waypoint_enabled.clear();self.update_waypoints()

    def move_waypoint_down(self):
        index=self.route_list.currentRow()
        if 0<=index<len(self.waypoints)-1:
            for values in (self.waypoints,self.waypoint_enabled):values[index],values[index+1]=values[index+1],values[index]
            self.update_waypoints();self.route_list.setCurrentRow(index+1)

    def insert_waypoint(self):
        if len(self.waypoints)>=20:self.error('最多20个目标');return
        index=max(0,self.route_list.currentRow());self.waypoints.insert(index,[v.value() for v in self.xyz]);self.waypoint_enabled.insert(index,True)
        self.preview_source.setCurrentIndex(0);self.update_waypoints();self.route_list.setCurrentRow(index)

    def save_target_task(self):
        try:
            from .target_task import save_task
            path,_=QFileDialog.getSaveFileName(self,'保存多目标任务',str(self.workspace.storage_path.parent/'targets.json'),'JSON (*.json)')
            if not path:return
            frame=self.workspace.backend().snapshot();metadata=dict(origin=self.origin,controller_address=self.workspace.backend().address,
                configuration={k:frame.get(k) for k in ('user_index','tool_index','user_offset','tool_offset')} if frame else None,
                safety_wall=load_wall(self.preview_view.wall_path))
            mode=self.preview_source.currentIndex();metadata['target_mode']='single' if mode==2 else 'route'
            if mode==2:targets=[[v.value() for v in self.xyz]];selected=[True]
            elif mode==1:
                _,xyz=self.origin_target();targets=[xyz];selected=[True];metadata['target_mode']='single'
            else:targets=self.waypoints or [[v.value() for v in self.xyz]];selected=self.waypoint_enabled or [True]
            save_task(Path(path),targets,selected,self.speed.value(),metadata)
            self.pin_notice(False);self.detail.show_message('已保存：'+str(Path(path).resolve())+'；返回位置不会在打开任务时被覆盖。','success');self.detail.show()
        except (ValueError,OSError,TypeError) as exc:self.error(exc)

    def open_target_task(self):
        try:
            if self.controller.snapshot()['phase'] in ('queued','moving','stopping','verifying_stop'):raise ValueError('运动或停止核对期间不能加载任务')
            from .target_task import load_task
            from pathlib import Path
            path,_=QFileDialog.getOpenFileName(self,'打开多目标任务',str(self.workspace.storage_path.parent),'JSON (*.json)')
            if not path:return
            task=load_task(Path(path));self.waypoints=task['targets'];self.waypoint_enabled=task['selected']
            single=task.get('metadata',{}).get('target_mode')=='single' and len(self.waypoints)==1
            if single:
                for value,position in zip(self.xyz,self.waypoints[0]):value.setValue(position)
            self.preview_source.setCurrentIndex(2 if single else 0);self.speed.setEditText(str(task['speed']));self.update_waypoints()
            frame=self.workspace.backend().snapshot();previous=task.get('metadata',{}).get('configuration')
            different=bool(previous and frame and previous!={k:frame.get(k) for k in ('user_index','tool_index','user_offset','tool_offset')})
            self.pin_notice(False);self.detail.show_message('任务已载入，但保存时的工具或坐标配置与当前不同；请核对后重新预览。' if different else '任务已载入。旧预览已取消，需要以当前实机反馈重新预览；不会自动运动。','warning' if different else 'info');self.detail.show()
        except (ValueError,OSError,TypeError) as exc:self.error(exc)

    def selected_route(self):
        if not self.waypoints:return [v.value() for v in self.xyz]
        targets=[xyz[:] for xyz,on in zip(self.waypoints,self.waypoint_enabled) if on]
        if not targets:raise ValueError('没有勾选目标，请至少勾选一个要执行的位置')
        return targets

    def open_coordinate_target(self):
        self.motion_mode.setCurrentIndex(2);return self

    def copy_position(self):
        frame=self.workspace.backend().snapshot()
        if not frame:self.error('请先连接只读反馈');return
        for value,position in zip(self.xyz,frame['pose'][:3]):
            value.blockSignals(True);value.setValue(position);value.blockSignals(False)
        self.point_seeded=True;self.invalidate_plan()

    def generate_target_preview(self):
        try:
            if self.controller.snapshot()['phase'] in ('queued','moving','stopping','verifying_stop'):raise ValueError('请先停止当前运动并完成反馈核对')
            backend=self.workspace.backend();origin_mode=self.preview_source.currentIndex()==1
            if origin_mode:
                frame,target=self.origin_target();distance=math.dist(frame['pose'][:3],target)
                self.path_source_summary.setText('来源：已保存原点\n实测起点：'+str([round(v,3) for v in frame['pose'][:3]])+'\n返回目标：'+str([round(v,3) for v in target])+f' · 距离 {distance:.3f} mm')
                self.preview_view.clear();self.clear_error()
                if distance<.01:
                    self.target.setText('当前位置已在原点附近（小于0.01 mm），无需移动。')
                    self.pin_notice(False);self.detail.show_message('当前反馈位置与保存原点距离小于0.01 mm，无需移动。','info',hint='上方列出了本次比较的起点与原点，可核对数据来源。');self.detail.show();return
                self.preview_view.generate(frame,target,backend.generation,speed=self.speed.value(),purpose='origin',reference=self.origin)
            else:
                self.preview_view.clear();target=[v.value() for v in self.xyz] if self.preview_source.currentIndex()==2 else self.selected_route();frame=backend.snapshot()
                self.path_source_summary.setText('来源：勾选目标列表' if self.waypoints and self.preview_source.currentIndex()==0 else '来源：输入XYZ；当前实机反馈作为起点')
                self.preview_view.generate(frame,target,backend.generation,speed=self.speed.value())
            self.clear_error()
        except (ValueError,OSError,RuntimeError,TypeError,KeyError) as exc:self.preview_view.clear();self.error(exc)

    def execute_target(self):
        try:
            backend=self.workspace.backend()
            if self.preview_view.plan and self.preview_view.plan.get('purpose')=='origin':
                from .manual_origin import load_origin
                saved=load_origin(self.origin_path)
                if saved!=self.preview_view.plan.get('reference'):raise ValueError('保存原点已变化，请重新预览回原点路径')
            target=validate_preview(self.preview_view.plan,backend.snapshot(),backend.generation,load_wall(self.preview_view.wall_path))
            plan=(self.controller.preview_route(self.preview_view.plan['targets'],self.speed.value()) if self.preview_view.plan.get('targets') else self.controller.preview_target(target,self.speed.value()))
            self.controller.execute(plan['id']);self.submitted_target=list(self.preview_view.plan['target']);self.clear_error()
            from .ui_events import journal
            journal().record('已提交预览目标请求；不代表已经到达','info','实机控制',details=dict(plan_id=plan['id'],purpose=self.preview_view.plan.get('purpose','targets'),target=self.preview_view.plan['target'],configuration=self.preview_view.plan['start'],wall_fingerprint=self.preview_view.plan['wall_fingerprint']))
            self.preview_view.clear('目标已提交；显示实时姿态。停止按钮和 Esc 可中断。')
        except (ValueError,OSError,RuntimeError) as exc:self.error(exc)
        self.refresh()

    def confirmation_changed(self):
        state=self.controller.snapshot()
        if state['unlocked'] or state['resumable']:
            self.controller.request_stop('现场确认或工具重量发生变化')
        self.plan_id=None

    def error(self,exc):
        self.pin_notice(True);self.detail.show_message(str(exc),'error');self.detail.show()

    def preview_changed(self):
        if self.preview_view.plan is None and self.detail.level=='success' and self.detail.raw_text.startswith('路径预览已生成'):self.clear_error()
        QTimer.singleShot(0,self.refresh)

    def pin_notice(self,critical):
        if critical:
            self.parameter_layout.removeWidget(self.detail);self.root_layout.insertWidget(1,self.detail)
        else:
            self.root_layout.removeWidget(self.detail);self.parameter_layout.insertWidget(0,self.detail)

    def preview_feedback(self,text,error):
        if error:self.error(text)
        else:self.pin_notice(False);self.detail.show_message(text,'success',hint='播放并核对完整路径；确认后点击“确认预览并执行”。');self.detail.show()

    def fault_dismissed(self,*_):
        if self._fault_box:self._fault_box.deleteLater()
        self._fault_box=None

    def show_control_fault(self,state):
        key=(state['phase'],state['safety']['stop_state'])
        if key[0]!='fault' and key[1]!='unconfirmed':self._fault_key=None;return
        if key==self._fault_key:return
        self._fault_key=key
        self.error(state['reason'])
        if self._fault_box is not None:return
        box=QMessageBox(self);self._fault_box=box
        box.setWindowTitle('实机控制异常');box.setIcon(QMessageBox.Critical)
        box.setText('无法确认机械臂已停止，请使用实体急停')
        box.setInformativeText(state['reason']+'\n关闭提示不会恢复运动。请检查控制器和连接状态。')
        box.setStandardButtons(QMessageBox.Ok);box.finished.connect(self.fault_dismissed);box.open()

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
        self.preview_view.clear('连接已断开，请重新预览。')
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
        self.controller.request_stop('人工停止',recoverable=True)
        self.preview_view.clear('已请求停止；执行新坐标前请重新预览。')
        self.plan_id=None;self.refresh()

    def end_session(self):
        self.controller.request_stop('结束本轮并锁定')
        self.preview_view.clear('本轮已结束，请重新预览。')
        self.clear_checks();self.plan_id=None;self.refresh()

    def reset_safety(self):
        try:
            self.preview_view.clear('停止前目标已取消，请重新预览。')
            state=self.controller.snapshot()
            if state['safety']['can_resume']:
                self.controller.resume_control()
            else:
                self.controller.reset_safety();self.clear_checks()
            self.plan_id=None;self.target.setText('请选择新的目标\n不会继续执行停止前的移动。');self.clear_error()
        except (ValueError,OSError) as exc:self.error(exc)
        self.refresh()

    def invalidate_plan(self):
        self.plan_id=None
        if hasattr(self,'preview_view'):self.preview_view.clear()
        self.target.setText('保持当前工具姿态；输入 XYZ 后生成预览。' if self.motion_mode.currentIndex()==2 else '参数已变化，请重新选择方向。')
        if hasattr(self,'timer'):self.refresh()

    def mode_changed(self):
        jogging=self.motion_mode.currentIndex()==0
        point=self.motion_mode.currentIndex()==2
        if self.previous_mode is not None:
            try:self.mode_parameters[self.previous_mode]=(self.step.value(),self.speed.value())
            except ValueError:pass
        mode=self.motion_mode.currentIndex();distance,speed=self.mode_parameters[mode];self.previous_mode=mode
        self.step_label.setText('上限（mm）' if jogging else '距离（mm）')
        self.step.configure([.01,.05,.1,.5,1,2,5,10,20,50,100,200,500,1000],.01,2000,distance)
        self.speed_label.setText('倍率（%）' if jogging else '速度（mm/s）')
        self.speed.configure([1,2,5,10,20,30,50,75,100] if jogging else [1,2,5,10,20,50,100,200,500],1,100 if jogging else float('inf'),speed,integer=True)
        self.execute_button.setVisible(not jogging)
        self.execute_button.setText('确认预览并执行' if point else '按住执行 · 松开停止')
        self.direction_panel.setVisible(not point);self.point_panel.setVisible(point);self.preview_source_panel.setVisible(point);self.path_source_summary.setVisible(point);self.build_target_button.setVisible(point)
        self.step.setVisible(not point and not jogging);self.step_label.setVisible(not point and not jogging)
        if point and not self.point_seeded:self.copy_position()
        self.preview_view.clear('输入 XYZ 后生成预览；只播放模型，不发送运动。')
        self.motion_hint.setText('按住方向持续移动，松开即请求停止；可反复点动。' if jogging else '选方向核对目标，再按住执行；松手后可继续下一次。')
        self.plan_id=None;self.target.setText('已取消10 cm行程限制；按住移动，松开停止。\n控制器点动速度 × 所选倍率；单次最长30秒。' if jogging else '距离0.01–2000 mm；不设额外低速上限。\n可输入速度，实际允许值由控制器校验。')
        if point:
            self.motion_hint.setText('选择单个坐标、多点路径或返回保存位置，再设置目标。保持工具姿态，先预览再执行；不自动绕过未知障碍。')
            self.target.setText('输入目标坐标 → 生成预览 → 确认预览并执行')
        if hasattr(self,'timer'):self.refresh()

    def direction_press(self,axis,sign):
        if self.motion_mode.currentIndex()!=0:return
        if self.held_direction is not None:return
        self.held_direction=(axis,sign)
        try:
            ratio=self.speed.value()
            self.controller.start_jog(axis,sign,ratio,None);self.clear_error()
            self.target.setText(f"{axis}{'+' if sign>0 else '−'} 连续点动 · {ratio}% · 无10 cm行程限制\n松开停止；不缓存下一次按键。")
        except (ValueError,OSError,RuntimeError) as exc:self.held_direction=None;self.error(exc)

    def direction_release(self,axis,sign):
        if self.held_direction==(axis,sign):
            self.held_direction=None;self.release()

    def preview(self,axis,sign):
        if self.motion_mode.currentIndex()!=1:return
        try:
            step=self.step.value()*sign;speed=self.speed.value()
            plan=self.controller.preview(axis,step,speed);self.plan_id=plan['id']
            xyz=' / '.join(f'{v:.3f}' for v in plan['target'][:3])
            self.target.setText(f"{axis} {step:+g} mm · {speed} mm/s\n目标 XYZ：{xyz} mm\n保持姿态 · 用户0 / 工具{plan['tool']} · 10秒内有效")
            self.clear_error()
        except (ValueError,OSError) as exc:self.plan_id=None;self.error(exc)
        self.refresh()

    def execute(self):
        if self.motion_mode.currentIndex()==2:return self.execute_target()
        try:self.controller.execute(self.plan_id);self.clear_error()
        except (ValueError,OSError,RuntimeError) as exc:self.plan_id=None;self.error(exc)

    def release(self):
        if self.motion_mode.currentIndex()==2:return
        if self.controller.snapshot()['phase'] in ('queued','moving'):
            self.controller.request_stop('松开移动按钮',recoverable=True,auto_rearm=True)
        self.plan_id=None;self.refresh()

    def refresh(self):
        if not isValid(self) or not isValid(self.pose):return
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
            self.pose.setText(f'X {p[0]:.3f}   Y {p[1]:.3f}   Z {p[2]:.3f} mm\nRx {p[3]:.2f}°   Ry {p[4]:.2f}°   Rz {p[5]:.2f}°')
            self.io_status.setText(f"用户 {frame['user_index']} / 工具 {frame['tool_index']} · 测头 "+('触发' if frame['digital_inputs']&1 else '松开')+' · '+('有报警' if frame['error'] else '无报警'))
        else:self.pose.setText('反馈不可用');self.io_status.setText('等待只读反馈连接')
        self.preview_view.update_live(frame)
        point=self.motion_mode.currentIndex()==2
        candidate=False
        if self.preview_view.plan:
            try:
                validate_preview(self.preview_view.plan,frame,self.workspace.backend().generation);candidate=True
            except (ValueError,TypeError,KeyError) as exc:self.preview_view.clear(str(exc))
        age=safety['feedback_age_ms'];freshness='暂无反馈' if age is None else f'{age:.0f} ms'
        jogging=self.motion_mode.currentIndex()==0
        self.safety_status.setText('反馈 '+freshness+' · '+safety['feedback_reason']+(' · 点动倍率1%–100%' if jogging else ' · 目标速度受控制器设置和全局倍率影响'))
        if safety.get('wall_reason'):self.safety_status.setText(self.safety_status.text()+' · '+safety['wall_reason'])
        if state['phase']=='moving' and state['motion_kind']=='jog':
            self.safety_status.setText('点动中 · 反馈 '+freshness+' · 松开方向按钮即请求停止')
        self.session_budget.setText(f"本次剩余 {safety['remaining_seconds']:.0f} 秒，可多次点动" if state['unlocked'] or state['resumable'] else '启用一次可反复点动，10分钟到期；异常会锁定。')
        text=state['reason']
        if state['phase']=='latched':
            if safety['can_resume']:text='已停止 · 点击“继续控制”，再选择新的目标'
            elif safety['can_reset']:text='本轮已锁定 · 点击“解除锁定”，再启用新一轮'
        if safety['stop_state']=='unconfirmed':text='无法确认停止 · 请使用实体急停，并检查连接及控制器状态'
        color='#b42318' if safety['stop_state']=='unconfirmed' else '#214f7d'
        action_hint=('请使用实体急停并检查连接，关闭提示不会恢复运动。' if safety['stop_state']=='unconfirmed' else
            '确认设备反馈已连接，再点击本页右上角“连接控制”。' if not state['connected'] else
            '核对现场与工具总重量，勾选确认，再点击“启用本轮控制”。' if state['phase']=='locked' else
            '请先松开移动按钮，等待后续反馈核对停止状态。' if state['phase'] in ('stopping','verifying_stop') else
            '先播放并核对完整路径，再点击“确认预览并执行”。' if point and candidate and state['phase']=='ready' else
            '输入坐标或勾选目标，再点击“规划并预览路径”。' if point and state['phase']=='ready' else '')
        if state['phase']=='latched' and state['reason'] and state['reason'] not in text:text+=' · 原因：'+state['reason']
        self.status.show_message(text,'error' if safety['stop_state']=='unconfirmed' or state['phase']=='fault' else 'warning' if state['phase'] in ('locked','latched','stopping','verifying_stop') or not state['connected'] else 'info',hint=action_hint)
        self.status.setToolTip(action_hint)
        self.status.setMinimumHeight(32)
        compact_style=self.status.styleSheet().replace('padding:9px 12px','padding:5px 10px').replace('font-size:13px','font-size:12px')
        if compact_style!=self.status.styleSheet():self.status.setStyleSheet(compact_style)
        self.show_control_fault(state)
        self.connect_button.setEnabled(not state['connected'] and not self.waiting_feedback);self.disconnect_button.setEnabled(state['connected'] or self.waiting_feedback)
        self.address.setEnabled(not state['connected'] and not self.waiting_feedback)
        self.stop_button.setEnabled(state['connected']);self.inline_stop.setEnabled(state['connected']);self.end_button.setEnabled(state['connected'])
        self.reset_button.setText('继续控制' if state['resumable'] and safety['can_resume'] else '解除锁定' if safety['can_reset'] else '等待停止反馈' if state['phase'] in ('stopping','verifying_stop') else '继续控制')
        self.reset_button.setEnabled(safety['can_resume'] or safety['can_reset'])
        self.reset_button.setVisible(bool(safety['can_resume'] or safety['can_reset'] or state['phase'] in ('stopping','verifying_stop')))
        self.end_button.setVisible(bool(state['connected'] and (state['unlocked'] or state['resumable'])))
        self.unlock_button.setEnabled(state['can_unlock']);self.unlock_button.setText('本轮已启用' if state['unlocked'] else '启用本轮控制')
        direction_held=False
        for index,button in enumerate(self.directions):
            axis=('X','Y','Z')[index//2];sign=(-1,1)[index%2]
            held=button.isDown() and self.held_direction==(axis,sign) and state['phase'] in ('queued','moving')
            direction_held=direction_held or held
            button.setEnabled((state['phase']=='ready' and safety['feedback_ok']) or held)
        holding=not point and self.execute_button.isDown() and state['phase'] in ('queued','moving')
        self.execute_button.setToolTip('先连接控制、启用本轮控制并生成有效路径预览；参数或选点变化后需重新预览。' if point else '先选择方向并核对目标，再按住执行，松开请求停止。')
        self.execute_button.setEnabled(bool((candidate if point else self.plan_id) and state['phase']=='ready' and safety['feedback_ok']) or holding)
        if (holding or direction_held) and self.isActiveWindow():self.controller.maintain_hold()
        if not state['unlocked'] and not state['resumable'] and state['phase'] in ('stopping','verifying_stop','latched','fault'):
            self.clear_checks();self.plan_id=None
        if not state['unlocked'] and state['phase'] in ('stopping','verifying_stop','latched','fault'):
            self.plan_id=None;self.target.setText('正在停止并核对反馈\n松手后自动恢复点动输入；异常需解除锁定。' if state['resumable'] and self.controller.auto_rearm else '本次目标已取消\n恢复控制后，请重新选择方向。')
        idle=state['phase'] not in ('queued','moving','stopping','verifying_stop')
        self.build_target_button.setEnabled(idle and bool(frame) and not self.preview_view.busy)
        self.return_origin_button.setEnabled(idle and bool(frame) and self.origin is not None and not self.preview_view.busy)
        for control in (self.motion_mode,self.preview_source,self.step,self.speed,self.payload,self.read_position,self.route_list,*self.route_buttons,*self.origin_buttons,*self.xyz,*self.checks):
            control.setEnabled(state['phase'] not in ('queued','moving','stopping','verifying_stop'))

        if point and self.preview_source.currentIndex()==1:
            for widget in (*self.xyz,self.read_position,self.route_list,self.origin_buttons[1]):widget.setEnabled(False)
            self.origin_buttons[1].setToolTip('请先将预览目标来源切回输入坐标，再修改原点')
        self.refresh_overview(state,frame,candidate)

    def refresh_overview(self,state,frame,candidate):
        from .control_overview import workflow_state,target_summary
        mode=self.motion_mode.currentIndex();can_execute=self.execute_button.isEnabled() and state['phase']=='ready'
        label,hint,level=workflow_state(state,mode,candidate,can_execute,self.preview_view.busy)
        self.path_source_summary.hide();self.overview.setToolTip(self.path_source_summary.text())
        color={'info':'#365b84','ready':'#216746','warning':'#986018','error':'#b42318'}[level]
        self.workflow_label.setText(label+' · '+hint);self.workflow_label.setStyleSheet('font-weight:600;color:'+color)
        target=None;source=''
        if state['phase'] in ('queued','moving') and mode==2:
            target=self.submitted_target;source='已提交目标（不代表已到达）'
        elif mode==2:
            if candidate and self.preview_view.plan:
                target=self.preview_view.plan['target'];source='已预览返回位置' if self.preview_view.plan.get('purpose')=='origin' else '已预览目标'
            elif self.preview_source.currentIndex()==1:
                if self.origin:target=self.origin['xyz'];source='保存返回位置 · 尚未有效预览'
            elif self.preview_source.currentIndex()==2:
                target=[v.value() for v in self.xyz];source='输入坐标 · 尚未有效预览'
            else:
                selected=[p for p,enabled in zip(self.waypoints,self.waypoint_enabled) if enabled]
                if selected:target=selected[-1];source=f'已选 {len(selected)} 点 · 末点（尚未有效预览）'
        elif mode==1 and self.plan_id and state.get('plan'):
            target=state['plan']['target'];source='定距目标'
        if target is not None:self.overview_target.setText(source+' · '+target_summary(frame,target).replace('\n',' · '))
        else:self.overview_target.setText('连续点动没有固定终点；松开方向按钮请求停止。' if mode==0 else '尚无有效目标，请先设置。')

    def event(self,event):
        if event.type() in (QEvent.Type.WindowDeactivate,QEvent.Type.Hide) and hasattr(self,'controller'):
            state=self.controller.snapshot()
            if state['unlocked'] or state['resumable']:
                self.controller.request_stop('控制窗口失去焦点或隐藏',recoverable=True)
        return super().event(event)

    def showEvent(self,event):
        super().showEvent(event);self.preview_view.closed=False
        try:
            from .manual_origin import load_origin
            latest=load_origin(self.origin_path)
            if latest!=self.origin:self.origin=latest;self.update_origin_label();self.preview_view.clear('保存原点已更新，请重新预览。')
        except (OSError,ValueError,TypeError) as exc:self.error('原点记录读取失败：'+str(exc))
        self.timer.start();self.refresh()

    def hideEvent(self,event):
        self.waiting_feedback=False;self.timer.stop();self.preview_view.clear('页面已隐藏；请重新生成预览。');super().hideEvent(event)

    def closeEvent(self,event):
        self.preview_view.shutdown();self.timer.stop();self.controller.close();self.clear_checks();self.plan_id=None;super().closeEvent(event)

    def reject(self):self.close()
