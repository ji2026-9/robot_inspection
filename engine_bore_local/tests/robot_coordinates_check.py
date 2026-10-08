import numpy as np,json,tempfile
from pathlib import Path
from inspection_gui.robot_coordinates import fit_mapping,transform,add_robot_coordinates
from PySide6.QtWidgets import QApplication
from inspection_gui.coordinate_calibration import CoordinateCalibrationDialog
rng=np.random.default_rng(42);points=rng.uniform(-200,200,(12,3));theta=.7
rotation=np.array([[np.cos(theta),-np.sin(theta),0],[np.sin(theta),np.cos(theta),0],[0,0,1]])
robot=points@rotation.T+[100,200,-300];matrix=fit_mapping(points[:8],robot[:8])
assert np.max(np.linalg.norm(transform(matrix,points[8:])-robot[8:],axis=1))<1e-9
try:fit_mapping(np.zeros((6,3)),np.zeros((6,3)))
except ValueError:pass
else:raise AssertionError('degenerate points accepted')
try:transform(np.diag([2,2,2,1]),[0,0,0])
except ValueError:pass
else:raise AssertionError('scale accepted')
from inspection_gui.robot_coordinates import BASE
settings=json.loads((BASE/'inspection_gui/device_settings.json').read_text())['devices']
cal=dict(id='synthetic',approved=True,source_frame='color_camera',target_frame='robot_b_base_user0',units='mm',matrix=matrix.tolist(),camera_serial=settings['camera']['serial_number'],robot_address=settings['robot_b']['address'],validation_count=4,validation_max_mm=.01,accepted_error_mm=2)
capture=dict(camera_identity_actual=dict(device_serial=cal['camera_serial']))
with tempfile.TemporaryDirectory() as folder:
 path=Path(folder)/'mapping.json';path.write_text(json.dumps(cal));hole=dict(id='H01');result=dict(camera_3d=[dict(id='H01',center_camera_mm=points[0].tolist())],holes=[hole],raw_report={})
 add_robot_coordinates(result,capture,path);assert np.allclose(result['robot_3d'][0]['center_robot_base_mm'],robot[0]);assert not result['robot_ready']
 add_robot_coordinates(result,dict(camera_identity_actual=dict(device_serial='wrong')),path);assert not result['robot_3d']
 cal['validation_max_mm']=10;path.write_text(json.dumps(cal));add_robot_coordinates(result,capture,path);assert not result['robot_3d']
 add_robot_coordinates(result,capture,Path(folder)/'missing.json');assert not result['robot_3d']
app=QApplication([]);dialog=CoordinateCalibrationDialog();assert not dialog.save.isEnabled();dialog.close()
print('PASS transform direction/units, independent points, degenerate fit, scale rejection, serial mismatch, failed validation, absent calibration, no motion, dialog')
