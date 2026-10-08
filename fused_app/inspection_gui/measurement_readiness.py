"""Readiness facts, with unimplemented calibration stages kept unavailable."""
from PySide6.QtWidgets import QDialog,QVBoxLayout,QLabel,QPushButton,QTableWidget,QTableWidgetItem,QHeaderView

def readiness_rows(backends,has_capture,has_targets):
    def connected(key):
        backend=backends.get(key)
        try:return bool(backend and backend.is_connected())
        except Exception:return False
    return [('相机连接',connected('camera'),'连接相机后检查驱动状态'),
        ('拍照机械臂 A',connected('robot_a'),'需要有效的实时状态'),
        ('测量机械臂 B',connected('robot_b'),'只读反馈正常不代表可以执行运动'),
        ('本次原图留样',has_capture,'原图与拍摄信息均保存'),
        ('测孔清单',has_targets,'对应当前照片，已确认选择'),
        ('相机内参标定',False,'尚未实现标定结果的有效性验证'),
        ('手眼标定及双臂坐标转换',False,'尚未验证相机坐标到测量机械臂坐标'),
        ('测针 TCP 与孔轴方向',False,'尚未完成工具标定及方向验证'),
        ('运动路径与测量接口',False,'尚未实现并验证实际任务执行')]

class ReadinessDialog(QDialog):
    def __init__(self,rows,parent=None):
        super().__init__(parent);self.setWindowTitle('测量就绪检查');self.resize(790,520)
        layout=QVBoxLayout(self);note=QLabel('当前存在未完成项，发送任务保持禁用。连接状态和检测置信度不能替代标定验证。');note.setWordWrap(True);layout.addWidget(note)
        table=QTableWidget(len(rows),3);table.setHorizontalHeaderLabels(['检查项目','状态','说明']);table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.ResizeToContents);table.horizontalHeader().setSectionResizeMode(1,QHeaderView.ResizeMode.ResizeToContents);table.horizontalHeader().setStretchLastSection(True)
        for row,(name,ready,description) in enumerate(rows):
            for column,value in enumerate([name,'已满足' if ready else '未满足',description]):table.setItem(row,column,QTableWidgetItem(value))
        layout.addWidget(table);close=QPushButton('关闭');close.clicked.connect(self.close);layout.addWidget(close)
