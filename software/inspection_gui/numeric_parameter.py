"""Editable presets with the same strict range check for typed values."""
import math
from PySide6.QtCore import QLocale,QEvent
from PySide6.QtGui import QDoubleValidator
from PySide6.QtWidgets import QComboBox
from .stepper import step_button


class NumericParameter(QComboBox):
    def __init__(self,parent=None):
        super().__init__(parent);self.setEditable(True);self.setInsertPolicy(QComboBox.NoInsert)
        self.minimum=0;self.maximum=0;self.integer=False
        self.increment=.1;self.last_valid=0
        self.setMinimumWidth(158);self.setMinimumHeight(36)
        self.minus_button=step_button(self,'−','减少参数',lambda:self.step_by(-1))
        self.plus_button=step_button(self,'+','增加参数',lambda:self.step_by(1))
        self.lineEdit().setTextMargins(32,0,32,0)
        self.currentTextChanged.connect(self._sync_buttons)

    def configure(self,values,minimum,maximum,default,*,integer=False):
        self.minimum=minimum;self.maximum=maximum;self.integer=integer
        self.increment=1 if integer else .1;self.last_valid=default
        validator=QDoubleValidator(minimum,maximum,0 if integer else 2,self)
        validator.setLocale(QLocale.c());validator.setNotation(QDoubleValidator.StandardNotation)
        self.lineEdit().setValidator(validator)
        self.blockSignals(True);self.clear();self.addItems([format(v,'g') for v in values])
        self.setCurrentText(format(default,'g'));self.blockSignals(False)
        self.setToolTip(f'可选择常用值，也可直接输入：{minimum:g}–{maximum:g}'+('，仅支持整数' if integer else ''))
        self._sync_buttons()

    def step_by(self,direction):
        if not self.isEnabled():return
        try:value=self.value()
        except ValueError:value=self.last_valid
        value=max(self.minimum,min(self.maximum,round(value+direction*self.increment,2)))
        self.setEditText(format(value,'g'))

    def _sync_buttons(self,*_):
        try:value=self.value();self.last_valid=value
        except ValueError:value=None
        self.minus_button.setEnabled(self.isEnabled() and (value is None or value>self.minimum))
        self.plus_button.setEnabled(self.isEnabled() and (value is None or value<self.maximum))
        self.minus_button.setToolTip(f'减少 {self.increment:g}；最小 {self.minimum:g}')
        self.plus_button.setToolTip(f'增加 {self.increment:g}；最大 {self.maximum:g}')

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'plus_button'):
            self.minus_button.setGeometry(3,3,27,max(20,self.height()-6))
            self.plus_button.setGeometry(self.width()-58,3,27,max(20,self.height()-6))

    def changeEvent(self,event):
        super().changeEvent(event)
        if event.type()==QEvent.EnabledChange and hasattr(self,'plus_button'):self._sync_buttons()

    def value(self):
        try:value=float(self.currentText().strip())
        except ValueError:raise ValueError('参数不能为空，且必须是数值')
        if not math.isfinite(value) or not self.minimum<=value<=self.maximum:
            raise ValueError(f'参数范围：{self.minimum:g}–{self.maximum:g}')
        if self.integer and not value.is_integer():raise ValueError('速度或倍率需要输入整数')
        return int(value) if self.integer else value
