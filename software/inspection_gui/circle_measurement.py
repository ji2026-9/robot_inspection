"""Vertical bore XY section planning and fitting. No hardware execution API."""
import copy,math,time
import numpy as np
from .target_task import BUILD_ID

def plan_circle(center,diameter,count=8,probe_radius=None):
    if not isinstance(center,(list,tuple)) or len(center)!=3 or any(type(v) not in (int,float) or not math.isfinite(v) or abs(v)>2500 for v in center):raise ValueError('估计中心XYZ无效')
    if type(diameter) not in (int,float) or not math.isfinite(diameter) or not .1<=diameter<=1000:raise ValueError('估计直径需为0.1–1000 mm')
    if type(count) is not int or count not in (4,8,12):raise ValueError('采点数选择4、8或12')
    if probe_radius is not None and (type(probe_radius) not in (int,float) or not math.isfinite(probe_radius) or not 0<probe_radius<diameter/2):raise ValueError('测针半径需为正数且小于估计孔半径')
    radius=diameter/2-(probe_radius or 0);directions=[]
    for i in range(count):
        angle=2*math.pi*i/count;target=[center[0]+radius*math.cos(angle),center[1]+radius*math.sin(angle),center[2]]
        directions.append(dict(index=i+1,angle_deg=360*i/count,nominal_contact=target,stages=['探测','触发记录及停止','核对停止','反向退离并核对释放','返回孔内起点']))
    return dict(schema_version=1,frame='robot_b_base',units='mm',center=list(center),estimated_diameter_mm=diameter,
        count=count,probe_radius_mm=probe_radius,directions=directions,preview_only=True,hardware_executable=False,build_id=BUILD_ID)

def fit_circle(points,probe_radius=None):
    values=np.asarray(points,dtype=float)
    if values.ndim!=2 or values.shape[1]!=3 or not 3<=len(values)<=500 or not np.isfinite(values).all():raise ValueError('需要3–500个有限XYZ坐标')
    if np.ptp(values[:,2])>.25:raise ValueError('采点高度跨度超过0.25 mm；仅支持同一XY截面，请重新采点或先校准测量平面')
    if probe_radius is not None and (type(probe_radius) not in (int,float) or not math.isfinite(probe_radius) or probe_radius<=0):raise ValueError('测针有效半径无效')
    xy=values[:,:2];origin=xy.mean(axis=0);local=xy-origin
    matrix=np.c_[2*local,np.ones(len(local))];rhs=np.sum(local*local,axis=1)
    if np.linalg.matrix_rank(matrix)<3 or np.linalg.cond(matrix)>1e8:raise ValueError('采点共线或分布过于集中，不能可靠拟合圆')
    sol=np.linalg.lstsq(matrix,rhs,rcond=None)[0];center=sol[:2]+origin
    radius2=sol[2]+sum(sol[:2]**2)
    if radius2<=0:raise ValueError('拟合圆半径无效')
    radius=float(math.sqrt(radius2));residual=np.linalg.norm(xy-center,axis=1)-radius
    return dict(center_configured_tcp_mm=[float(center[0]),float(center[1]),float(values[:,2].mean())],
        trajectory_diameter_mm=radius*2,estimated_bore_diameter_mm=2*(radius+probe_radius) if probe_radius is not None else None,
        probe_radius_mm=probe_radius,sample_count=len(values),rms_residual_mm=float(np.sqrt(np.mean(residual**2))),
        max_abs_residual_mm=float(np.max(np.abs(residual))),residuals_mm=residual.tolist(),precision_verified=False,
        warning='当前配置TCP轨迹拟合；测球TCP及有效半径未正式标定验证。拟合残差不等于测量精度。')
