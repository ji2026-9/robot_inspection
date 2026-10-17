"""Operator-readable event history and diagnostic export."""
import json
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QComboBox,QPushButton,QTableWidget,QTableWidgetItem,QHeaderView,QAbstractItemView,QPlainTextEdit,QFileDialog
from .ui_events import journal
from .probe_workspace import atomic_json
from .target_task import BUILD_ID
from .ui_feedback import FeedbackLabel
class EventHistoryPage(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent);from .page_style import PAGE_STYLE;self.setStyleSheet(PAGE_STYLE);self.revision=-1;self.rows=[]
        root=QVBoxLayout(self);head=QHBoxLayout();head.addWidget(QLabel('运行事件与故障记录'));head.addStretch()
        self.filter=QComboBox();[self.filter.addItem(label,value) for label,value in [('全部','全部'),('错误','error'),('警告','warning'),('完成','success')]];self.filter.currentIndexChanged.connect(lambda:self.refresh(True));head.addWidget(self.filter)
        export=QPushButton('导出诊断记录');export.clicked.connect(self.export);head.addWidget(export);root.addLayout(head)
        self.status=FeedbackLabel('保留本次运行最近500条；文件日志持续追加。选择事件可复制完整原因和处理方法。');root.addWidget(self.status)
        self.table=QTableWidget(0,4);self.table.setHorizontalHeaderLabels(['时间','级别','来源','原因']);self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents);self.table.horizontalHeader().setSectionResizeMode(3,QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows);self.table.setEditTriggers(QAbstractItemView.NoEditTriggers);root.addWidget(self.table,1)
        self.detail=QPlainTextEdit();self.detail.setReadOnly(True);self.detail.setMaximumHeight(180);root.addWidget(self.detail);self.table.itemSelectionChanged.connect(self.selected)
        self.timer=QTimer(self);self.timer.setInterval(500);self.timer.timeout.connect(self.refresh)
    def refresh(self,force=False):
        j=journal()
        if not force and self.revision==j.revision:return
        self.revision=j.revision;level=self.filter.currentData();self.rows=[e for e in j.snapshot() if level=='全部' or e['level']==level]
        self.table.setRowCount(len(self.rows))
        for i,e in enumerate(self.rows):
            for c,key in enumerate(('time','level','source','message')):self.table.setItem(i,c,QTableWidgetItem(e[key]))
        if j.save_error:self.status.show_message('诊断日志写入异常：'+j.save_error,'error')
    def selected(self):
        i=self.table.currentRow()
        if 0<=i<len(self.rows):self.detail.setPlainText(json.dumps(self.rows[i],ensure_ascii=False,indent=2))
    def export(self):
        path,_=QFileDialog.getSaveFileName(self,'导出诊断记录','diagnostics.json','JSON (*.json)')
        if not path:return
        try:
            config_snapshot={};root=journal().path.parent if journal().path else None
            if root:
                for name in ('manual_origin.json','safety_wall.json'):
                    file=root/name
                    if file.exists():
                        try:config_snapshot[name]=json.loads(file.read_text(encoding='utf-8'))
                        except (OSError,ValueError) as exc:config_snapshot[name]={'read_error':str(exc)}
            atomic_json(Path(path),dict(build_id=BUILD_ID,events=journal().snapshot(),configuration_snapshot=config_snapshot,log_write_error=journal().save_error))
            self.status.show_message('诊断记录和配置快照已导出。','success')
        except OSError as exc:self.status.show_message(str(exc),'error')
    def showEvent(self,e):super().showEvent(e);self.refresh(True);self.timer.start()
    def hideEvent(self,e):self.timer.stop();super().hideEvent(e)
