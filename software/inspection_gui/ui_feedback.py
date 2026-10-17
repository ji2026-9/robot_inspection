"""Visible, persistent operation feedback. No motion or network side effects."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QLabel,QApplication

COLORS={'error':('#fff0ee','#a52520','#d14438','操作未完成'),
        'warning':('#fff7e5','#805000','#c48715','注意'),
        'success':('#edf9f0','#205f39','#2d8b53','操作完成'),
        'info':('#edf4ff','#204c7d','#3475bb','操作提示')}

def severity(text):
    text=str(text)
    if text.startswith(('未生成','未完成','未执行','未保存','未测试','未开始','未启用','无法','不能','失败','保存失败','预演失败','连接失败','打开失败','导出失败','采点保存 / 检查失败','原点记录不可用')) or any(x in text for x in ('失败：','失败，','无法确认停止','队列溢出')):return 'error'
    if text.startswith(('已保存','已应用','已导出','已读取','分析已保存','本组及分析结果已导出','● 已连接')):return 'success'
    if text.startswith(('请先','需要','未连接','● 未连接','等待','墙位置','工具包络','有未应用','现场墙面')):return 'warning'
    return 'info'

def next_step(message):
    if '预留距离必须小于' in message:return '将墙内侧禁入预留设为小于实测墙距的值，再应用；墙距按现场测量填写。'
    if any(x in message for x in ('重合','小于0.01','重复目标')):return '修改该目标坐标，或取消勾选重复目标，再重新预览。'
    if '2000' in message and ('距离' in message or '目标' in message):return '核对坐标单位为 mm；距离过大时分段设置目标，再重新预览。'
    if any(x in message for x in ('没有勾选','至少勾选','未选择目标')):return '在目标列表左侧勾选本次要执行的点。'
    if '安全墙' in message or '墙位置' in message:return '到“安全墙”页核对现场墙面与工具包络，再重新预览；不要用参考值代替实测值。'
    if any(x in message for x in ('反馈','连接','IP','端口')):return '到“设备连接”页检查地址和连接状态；反馈恢复并保持静止后重试。'
    if any(x in message for x in ('工具','坐标配置','用户坐标')):return '核对当前工具与用户坐标配置；配置一致后重新读取位置并预览。'
    if any(x in message for x in ('写入权限','磁盘','Permission','拒绝访问','无写入权限')):return '检查目标目录的写入权限和磁盘空间，再重试保存。'
    if '逆解' in message or '关节路径' in message:return '调整目标位置或分段设置，重新检查完整路径。'
    return '按上述原因修改后重试；仍失败时，右键复制完整提示用于排查。'

class FeedbackLabel(QLabel):
    def __init__(self,text='',parent=None):
        super().__init__(parent);self.raw_text='';self.level='info';self._render_key=None
        self.setWordWrap(True);self.setTextFormat(Qt.PlainText);self.setTextInteractionFlags(Qt.TextSelectableByMouse|Qt.TextSelectableByKeyboard)
        self.setContextMenuPolicy(Qt.ActionsContextMenu)
        action=QAction('复制完整提示',self);action.triggered.connect(self.copy_message);self.addAction(action)
        self.setText(text)
    def copy_message(self):QApplication.clipboard().setText(self.text())
    def setText(self,text):self.show_message(str(text),severity(text))
    def set_status(self,text,level=None):
        # Background refresh must not erase an unresolved user-operation error.
        if self.level!='error':self.show_message(str(text),level or severity(text))
    def show_message(self,text,level='info',hint=None):
        if level not in COLORS:raise ValueError('Unknown feedback severity')
        text=str(text);hint=next_step(text) if hint is None and level=='error' else hint
        key=(text,level,hint)
        if key==self._render_key:return
        self._render_key=key;self.raw_text=text;self.level=level
        bg,fg,line,title=COLORS[level]
        rendered=f'【{title}】 {text}'+(('\n下一步：'+hint) if hint else '') if text else ''
        super().setText(rendered);self.setAccessibleName(title);self.setAccessibleDescription(text)
        self.setStyleSheet(f'QLabel{{background:{bg};color:{fg};border:1px solid {line};border-left:5px solid {line};border-radius:6px;padding:9px 12px;font-size:13px;font-weight:600;}}')
        self.setMinimumHeight(48 if text else 0)
        if text and level in ('error','warning','success'):
            from .ui_events import journal
            owner=self.parentWidget()
            while owner is not None and type(owner).__name__ in ('QFrame','QWidget','QScrollArea'):owner=owner.parentWidget()
            journal().record(text,level,type(owner).__name__ if owner else '界面提示',hint)
    def clear(self):self.show_message('','info')
