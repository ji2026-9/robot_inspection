"""Software wall gate for all manual motion modes. No hardware safety claims."""
import copy,math,threading,time
from pathlib import Path
import numpy as np
from .wall_collision import load_collision_meshes,check_pose,check_path
from .joint_preview import compile_joint_preview,tcp_matrix
from .readonly_kinematics import pose_matrix
from .probe_workspace import cartesian_frames
from concurrent.futures import ThreadPoolExecutor
_pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='global-wall-model')
_model_lock=threading.Lock()
_models={}

class WallGuard:
    def __init__(self,service,mesh_path=None):
        self.service=service;self.meshes=None;self.error='碰撞模型加载中';self.monitor_stamp=None;self.monitor_result=None
        path=mesh_path or Path(__file__).parent/'assets/local_dobot_cr5.npz'
        path=Path(path).resolve()
        try:stamp=path.stat().st_mtime_ns
        except OSError:stamp=None
        with _model_lock:
            key=(str(path),stamp)
            if key not in _models:_models[key]=_pool.submit(load_collision_meshes,path)
            self.model_future=_models[key]
    def ready(self):
        reason=self.service.reason()
        if reason:raise ValueError(reason)
        if self.meshes is None and self.model_future.done():
            try:self.meshes=self.model_future.result();self.error=''
            except Exception as exc:self.error='碰撞模型不可用：'+str(exc)
        if self.meshes is None:raise ValueError(self.error)
        return self.service.snapshot(),self.service.revision
    def model_uncertainty(self,frame):
        model=tcp_matrix(np.deg2rad(frame['joints']),pose_matrix(frame['tool_offset']))
        gap=float(np.linalg.norm(model[:3,3]-np.asarray(frame['pose'][:3])))
        if not math.isfinite(gap) or gap>20:raise ValueError('显示模型与反馈TCP偏差超过20 mm，不能用于安全墙检查')
        return gap
    def pose_check(self,frame,wall):
        gap=self.model_uncertainty(frame)
        return check_pose(self.meshes,np.deg2rad(frame['joints']),wall,frame['tool_offset'],wall['tool_radius_mm']+gap,frame['pose'])
    def monitor(self,frame):
        wall,revision=self.ready();stamp=(revision,frame.get('received_monotonic'))
        if stamp==self.monitor_stamp:
            if self.monitor_result['minimum_clearance_mm']<=wall['stop_reserve_mm']:raise ValueError('安全墙：姿态进入停止预留区')
            return self.monitor_result
        result=self.pose_check(frame,wall)
        # A short prediction supplements (does not certify) the stopping reserve.
        velocities=frame.get('joint_speeds')
        if velocities is not None:
            v=np.asarray(velocities,float)
            if v.shape!=(6,) or not np.isfinite(v).all():raise ValueError('安全墙预测所需关节速度无效')
            if np.max(np.abs(v))>1e-6:
                radius=wall['tool_radius_mm']+self.model_uncertainty(frame)
                for seconds in (.1,.2,.3):
                    predicted=np.asarray(frame['joints'])+v*seconds
                    future=check_pose(self.meshes,np.deg2rad(predicted),wall,frame['tool_offset'],radius)
                    if future['minimum_clearance_mm']<result['minimum_clearance_mm']:result=future
        self.monitor_stamp=stamp;self.monitor_result=result
        clearance=result['minimum_clearance_mm']
        notice=f'当前或预测姿态进入停止预留区（模型间隙{clearance:.1f} mm）' if clearance<=wall['stop_reserve_mm'] else ''
        self.service.report_check(clearance,notice)
        if result['minimum_clearance_mm']<=wall['stop_reserve_mm']:
            raise ValueError(f"安全墙：当前或预测姿态进入停止预留区（模型间隙{result['minimum_clearance_mm']:.1f} mm）")
        return result
    def check_request(self,frame,plan,cancelled):
        wall,revision=self.ready()
        def cancel():return cancelled() or revision!=self.service.revision
        self.monitor(frame)
        if plan.get('kind')=='jog':
            # Native jogging has no fixed endpoint: check a speed-scaled lookahead
            # and continue checking every feedback packet while the button is held.
            target=frame['pose'][:];axis=('X','Y','Z').index(plan['axis'])
            target[axis]+=plan['sign']*wall['stop_reserve_mm']
        else:target=plan['target'][:]
        distance=math.dist(frame['pose'][:3],target[:3])
        poses=[frame['pose'],target]+plan.get('route_tail',[])
        samples=[]
        for index,(a,b) in enumerate(zip(poses,poses[1:])):
            task=dict(coordinate_frame='robot_b_base',user_index=0,waypoints=[dict(stage='起点',tcp_pose=a),dict(stage=f'目标 {index+1}',tcp_pose=b)])
            segment=cartesian_frames(task,samples=max(2,math.ceil(math.dist(a[:3],b[:3])/3)))
            samples.extend(segment if not samples else segment[1:])
        frames,report=compile_joint_preview(samples,frame['tool_offset'],frame['joints'],cancelled=cancel)
        if cancel():raise InterruptedError('安全墙检查已取消')
        if not report.get('complete') or not frames:raise ValueError('安全墙：无法核验完整关节路径，拒绝发送运动')
        radius=wall['tool_radius_mm']+self.model_uncertainty(frame)
        result=check_path(self.meshes,[np.deg2rad(frame['joints'])]+[f['joints'] for f in frames],wall,frame['tool_offset'],radius,step_deg=1.,cancelled=cancel)
        if result['minimum_clearance_mm']<=wall['stop_reserve_mm']:raise ValueError('安全墙：路径进入墙面或停止预留区，拒绝发送运动')
        if cancel():raise InterruptedError('安全墙配置变化或停止请求，已取消原目标')
        return revision
