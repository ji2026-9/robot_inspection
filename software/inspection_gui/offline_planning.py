"""Nominal-workpiece simulation. No measured coordinates or robot commands."""
from dataclasses import dataclass, asdict
import math
import numpy as np

@dataclass
class SimulationConfig:
    bore_diameter_mm: float = 100.0
    bore_pitch_mm: float = 115.0
    deck_height_mm: float = 250.0
    block_width_mm: float = 170.0
    block_height_mm: float = 140.0
    approach_mm: float = 65.0
    insertion_mm: float = 35.0
    probe_ball_diameter_mm: float = 6.0
    tool_length_mm: float = 145.0

    def validate(self):
        values=asdict(self)
        if any(not math.isfinite(float(v)) or v<=0 for v in values.values()):
            raise ValueError('模拟尺寸必须为有限的正数')
        if self.bore_pitch_mm<=self.bore_diameter_mm+6: raise ValueError('孔间距必须大于孔径并保留端面材料')
        if self.block_width_mm<=self.bore_diameter_mm+20: raise ValueError('箱体宽度不足')
        if self.insertion_mm>self.block_height_mm-20: raise ValueError('进入深度超过模拟孔的可用深度')
        if self.probe_ball_diameter_mm>=self.bore_diameter_mm: raise ValueError('测球直径必须小于孔径')
        if self.approach_mm<=5: raise ValueError('接近距离必须大于5mm')
        return self

def transform_point(matrix, point):
    t=np.asarray(matrix,dtype=float);p=np.asarray(point,dtype=float)
    if t.shape!=(4,4) or p.shape!=(3,) or not np.isfinite(t).all() or not np.isfinite(p).all():
        raise ValueError('坐标转换输入无效')
    if not np.allclose(t[3],[0,0,0,1]) or not np.allclose(t[:3,:3].T@t[:3,:3],np.eye(3),atol=1e-6) or not np.isclose(np.linalg.det(t[:3,:3]),1,atol=1e-6):
        raise ValueError('需要有效的刚体变换矩阵')
    return (t@np.r_[p,1])[:3].tolist()

def translated(x,y,z):
    t=np.eye(4);t[:3,3]=[x,y,z];return t

def build_plan(result=None, selected_ids=None, config=None):
    cfg=(config or SimulationConfig()).validate()
    all_holes=(result or {}).get('fitted_holes',[])
    reliable={h['id']:h for h in all_holes if h.get('reliable_center')}
    demo=result is None
    demo_ids=[f'H{i:02}' for i in range(1,5)]
    ids=(demo_ids if selected_ids is None else sorted(set(selected_ids)&set(demo_ids))) if demo else sorted(set(selected_ids or [])&set(reliable))
    # Existing detection IDs identify image-order slots only. We do not fabricate
    # a homography/depth value from four collinear centres or claim a calibration.
    slot_ids=sorted({h['id'] for h in all_holes})
    if not demo and slot_ids!=[f'H{i:02}' for i in range(1,5)]:
        ids=[]  # missing holes cannot establish four nominal slot identities
    centres=[[(i-1.5)*cfg.bore_pitch_mm,0.,cfg.deck_height_mm] for i in range(4)]
    world_from_b=translated(480,100,0)
    b_from_world=np.linalg.inv(world_from_b)
    holes=[];waypoints=[{'hole_id':None,'stage':'待机','tip_world_mm':[230.,0.,cfg.deck_height_mm+cfg.approach_mm+130]}]
    for i,hid in enumerate([f'H{i:02}' for i in range(1,5)]):
        c=centres[i]; holes.append({'id':hid,'selected':hid in ids,'center_world_mm':c,
            'center_b_mm':transform_point(b_from_world,c),'axis_world':[0.,0.,-1.],
            'source_center_px':reliable.get(hid,{}).get('center_px')})
        if hid not in ids:continue
        for stage,dz in [('转移',cfg.approach_mm+130),('接近',cfg.approach_mm),('孔口',5.),('进入',-cfg.insertion_mm),('退出',cfg.approach_mm),('抬升',cfg.approach_mm+130)]:
            p=[c[0],c[1],c[2]+dz]
            waypoints.append({'hole_id':hid,'stage':stage,'tip_world_mm':p,'tip_b_mm':transform_point(b_from_world,p)})
    world_from_a=translated(-480,100,0)
    world_from_camera=np.diag([1.,-1.,-1.,1.]);world_from_camera[:3,3]=[0,0,570]
    return {'schema_version':1,'simulation_only':True,'hardware_executable':False,'units':'mm',
        'geometry_source':'nominal approximation from training-photo appearance; dimensions assumed',
        'mapping_method':'nominal_cad_slot_association_not_pixel_reconstruction',
        'input_mode':'example' if demo else 'selected_detection',
        'source_image':(result or {}).get('image_path'),'physical_identity_verified':False,
        'calibration_verified':False,'collision_verified':False,'config':asdict(cfg),
        'world_from_b_base':world_from_b.tolist(),'world_from_a_base':world_from_a.tolist(),
        'world_from_virtual_camera':world_from_camera.tolist(),
        'b_base_from_virtual_camera':(b_from_world@world_from_camera).tolist(),
        'holes':holes,'selected_ids':ids,'waypoints':waypoints,
        'warnings':['几何尺寸、坐标和基座位置均为模拟值','孔号为本次照片顺序，非永久物理身份',
                    '本任务仅用于预览；没有真实标定、碰撞验证或测量结果']}

