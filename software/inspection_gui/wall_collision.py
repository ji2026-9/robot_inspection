"""Offline display-mesh vs infinite wall half-space tests. No robot control.

Static polygon/half-space intersection uses vertex extrema. Path checks use
bounded joint-linear samples, NOT continuous collision detection, controller
interpolation validation, self-collision checks or a hardware motion permit.
"""
import json,math
from pathlib import Path
import numpy as np
from .safety_wall import validate_wall
from .offline_planning import robot_frames
from .readonly_kinematics import pose_matrix


def load_collision_meshes(path):
    from scipy.spatial import ConvexHull,QhullError
    meshes=[]
    with np.load(Path(path),allow_pickle=False) as archive:
        for i,meta in enumerate(json.loads(str(archive['metadata']))):
            joint=meta['joint'];points=np.asarray(archive[f'v{i}'],dtype=float)
            if joint not in ('base','J1','J2','J3','J4','J5','J6') or points.ndim!=2 or points.shape[1]!=3 or not len(points) or not np.isfinite(points).all():
                raise ValueError('三维网格无效，不能检查')
            # Convex-hull vertices preserve every directional support maximum.
            try:points=points[ConvexHull(points).vertices]
            except QhullError:pass
            meshes.append(dict(joint=joint,name=f'{joint} 网格 {i+1}',vertices=points))
    if {m['joint'] for m in meshes}!=set(('base','J1','J2','J3','J4','J5','J6')):
        raise ValueError('显示模型缺少底座或关节网格，拒绝检查')
    return meshes


def finite6(value,label):
    a=np.asarray(value,dtype=float)
    if a.shape!=(6,) or not np.isfinite(a).all():raise ValueError(label+'需要6个有限数值')
    return a


def check_pose(meshes,joints_rad,wall,tool_offset=None,tool_radius_mm=None,actual_tcp=None):
    wall=validate_wall(wall)
    if not wall['direction_confirmed']:raise ValueError('安全墙方向尚未确认')
    q=finite6(joints_rad,'关节角（弧度）');frames=robot_frames(q,(0,0,0))
    angle=math.radians(wall['yaw_deg']);normal=np.array([math.cos(angle),math.sin(angle),0.])
    boundary=wall['distance_mm']-wall['margin_mm'];parts=[]
    if not meshes:raise ValueError('没有三维网格，不能检查')
    for mesh in meshes:
        matrix=frames[mesh['joint']];vertices=np.asarray(mesh['vertices'],float)
        projection=vertices@(matrix[:3,:3].T@normal)+normal@matrix[:3,3]
        if not len(projection) or not np.isfinite(projection).all():raise ValueError('网格坐标无效')
        clearance=float(boundary-np.max(projection))
        parts.append(dict(part=mesh['joint'],mesh=mesh['name'],clearance_mm=clearance,collision=clearance<=0))
    tool_checked=False;tool_segment=None
    if tool_radius_mm is not None:
        if type(tool_radius_mm) not in (int,float) or not math.isfinite(tool_radius_mm) or tool_radius_mm<=0:
            raise ValueError('工具包络半径必须大于0，需按实际工具确定')
        if tool_offset is None:raise ValueError('缺少控制器工具偏移，不能检查测针包络')
        tool=pose_matrix(finite6(tool_offset,'工具偏移').tolist())
        flange=frames['flange'];tcp=flange@tool
        if actual_tcp is not None:
            tcp=pose_matrix(finite6(actual_tcp,'反馈TCP').tolist());flange=tcp@np.linalg.inv(tool)
        clearance=float(boundary-max(normal@flange[:3,3],normal@tcp[:3,3])-tool_radius_mm)
        parts.append(dict(part='tool',mesh='法兰至TCP工具包络',clearance_mm=clearance,collision=clearance<=0))
        tool_checked=True;tool_segment=[flange[:3,3].tolist(),tcp[:3,3].tolist()]
    return dict(kind='pose',collision=any(p['collision'] for p in parts),parts=parts,
                minimum_clearance_mm=min(p['clearance_mm'] for p in parts),joints_rad=q.tolist(),
                tool_checked=tool_checked,tool_segment_mm=tool_segment,model_only=True,hardware_executable=False,
                continuous_verified=False,wall=wall)


def check_path(meshes,path_rad,wall,tool_offset=None,tool_radius_mm=None,step_deg=2.,cancelled=None):
    if not 0<step_deg<=2:raise ValueError('采样角度必须大于0且不超过2度')
    if not 2<=len(path_rad)<=2500:raise ValueError('需要2至2500个关节路径点')
    points=[finite6(q,'路径关节角') for q in path_rad]
    divisions=[max(1,int(math.ceil(np.max(np.abs(b-a))/math.radians(step_deg)))) for a,b in zip(points,points[1:])]
    if sum(divisions)+1>10000:raise ValueError('细分后超过10000个姿态，请缩短路径')
    samples=0;minimum=float('inf');worst=None
    for segment,(a,b,count) in enumerate(zip(points,points[1:],divisions)):
        for index in range(count+1):
            if index==0 and segment:continue
            if cancelled and cancelled():raise InterruptedError('检查已取消')
            q=a+(b-a)*(index/count)
            result=check_pose(meshes,q,wall,tool_offset,tool_radius_mm);samples+=1
            if result['minimum_clearance_mm']<minimum:minimum=result['minimum_clearance_mm'];worst=result
            if result['collision']:
                return dict(result,kind='path',samples=samples,segment=segment,fraction=index/count,
                            step_deg=step_deg,discrete_only=True)
    return dict(worst,kind='path',samples=samples,segment=None,minimum_clearance_mm=minimum,
                step_deg=step_deg,discrete_only=True)
