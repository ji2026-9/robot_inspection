"""Offline point-pair calibration, independent checks, explicit activation."""
import csv,json,uuid
from datetime import datetime
from pathlib import Path
import numpy as np
from PySide6.QtWidgets import QDialog,QVBoxLayout,QLabel,QPushButton,QFileDialog,QMessageBox,QDoubleSpinBox,QCheckBox
from .robot_coordinates import BASE,CALIBRATION,fit_mapping,transform

class CoordinateCalibrationDialog(QDialog):
    def __init__(self,parent=None):
        super().__init__(parent);self.setWindowTitle('固定相机 → 测量机械臂 B 基座标定');self.resize(760,550);self.candidate=None
        layout=QVBoxLayout(self)
        note=QLabel('同一个参考点：相机记录彩色相机坐标XYZ，针尖记录B基座坐标XYZ（User 0、正确标定的Tool 1）。单位均为mm。至少6个标定点和3个独立验证点；分布覆盖测量区域。孔心不能与工件表面接触点混用。此窗口不会移动机械臂。');note.setWordWrap(True);layout.addWidget(note)
        template=QPushButton('保存空白对应点表格');template.clicked.connect(self.template);layout.addWidget(template)
        layout.addWidget(QLabel('允许的独立验证最大误差（mm；这是验收门槛，不是精度保证）'))
        self.limit=QDoubleSpinBox();self.limit.setRange(.1,20);self.limit.setValue(2);self.limit.valueChanged.connect(self.reset);layout.addWidget(self.limit)
        load=QPushButton('导入对应点 CSV 并计算');load.clicked.connect(self.calculate);layout.addWidget(load)
        self.status=QLabel('尚未计算。现有标定：'+('已保存，需确认相机和机械臂未移动' if CALIBRATION.exists() else '无'));self.status.setWordWrap(True);layout.addWidget(self.status)
        self.confirm=QCheckBox('我确认相机固定、B基座未移动，针尖TCP正确；验证点与标定点独立，且坐标属于同一参考点。');layout.addWidget(self.confirm)
        self.save=QPushButton('保存并启用坐标显示（不发送运动）');self.save.setEnabled(False);self.save.clicked.connect(self.activate);layout.addWidget(self.save)
        disable=QPushButton('停用现有标定');disable.clicked.connect(self.disable);layout.addWidget(disable)
        close=QPushButton('关闭');close.clicked.connect(self.close);layout.addWidget(close)
    def reset(self):self.candidate=None;self.save.setEnabled(False);self.status.setText('验收门槛已改变，请重新计算。')
    def template(self):
        file,_=QFileDialog.getSaveFileName(self,'保存空白点表','相机机械臂对应点.csv','CSV (*.csv)')
        if file:
            try:
                with open(file,'w',encoding='utf-8-sig',newline='') as stream:csv.writer(stream).writerow(['point_id','role','camera_x','camera_y','camera_z','robot_x','robot_y','robot_z'])
                QMessageBox.information(self,'表格说明','role填写fit（至少6点）或check（至少3点）。其余坐标填写实测毫米值，不要填写示例值。')
            except OSError as e:QMessageBox.warning(self,'保存失败',str(e))
    def calculate(self):
        file,_=QFileDialog.getOpenFileName(self,'导入实际对应点','','CSV (*.csv)')
        if not file:return
        self.candidate=None;self.save.setEnabled(False)
        try:
            with open(file,encoding='utf-8-sig',newline='') as stream:rows=list(csv.DictReader(stream))
            ids=[row['point_id'].strip() for row in rows]
            if any(not v for v in ids) or len(set(ids))!=len(ids):raise ValueError('参考点编号必须唯一且不为空')
            if any(row['role'] not in ('fit','check') for row in rows):raise ValueError('role必须为fit或check')
            camera=np.array([[float(row['camera_'+axis]) for axis in 'xyz'] for row in rows]);robot=np.array([[float(row['robot_'+axis]) for axis in 'xyz'] for row in rows])
            if not np.isfinite(camera).all() or not np.isfinite(robot).all():raise ValueError('坐标含无效数字')
            fit=np.array([row['role']=='fit' for row in rows]);check=~fit
            if fit.sum()<6:raise ValueError('至少需要6个标定点')
            if check.sum()<3:raise ValueError('至少需要3个独立验证点')
            # Duplicate positions cannot be called independent validation.
            for sample in camera[check]:
                if np.linalg.norm(camera[fit]-sample,axis=1).min()<1:raise ValueError('验证点与标定点重复或过近')
            matrix=fit_mapping(camera[fit],robot[fit]);errors=np.linalg.norm(transform(matrix,camera)-robot,axis=1)
            maximum=float(errors[check].max());rmse=float(np.sqrt(np.mean(errors[check]**2)))
            if max(maximum,float(errors[fit].max()))>self.limit.value():raise ValueError(f'误差未通过：标定最大{errors[fit].max():.3f}mm；验证最大{maximum:.3f}mm')
            settings=json.loads((BASE/'inspection_gui/device_settings.json').read_text(encoding='utf-8'))['devices'];serial=settings['camera']['serial_number'];address=settings['robot_b']['address']
            if not serial or not address:raise ValueError('请先保存相机序列号和机械臂B地址')
            self.candidate=dict(id=str(uuid.uuid4()),created_at=datetime.now().astimezone().isoformat(),source_frame='color_camera',target_frame='robot_b_base_user0',units='mm',matrix=matrix.tolist(),camera_serial=serial,robot_address=address,tool_index_used=1,user_index_used=0,validation_count=int(check.sum()),validation_max_mm=maximum,validation_rmse_mm=rmse,fit_max_mm=float(errors[fit].max()),accepted_error_mm=self.limit.value(),points=rows,approved=True)
            self.status.setText(f'计算通过：{fit.sum()}标定点，{check.sum()}独立验证点；标定最大误差{errors[fit].max():.3f}mm；验证最大误差{maximum:.3f}mm，RMSE {rmse:.3f}mm。该误差仅代表这些参考点，请确认后启用。');self.save.setEnabled(True)
        except (OSError,ValueError,KeyError,TypeError,np.linalg.LinAlgError) as e:self.status.setText('未启用：'+str(e))
    def activate(self):
        if not self.candidate or not self.confirm.isChecked():QMessageBox.warning(self,'请确认实测条件','请先勾选实测条件确认。');return
        try:
            CALIBRATION.parent.mkdir(parents=True,exist_ok=True)
            if CALIBRATION.exists():CALIBRATION.with_name('backup_'+uuid.uuid4().hex+'.json').write_bytes(CALIBRATION.read_bytes())
            temp=CALIBRATION.with_suffix('.tmp');temp.write_text(json.dumps(self.candidate,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(CALIBRATION)
            self.status.setText('已启用。对新拍摄照片重新检测后显示B基座XYZ；旧结果保留原标定版本，不自动改写。');self.save.setEnabled(False)
        except OSError as e:QMessageBox.warning(self,'保存失败',str(e))
    def disable(self):
        try:
            if CALIBRATION.exists():
                data=json.loads(CALIBRATION.read_text(encoding='utf-8'));data['approved']=False
                temp=CALIBRATION.with_suffix('.tmp');temp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(CALIBRATION)
            self.status.setText('标定已停用；请重新检测，不使用已有结果控制机械臂。');self.candidate=None;self.save.setEnabled(False)
        except (OSError,ValueError) as e:QMessageBox.warning(self,'停用失败',str(e))
