"""Guided, receive-only experiment sessions; operator handles real contacts."""
import copy,time
from pathlib import Path
from datetime import datetime
from .ui_feedback import FeedbackLabel
from PySide6.QtCore import QTimer,Qt
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,
    QCheckBox,QComboBox,QTableWidget,QTableWidgetItem,QAbstractItemView,QHeaderView,
    QFileDialog,QScrollArea,QWidget,QSplitter,QPlainTextEdit)
from .sphere_analysis import ContactSession,configuration,orientation_difference,FLAGS,load_reference
from .probe_trigger import di1_state
from .probe_workspace import capture_position,atomic_json


class SphereAnalysisDialog(QDialog):
    def __init__(self,workspace):
        super().__init__(workspace);self.workspace=workspace;self.session=None;self.anchor=None;self.last_count=-1
        self.setWindowTitle('白球采集与分析 · 只读实验');self.resize(1080,730);self.setMinimumSize(800,540)
        self.directory=workspace.storage_path.parent/'contact_sessions'
        self.reference_error=''
        try:self.reference=load_reference(workspace.storage_path.parent/'reference_sphere.json')
        except (OSError,ValueError) as exc:self.reference=None;self.reference_error=str(exc)
        root=QVBoxLayout(self);heading=QLabel('白球采集与分析');heading.setStyleSheet('font-size:20px;font-weight:600;color:#19446b');root.addWidget(heading)
        self.reference_label=QLabel();self.reference_label.setWordWrap(True);root.addWidget(self.reference_label);self.show_reference(self.reference)
        self.live=QLabel('读取反馈中…');self.live.setWordWrap(True);root.addWidget(self.live)
        split=QSplitter(Qt.Horizontal);root.addWidget(split,1)
        scroll=QScrollArea();scroll.setWidgetResizable(True);content=QWidget();left=QVBoxLayout(content);scroll.setWidget(content);split.addWidget(scroll)
        self.mode=QComboBox();self.mode.addItem('球面分布采点（固定朝向）','sphere');self.mode.addItem('同一点重复采点（固定朝向）','repeat');left.addWidget(self.mode)
        self.instructions=QLabel();self.instructions.setWordWrap(True);left.addWidget(self.instructions);self.mode.currentIndexChanged.connect(self.mode_changed)
        self.ready=QCheckBox('本组为测球接触白球；\n白球已固定，期间不移动')
        left.addWidget(self.ready)
        self.start=QPushButton('新建并开始本组');self.start.clicked.connect(self.start_session);left.addWidget(self.start)
        self.stop=QPushButton('结束本组采集');self.stop.clicked.connect(lambda:self.stop_session());left.addWidget(self.stop)
        self.analyze_button=QPushButton('分析本组数据');self.analyze_button.clicked.connect(self.analyze);left.addWidget(self.analyze_button)
        self.load=QPushButton('打开已有采集组');self.load.clicked.connect(self.open_session);left.addWidget(self.load)
        self.export=QPushButton('导出本组及分析结果');self.export.clicked.connect(self.export_session);left.addWidget(self.export)
        self.status=FeedbackLabel('未开始采集。原有触发记录不会自动加入新组。');root.insertWidget(1,self.status)
        note=QLabel('不写工具参数、不控制机械臂。\n按所录参考球尺寸估算测针有效半径，结果未标定验证。\n球面拟合残差与重复性均不等于测量精度。');note.setWordWrap(True);left.addWidget(note);left.addStretch()
        right=QWidget();right_layout=QVBoxLayout(right);split.addWidget(right);split.setSizes([340,700])
        self.table=QTableWidget(0,3);self.table.setHorizontalHeaderLabels(['接收时间','X / Y / Z mm','状态']);self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch);self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows);self.table.setSelectionMode(QAbstractItemView.SingleSelection);right_layout.addWidget(self.table,1)
        self.table.itemSelectionChanged.connect(self.update_controls)
        self.exclude=QPushButton('排除 / 恢复选中点（保留原始记录）');self.exclude.clicked.connect(self.exclude_selected);right_layout.addWidget(self.exclude)
        self.result=QPlainTextEdit();self.result.setReadOnly(True);self.result.setPlaceholderText('完成采点并结束本组后，分析结果显示在这里。');right_layout.addWidget(self.result,1)
        self.timer=QTimer(self);self.timer.setInterval(200);self.timer.timeout.connect(self.poll)
        self.ready.toggled.connect(self.update_controls);self.mode_changed();self.update_controls()

    def show_reference(self,reference):
        if self.reference_error:self.reference_label.setText('参考球参数读取失败：'+self.reference_error);return
        if reference is None:self.reference_label.setText('本历史组未附参考球尺寸，只分析组合球面；不套用当前参考值。');return
        self.reference_label.setText(f"参考白球直径：{reference['diameter_mm']:.4f} mm · 半径：{reference['diameter_mm']/2:.5f} mm\n来源：{reference['source_note']}")

    def mode_changed(self):
        self.instructions.setText('至少 9 个分布位置：覆盖不同周向和高度，测头保持同一朝向。手拨测针或只测一圈不能代替球面分布采点。' if self.mode.currentData()=='sphere' else
            '至少 5 次：同一球面位置、同一接近方向、同一朝向；每次退开并重新接触。手拨测针只验证信号，不是接触重复性。')

    def update_controls(self,*_):
        active=self.session is not None and self.session.data['status']=='collecting'
        self.start.setEnabled(not active and self.ready.isChecked());self.stop.setEnabled(active)
        self.mode.setEnabled(not active);self.ready.setEnabled(not active);self.load.setEnabled(not active)
        self.analyze_button.setEnabled(self.session is not None and not active)
        self.exclude.setEnabled(self.session is not None and not active and self.table.currentRow()>=0);self.export.setEnabled(self.session is not None and not active)
        self.exclude.setToolTip('先结束本组，并选择表格中的一个点')

    def start_session(self):
        try:
            if not self.ready.isChecked():raise ValueError('请先确认白球固定及真实接触采点条件')
            if self.reference_error:raise ValueError('参考球参数不可用：'+self.reference_error)
            self.workspace.refresh_feedback();frame=self.workspace.backend().snapshot()
            if di1_state(frame) is not False:raise ValueError('需要有效反馈，且测针已松开（DI_1=0）')
            if self.workspace.trigger_save_error or self.workspace.trigger_missed:raise ValueError('原始采点保存异常或队列溢出，先排查后再新建组')
            if frame['user_index']!=0:raise ValueError('只支持用户坐标 0')
            anchor=capture_position('采集起点',frame);anchor['controller_address']=self.workspace.backend().address
            mode=self.mode.currentData();name=('球面分布_' if mode=='sphere' else '同点重复_')+datetime.now().strftime('%Y%m%d_%H%M%S')
            self.session=ContactSession.create(self.directory,mode,name,[e['id'] for e in self.workspace.trigger_journal.records],anchor,self.reference)
            self.show_reference(self.reference)
            self.anchor=anchor;self.last_count=-1;self.result.clear();self.status.setText('本组采集中：只纳入开始之后的真实触发。');self.render_table();self.update_controls()
        except (ValueError,OSError,KeyError) as exc:self.status.setText('未开始：'+str(exc))

    def stop_session(self,reason='用户结束本组采集'):
        try:
            if self.session and self.session.data['status']=='collecting':
                # The user can click End before the 200 ms poll sees the last
                # contact. Drain already received events before closing the group.
                self.workspace.refresh_feedback()
                for event in self.workspace.trigger_journal.records:
                    self.session.append(event)
                if self.session.data['status']=='collecting':self.session.stop(reason)
                self.render_table()
                self.status.show_message(self.session.data['stop_reason']+'；已保存本组数据。','success' if reason=='用户结束本组采集' else 'warning')
            self.update_controls()
        except (OSError,ValueError,KeyError) as exc:self.status.setText('保存失败，不能确认结束：'+str(exc))

    def poll(self):
        frame=self.workspace.backend().snapshot();state=di1_state(frame)
        self.live.setText('反馈不可用' if state is None else f"DI_1：{int(state)} · 用户 {frame['user_index']} / 工具 {frame['tool_index']} · 仅接收反馈")
        if not self.session or self.session.data['status']!='collecting':return
        try:
            self.workspace.refresh_feedback()
            if state is None:self.stop_session('反馈中断，本组已停止；重连后新建组');return
            current=capture_position('当前配置',frame);current['controller_address']=self.workspace.backend().address
            if self.anchor and configuration(current)!=configuration(self.anchor):self.stop_session('工具 / 坐标配置变化，本组已停止');return
            if self.anchor and orientation_difference(self.anchor,current)>.2:self.stop_session('测头朝向变化超过 0.2°，本组已停止');return
            if self.workspace.trigger_save_error or self.workspace.trigger_missed:self.stop_session('原始采点保存异常或队列溢出，本组已停止');return
            for event in self.workspace.trigger_journal.records:
                if self.anchor and event['feedback_received_at']>=self.session.data['started_at']:
                    if configuration(event)!=configuration(self.anchor) or orientation_difference(self.anchor,event)>.2:
                        self.stop_session('触发帧的工具配置或朝向变化，本组已停止');return
                self.session.append(event)
            if len(self.session.data['records'])!=self.last_count:self.render_table()
            self.status.set_status(f"{self.session.data['name']}\n本组 {len(self.session.data['records'])} 点 · "+('采集中' if self.session.data['status']=='collecting' else self.session.data['stop_reason']))
            self.update_controls()
        except (ValueError,OSError,KeyError) as exc:self.status.setText('采点保存 / 检查失败，请结束并排查：'+str(exc))

    def render_table(self):
        rows=self.session.data['records'] if self.session else [];excluded=set(self.session.data['excluded_ids']) if self.session else set()
        self.table.setRowCount(len(rows));self.last_count=len(rows)
        for i,row in enumerate(rows):
            vals=[datetime.fromtimestamp(row['feedback_received_at']).strftime('%H:%M:%S.%f')[:-3],
                ' / '.join(f'{x:.3f}' for x in row['tcp_pose'][:3]),'已排除' if row['id'] in excluded else '纳入']
            for j,value in enumerate(vals):self.table.setItem(i,j,QTableWidgetItem(value))

    def exclude_selected(self):
        try:
            row=self.table.currentRow()
            if self.session and 0<=row<len(self.session.data['records']):
                self.session.exclude(self.session.data['records'][row]['id']);self.result.clear();self.render_table()
        except (ValueError,OSError) as exc:self.status.show_message(str(exc),'error')

    def analyze(self):
        try:
            r=self.session.analyze()
            if r['analysis_mode']=='sphere':
                text=f"有效点：{r['sample_count']}\n组合球面直径：{r['combined_diameter_mm']:.4f} mm（不是白球直径）\n当前 TCP 反馈坐标下的拟合中心："+' / '.join(f'{x:.4f}' for x in r['fitted_centre_configured_tcp_mm'])+f" mm\n径向拟合残差 RMS：{r['rms_radial_residual_mm']:.4f} mm\n最大绝对残差：{r['max_abs_radial_residual_mm']:.4f} mm\n\n"+'\n'.join(r['warnings'])
                if r['estimated_stylus_effective_radius_mm'] is not None:
                    text+=f"\n\n参考白球直径：{r['reference_ball_diameter_mm']:.4f} mm\n估算测针有效半径：{r['estimated_stylus_effective_radius_mm']:.4f} mm\n估算测针有效直径：{r['estimated_stylus_effective_diameter_mm']:.4f} mm\n计算：组合半径 − 参考球半径；仅估算，未写入工具参数。"
            else:
                text=f"有效点：{r['sample_count']}\n三轴标准差："+' / '.join(f'{x:.4f}' for x in r['axis_std_mm'])+f" mm\n三维离散 RMS：{r['rms_spread_mm']:.4f} mm\n最大两点距离：{r['max_pair_distance_mm']:.4f} mm\n\n"+r['note']
            self.result.setPlainText(text);self.status.setText('分析已保存；没有写入 TCP 或标定参数。')
        except (ValueError,OSError,KeyError) as exc:self.result.clear();self.status.setText('不能分析：'+str(exc))

    def open_session(self):
        path,_=QFileDialog.getOpenFileName(self,'打开采集组',str(self.directory),'JSON (*.json)')
        if not path:return
        try:
            self.session=ContactSession.load(path);self.anchor=None;self.mode.setCurrentIndex(0 if self.session.data['mode']=='sphere' else 1)
            self.show_reference(self.session.data.get('reference_ball'))
            self.result.clear();self.render_table();self.update_controls();self.status.setText('已打开历史组，需重新分析；不会恢复自动采集。')
        except (ValueError,OSError,KeyError,TypeError) as exc:self.status.setText('打开失败：'+str(exc))

    def export_session(self):
        if not self.session:return
        path,_=QFileDialog.getSaveFileName(self,'导出本组及结果',self.session.data['name']+'.json','JSON (*.json)')
        if path:
            try:atomic_json(path,{**copy.deepcopy(self.session.data),**FLAGS});self.status.setText('本组及分析结果已导出。')
            except OSError as exc:self.status.setText('导出失败：'+str(exc))

    def showEvent(self,event):super().showEvent(event);self.timer.start();self.poll()

    def closeEvent(self,event):
        self.stop_session('分析窗口关闭，本组停止');self.timer.stop();super().closeEvent(event)

    def reject(self):self.close()
