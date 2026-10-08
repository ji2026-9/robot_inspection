"""Read the exact archived RGB-D pair; estimate only in camera coordinates."""
import hashlib
from pathlib import Path
import numpy as np
import cv2
from .capture_archive import capture_information
from .rgbd_geometry import color_points,estimate_aperture

def restore_camera_3d(result, estimates):
    by_id={e['id']:e for e in estimates}
    for key in ('holes','detected_holes','fitted_holes'):
        for hole in result.get(key,[]):hole['camera_3d']=by_id.get(hole['id'])
    result['camera_3d']=estimates
    result['robot_ready']=False

def add_camera_3d(result, photo):
    info=capture_information(photo)
    if not info:return
    report=result.get('raw_report')
    if report is None:return
    estimates=[];notes=[]
    try:
        archive=info.get('depth_archive')
        if not archive:raise ValueError(info.get('depth_note') or '这张照片没有对应深度留样')
        if hashlib.sha256(Path(photo).read_bytes()).hexdigest()!=info['image_sha256']:raise ValueError('照片留样校验不一致')
        if Path(archive['file']).name!=archive['file']:raise ValueError('深度留样路径无效')
        depth_path=Path(photo).parent/archive['file']
        if hashlib.sha256(depth_path.read_bytes()).hexdigest()!=archive['sha256']:raise ValueError('深度留样校验不一致')
        delta=info['frame_timestamps']['timestamp_delta_ms']
        if delta is None or not 0<=delta<=50:raise ValueError('彩色与深度时间检查失败')
        with np.load(depth_path,allow_pickle=False) as saved:depth=saved['depth_raw']
        xyz,uv=color_points(depth,archive['scale_mm'],info['camera_calibration'],result['image_size'])
        for hole in result.get('fitted_holes',[]):
            try:estimates.append(estimate_aperture(hole,xyz,uv,info['camera_calibration']))
            except (ValueError,cv2.error,np.linalg.LinAlgError) as error:notes.append(hole['id']+'：'+str(error))
    except (OSError,ValueError,KeyError,TypeError,cv2.error,np.linalg.LinAlgError) as error:
        notes.append(str(error))
    restore_camera_3d(result,estimates)
    result['camera_3d_notes']=notes
    report['camera_3d']=estimates;report['camera_3d_notes']=notes
    report['camera_3d_frame']='color_camera';report['robot_ready']=False

    from .robot_coordinates import add_robot_coordinates
    add_robot_coordinates(result,info)
