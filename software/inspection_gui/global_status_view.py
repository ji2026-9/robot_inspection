"""One fresh feedback source for the global status strip. Never connects hardware."""
import time,math
from PySide6.QtCore import QTimer,Qt,Signal
from PySide6.QtWidgets import QWidget,QHBoxLayout,QLabel,QPushButton
PHASES={'locked':'待准备','ready':'可操作','queued':'路径核验中','moving':'运动中','stopping':'停止请求中','verifying_stop':'停止核对中','latched':'停止锁定','fault':'控制异常','disconnected':'未连接'}
def read_status(backend,now=None):
    now=time.monotonic() if now is None else now
    frame=backend.snapshot() if backend else None;control=getattr(backend,'manual_control',None) if backend else None
    controller=control.snapshot() if control else {};fresh=False
    if isinstance(frame,dict):
        stamp=frame.get('received_monotonic');fresh=type(stamp) in (int,float) and math.isfinite(stamp) and 0<=now-stamp<=.2
    if not fresh:return dict(fresh=False,feedback='反馈未连接 / 已过期',robot='实机状态未知',probe='测头 —',scale='倍率 —',coordinates='坐标配置 —',control=('控制条件未满足' if controller.get('phase')=='ready' and not controller.get('safety',{}).get('feedback_ok') else PHASES.get(controller.get('phase'),'控制未连接')) if controller.get('connected') else '控制未连接',can_stop=bool(controller.get('connected')))
    scale=frame.get('speed_percent');valid=type(scale) in (int,float) and math.isfinite(scale) and 0<=scale<=100
    return dict(fresh=True,feedback='实机反馈已连接',robot='报警' if frame.get('error') else '运行中' if frame.get('running') else '已使能' if frame.get('enabled') else '未使能',
        probe='测头触发' if frame.get('digital_inputs',0)&1 else '测头松开',scale=f'倍率 {scale:g}%' if valid else '倍率未知',
        coordinates=f"用户 {frame.get('user_index','—')} / 工具 {frame.get('tool_index','—')}",control=('控制条件未满足' if controller.get('phase')=='ready' and not controller.get('safety',{}).get('feedback_ok') else PHASES.get(controller.get('phase'),'控制未连接')) if controller.get('connected') else '控制未连接',can_stop=bool(controller.get('connected')))
class WallStatusLabel(QLabel):
    clicked=Signal()
    def __init__(self):
        super().__init__();self.setCursor(Qt.PointingHandCursor);self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName('全局安全墙状态，按回车查看设置');self.setToolTip('点击此状态，或按回车，进入安全墙设置')
    def mouseReleaseEvent(self,event):
        if event.button()==Qt.LeftButton:self.clicked.emit()
        super().mouseReleaseEvent(event)
    def keyPressEvent(self,event):
        if event.key() in (Qt.Key_Return,Qt.Key_Enter,Qt.Key_Space):self.clicked.emit();event.accept()
        else:super().keyPressEvent(event)

class GlobalStatusStrip(QWidget):
    def __init__(self,get_backend,parent=None):
        super().__init__(parent);self.get_backend=get_backend;self.previous=None
        row=QHBoxLayout(self);row.setContentsMargins(12,2,12,2);row.setSpacing(10)
        self.label=QLabel();self.label.setWordWrap(True);self.label.setStyleSheet('font-size:12px;color:#36506b;');row.addWidget(self.label,1)
        self.stop=QPushButton('停止运动 · Esc');self.stop.setStyleSheet('QPushButton{background:#b73b32;color:white;border:0;border-radius:4px;padding:4px 12px;font-weight:600;} QPushButton:disabled{background:#e3e8ef;color:#66788a;}');self.stop.pressed.connect(self.request_stop);row.addWidget(self.stop)
        self.timer=QTimer(self);self.timer.setInterval(200);self.timer.timeout.connect(self.refresh);self.timer.start();self.refresh()
    def refresh(self):
        try:state=read_status(self.get_backend())
        except (ValueError,RuntimeError,KeyError,TypeError):
            state=read_status(None);state['can_stop']=bool(getattr(getattr(self.get_backend(),'manual_control',None),'connected',False))
        text='  ·  '.join(state[k] for k in ('feedback','robot','control','probe','scale','coordinates'))
        if self.label.text()!=text:self.label.setText(text)
        self.stop.setEnabled(state['can_stop']);self.stop.setToolTip('向当前控制连接请求最高优先级停止' if state['can_stop'] else '本软件控制通道未连接，不能发送停止命令')
        if self.previous and self.previous['fresh'] and not state['fresh']:
            from .ui_events import journal
            journal().record('实时反馈已过期，界面不再显示旧数据为实时状态','warning','全局状态','检查设备连接；恢复反馈后重新核对任务。')
        self.previous=state
    def request_stop(self):
        control=getattr(self.get_backend(),'manual_control',None)
        if control:control.request_stop('全局停止按钮',recoverable=True)
