"""Checkbox target table; row selection does not imply motion selection."""
from PySide6.QtWidgets import QTableWidget,QHeaderView,QAbstractItemView
class TargetTable(QTableWidget):
    def __init__(self):
        super().__init__(0,4);self.setHorizontalHeaderLabels(['执行','X / mm','Y / mm','Z / mm']);self.verticalHeader().hide()
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeToContents)
        self.setSelectionBehavior(QAbstractItemView.SelectRows);self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setEditTriggers(QAbstractItemView.DoubleClicked|QAbstractItemView.EditKeyPressed)
        self.setMinimumHeight(130)
    def count(self):return self.rowCount()
    def item(self,row,column=0):return super().item(row,column)
    def setCurrentRow(self,row):self.setCurrentCell(row,0);self.selectRow(row)
