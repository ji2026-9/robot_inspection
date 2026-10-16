"""Model overview: metadata only; never imports or loads inference weights."""
from pathlib import Path
import json,threading
from PySide6.QtCore import Qt,QObject,Signal,QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QLabel,QFrame,
    QPushButton,QPlainTextEdit,QGridLayout,QSizePolicy)


def read_model_overview(base):
    base=Path(base);manifest=base/'active_models.json'
    data=json.loads(manifest.read_text(encoding='utf-8-sig')) if manifest.exists() else {}
    if not isinstance(data,dict):raise ValueError('模型清单格式无效')
    models=[]
    for key,label,default in (('bore','孔检测模型','engine_part_bore_100.pt'),('part','零件定位模型','engine_part_only_fixed.pt')):
        raw=data.get(key) or str(Path('models')/default)
        path=Path(raw)
        if not path.is_absolute():path=base/path
        present=path.is_file()
        size=path.stat().st_size if present else 0
        models.append(dict(key=key,label=label,name=path.name,path=str(path),present=present,size=size))
    return dict(version=str(data.get('version') or '未标记版本'),manifest=manifest.exists(),models=models)


class OverviewSignals(QObject):
    loaded=Signal(int,object,str)


class ModelManagementPage(QWidget):
    def __init__(self,bridge,parent=None,base=None):
        super().__init__(parent);self.bridge=bridge;self.base=Path(base) if base else bridge.base
        self.generation=0;self.loading=False;self.signature=None;self.cards={}
        self.signals=OverviewSignals(self);self.signals.loaded.connect(self.loaded)
        self.setStyleSheet('''QWidget{background:#f4f7fb;color:#263b51;} QLabel{background:transparent;}
            QFrame#card{background:white;border:1px solid #dce5f0;border-radius:12px;}
            QLabel#heading{font-size:20px;font-weight:600;} QLabel#section{font-size:15px;font-weight:600;}
            QLabel#muted{color:#71849a;} QPushButton{background:white;border:1px solid #cad8e8;border-radius:7px;padding:10px 15px;color:#285580;}
            QPushButton:disabled{color:#9caabd;} QPushButton#primary{background:#2463ad;color:white;border:0;}
            QPlainTextEdit{background:white;border:1px solid #dce5f0;border-radius:7px;padding:8px;}''')
        root=QVBoxLayout(self);root.setContentsMargins(22,20,22,20);root.setSpacing(16)
        header=QHBoxLayout();title=QLabel('模型管理');title.setObjectName('heading');header.addWidget(title)
        header.addStretch();self.refresh_button=QPushButton('刷新模型信息');self.refresh_button.clicked.connect(lambda:self.refresh_async(True));header.addWidget(self.refresh_button);root.addLayout(header)
        self.version=QLabel('正在读取本地模型信息…');self.version.setObjectName('muted');root.addWidget(self.version)
        grid=QGridLayout();grid.setSpacing(16)
        for i,(key,label,desc) in enumerate((('bore','孔检测模型','识别箱体上的孔，供圆心拟合与后续测量使用。'),('part','零件定位模型','确定零件范围，辅助排除零件外的误检。'))):
            card=QFrame();card.setObjectName('card');box=QVBoxLayout(card);box.setContentsMargins(20,18,20,18);box.setSpacing(10)
            heading=QLabel(label);heading.setObjectName('section');box.addWidget(heading)
            name=QLabel('读取中…');name.setWordWrap(True);name.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Preferred);name.setStyleSheet('font-size:17px;font-weight:600');box.addWidget(name)
            detail=QLabel(desc);detail.setWordWrap(True);detail.setObjectName('muted');box.addWidget(detail)
            status=QLabel('—');box.addWidget(status)
            path=QLabel('');path.setWordWrap(True);path.setMinimumWidth(0);path.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Preferred);path.setObjectName('muted');path.setTextInteractionFlags(Qt.TextSelectableByMouse);box.addWidget(path)
            self.cards[key]=(name,status,path);grid.addWidget(card,0,i)
        root.addLayout(grid)
        workflow=QFrame();workflow.setObjectName('card');box=QVBoxLayout(workflow);box.setContentsMargins(20,18,20,18);box.setSpacing(12)
        heading=QLabel('更新模型');heading.setObjectName('section');box.addWidget(heading)
        note=QLabel('① 添加照片与标注　 →　 ② 训练候选模型　 →　 ③ 查看验证结果，合格后启用')
        note.setWordWrap(True);box.addWidget(note)
        hint=QLabel('训练数据和验证工具会打开独立窗口；运行期间暂停检测。仅浏览本页不会训练或切换模型。')
        hint.setObjectName('muted');hint.setWordWrap(True);box.addWidget(hint)
        actions=QHBoxLayout();self.dataset_button=QPushButton('添加数据 / 训练');self.dataset_button.setObjectName('primary')
        self.validation_button=QPushButton('查看验证结果');self.folder_button=QPushButton('打开模型文件夹')
        self.folder_button.clicked.connect(lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.base/'models'))))
        actions.addWidget(self.dataset_button);actions.addWidget(self.validation_button);actions.addWidget(self.folder_button);actions.addStretch();box.addLayout(actions)
        self.task_state=QLabel();box.addWidget(self.task_state);root.addWidget(workflow)
        title=QLabel('管理任务日志');title.setObjectName('section');root.addWidget(title)
        self.log=QPlainTextEdit();self.log.setReadOnly(True);self.log.setMaximumBlockCount(150);self.log.setPlaceholderText('启动训练或验证工具后，这里显示任务进度。');root.addWidget(self.log,1)
        bridge.log.connect(self.log.appendPlainText);bridge.busy_changed.connect(self.update_task)
        bridge.model_updated.connect(lambda:self.refresh_async(True));bridge.finished.connect(lambda:self.refresh_async(True))
        self.update_task(bridge.busy)

    def update_task(self,busy):
        self.task_state.setText('● 管理工具运行中 · 请在已打开的工具窗口继续，检测暂时暂停' if busy else '● 空闲 · 可以检测或启动模型更新')

    def refresh_async(self,force=False):
        if self.loading:return
        try:
            stat=(self.base/'active_models.json').stat();signature=(stat.st_mtime_ns,stat.st_size)
        except OSError:signature=None
        if not force and getattr(self,'has_result',False) and signature==self.signature:return
        self.signature=signature;self.loading=True;self.refresh_button.setEnabled(False);self.generation+=1
        generation=self.generation;signals=self.signals;base=self.base
        def work():
            try:data=read_model_overview(base);error=''
            except (OSError,ValueError,TypeError) as exc:data=None;error=str(exc)
            try:signals.loaded.emit(generation,data,error)
            except RuntimeError:pass
        threading.Thread(target=work,daemon=True,name='model-metadata').start()

    def loaded(self,generation,data,error):
        if generation!=self.generation:return
        self.loading=False;self.refresh_button.setEnabled(True);self.has_result=not bool(error)
        if error:self.version.setText('模型信息读取失败：'+error);return
        self.version.setText('当前配置版本：'+data['version']+'　｜　'+('已读取正式模型清单' if data['manifest'] else '使用默认模型配置；尚无版本清单'))
        for model in data['models']:
            name,status,path=self.cards[model['key']];name.setText(model['name']);path.setText(model['path']);path.setToolTip(model['path'])
            status.setText(f"● 文件可用 · {model['size']/1024/1024:.1f} MB" if model['present'] else '● 文件缺失，请检查模型配置')
            status.setStyleSheet('color:#217654' if model['present'] else 'color:#b42318')

    def showEvent(self,event):
        super().showEvent(event);self.refresh_async()
