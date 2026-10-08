"""Rigid color-camera to robot-B base mapping; no motion commands."""
from pathlib import Path
import json,hashlib
import numpy as np
BASE=Path(__file__).resolve().parents[1]
CALIBRATION=BASE/'data/calibration/camera_to_robot_b.json'
def fit_mapping(camera,robot):
    a=np.asarray(camera,float);b=np.asarray(robot,float)
    if a.shape!=b.shape or a.ndim!=2 or a.shape[1]!=3 or len(a)<6 or not np.isfinite(a).all() or not np.isfinite(b).all():raise ValueError('至少需要6组有效的三维对应点，单位mm')
    aa=a-a.mean(0);bb=b-b.mean(0)
    for points in (aa,bb):
        singular=np.linalg.svd(points,compute_uv=False)
        if singular[1]<10:raise ValueError('参考点分布过窄或近似共线，请扩大标定范围')
    u,s,vt=np.linalg.svd(aa.T@bb);d=np.eye(3);d[2,2]=np.linalg.det(vt.T@u.T)
    rotation=vt.T@d@u.T;translation=b.mean(0)-rotation@a.mean(0)
    matrix=np.eye(4);matrix[:3,:3]=rotation;matrix[:3,3]=translation
    return matrix

def transform(matrix,points):
    m=np.asarray(matrix,float);p=np.asarray(points,float)
    if m.shape!=(4,4) or not np.isfinite(m).all() or not np.isfinite(p).all() or p.shape[-1]!=3:raise ValueError('转换数据无效')
    if not np.allclose(m[3],[0,0,0,1]) or not np.allclose(m[:3,:3].T@m[:3,:3],np.eye(3),atol=1e-6) or not np.isclose(np.linalg.det(m[:3,:3]),1,atol=1e-6):raise ValueError('必须使用刚体变换，不能缩放或镜像')
    return p@m[:3,:3].T+m[:3,3]

def restore_robot_coordinates(result,estimates):
    mapping={e['id']:e for e in estimates}
    for key in ('holes','detected_holes','fitted_holes'):
        for hole in result.get(key,[]):hole['robot_3d']=mapping.get(hole['id'])
    result['robot_3d']=estimates;result['robot_ready']=False

def add_robot_coordinates(result,capture,path=CALIBRATION):
    estimates=[];note='未完成相机到B基座标定'
    try:
        raw=Path(path).read_bytes();cal=json.loads(raw)
        if cal.get('approved') is not True or cal.get('source_frame')!='color_camera' or cal.get('target_frame')!='robot_b_base_user0' or cal.get('units')!='mm':raise ValueError('坐标标定未启用或坐标系不符')
        serial=capture.get('camera_identity_actual',{}).get('device_serial')
        if not serial or serial!=cal['camera_serial']:raise ValueError('拍摄相机与标定相机不一致')
        settings=json.loads((BASE/'inspection_gui/device_settings.json').read_text(encoding='utf-8'))
        if settings['devices']['robot_b']['address']!=cal['robot_address']:raise ValueError('机械臂地址与标定记录不一致')
        transform(cal['matrix'],[0,0,0])
        if cal['validation_count']<3 or cal['validation_max_mm']>cal['accepted_error_mm']:raise ValueError('独立验证没有通过')
        for item in result.get('camera_3d',[]):
            center=transform(cal['matrix'],item['center_camera_mm']).tolist()
            estimates.append(dict(id=item['id'],center_robot_base_mm=center,coordinate_frame='robot_b_base_user0',units='mm',calibration_id=cal['id'],calibration_sha256=hashlib.sha256(raw).hexdigest(),robot_address=cal['robot_address'],validation_max_mm=cal['validation_max_mm'],robot_ready=False,status='estimate_review_required'))
        note='B基座坐标估计；相机及基座移动后必须停用并重新标定'
    except (OSError,ValueError,TypeError,KeyError) as error:note=str(error) if Path(path).exists() else note
    restore_robot_coordinates(result,estimates);result['robot_coordinate_note']=note
    if result.get('raw_report') is not None:result['raw_report'].update(robot_3d=estimates,robot_coordinate_note=note,robot_ready=False)
