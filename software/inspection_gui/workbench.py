"""Lazy in-window work pages. Navigation never sends a movement command."""
from PySide6.QtCore import QEvent,Qt,QTimer,Signal
import time
from PySide6.QtWidgets import QWidget,QVBoxLayout,QTabWidget,QScrollArea,QLabel,QPushButton,QDialog


class Workbench(QWidget):
    page_ready=Signal(str,object)
    def __init__(self,visual,parent=None):
        super().__init__(parent);self.pages={'visual':visual};self.factories={};self.keys=['visual']
        self.closing=False;self.loading=set();self.last_error=''
        self.containers={};self.open_times_ms={}
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        self.tabs=QTabWidget();self.tabs.setDocumentMode(True);self.tabs.setUsesScrollButtons(True)
        self.tabs.setStyleSheet('QTabWidget::pane{border:0;} QTabBar::tab{padding:10px 12px;background:#eaf0f8;color:#506984;} QTabBar::tab:selected{background:#245fa6;color:white;}')
        self.tabs.addTab(visual,'视觉检测');layout.addWidget(self.tabs)
        self.tabs.currentChanged.connect(self._selected)
        if parent:parent.installEventFilter(self)

    def register(self,key,label,factory):
        self.factories[key]=factory;self.keys.append(key)
        placeholder=QWidget();layout=QVBoxLayout(placeholder);layout.setContentsMargins(0,0,0,0)
        note=QLabel('正在准备 '+label+'…');note.setAlignment(Qt.AlignCenter);layout.addWidget(note)
        self.containers[key]=placeholder;self.tabs.addTab(placeholder,label)

    def _selected(self,index):
        if index>=0 and not self.closing:
            key=self.keys[index]
            if key not in self.pages:
                # Let the selected tab/header paint before constructing controls.
                QTimer.singleShot(0,lambda:self.open_page(key) if not self.closing and self.tabs.currentIndex()==index else None)

    def open_page(self,key):
        if key not in self.keys:raise ValueError('未知工作页：'+key)
        index=self.keys.index(key)
        if key not in self.pages:
            if key in self.loading:return None
            self.loading.add(key)
            started=time.perf_counter()
            try:
                page=self.factories[key]()
                if not isinstance(page,QWidget):raise ValueError('工作页创建失败')
                if isinstance(page,QDialog):page.setModal(False)
                page.setWindowFlags(Qt.Widget);page.installEventFilter(self)
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
                message=QLabel('无法打开工作页：'+str(exc));message.setWordWrap(True);box.addWidget(message)
                retry=QPushButton('重试');retry.clicked.connect(lambda:self.open_page(key));box.addWidget(retry);box.addStretch()
                self.tabs.setCurrentIndex(index);return None
            finally:self.loading.discard(key)
        self.tabs.setCurrentIndex(index)
        if not self.pages[key].isVisible():self.pages[key].show()
        return self.pages[key]

    def eventFilter(self,watched,event):
        if not self.closing and event.type()==QEvent.Close and watched in self.pages.values():
            key=next(k for k,v in self.pages.items() if v is watched)
            QTimer.singleShot(0,lambda:self.open_page('visual') if not self.closing and self.tabs.currentIndex()==self.keys.index(key) else None)
        if event.type()==QEvent.WindowDeactivate and watched is self.parentWidget():
            page=self.pages.get('control');controller=getattr(page,'controller',None)
            if controller:
                state=controller.snapshot()
                if state['unlocked'] or state['resumable']:controller.request_stop('主窗口失去焦点',recoverable=True)
        return super().eventFilter(watched,event)

    def shutdown(self):
        self.closing=True
        for key,page in tuple(self.pages.items()):
            if key!='visual':page.close()