JOINT_OFFSETS=np.array([[0,147,0],[0,0,147],[0,427,-122],[0,357,116],[0,116,0],[0,0,105]],float)
JOINT_AXES=['y','z','z','z','y','z']
Y_UP_TO_Z_UP=np.array([[1,0,0,0],[0,0,-1,0],[0,1,0,0],[0,0,0,1]],float)
# DobotStudio Pro's RoboticArmLoader.initAxesHelper sets TOOL.rotation.z=180deg.
# Mesh J6 is a display joint frame, not the controller's flange/tool-zero axes.
# This is a frame convention only, not a fitted calibration or a link correction.
DISPLAY_J6_TO_FLANGE=np.diag([-1.,-1.,1.,1.])

def rotation(axis, angle):
    c,s=math.cos(angle),math.sin(angle);r=np.eye(4)
    if axis=='y':r[:3,:3]=[[c,0,s],[0,1,0],[-s,0,c]]
    else:r[:3,:3]=[[c,-s,0],[s,c,0],[0,0,1]]
    return r

def robot_frames(joints, base):
    t=translated(*base)@Y_UP_TO_Z_UP;frames={'base':t.copy()}
    for i,(offset,axis,q) in enumerate(zip(JOINT_OFFSETS,JOINT_AXES,joints)):
        t=t@translated(*offset)@rotation(axis,q);frames[f'J{i+1}']=t.copy()
    frames['flange']=frames['J6']@DISPLAY_J6_TO_FLANGE
    return frames

def solve_visual_ik(target, base, tool_length, seed=None):
    from scipy.optimize import least_squares
    target=np.asarray(target,float)
    def residual(q):
        t=robot_frames(q,base)['J6'];tip=t[:3,3]+t[:3,2]*tool_length
        return np.r_[tip-target,(t[:3,2]-[0,0,-1])*180]
    seeds=[np.asarray(seed,float)] if seed is not None else []
    seeds.extend([np.deg2rad([60,-65,105,50,90,0]),np.deg2rad([-60,65,-105,-50,90,0]),np.deg2rad([0,-90,100,80,90,0])])
    best=None
    lower=np.full(6,-4*np.pi);upper=np.full(6,4*np.pi)
    for q in seeds:
        q=np.clip(q,lower+1e-6,upper-1e-6)
        fit=least_squares(residual,q,bounds=(lower,upper),max_nfev=120,ftol=1e-6,xtol=1e-6,gtol=1e-6)
        cost=float(np.linalg.norm(residual(fit.x)))
        if best is None or cost<best[0]:best=(cost,fit.x)
        if cost<.3:break
    q=best[1]
    if seed is not None:q=q+2*np.pi*np.round((np.asarray(seed)-q)/(2*np.pi))
    return q,best[0]

def compile_trajectory(plan, samples=10, cancelled=None):
    """Cartesian interpolation checked against the display-model IK only."""
    cfg=plan['config'];base=(480,100,0);frames=[];seed=None
    points=plan['waypoints']
    if len(points)<2:return [],[]
    errors=[]
    for a,b in zip(points,points[1:]):
        pa,pb=np.asarray(a['tip_world_mm']),np.asarray(b['tip_world_mm'])
        for u in np.linspace(0,1,samples,endpoint=False):
            if cancelled is not None and cancelled():return [],[]
            tip=pa+(pb-pa)*u;q,err=solve_visual_ik(tip,base,cfg['tool_length_mm'],seed)
            seed=q;errors.append(err);frames.append({'joints':q,'tip':tip,'hole_id':b['hole_id'],'stage':b['stage']})
    if cancelled is not None and cancelled():return [],[]
    last=points[-1];q,err=solve_visual_ik(last['tip_world_mm'],base,cfg['tool_length_mm'],seed)
    errors.append(err);frames.append({'joints':q,'tip':np.array(last['tip_world_mm']),'hole_id':last['hole_id'],'stage':'完成'})
    return frames,errors
