"""Readable +/- controls that retain Qt's numeric validation and key handling."""
from PySide6.QtCore import Qt,QEvent
from PySide6.QtWidgets import QAbstractSpinBox,QDoubleSpinBox,QSpinBox,QToolButton

BUTTON_STYLE='''QToolButton{background:#edf3fb;color:#285580;border:1px solid #d5e0ee;
    border-radius:5px;font-size:19px;font-weight:600;padding:0;}
    QToolButton:hover{background:#dceafa;border-color:#85acdb;}
    QToolButton:pressed{background:#c6dcf5;}
    QToolButton:disabled{background:#f0f2f5;color:#bbc5d2;border-color:#e4e8ee;}'''

def step_button(parent,text,name,callback):
    button=QToolButton(parent);button.setText(text);button.setAccessibleName(name)
    button.setToolTip(name);button.setFocusPolicy(Qt.NoFocus);button.setAutoRepeat(True)
    button.setAutoRepeatDelay(450);button.setAutoRepeatInterval(100)
    button.setStyleSheet(BUTTON_STYLE);button.pressed.connect(callback)
    return button


class StepperMixin:
    def __init__(self,parent=None):
        super().__init__(parent)
        QAbstractSpinBox.setButtonSymbols(self,QAbstractSpinBox.NoButtons)
        self.setMinimumHeight(36);self.setMinimumWidth(144)
        self.setStyleSheet('QAbstractSpinBox{background:white;color:#263b51;border:1px solid #ccd8e6;border-radius:6px;padding:5px 36px;}'
            'QAbstractSpinBox:focus{border-color:#659bd5;} QAbstractSpinBox:disabled{background:#f2f4f7;color:#9ba8b8;}')
        self.minus_button=step_button(self,'−','减少数值',self.stepDown)
        self.plus_button=step_button(self,'+','增加数值',self.stepUp)
        self.valueChanged.connect(self._sync_buttons);self.editingFinished.connect(self._sync_buttons)
        self._sync_buttons()

    def _sync_buttons(self,*_):
        if not hasattr(self,'plus_button'):return
        flags=self.stepEnabled();editable=self.isEnabled() and not self.isReadOnly()
        self.minus_button.setEnabled(editable and bool(flags&QAbstractSpinBox.StepDownEnabled))
        self.plus_button.setEnabled(editable and bool(flags&QAbstractSpinBox.StepUpEnabled))
        step=format(self.singleStep(),'g')
        self.minus_button.setToolTip('减少 '+step+self.suffix())
        self.plus_button.setToolTip('增加 '+step+self.suffix())

    def setRange(self,*args):super().setRange(*args);self._sync_buttons()
    def setMinimum(self,value):super().setMinimum(value);self._sync_buttons()
    def setMaximum(self,value):super().setMaximum(value);self._sync_buttons()
    def setSingleStep(self,value):super().setSingleStep(value);self._sync_buttons()
    def setReadOnly(self,value):super().setReadOnly(value);self._sync_buttons()

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'plus_button'):
            self.minus_button.setGeometry(3,3,29,max(20,self.height()-6))
            self.plus_button.setGeometry(self.width()-32,3,29,max(20,self.height()-6))

    def changeEvent(self,event):
        super().changeEvent(event)
        if event.type() in (QEvent.EnabledChange,QEvent.ReadOnlyChange):self._sync_buttons()

    def wheelEvent(self,event):
        if self.hasFocus():super().wheelEvent(event)
        else:event.ignore()


class DoubleParameter(StepperMixin,QDoubleSpinBox):pass
class IntegerParameter(StepperMixin,QSpinBox):pass
