"""Guided bore task: offline direction preview, receive-only samples, results."""
import copy,json,math,time
from pathlib import Path
from PySide6.QtCore import Qt,QTimer,QPointF
from PySide6.QtGui import QPainter,QColor,QPen
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QGridLayout,QLabel,QPushButton,QComboBox,QCheckBox,QTableWidget,QTableWidgetItem,QHeaderView,QPlainTextEdit,QSplitter,QScrollArea,QFileDialog,QAbstractItemView
from .stepper import DoubleParameter
from .ui_feedback import FeedbackLabel
from .circle_measurement import plan_circle,fit_circle
from .coordinate_target import validate_start
from .probe_workspace import capture_position,atomic_json
from .sphere_analysis import configuration,orientation_difference
from .target_task import BUILD_ID
class CircleDiagram(QWidget):
    def __init__(self):super().__init__();self.plan=None;self.points=[];self.setMinimumSize(300,230)
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.Antialiasing);p.fillRect(self.rect(),QColor('#f6f9fc'));p.setPen(QColor('#36506b'));p.drawText(12,22,'XY截面 · 采点方向示意（非实机轨迹）')
        if not self.plan:return
        cx,cy=self.width()/2,self.height()/2+10;r=min(self.width(),self.height())*.34
        p.setPen(QPen(QColor('#8fa8c1'),2));p.drawEllipse(QPointF(cx,cy),r,r)
        for d in self.plan['directions']:
            angle=math.radians(d['angle_deg']);x=cx+r*math.cos(angle);y=cy-r*math.sin(angle)
            p.setPen(QPen(QColor('#4482bb'),1));p.drawLine(int(cx),int(cy),int(x),int(y));p.setBrush(QColor('#2563ad'));p.drawEllipse(int(x)-4,int(y)-4,8,8);p.drawText(int(x)+6,int(y),str(d['index']))
