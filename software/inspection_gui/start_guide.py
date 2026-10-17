"""Read-only first-use guidance; buttons only navigate to existing pages."""
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QFrame,QVBoxLayout,QHBoxLayout,QLabel,QPushButton
from .global_status_view import read_status

def next_step(backend,wall_reason=''):
    status=read_status(backend)
    if not status['fresh']:return '先连接设备','设备反馈尚未连接或已过期。先连接反馈；离线预览仍可使用。','devices'
    if status['robot']=='报警':return '先处理控制器报警','查看报警原因，排除后再准备任务。','devices'
    if status['robot']=='运行中':return '机械臂正在运行','先观察运行状态；本引导不会发送停止、使能或运动指令。','control'
    if wall_reason:return '先核对安全墙',wall_reason+'。模型中显示墙面，不代表真实墙的位置已经确认。','wall'
    return '选择任务','可进入采点或实机控制。运动还需在控制页核对工具、连接控制并启用；本提示不代表允许运动。','probe'

class StartGuide(QFrame):
    def __init__(self,get_backend,get_wall_reason,navigate,parent=None):
        super().__init__(parent);self.get_backend=get_backend;self.get_wall_reason=get_wall_reason;self.navigate=navigate;self.destination='devices'
        self.setStyleSheet('StartGuide{background:#edf4fd;border:1px solid #cbdcf1;border-radius:8px;} QLabel{background:transparent;color:#294b70;} QPushButton{padding:7px 12px;}')
        root=QVBoxLayout(self);root.setContentsMargins(12,8,12,8)
        line=QHBoxLayout();self.title=QLabel('开始使用');self.title.setStyleSheet('font-weight:600;font-size:15px;');line.addWidget(self.title,1)
        self.action=QPushButton('连接设备');self.action.clicked.connect(lambda:self.navigate(self.destination));line.addWidget(self.action)
        for text,key in [('离线三维预览','simulation'),('查看结果','records')]:
            button=QPushButton(text);button.clicked.connect(lambda checked=False,k=key:self.navigate(k));line.addWidget(button)
        root.addLayout(line);self.note=QLabel();self.note.setWordWrap(True);root.addWidget(self.note)
        self.timer=QTimer(self);self.timer.setInterval(1000);self.timer.timeout.connect(self.refresh)
    def refresh(self):
        try:title,note,key=next_step(self.get_backend(),self.get_wall_reason())
        except (ValueError,RuntimeError,KeyError,TypeError):title,note,key='先检查设备连接','状态读取失败；请到设备页检查反馈。','devices'
        self.destination=key;self.title.setText('开始使用 · '+title);self.note.setText(note)
        self.action.setText({'devices':'查看设备连接','wall':'核对安全墙','probe':'进入触碰采点','control':'查看实机状态'}[key])
    def showEvent(self,event):super().showEvent(event);self.refresh();self.timer.start()
    def hideEvent(self,event):self.timer.stop();super().hideEvent(event)
