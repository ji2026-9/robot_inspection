"""Offline, detection-bound workstation preview. Never sends hardware motion."""
from dataclasses import asdict
from pathlib import Path
import copy,json,threading,time
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from PySide6.QtCore import Qt,QTimer,QObject,Signal
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,
    QWidget,QFrame,QFormLayout,QDoubleSpinBox,QCheckBox,QSlider,QFileDialog,
    QMessageBox,QTableWidget,QTableWidgetItem,QHeaderView,QSplitter,QScrollArea,QComboBox,QLineEdit,QApplication,QGridLayout)
from .offline_planning import SimulationConfig,build_plan,compile_trajectory,robot_frames
from .simulation_scene3d import Scene3D

class PlanSignals(QObject):
    finished=Signal(int,object,object,object)
    connected=Signal(bool,str)

class SimulationDialog(QDialog):
    def __init__(self,parent=None):
        super().__init__(parent);self.setWindowTitle('双机械臂 · 实时位姿与路径预览')
        self.setStyleSheet('''QDialog,QWidget{background:#f7f9fc;color:#263b51;}
            QLabel{background:transparent;} QPushButton{background:#fff;color:#204e79;border:1px solid #c5d4e3;border-radius:5px;padding:7px 12px;}
            QPushButton:hover{background:#eaf3fd;} QPushButton:disabled{color:#9aa8b6;}
            QDoubleSpinBox{background:white;color:#263b51;padding:5px;border:1px solid #ccd7e2;border-radius:4px;}
            QTableWidget{background:white;color:#263b51;gridline-color:#e2e8f0;}
            QHeaderView::section{background:#edf3fa;color:#31516f;padding:5px;border:0;}
            QCheckBox{background:transparent;color:#234b71;}
            QFrame#dataCard,QFrame#taskCard{background:white;border:1px solid #e1e8f0;border-radius:12px;}
            QLabel#sectionTitle{color:#24415f;font-size:13px;font-weight:600;}
            QLabel#muted{color:#7b8da0;font-size:11px;}
            QLabel#metricName{color:#7b8da0;font-size:11px;}
            QLabel#metricValue{color:#183a60;font-size:16px;font-weight:600;}
            QWidget#metricCell{background:transparent;}
            QLabel#stateChip{background:#eef7f2;color:#30815c;border-radius:5px;padding:5px 8px;font-size:11px;}
            QPushButton#holeTile{background:#f7f9fc;color:#7c8da0;border:1px solid #e3e9f0;border-radius:7px;padding:9px;font-weight:600;}
            QPushButton#holeTile:checked{background:#eaf2ff;color:#225eaf;border:1px solid #b9d0f2;}
            QPushButton#holeTile:hover{border-color:#8bb0e3;}
            QPushButton#holeTile:disabled{background:#f5f6f8;color:#bac3cf;border-color:#edf0f4;}
            QScrollArea{border:none;background:transparent;}
            QComboBox,QLineEdit{background:white;border:1px solid #d8e2ed;border-radius:6px;padding:6px 9px;}
            QScrollBar:vertical{width:8px;background:transparent;}
            QScrollBar::handle:vertical{background:#ced9e5;border-radius:4px;min-height:30px;}
            QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0px;}
            ''')
        screen=self.screen().availableGeometry()
        self.resize(min(1380,screen.width()-40),min(820,screen.height()-40));self.setMinimumSize(720,500)
        self.executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='preview-plan')
        self.cancel=threading.Event();self.future=None;self.closed=False;self.input_key=None
        self.connection_pending=False;self.live_enabled=False;self.auto_attempted=False
        self.play_position=0.;self.last_tick=0.
        self.config=SimulationConfig();self.result=None;self.selected=None
        self.plan=None;self.trajectory=[];self.generation=0;self.loading=False;self.loading_selection=False
        root=QVBoxLayout(self);root.setContentsMargins(12,12,12,12)
        title=QLabel('双机械臂工作站');title.setStyleSheet('font-size:20px;font-weight:600;color:#19446b;');root.addWidget(title)
        note=QLabel('只读监视 · 工件尺寸与基座布局为模拟值')
        note.setStyleSheet('color:#7b8da0;font-size:11px;');root.addWidget(note)
        connection=QHBoxLayout()
        self.mode=QComboBox();self.mode.addItems(['离线路径预览','实时机械臂 B（只读）'])
        self.mode.currentIndexChanged.connect(self.change_mode);connection.addWidget(self.mode)
        from .devices_view import current_settings
        self.address=QLineEdit(current_settings()['robot_b'].get('address') or '192.168.5.1')
        self.address.setPlaceholderText('机械臂 IP');self.address.setMaximumWidth(170);connection.addWidget(self.address)
        self.connect_button=QPushButton('连接只读反馈');self.connect_button.clicked.connect(self.connect_feedback);connection.addWidget(self.connect_button)
        self.feedback_state=QLabel('30004 · 等待反馈');self.feedback_state.setWordWrap(True);connection.addWidget(self.feedback_state,1);root.addLayout(connection)
        self.telemetry=QLabel('');self.telemetry.setWordWrap(True);self.telemetry.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.telemetry.hide()  # Retain a plain-text status for accessibility and diagnostics.
        note.setWordWrap(True)
        split=QSplitter(Qt.Orientation.Horizontal);root.addWidget(split,1)
        panel=QWidget();panel.setMinimumWidth(240)
        left=QVBoxLayout(panel);left.setContentsMargins(0,0,8,0);left.setSpacing(12)
        self.live_panel=QWidget();live=QVBoxLayout(self.live_panel);live.setContentsMargins(0,0,0,0);live.setSpacing(12)
        self.live_badge=QLabel('等待反馈');self.live_badge.setObjectName('stateChip');live.addWidget(self.live_badge)
        self.pose_values={};self.joint_values={}
        def data_card(title,fields,values,unit):
            card=QFrame();card.setObjectName('dataCard');layout=QVBoxLayout(card);layout.setContentsMargins(14,14,14,14);layout.setSpacing(12)
            head=QHBoxLayout();label=QLabel(title);label.setObjectName('sectionTitle');head.addWidget(label)
            units=QLabel(unit);units.setObjectName('muted');head.addStretch();head.addWidget(units);layout.addLayout(head)
            grid=QGridLayout();grid.setHorizontalSpacing(12);grid.setVerticalSpacing(14)
            for i,field in enumerate(fields):
                cell=QWidget();cell.setObjectName('metricCell');cl=QVBoxLayout(cell);cl.setContentsMargins(0,0,0,0);cl.setSpacing(3)
                name=QLabel(field);name.setObjectName('metricName');value=QLabel('—');value.setObjectName('metricValue')
                cl.addWidget(name);cl.addWidget(value);values[field]=value;grid.addWidget(cell,i//3,i%3)
            layout.addLayout(grid);live.addWidget(card)
        data_card('末端位姿',('X','Y','Z','Rx','Ry','Rz'),self.pose_values,'mm / °')
        data_card('关节角度',tuple(f'J{i}' for i in range(1,7)),self.joint_values,'°')
        self.coordinate_meta=QLabel('用户坐标 —  ·  工具 —');self.coordinate_meta.setObjectName('muted');live.addWidget(self.coordinate_meta)
        self.feedback_time=QLabel('');self.feedback_time.setObjectName('muted');live.addWidget(self.feedback_time)
        left.addWidget(self.live_panel);self.live_panel.hide()
        self.task_panel=QWidget();task_layout=QVBoxLayout(self.task_panel);task_layout.setContentsMargins(0,0,0,0);task_layout.setSpacing(12)
        left.addWidget(self.task_panel)
        task=QFrame();task.setObjectName('taskCard');tl=QVBoxLayout(task);tl.setContentsMargins(14,14,14,14);tl.setSpacing(12)
        heading=QHBoxLayout();label=QLabel('预览任务');label.setObjectName('sectionTitle');heading.addWidget(label)
        self.selection_count=QLabel('4 / 4');self.selection_count.setObjectName('muted');heading.addStretch();heading.addWidget(self.selection_count);tl.addLayout(heading)
        self.source=QLabel('');self.source.setObjectName('muted');self.source.setWordWrap(True);tl.addWidget(self.source)
        self.selection_panel=QGridLayout();self.selection_panel.setSpacing(8);self.checks={}
        for i in range(1,5):
            hid=f'H{i:02}';box=QPushButton(hid);box.setCheckable(True);box.setObjectName('holeTile')
            box.setToolTip('选择或取消 '+hid);box.toggled.connect(self.selection_changed)
            self.selection_panel.addWidget(box,(i-1)//2,(i-1)%2);self.checks[hid]=box
        tl.addLayout(self.selection_panel);task_layout.addWidget(task)
        left=task_layout
        label=QLabel('假设尺寸与路径参数（mm）');label.setStyleSheet('font-weight:600;color:#234b71;');left.addWidget(label)
        form=QFormLayout();self.spins={}
        fields=[('bore_diameter_mm','孔径',30,130),('bore_pitch_mm','孔间距',50,180),
                ('approach_mm','孔外接近距离',10,150),('insertion_mm','进入深度',5,100),
                ('probe_ball_diameter_mm','测球直径',2,25)]
        for key,text,lo,hi in fields:
            spin=QDoubleSpinBox();spin.setRange(lo,hi);spin.setDecimals(1);spin.setValue(getattr(self.config,key));spin.setSuffix(' mm');spin.valueChanged.connect(self.schedule_rebuild)
            form.addRow(text,spin);self.spins[key]=spin
        left.addLayout(form)
        info=QLabel('工件参考：训练照片中的四缸孔箱体。尺寸尚未实测。\n孔号沿本次照片顺序对应模拟槽位，不代表永久物理身份。');info.setWordWrap(True);left.addWidget(info)
        self.table=QTableWidget(0,4);self.table.setHorizontalHeaderLabels(['孔','B-X','B-Y','B-Z']);self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch);self.table.setMaximumHeight(165);left.addWidget(self.table)
        coords=QLabel('表格为模拟机械臂 B 基座坐标（mm）。\n当前未用深度或真实标定把像素重建为三维。');coords.setWordWrap(True);coords.setStyleSheet('color:#718096;');left.addWidget(coords)
        self.quality=QLabel('');self.quality.setWordWrap(True);left.addWidget(self.quality);panel.layout().addStretch()
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(panel)
        scroll.setMinimumWidth(300);scroll.setMaximumWidth(340);scroll.setFrameShape(QFrame.Shape.NoFrame)
        split.addWidget(scroll);split.setChildrenCollapsible(False)
        right=QWidget();right_layout=QVBoxLayout(right);right_layout.setContentsMargins(0,0,0,0)
        self.scene=Scene3D();self.scene.setToolTip('左键旋转 · 右键平移 · 滚轮缩放\n外观关节链与基座布局为近似显示。');right_layout.addWidget(self.scene,1);split.addWidget(right);split.setSizes([310,1000])
        self.status=QLabel('');self.status.setWordWrap(True);self.status.setStyleSheet('font-size:14px;font-weight:600;color:#1f5476;padding:5px;');root.addWidget(self.status)
        self.progress=QSlider(Qt.Orientation.Horizontal);self.progress.setRange(0,0);self.progress.valueChanged.connect(self.seek);root.addWidget(self.progress)
        self.playback_controls=QWidget();controls=QHBoxLayout(self.playback_controls);controls.setContentsMargins(0,0,0,0);controls.setSpacing(8)
        self.play=QPushButton('开始预览');self.play.clicked.connect(self.toggle)
        self.reset_button=QPushButton('回到起点');self.reset_button.clicked.connect(self.reset)
        self.export=QPushButton('导出模拟任务');self.export.clicked.connect(self.export_plan)
        for button in (self.play,self.reset_button,self.export):controls.addWidget(button)
        controls.addStretch()
        self.speed_label=QLabel('速度');controls.addWidget(self.speed_label)
        self.speed=QDoubleSpinBox();self.speed.setRange(.25,3);self.speed.setValue(1);self.speed.setSingleStep(.25);self.speed.setSuffix(' ×');self.speed.setFixedWidth(100);controls.addWidget(self.speed)
        root.addWidget(self.playback_controls)
        views=QHBoxLayout();views.addStretch()
        view_label=QLabel('视角');view_label.setObjectName('muted');views.addWidget(view_label)
        view=QPushButton('恢复斜视');view.clicked.connect(self.scene.reset_view);views.addWidget(view)
        top=QPushButton('俯视');top.clicked.connect(self.scene.view_top);views.addWidget(top);root.addLayout(views)
        self.timer=QTimer(self);self.timer.setInterval(33);self.timer.timeout.connect(self.tick)
        self.debounce=QTimer(self);self.debounce.setSingleShot(True);self.debounce.setInterval(250);self.debounce.timeout.connect(self.rebuild)
        self.signals=PlanSignals(self);self.signals.finished.connect(self.plan_finished)
        self.signals.connected.connect(self.feedback_connected)
        self.feedback_timer=QTimer(self);self.feedback_timer.setInterval(100);self.feedback_timer.timeout.connect(self.refresh_feedback)
        self.asset_note=QLabel('外观模型用于姿态展示，运动学与碰撞未验证；真实 TCP 按反馈坐标显示。');self.asset_note.setWordWrap(True)
        self.asset_note.setStyleSheet('color:#6f7f90;font-size:11px;');root.addWidget(self.asset_note)

    def set_detection(self,result,selected_ids):
        key=json.dumps({'result':{'image':(result or {}).get('image_path'),'holes':(result or {}).get('fitted_holes',[])},
                        'selected':selected_ids,'example':result is None},sort_keys=True,default=str)
        if key==self.input_key and self.plan is not None:return
        self.input_key=key
        self.timer.stop();self.result=copy.deepcopy(result) if result is not None else None
        self.selected=list(selected_ids or []) if result is not None else [f'H{i:02}' for i in range(1,5)]
        available={h['id'] for h in (result or {}).get('fitted_holes',[]) if h.get('reliable_center')} if result is not None else set(self.selected)
        self.loading_selection=True
        for hid,box in self.checks.items():box.setChecked(hid in self.selected);box.setEnabled(hid in available)
        self.loading_selection=False
        name=Path((result or {}).get('image_path') or '未命名').name
        shown=name if len(name)<=32 else name[:28]+'…'+Path(name).suffix
        self.source.setText('示例工件 · 未绑定检测照片' if result is None else '检测照片 · '+shown)
        self.update_selection_count()
        self.source.setToolTip(name if result is not None else '')
        self.rebuild()

    def update_selection_count(self):
        selected=sum(box.isChecked() for box in self.checks.values())
        available=sum(box.isEnabled() for box in self.checks.values())
        self.selection_count.setText(f'已选 {selected} / {available}')

    def selection_changed(self,*_):
        if self.loading_selection:return
        self.selected=[hid for hid,b in self.checks.items() if b.isChecked()];self.update_selection_count();self.input_key=None;self.schedule_rebuild()

    def schedule_rebuild(self,*_):
        self.invalidate_path();self.debounce.start()

    def invalidate_path(self):
        self.timer.stop();self.cancel.set();self.generation+=1
        if self.future is not None:self.future.cancel()
        self.trajectory=[];self.loading=False
        self.scene.trajectory=[];self.scene.frame_index=0;self.scene.update()
        self.progress.blockSignals(True);self.progress.setRange(0,0);self.progress.setValue(0);self.progress.blockSignals(False)
        self.play.setText('开始预览');self.play.setEnabled(False);self.export.setEnabled(False);self.progress.setEnabled(False)

    def rebuild(self):
        self.invalidate_path();generation=self.generation
        try:
            cfg=asdict(self.config)
            for k,s in self.spins.items():cfg[k]=s.value()
            self.config=SimulationConfig(**cfg).validate();self.plan=build_plan(self.result,self.selected,self.config)
        except ValueError as exc:
            self.plan=None;self.scene.set_plan(None,[]);self.table.setRowCount(0);self.quality.setText('参数无效，旧路径已清除。');self.status.setText(str(exc));return
        self.loading=True;self.play.setEnabled(False);self.export.setEnabled(False);self.progress.setEnabled(False)
        self.scene.set_plan(self.plan,[]);self.table.setRowCount(4)
        for i,h in enumerate(self.plan['holes']):
            for j,v in enumerate([h['id']]+[f'{x:.1f}' for x in h['center_b_mm']]):self.table.setItem(i,j,QTableWidgetItem(v))
        if not self.plan['selected_ids']:
            self.loading=False;self.trajectory=[];self.status.setText('请选择要预览的可靠孔；四个孔未完整拟合时不建立名义槽位对应。');self.quality.setText('没有生成路径。');return
        self.status.setText('正在生成选中孔的三维进退路径…')
        plan=copy.deepcopy(self.plan);cancel=threading.Event();self.cancel=cancel;signals=self.signals
        def work():
            try:frames,errors=compile_trajectory(plan,14,cancel.is_set);error=None
            except Exception as exc:frames=[];errors=[];error=str(exc)
            if not cancel.is_set():
                try:signals.finished.emit(generation,frames,errors,error)
                except RuntimeError:pass
        self.future=self.executor.submit(work)

    def plan_finished(self,generation,frames,errors,error):
        if generation!=self.generation:return
        self.loading=False
        if error or not frames or max(errors,default=0)>1:
            self.status.setText('显示模型无法可靠匹配该路径，请调整尺寸或接近参数。'+(error or ''))
            self.trajectory=[];self.quality.setText('没有开放播放或导出。');return
        self.trajectory=frames;self.scene.set_plan(self.plan,frames)
        self.progress.setEnabled(not self.live_enabled);self.progress.setRange(0,len(frames)-1);self.progress.setValue(0)
        self.play.setEnabled(not self.live_enabled);self.export.setEnabled(not self.live_enabled)
        positional=[]
        for f in frames:
            t=robot_frames(f['joints'],(480,100,0))['J6'];actual=t[:3,3]+t[:3,2]*self.config.tool_length_mm
            positional.append(float(np.linalg.norm(actual-f['tip'])))
        self.plan['display_model_tip_residual_max_mm']=max(positional)
        self.quality.setText(f'选中 {len(self.plan["selected_ids"])} 个孔 · {len(frames)} 帧\n显示模型末端拟合残差 {max(positional):.3f} mm\n该残差不是实机定位或检测精度。')
        self.seek(0)

    def seek(self,index):
        if not self.trajectory or self.live_enabled:return
        index=max(0,min(int(index),len(self.trajectory)-1))
        self.scene.frame_index=index;f=self.trajectory[index];tip=f['tip']
        self.status.setText(f'{f["hole_id"] or "待机"} · {f["stage"]}    模拟测球位置：X {tip[0]:.1f} / Y {tip[1]:.1f} / Z {tip[2]:.1f} mm')
        self.scene.update()

    def toggle(self):
        if self.live_enabled:return
        if self.timer.isActive():self.timer.stop();self.play.setText('继续预览')
        elif self.trajectory:
            if self.progress.value()==self.progress.maximum():self.progress.setValue(0)
            self.play_position=float(self.progress.value());self.last_tick=time.monotonic();self.timer.start();self.play.setText('暂停')

    def tick(self):
        now=time.monotonic();self.play_position+=(now-self.last_tick)*self.speed.value()/.06;self.last_tick=now
        n=min(self.progress.maximum(),int(self.play_position));self.progress.setValue(n)
        if n==self.progress.maximum():self.timer.stop();self.play.setText('重新预览')

    def reset(self):
        self.timer.stop();self.progress.setValue(0);self.play_position=0.;self.seek(0);self.play.setText('开始预览')

    def export_plan(self):
        if not self.plan or self.loading or not self.trajectory:return
        path,_=QFileDialog.getSaveFileName(self,'导出模拟任务（不可执行于硬件）','offline_simulation_task.json','JSON (*.json)')
        if not path:return
        data=copy.deepcopy(self.plan);data['display_trajectory']=[{'joints_deg':np.rad2deg(f['joints']).tolist(),'tip_world_mm':f['tip'].tolist(),'hole_id':f['hole_id'],'stage':f['stage']} for f in self.trajectory]
        try:Path(path).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
        except OSError as exc:QMessageBox.warning(self,'导出失败',str(exc));return
        self.status.setText('已导出模拟任务：'+Path(path).name)

    def change_mode(self,index):
        self.live_enabled=index==1;self.timer.stop();self.play.setText('开始预览')
        self.live_panel.setVisible(self.live_enabled);self.task_panel.setVisible(not self.live_enabled)
        for widget in (self.progress,self.playback_controls):widget.setVisible(not self.live_enabled)
        self.play.setEnabled(bool(self.trajectory) and not self.loading and not self.live_enabled)
        self.progress.setEnabled(bool(self.trajectory) and not self.loading and not self.live_enabled)
        self.export.setEnabled(bool(self.trajectory) and not self.loading and not self.live_enabled)
        if self.live_enabled:self.refresh_feedback()
        else:
            self.scene.set_live_frame(None,False);self.telemetry.setText('')
            if self.trajectory:self.seek(self.progress.value())

    def connect_feedback(self):
        if self.connection_pending:return
        from .devices_view import _registered_backends,remember_settings,current_settings,_validate_address
        address=self.address.text().strip()
        if not address or not _validate_address(address):
            self.feedback_state.setText('请填写有效的机械臂 IP 地址');return
        backend=_registered_backends['robot_b']
        if backend.is_connected():
            self.address.setText(backend.address);self.mode.setCurrentIndex(1);self.refresh_feedback();return
        settings=current_settings();settings['robot_b'].update(address=address,port=30004,transport='网口');remember_settings(settings)
        self.connection_pending=True;self.connect_button.setEnabled(False);self.feedback_state.setText('正在连接只读反馈…')
        signals=self.signals
        def work():
            try:ok=bool(backend.connect(settings['robot_b']));error=''
            except Exception as exc:ok=False;error=str(exc)
            try:signals.connected.emit(ok,error)
            except RuntimeError:backend.disconnect()
        threading.Thread(target=work,daemon=True,name='robot-feedback-connect').start()

    def feedback_connected(self,ok,error):
        self.connection_pending=False;self.connect_button.setEnabled(True)
        if ok:self.mode.setCurrentIndex(1)
        else:self.feedback_state.setText('反馈连接失败：'+error)
        self.refresh_feedback()

    def refresh_feedback(self):
        from .devices_view import _registered_backends
        backend=_registered_backends['robot_b'];frame=backend.snapshot() if backend.is_connected() else None
        if frame:
            self.feedback_state.setText(f'只读反馈已连接 · {backend.address}:30004')
            self.connect_button.setText('反馈已连接');self.connect_button.setEnabled(False)
        elif not self.connection_pending:
            self.connect_button.setText('重新连接反馈');self.connect_button.setEnabled(True)
            if self.live_enabled:self.feedback_state.setText('反馈已中断 · '+(backend.error or '未收到新数据'))
        if not self.live_enabled:return
        self.scene.set_live_frame(frame,True)
        if not frame:
            self.telemetry.setText('实时位姿不可用；旧反馈已失效。')
            self.live_badge.setText('反馈已中断');self.live_badge.setStyleSheet('color:#ad7041;background:#fff4e8;')
            for label in (*self.pose_values.values(),*self.joint_values.values()):label.setText('—')
            self.coordinate_meta.setText('用户坐标 —  ·  工具 —');self.feedback_time.setText('等待重新连接');return
        for key,value in zip(self.pose_values,frame['pose']):self.pose_values[key].setText(f'{value:.2f}')
        for key,value in zip(self.joint_values,frame['joints']):self.joint_values[key].setText(f'{value:.2f}')
        state='运行中' if frame['running'] else ('已使能 · 静止' if frame['enabled'] else '未使能 · 静止')
        self.live_badge.setText('● '+('有报警 · '+state if frame['error'] else state+' · 无报警'))
        self.live_badge.setStyleSheet('color:#b64d48;background:#fff0ee;' if frame['error'] else '')
        self.coordinate_meta.setText(f"用户坐标 {frame['user_index']}  ·  工具 {frame['tool_index']}")
        self.feedback_time.setText('更新于 '+time.strftime('%H:%M:%S',time.localtime(frame['received_at'])))
        self.telemetry.setText('实时反馈正常')
        self.status.setText('实时监视 · 仅接收状态反馈' if frame['user_index']==0 else
            '实时关节显示；当前用户坐标非 0，TCP 仅显示数值，避免误放到模拟世界。')

    def showEvent(self,event):
        super().showEvent(event);self.closed=False;self.feedback_timer.start()
        from .devices_view import _registered_backends
        if _registered_backends['robot_b'].is_connected():self.mode.setCurrentIndex(1);self.refresh_feedback()
        elif not self.auto_attempted:
            self.auto_attempted=True;QTimer.singleShot(0,self.connect_feedback)

    def closeEvent(self,event):
        self.closed=True;self.timer.stop();self.debounce.stop();self.feedback_timer.stop()
        # Dialog is reused by the main window; keep a completed path cached.
        if self.loading:
            self.cancel.set();self.generation+=1;self.loading=False;self.input_key=None
        super().closeEvent(event)

    def shutdown(self):
        self.cancel.set();self.generation+=1;self.feedback_timer.stop();self.timer.stop();self.debounce.stop()
        self.executor.shutdown(wait=False,cancel_futures=True)