class CircleMeasurementPage(QWidget):
    def __init__(self,workspace,parent=None):
        super().__init__(parent);from .page_style import PAGE_STYLE;self.setStyleSheet(PAGE_STYLE);self.workspace=workspace;self.plan=None;self.points=[];self.records=[];self.result=None;self.active=False;self.seen=set();self.anchor=None;self.data_source='未采集'
        root=QVBoxLayout(self);root.addWidget(QLabel('圆孔测量 · 设置 → 方向预览 / 只读采点 → 分析结果'))
        self.status=FeedbackLabel('支持竖直圆孔同一XY截面；本页不发送运动。自动探测、退离仍需单独完成实机验证。');root.addWidget(self.status)
        self.result_quality=QLabel();self.result_quality.setWordWrap(True);self.result_quality.setStyleSheet("padding:8px;background:#fff4dc;color:#795014;font-weight:600;");root.addWidget(self.result_quality)
        split=QSplitter();root.addWidget(split,1);scroll=QScrollArea();scroll.setWidgetResizable(True);left_widget=QWidget();left=QVBoxLayout(left_widget);scroll.setWidget(left_widget);scroll.setMinimumWidth(310);scroll.setMaximumWidth(390);split.addWidget(scroll)
        grid=QGridLayout();self.center=[]
        for i,axis in enumerate('XYZ'):
            grid.addWidget(QLabel('估计中心 '+axis),i,0);value=DoubleParameter();value.setRange(-2500,2500);value.setDecimals(3);value.setSuffix(' mm');grid.addWidget(value,i,1);self.center.append(value)
        self.diameter=DoubleParameter();self.diameter.setRange(.1,1000);self.diameter.setValue(20);self.diameter.setSuffix(' mm');grid.addWidget(QLabel('估计孔径'),3,0);grid.addWidget(self.diameter,3,1)
        self.count=QComboBox();self.count.addItems(['4','8','12']);self.count.setCurrentText('8');grid.addWidget(QLabel('方向数'),4,0);grid.addWidget(self.count,4,1)
        self.radius=DoubleParameter();self.radius.setRange(.001,50);self.radius.setDecimals(4);self.radius.setValue(1);self.radius.setSuffix(' mm');grid.addWidget(QLabel('有效测针半径'),5,0);grid.addWidget(self.radius,5,1);left.addLayout(grid)
        self.compensate=QCheckBox('使用有效半径补偿（手工声明）');left.addWidget(self.compensate)
        self.buttons=[]
        for text,callback in [('读取当前位置为估计中心',self.read_center),('生成采点方向预览',self.generate),('离线演练一组（不连接实机）',self.demo),('开始本孔只读采点',self.start_collection),('结束采点',self.end_collection),('拟合圆心与直径',self.analyze),('导出原始点与结果',self.export)]:
            button=QPushButton(text);button.clicked.connect(callback);left.addWidget(button);self.buttons.append(button)
        self.buttons[1].setStyleSheet('background:#2563ad;color:white;padding:8px;border-radius:6px;')
        left.addStretch();right=QWidget();right_layout=QVBoxLayout(right);split.addWidget(right);self.diagram=CircleDiagram();right_layout.addWidget(self.diagram,1)
        self.table=QTableWidget(0,4);self.table.setEditTriggers(QAbstractItemView.NoEditTriggers);self.table.setHorizontalHeaderLabels(['点','X / mm','Y / mm','Z / mm']);self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch);right_layout.addWidget(self.table,1)
        self.detail=QPlainTextEdit();self.detail.setReadOnly(True);right_layout.addWidget(self.detail,1)
        self.timer=QTimer(self);self.timer.setInterval(200);self.timer.timeout.connect(self.poll)
        for value in (*self.center,self.diameter,self.radius):value.valueChanged.connect(self.invalidate)
        self.count.currentIndexChanged.connect(self.invalidate);self.compensate.toggled.connect(self.invalidate);self.update_controls()
    def update_quality(self):
        self.result_quality.setText('数据来源：'+self.data_source+' · '+('已有拟合估算' if self.result else '尚无有效拟合结果')+' · 测量精度未验证；拟合残差不是实际精度')

    def update_controls(self):
        self.update_quality()
        for i in (0,1,2,3):self.buttons[i].setEnabled(not self.active)
        self.buttons[4].setEnabled(self.active);self.buttons[5].setEnabled(not self.active and len(self.points)>=3);self.buttons[6].setEnabled(not self.active and bool(self.points))
        self.buttons[5].setToolTip('先结束采点，并至少采集3个不共线的同截面点')
        self.buttons[6].setToolTip('先结束采点，再导出原始点和固定结果快照')

    def invalidate(self,*_):
        self.plan=None;self.result=None;self.diagram.plan=None;self.diagram.update();self.detail.setPlainText('参数已变化，请重新生成方向预览；旧结果已失效。');self.update_quality()
    def read_center(self):
        try:
            if self.active:raise ValueError('请先结束本孔采点再修改估计中心')
            frame=validate_start(self.workspace.backend().snapshot())
            for v,x in zip(self.center,frame['pose'][:3]):v.setValue(x)
            self.status.show_message('已读取反馈XYZ作为估计中心，请核对是否位于孔内。','info')
        except (ValueError,KeyError,TypeError) as exc:self.status.show_message(str(exc),'error')
    def generate(self):
        try:
            if self.active:raise ValueError('请先结束本孔采点')
            self.plan=plan_circle([v.value() for v in self.center],self.diameter.value(),int(self.count.currentText()),self.radius.value() if self.compensate.isChecked() else None)
            self.diagram.plan=self.plan;self.diagram.update();self.detail.setPlainText(f'本孔 {self.plan["count"]} 个方向，统一高度 Z {self.plan["center"][2]:.3f} mm。\n计划循环：探测 → 触发记录及请求停止 → 核对停止 → 反向退离并核对释放 → 返回起点。\n这里只展示方向；没有下发运动指令。');self.status.show_message('采点方向已生成；仅方向示意，不是已验证可执行的机械臂路径。','info')
        except (ValueError,TypeError) as exc:self.status.show_message(str(exc),'error')
    def demo(self):
        if self.active:self.status.show_message('请先结束实测采集再运行离线演练','error');return
        self.generate()
        if not self.plan:return
        self.points=[d['nominal_contact'] for d in self.plan['directions']];self.records=[];self.anchor=None;self.data_source='离线合成演练';self.render();self.analyze()
    def start_collection(self):
        try:
            if self.active:raise ValueError('本孔正在采集')
            self.workspace.refresh_feedback();frame=validate_start(self.workspace.backend().snapshot())
            if self.workspace.trigger_save_error or self.workspace.trigger_missed:raise ValueError('原始触发记录异常，请先排查')
            self.anchor=capture_position('圆孔采集起点',frame);self.anchor['controller_address']=self.workspace.backend().address
            self.seen={r['id'] for r in self.workspace.trigger_journal.records};self.points=[];self.records=[];self.result=None;self.active=True;self.data_source='真实接收帧（非硬件锁存）';self.timer.start()
            for value in (*self.center,self.diameter,self.radius,self.count,self.compensate):value.setEnabled(False)
            self.session_path=self.workspace.storage_path.parent/'circle_sessions'/(str(time.time_ns())+'.json')
            self.status.show_message('只读采集中：只接收开始之后的触发点。本页不移动机械臂；保持同一高度和姿态。','info');self.render()
        except (ValueError,KeyError,TypeError) as exc:self.status.show_message(str(exc),'error')
    def poll(self):
        if not self.active:return
        try:
            self.workspace.refresh_feedback();frame=self.workspace.backend().snapshot()
            if not isinstance(frame,dict) or time.monotonic()-frame.get('received_monotonic',0)>.2:raise ValueError('反馈中断，本孔采集已结束')
            if frame.get('error'):raise ValueError('控制器报警，本孔采集已结束')
            current=capture_position('圆孔当前配置',frame);current['controller_address']=self.workspace.backend().address
            if configuration(current)!=configuration(self.anchor):raise ValueError('工具或用户配置变化，本孔采集已结束')
            if self.workspace.trigger_save_error or self.workspace.trigger_missed:raise ValueError('原始触发记录保存异常，本孔采集已结束')
            for record in self.workspace.trigger_journal.records:
                if record['id'] in self.seen:continue
                self.seen.add(record['id'])
                if configuration(record)!=configuration(self.anchor) or orientation_difference(record,self.anchor)>.2:raise ValueError('触发点配置或朝向变化，已停止本孔采集')
                if len(self.points)>=500:raise ValueError('本孔采点超过500个，已停止采集')
                self.records.append(copy.deepcopy(record));self.points.append(record['tcp_pose'][:3]);self.result=None
            self.render();self.status.set_status(f'本孔已采 {len(self.points)} 点 · 同一XY截面 · 接收帧坐标不是硬件锁存')
        except (ValueError,OSError,KeyError,TypeError) as exc:self.end_collection();self.status.show_message(str(exc),'error')
    def end_collection(self):
        was_active=self.active
        self.active=False;self.timer.stop()
        for value in (*self.center,self.diameter,self.radius,self.count,self.compensate):value.setEnabled(True)
        self.status.show_message(f'本孔采集已结束，共 {len(self.points)} 点。','info')
        self.update_controls()
        if was_active and self.records:
            try:atomic_json(self.session_path,dict(build_id=BUILD_ID,data_source=self.data_source,points=self.points,raw_records=self.records,configuration=self.anchor,precision_verified=False,hardware_executable=False))
            except (ValueError,OSError) as exc:self.status.show_message('本孔记录保存失败：'+str(exc),'error')
    def render(self):
        self.update_quality()
        self.update_controls()
        self.table.setRowCount(len(self.points))
        for i,xyz in enumerate(self.points):
            for col,value in enumerate([i+1]+xyz):self.table.setItem(i,col,QTableWidgetItem(str(value) if col==0 else f'{value:.4f}'))
    def analyze(self):
        try:
            if self.active:raise ValueError('请先结束本孔采集，再拟合')
            self.result=fit_circle(self.points,self.radius.value() if self.compensate.isChecked() else None)
            center=self.result['center_configured_tcp_mm'];diameter=self.result['estimated_bore_diameter_mm']
            self.detail.setPlainText('数据来源：'+self.data_source+f'\n有效点数：{self.result["sample_count"]}\n当前TCP轨迹拟合中心：X {center[0]:.3f} / Y {center[1]:.3f} / Z {center[2]:.3f} mm\n'+(f'补偿后估算孔径：{diameter:.4f} mm' if diameter is not None else f'未补偿轨迹直径：{self.result["trajectory_diameter_mm"]:.4f} mm；未启用有效半径补偿')+f'\n拟合残差 RMS：{self.result["rms_residual_mm"]:.4f} mm\n最大绝对残差：{self.result["max_abs_residual_mm"]:.4f} mm\n'+self.result['warning']);self.status.show_message('拟合完成。'+('这是合成演练结果，不是实测结果。' if self.data_source=='离线合成演练' else '结果为当前TCP配置下的估算，不代表精度认证。'),'info')
        except (ValueError,TypeError) as exc:self.result=None;self.detail.setPlainText('拟合失败：'+str(exc)+'\n旧拟合结果已失效，请检查点位后重新拟合。');self.status.show_message(str(exc),'error')
        finally:self.update_quality()
    def export(self):
        if self.active:self.status.show_message('请先结束采点，再导出固定数据快照','error');return
        path,_=QFileDialog.getSaveFileName(self,'导出圆孔任务及结果','circle_measurement.json','JSON (*.json)')
        if not path:return
        try:atomic_json(Path(path),dict(build_id=BUILD_ID,data_source=self.data_source,task=self.plan,points=self.points,raw_records=self.records,configuration=self.anchor,result=self.result,precision_verified=False,hardware_executable=False));self.status.show_message('已导出：'+str(Path(path).resolve()),'success')
        except (ValueError,OSError) as exc:self.status.show_message(str(exc),'error')
    def closeEvent(self,event):self.end_collection();super().closeEvent(event)
