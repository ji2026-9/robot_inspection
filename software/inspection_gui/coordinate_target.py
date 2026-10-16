"""Coordinate-target preview and fail-closed execution checks. No device APIs."""
import copy,hashlib,json,math,time,uuid
from datetime import datetime
import numpy as np
from scipy.spatial.transform import Rotation
from .probe_workspace import vector6,cartesian_frames
from .joint_preview import compile_joint_preview,tcp_matrix
from .readonly_kinematics import pose_matrix
from .safety_wall import validate_wall
from .wall_collision import check_path

def wall_fingerprint(wall):
    return hashlib.sha256(json.dumps(validate_wall(wall),sort_keys=True).encode()).hexdigest()

def validate_start(frame,now=None):
    now=time.monotonic() if now is None else now
    if not isinstance(frame,dict) or not 0<=now-frame.get('received_monotonic',float('-inf'))<=.2:
        raise ValueError('需要不超过200 ms的新鲜只读反馈')
    for key in ('pose','joints','tool_offset','user_offset'):vector6(frame.get(key),key)
    if type(frame.get('user_index')) is not int or frame['user_index']!=0:raise ValueError('目标坐标必须使用测量臂底座坐标：用户0')
    if frame.get('mode') not in (4,5) or frame.get('running') or frame.get('error'):
        raise ValueError('请先保持机械臂静止且无报警；预演无需上使能')
    if type(frame.get('tool_index')) is not int:raise ValueError('工具编号无效')
    if type(frame.get('digital_inputs')) is not int or frame['digital_inputs']&1:
        raise ValueError('测针状态未知或已触发，请先释放测针')
    return frame

def build_target_preview(frame,target_pose,wall,tool_radius_mm,meshes,*,generation=0,now=None,cancelled=None):
    frame=copy.deepcopy(validate_start(frame,now));target=vector6(target_pose,'目标位姿')
    wall=validate_wall(wall)
    if not wall['direction_confirmed']:raise ValueError('安全墙方向未确认，请先设置安全墙')
    if type(tool_radius_mm) not in (float,int) or not math.isfinite(tool_radius_mm) or tool_radius_mm<=0:
        raise ValueError('必须填写并确认能够覆盖全部测针工具的包络半径')
    distance=math.dist(frame['pose'][:3],target[:3])
    if distance>2000 or max(abs(x) for x in target[:3])>2500:raise ValueError('目标超出本预演支持范围')
    rotations=Rotation.from_euler('xyz',[frame['pose'][3:],target[3:]],degrees=True)
    angle=float(np.rad2deg((rotations[0].inv()*rotations[1]).magnitude()))
    samples=max(2,int(math.ceil(distance/4)),int(math.ceil(angle/2)))
    if samples>250:raise ValueError('目标过远或转角过大，请分段设置目标')
    task=dict(schema_version=1,task_id=uuid.uuid4().hex,coordinate_frame='robot_b_base',user_index=0,
              tool_index=frame['tool_index'],preview_only=True,hardware_executable=False,
              waypoints=[dict(stage='起点',tcp_pose=frame['pose']),dict(stage='目标点',tcp_pose=target)])
    frames,ik=compile_joint_preview(cartesian_frames(task,samples=samples),frame['tool_offset'],frame['joints'],cancelled=cancelled)
    if ik.get('cancelled'):raise InterruptedError('目标已变化，预演取消')
    ik['tool_offset']=frame['tool_offset'];task['joint_preview_report']=ik;task['preview_tool_offset']=frame['tool_offset']
    start_q=np.deg2rad(frame['joints'])
    points=[start_q]+[f['joints'] for f in frames]
    if len(points)==1:points.append(start_q.copy())
    collision=check_path(meshes,points,wall,frame['tool_offset'],float(tool_radius_mm),cancelled=cancelled)
    tool=pose_matrix(frame['tool_offset']);model_start=tcp_matrix(start_q,tool)
    measured=pose_matrix(frame['pose'])
    model_error_mm=float(np.linalg.norm(model_start[:3,3]-measured[:3,3]))
    model_error_deg=float(np.rad2deg(Rotation.from_matrix(model_start[:3,:3]@measured[:3,:3].T).magnitude()))
    problems=[]
    if not ik.get('complete'):problems.append('没有完整连续逆解：'+str((ik.get('failure') or {}).get('reason','未知原因')))
    if collision['collision']:problems.append('路径进入安全墙禁区：'+','.join(sorted({p['part'] for p in collision['parts'] if p['collision']})))
    return dict(id=task['task_id'],created_at=datetime.now().astimezone().isoformat(),start=frame,
                generation=generation,target_pose=target,wall=wall,wall_fingerprint=wall_fingerprint(wall),
                tool_radius_mm=float(tool_radius_mm),task=task,frames=frames,collision=collision,problems=problems,
                preview_complete=bool(ik.get('complete')),sampled_path_clear=bool(ik.get('complete') and not collision['collision']),
                start_model_error_mm=model_error_mm,start_model_error_deg=model_error_deg,
                hardware_executable=False,execution_blockers=['显示几何和测针TCP未完成实物验证',
                    '碰撞检查仅为采样，未证明连续路径无碰撞','控制器实际插补轨迹与预演的一致性未验证'])

def validate_context(plan,frame,wall,generation,now=None):
    validate_start(frame,now)
    if generation!=plan['generation']:raise ValueError('机械臂连接已变化，必须重新预演')
    old=plan['start']
    for key in ('user_index','tool_index','user_offset','tool_offset'):
        if frame[key]!=old[key]:raise ValueError('工具或坐标系已变化，必须重新预演')
    if np.max(np.abs(np.asarray(frame['joints'])-old['joints']))>.1 or math.dist(frame['pose'][:3],old['pose'][:3])>.1:
        raise ValueError('实际起点已变化，必须重新预演')
    orientation_delta=(np.asarray(frame['pose'][3:])-old['pose'][3:]+180)%360-180
    if np.max(np.abs(orientation_delta))>.1:raise ValueError('实际工具姿态已变化，必须重新预演')
    if wall_fingerprint(wall)!=plan['wall_fingerprint']:raise ValueError('安全墙已变化，必须重新预演')
    if plan.get('problems'):raise ValueError('预演检查不通过，禁止运动：'+'；'.join(plan['problems']))
    return True

EXECUTION_MIN_CLEARANCE_MM = 15.0


def request_execution(plan,frame,wall,generation,now=None):
    """Validate context and sampled clearance; never sends motion itself.

    The approval is only a software gate. Actual motion still requires the
    operator to unlock the manual-control channel (human confirmation) and the
    manual control's own runtime monitors (DI_1 stop, deviation, timeout).
    Saved ``hardware_executable`` / ``execution_blockers`` fields are ignored:
    editing an exported report cannot authorise movement.
    """
    validate_context(plan,frame,wall,generation,now)
    clearance = float(plan.get('collision', {}).get('minimum_clearance_mm', -float('inf')))
    if not math.isfinite(clearance):
        raise ValueError('碰撞检查结果无效，禁止运动')
    if clearance < EXECUTION_MIN_CLEARANCE_MM:
        raise ValueError(
            f'采样最小间隙 {clearance:.1f} mm 低于执行门槛 {EXECUTION_MIN_CLEARANCE_MM:.0f} mm；'
            '提前报错，禁止运动')
    return dict(approved=True, target_pose=plan['target_pose'],
                tool_index=plan['task']['tool_index'], minimum_clearance_mm=clearance,
                required_margin_mm=EXECUTION_MIN_CLEARANCE_MM, sampled_only=True,
                hardware_executable=False)
