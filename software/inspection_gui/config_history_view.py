"""Inspect and explicitly restore local origin/wall revisions."""
from pathlib import Path
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QTableWidget,QTableWidgetItem,QHeaderView,QAbstractItemView,QPlainTextEdit
from .ui_feedback import FeedbackLabel
from .config_history import read_revision,archive_config,KINDS
from .manual_origin import validate_origin
from .probe_workspace import atomic_json
class ConfigHistoryPage(QWidget):
    def __init__(self,root,get_backend,parent=None):
        super().__init__(parent);from .page_style import PAGE_STYLE;self.setStyleSheet(PAGE_STYLE);self.root=Path(root);self.get_backend=get_backend;self.rows=[]
        layout=QVBoxLayout(self);head=QHBoxLayout();head.addWidget(QLabel('原点与安全墙 · 配置版本'));head.addStretch()
        refresh=QPushButton('刷新');refresh.clicked.connect(self.refresh);head.addWidget(refresh);self.restore=QPushButton('恢复所选版本');self.restore.clicked.connect(self.restore_selected);head.addWidget(self.restore);layout.addLayout(head)
        self.status=FeedbackLabel('配置变更前自动留存上一版本。恢复不启动机械臂；之后仍需重新核对和预览。');layout.addWidget(self.status)
        self.table=QTableWidget(0,3);self.table.setHorizontalHeaderLabels(['类型','版本时间戳','校验']);self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch);self.table.setSelectionBehavior(QAbstractItemView.SelectRows);self.table.setEditTriggers(QAbstractItemView.NoEditTriggers);self.table.itemSelectionChanged.connect(self.selected);layout.addWidget(self.table,1)
        self.detail=QPlainTextEdit();self.detail.setReadOnly(True);layout.addWidget(self.detail,1);self.refresh()
    def refresh(self):
        self.rows=[]
        for kind in KINDS:
            for path in sorted((self.root/'config_versions'/kind).glob('*.json'),reverse=True)[:100]:self.rows.append(path)
        self.table.setRowCount(len(self.rows))
        for i,path in enumerate(self.rows):
            try:record,_=read_revision(path);values=[{'origin':'自定义原点','wall':'安全墙'}[record['kind']],path.stem,'通过']
            except (OSError,ValueError,KeyError):values=[path.parent.name,path.stem,'损坏，不可恢复']
            for c,v in enumerate(values):self.table.setItem(i,c,QTableWidgetItem(v))
    def selected(self):
        index=self.table.currentRow();self.restore.setEnabled(0<=index<len(self.rows))
        if index>=0:
            try:_,data=read_revision(self.rows[index]);self.detail.setPlainText(__import__('json').dumps(data,ensure_ascii=False,indent=2))
            except (OSError,ValueError,KeyError) as exc:self.status.show_message(str(exc),'error')
    def restore_selected(self):
        try:
            index=self.table.currentRow()
            if not 0<=index<len(self.rows):raise ValueError('请先选择一个配置版本')
            control=getattr(self.get_backend(),'manual_control',None)
            if control and control.snapshot()['phase'] in ('queued','moving','stopping','verifying_stop'):raise ValueError('运动或停止核对期间不能恢复配置')
            record,data=read_revision(self.rows[index]);kind=record['kind'];target=self.root/KINDS[kind]
            if kind=='wall':
                from .global_wall import wall_service
                wall_service(target).apply(data)
            else:
                data=validate_origin(data);archive_config(target,'origin');atomic_json(target,data)
            self.status.show_message('配置版本已恢复。旧预览必须重新生成；没有启动机械臂。','success');self.refresh()
        except (ValueError,OSError,KeyError,TypeError) as exc:self.status.show_message(str(exc),'error')
    def showEvent(self,event):super().showEvent(event);self.refresh()
