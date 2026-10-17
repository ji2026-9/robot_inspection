"""Nonblocking global wall warning, shared by real and virtual motion."""
import time
from PySide6.QtCore import QObject
from PySide6.QtWidgets import QMessageBox
class WallAlertPresenter(QObject):
    def __init__(self,service,parent):
        super().__init__(parent);self.parent_window=parent;self.box=None;self.last_key=None;self.last_at=0
        service.alert.connect(self.show_warning)
    def show_warning(self,event):
        key=(event['source'],event['message']);now=time.monotonic()
        if self.box is not None or (key==self.last_key and now-self.last_at<5):return
        self.last_key=key;self.last_at=now
        box=QMessageBox(self.parent_window);self.box=box
        box.setWindowTitle('安全墙预警');box.setIcon(QMessageBox.Warning)
        box.setText('安全墙区域：运动已被阻止' if event['source']=='虚拟预览' else '安全墙区域：已请求停止运动')
        box.setInformativeText(event['message']+'\n\n关闭提示不会恢复运动。检查墙面及工具位置后，重新预览。')
        box.setStandardButtons(QMessageBox.Ok);box.button(QMessageBox.Ok).setText('知道了')
        box.finished.connect(self.dismissed);box.open()
    def dismissed(self,*_):
        if self.box:self.box.deleteLater()
        self.box=None
