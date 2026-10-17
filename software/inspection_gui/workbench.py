"""Lazy in-window work pages. Navigation never sends a movement command."""
from .ui_feedback import FeedbackLabel
from PySide6.QtCore import QEvent,Qt,QTimer,Signal
import time
from PySide6.QtWidgets import QWidget,QVBoxLayout,QTabWidget,QScrollArea,QLabel,QPushButton,QDialog,QComboBox,QHBoxLayout,QButtonGroup,QToolButton


COMMON_SETTINGS={'devices','wall'}
ADVANCED_SETTINGS={'sphere','stop','models','configs'}

class Workbench(QWidget):
    page_ready=Signal(str,object)
    def __init__(self,visual,parent=None):
        super().__init__(parent);self.pages={'visual':visual};self.factories={};self.keys=['visual']
        self.closing=False;self.loading=set();self.last_error=''
        self.setStyleSheet('QLineEdit:focus,QComboBox:focus,QTableWidget:focus{border:2px solid #3475bb;} QPushButton:focus{border:2px solid #3475bb;} QHeaderView::section{background:#edf3fa;color:#36506b;padding:6px;}')
        self.containers={};self.open_times_ms={}
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        self.tabs=QTabWidget();self.tabs.setDocumentMode(True);self.tabs.setUsesScrollButtons(True)
        self.tabs.setStyleSheet('QTabWidget::pane{border:0;} QTabBar::tab{padding:10px 12px;background:#eaf0f8;color:#506984;} QTabBar::tab:selected{background:#245fa6;color:white;}')
        self.tabs.addTab(visual,'视觉检测');layout.addWidget(self.tabs)
        self.navigation=QWidget();nav=QHBoxLayout(self.navigation);nav.setContentsMargins(4,2,4,4)
        self.nav_buttons={};self.nav_group=QButtonGroup(self);self.nav_group.setExclusive(True)
        self.group_nav=QComboBox();self.group_nav.addItems(['工作台','实机控制','测量任务','记录与结果','设置'])
        for name in ('工作台','实机控制','测量任务','记录与结果','设置'):
            button=QPushButton(name);button.setCheckable(True);button.setMinimumHeight(38)
            button.setStyleSheet('QPushButton{border:0;border-radius:6px;padding:8px 20px;color:#49647f;background:#edf2f8;} QPushButton:checked{background:#245fa6;color:white;font-weight:600;}')
            button.clicked.connect(lambda checked=False,n=name:self.select_group(n));self.nav_group.addButton(button);self.nav_buttons[name]=button
            if name=='设置':nav.addStretch()
            nav.addWidget(button)
        self.guide_toggle=QToolButton();self.guide_toggle.setText('使用引导');self.guide_toggle.setCheckable(True)
        self.guide_toggle.setStyleSheet('QToolButton{border:0;border-radius:5px;padding:7px 12px;background:#edf2f8;color:#49647f;} QToolButton:hover,QToolButton:checked{background:#dce9fa;color:#245fa6;}')
        self.guide_toggle.toggled.connect(lambda checked:self.start_guide.setVisible(checked and self.keys[self.tabs.currentIndex()]=='visual') if hasattr(self,'start_guide') else None)
        nav.insertWidget(nav.count()-1,self.guide_toggle)
        layout.insertWidget(0,self.navigation);self.nav_buttons['工作台'].setChecked(True)
        self.group_nav.setAccessibleName('功能分组');self.group_nav.setToolTip('按任务类型整理页面，切换分组不会创建重复窗口。')
        self.group_nav.hide();self.group_nav.currentTextChanged.connect(self.select_group)
        self.capability=QLabel();self.capability.setWordWrap(True);self.capability.setStyleSheet('padding:5px 10px;background:#edf3fa;color:#365879;')
        layout.insertWidget(1,self.capability);self.capability.hide()
        self.settings_tier='常用设置';self.settings_pages={};self.settings_bar=QWidget();settings_row=QHBoxLayout(self.settings_bar);settings_row.setContentsMargins(8,0,8,0)
        self.settings_buttons={};self.settings_group=QButtonGroup(self)
        for tier in ('常用设置','高级工具'):
            button=QPushButton(tier);button.setCheckable(True);button.setChecked(tier==self.settings_tier)
            button.setStyleSheet('QPushButton{padding:6px 14px;border:0;border-radius:5px;background:#edf2f8;color:#49647f;} QPushButton:checked{background:#dce9fa;color:#245fa6;font-weight:600;}')
            button.clicked.connect(lambda checked=False,t=tier:self.select_settings_tier(t));self.settings_group.addButton(button);self.settings_buttons[tier]=button;settings_row.addWidget(button)
        settings_row.addStretch();layout.insertWidget(1,self.settings_bar);self.settings_bar.hide()
        self.tabs.currentChanged.connect(self._selected)
        if parent:parent.installEventFilter(self)

    def group_for(self,key):
        return {'visual':'工作台','simulation':'工作台','probe':'测量任务','circle':'测量任务','contact':'测量任务','control':'实机控制','records':'记录与结果','events':'记录与结果'}.get(key,'设置')

    def select_settings_tier(self,tier):
        if tier not in self.settings_buttons:raise ValueError('未知设置分类')
        current=self.keys[self.tabs.currentIndex()]
        if self.group_for(current)=='设置':self.settings_pages[self.settings_tier]=current
        self.settings_tier=tier;self.settings_buttons[tier].setChecked(True);self.select_group('设置')

    def section_indices(self,group):
        allowed=COMMON_SETTINGS if self.settings_tier=='常用设置' else ADVANCED_SETTINGS
        return [i for i,key in enumerate(self.keys) if self.group_for(key)==group and (group!='设置' or key in allowed)]

    def select_group(self,group):
        # Remember each section independently, without rebuilding pages or connections.
        group={'设备与标定':'设置','记录与模型':'记录与结果'}.get(group,group)
        if group not in self.nav_buttons:return
        if not hasattr(self,'section_pages'):self.section_pages={}
        old=self.tabs.currentIndex()
        if old>=0:self.section_pages[self.group_for(self.keys[old])]=self.keys[old]
        self.settings_bar.setVisible(group=='设置')
        visible=self.section_indices(group)
        if not visible:return
        self.group_nav.blockSignals(True);self.group_nav.setCurrentText(group);self.group_nav.blockSignals(False)
        self.nav_buttons[group].setChecked(True)
        remembered=self.settings_pages.get(self.settings_tier) if group=='设置' else self.section_pages.get(group)
        selected=self.keys.index(remembered) if remembered in self.keys and self.keys.index(remembered) in visible else visible[0]
        self.tabs.blockSignals(True)
        for i in range(len(self.keys)):self.tabs.setTabVisible(i,i in visible)
        self.tabs.setCurrentIndex(selected);self.tabs.blockSignals(False)
        self.tabs.tabBar().setVisible(len(visible)>1)
        self.tabs.currentChanged.emit(selected)

    def register(self,key,label,factory):
        self.factories[key]=factory;self.keys.append(key)
        placeholder=QWidget();layout=QVBoxLayout(placeholder);layout.setContentsMargins(0,0,0,0)
        note=QLabel('正在准备 '+label+'…');note.setAlignment(Qt.AlignCenter);layout.addWidget(note)
        self.containers[key]=placeholder;index=self.tabs.addTab(placeholder,label)
        self.tabs.setTabVisible(index,self.group_for(key)==self.group_nav.currentText())

    def _selected(self,index):
        if index>=0 and not self.closing:
            key=self.keys[index]
            descriptions={
                'visual':'视觉工作台 · 检测结果与坐标需经对应标定后用于实机',
                'simulation':'仅模型预览 · 模型播放不会让实机运动',
                'control':'实机控制 · 预览与执行分开；软件停止不能替代实体急停',
                'probe':'只读触碰采点 · 保存当前工具坐标；本页不发送运动',
                'circle':'圆孔分析 · 只读采点与估算拟合可用；自动探测 / 退离未开放',
                'contact':'自动测孔 · 逐孔接触停止与退让；需先在实机控制页启用，异常即锁定',
                'sphere':'标定与验证工具 · 拟合成功不等于精度已验证',
                'wall':'全局软件安全墙 · 需按真实现场确认位置；不是控制器安全平面',
                'stop':'诊断工具 · 静止通信测试不代表运动中停止性能已验证',
                'records':'任务与结果 · 请同时核对数据来源、工具配置和精度验证状态'}
            self.capability.setText(descriptions.get(key,'配置与记录 · 修改配置后需重新核对相关任务'))
            self.tabs.setTabToolTip(index,self.capability.text());self.nav_buttons[self.group_for(key)].setToolTip(self.capability.text())
            if hasattr(self,'start_guide'):self.start_guide.setVisible(key=='visual' and self.guide_toggle.isChecked())
            if key not in self.pages:
                # Let the selected tab/header paint before constructing controls.
                QTimer.singleShot(0,lambda:self.open_page(key) if not self.closing and self.tabs.currentIndex()==index else None)

    def open_page(self,key):
        if key not in self.keys:raise ValueError('未知工作页：'+key)
        index=self.keys.index(key)
        if self.group_for(key)=='设置':
            tier='常用设置' if key in COMMON_SETTINGS else '高级工具'
            if self.settings_tier!=tier:self.select_settings_tier(tier)
        if self.group_nav.currentText()!=self.group_for(key) or not self.tabs.isTabVisible(index):self.select_group(self.group_for(key))
        if key not in self.pages:
            if key in self.loading:return None
            self.loading.add(key)
            started=time.perf_counter()
            try:
                page=self.factories[key]()
                if not isinstance(page,QWidget):raise ValueError('工作页创建失败')
                if isinstance(page,QDialog):page.setModal(False)
                page.setWindowFlags(Qt.Widget);page.installEventFilter(self)
                if key=='control':scroll=page
                else:
                    scroll=QScrollArea();scroll.setFrameShape(QScrollArea.NoFrame);scroll.setWidgetResizable(True);scroll.setWidget(page)
                container=self.containers[key];layout=container.layout()
                while layout.count():
                    item=layout.takeAt(0)
                    if item.widget():item.widget().deleteLater()
                layout.addWidget(scroll)
                self.pages[key]=page
                self.open_times_ms[key]=(time.perf_counter()-started)*1000
                self.page_ready.emit(key,page)
            except Exception as exc:
                self.last_error=str(exc);placeholder=self.tabs.widget(index)
                box=placeholder.layout()
                while box.count():
                    item=box.takeAt(0)
                    if item.widget():item.widget().deleteLater()
                message=FeedbackLabel();message.show_message('无法打开工作页：'+str(exc),'error',hint='点击下方“重试”；仍失败可右键复制完整提示用于排查。');box.addWidget(message)
                retry=QPushButton('重试');retry.clicked.connect(lambda:self.open_page(key));box.addWidget(retry);box.addStretch()
                self.tabs.setCurrentIndex(index);return None
            finally:self.loading.discard(key)
        self.tabs.setCurrentIndex(index)
        if not self.pages[key].isVisible():self.pages[key].show()
        return self.pages[key]

    def eventFilter(self,watched,event):
        if not getattr(self,'closing',True) and event.type()==QEvent.Close and watched in self.pages.values():
            key=next(k for k,v in self.pages.items() if v is watched)
            QTimer.singleShot(0,lambda:self.open_page('visual') if not self.closing and self.tabs.currentIndex()==self.keys.index(key) else None)
        if not getattr(self,'closing',True) and event.type()==QEvent.WindowDeactivate and watched is self.parentWidget():
            page=self.pages.get('control');controller=getattr(page,'controller',None)
            if controller:
                state=controller.snapshot()
                if state['unlocked'] or state['resumable']:controller.request_stop('主窗口失去焦点',recoverable=True)
        return super().eventFilter(watched,event)

    def shutdown(self):
        self.closing=True
        for key,page in tuple(self.pages.items()):
            if key!='visual':page.close()
