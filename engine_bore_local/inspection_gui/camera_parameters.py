"""Desired camera settings are distinct from verified device readback."""
from pathlib import Path
from datetime import datetime
import json
from PySide6.QtCore import QThread,Signal
from PySide6.QtWidgets import QDialog,QVBoxLayout,QFormLayout,QLabel,QDoubleSpinBox,QComboBox,QPushButton,QMessageBox

class ParameterWorker(QThread):
    completed=Signal(object);failed=Signal(str)
    def __init__(self,backend,desired=None,parent=None):super().__init__(parent);self.backend=backend;self.desired=desired
    def run(self):
        try:
            if not self.backend.is_connected():raise ValueError('相机未连接')
            if self.desired is not None:
                if getattr(self.backend,'_inspection_acquiring',False):raise ValueError('请先停止实时采集，再写入相机参数')
                self.backend._inspection_parameter_busy=True
                answer=self.backend.set_parameters(dict(self.desired))
                if answer is False:raise ValueError('驱动拒绝参数设置')
            result=self.backend.get_parameters()
            if not isinstance(result,dict):raise ValueError('驱动未提供有效的参数读回')
            self.completed.emit(result)
        except Exception as error:self.failed.emit(str(error))
        finally:self.backend._inspection_parameter_busy=False

class CameraParametersDialog(QDialog):
    def __init__(self,backend=None,parent=None):
        super().__init__(parent);self.backend=backend;self.worker=None;self.actual=None
        self.setWindowTitle('工业相机采集参数');self.resize(570,350)
        layout=QVBoxLayout(self);self.status=QLabel('以下是期望设置。尚未读取设备参数，保存不会代表已经生效。');self.status.setWordWrap(True);layout.addWidget(self.status)
        form=QFormLayout();self.exposure=QDoubleSpinBox();self.exposure.setRange(1,10000000);self.exposure.setSuffix(' μs');self.gain=QDoubleSpinBox();self.gain.setRange(0,100);self.gain.setSuffix(' dB')
        self.trigger=QComboBox()
        for title,value in [('连续采集','continuous'),('软件触发','software'),('硬件触发','hardware')]:self.trigger.addItem(title,value)
        form.addRow('期望曝光时间',self.exposure);form.addRow('期望增益',self.gain);form.addRow('期望触发模式',self.trigger);layout.addLayout(form)
        self.readback=QLabel('实际读回：未获取');self.readback.setWordWrap(True);layout.addWidget(self.readback)
        self.save=QPushButton('保存期望配置（不写入相机）');self.save.clicked.connect(self.save_desired);layout.addWidget(self.save)
        self.read=QPushButton('读取实际参数');self.read.clicked.connect(self.read_actual);layout.addWidget(self.read)
        self.apply=QPushButton('写入相机并读回验证');self.apply.clicked.connect(self.apply_actual);layout.addWidget(self.apply)
        caps=getattr(backend,'parameter_capabilities',{}) if backend else {}
        valid=isinstance(caps,dict) and all(k in caps for k in ['exposure_us','gain_db','trigger_modes'])
        if valid:
            self.exposure.setRange(*caps['exposure_us']);self.gain.setRange(*caps['gain_db'])
            for i in range(self.trigger.count()):self.trigger.model().item(i).setEnabled(self.trigger.itemData(i) in caps['trigger_modes'])
        self.apply.setEnabled(bool(valid and callable(getattr(backend,'set_parameters',None)) and callable(getattr(backend,'get_parameters',None))))
        self.read.setEnabled(callable(getattr(backend,'get_parameters',None)))
        self.config_path=Path(__file__).resolve().parents[1]/'data/camera_parameters.json'
        try:
            data=json.loads(self.config_path.read_text(encoding='utf-8')).get('desired',{});self.exposure.setValue(data.get('exposure_us',self.exposure.value()));self.gain.setValue(data.get('gain_db',0));index=self.trigger.findData(data.get('trigger_mode'));self.trigger.setCurrentIndex(max(0,index))
        except (OSError,ValueError):pass
        if not self.apply.isEnabled():self.status.setText('厂家驱动尚未提供参数读写能力及有效范围。可保存期望配置，实际写入暂不可用。')
    def desired(self):return {'exposure_us':self.exposure.value(),'gain_db':self.gain.value(),'trigger_mode':self.trigger.currentData()}
    def save_desired(self):
        try:
            self.config_path.parent.mkdir(parents=True,exist_ok=True)
            data={'saved_at':datetime.now().astimezone().isoformat(),'desired':self.desired(),'actual_readback':self.actual,'applied':False}
            self.config_path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');self.status.setText('期望配置已保存，不代表相机实际参数。')
        except OSError as error:QMessageBox.warning(self,'配置未保存',str(error))
    def read_actual(self):self.run_operation(None)
    def apply_actual(self):self.run_operation(self.desired())
    def run_operation(self,desired):
        if self.worker and self.worker.isRunning():return
        if getattr(self.backend,'_inspection_acquiring',False):QMessageBox.information(self,'先停止采集','请先停止实时采集，再读取或写入相机参数。');return
        self.backend._inspection_parameter_busy=True
        self.worker=ParameterWorker(self.backend,desired,self);self.worker.completed.connect(self.on_readback);self.worker.failed.connect(self.on_error)
        self.apply.setEnabled(False);self.read.setEnabled(False);self.worker.finished.connect(self.restore_controls);self.worker.start()
    def on_readback(self,actual):
        self.actual=actual;self.backend._inspection_parameter_readback={'received_at':datetime.now().astimezone().isoformat(),'values':actual}
        self.readback.setText('实际读回：'+json.dumps(actual,ensure_ascii=False))
        expected = self.worker.desired if self.worker else None
        if expected:
            import math
            try:
                matches = all(k in actual and (math.isclose(float(actual[k]),float(v),rel_tol=1e-4,abs_tol=1e-3) if isinstance(v,(int,float)) else actual[k]==v) for k,v in expected.items())
            except (ValueError,TypeError): matches = False
            self.status.setText('写入后设备读回与期望配置一致。' if matches else '设备读回与期望配置不一致，不能确认参数已按期望生效。')
        else:self.status.setText('已取得设备实际读回参数。')
    def on_error(self,error):self.status.setText('参数操作失败：'+error)
    def restore_controls(self):
        self.read.setEnabled(callable(getattr(self.backend,'get_parameters',None)))
        caps=getattr(self.backend,'parameter_capabilities',{})
        self.apply.setEnabled(all(k in caps for k in ['exposure_us','gain_db','trigger_modes']) and callable(getattr(self.backend,'set_parameters',None)))
    def closeEvent(self,event):
        if self.worker and self.worker.isRunning():event.ignore();self.status.setText('参数操作仍在进行，请等待完成。');return
        event.accept()
