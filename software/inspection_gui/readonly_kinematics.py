"""Strictly whitelisted PositiveKin queries. No enable/mode/motion commands."""
import ipaddress, math, re, socket, time
import numpy as np
from scipy.spatial.transform import Rotation
from .probe_workspace import vector6,index
from .offline_planning import robot_frames


def positive_command(joints,user,tool):
    joints=vector6(joints,'关节角');index(user,'用户坐标');index(tool,'工具')
    return 'PositiveKin('+','.join(format(q,'.12g') for q in joints)+f',user={user},tool={tool})'


def parse_pose_reply(reply):
    match=re.match(r'^\s*(-?\d+)\s*,\s*\{([^{}]*)\}',reply)
    if not match:raise ValueError('控制器正解响应格式不兼容')
    if int(match[1])!=0:raise ValueError('控制器拒绝正解查询，错误码 '+match[1])
    try:values=[float(v.strip()) for v in match[2].split(',')]
    except ValueError:raise ValueError('控制器返回无效位姿')
    return vector6(values)


def read_positive_kinematics(address,joints,user=0,tool=0):
    # The only transmitted application message is constructed internally above.
    ipaddress.ip_address(address);command=positive_command(joints,user,tool)
    with socket.create_connection((address,29999),timeout=2) as connection:
        connection.settimeout(2);connection.sendall(command.encode('ascii'))
        reply=bytearray();deadline=time.monotonic()+3
        while b';' not in reply:
            if time.monotonic()>deadline:raise TimeoutError('正解查询超时')
            chunk=connection.recv(1024)
            if not chunk:raise ConnectionError('正解查询连接已关闭')
            reply.extend(chunk)
            if len(reply)>8192:raise ValueError('控制器响应过长')
    return parse_pose_reply(reply.decode('ascii'))


def pose_matrix(pose):
    p=vector6(pose);t=np.eye(4);t[:3,:3]=Rotation.from_euler('xyz',p[3:],degrees=True).as_matrix();t[:3,3]=p[:3];return t


def compare_pose(matrix,reference):
    return {'position_mm':float(np.linalg.norm(matrix[:3,3]-reference[:3,3])),
        'orientation_deg':float(np.rad2deg(Rotation.from_matrix(matrix[:3,:3]@reference[:3,:3].T).magnitude()))}


def audit_snapshot(address,frame,query_controller=False):
    if frame is None:raise ValueError('未连接实时反馈')
    if frame['user_index']!=0:raise ValueError('当前用户坐标不是 0，先切回基座坐标反馈再核对')
    joints=vector6(frame['joints'],'关节角');tool=index(frame['tool_index'],'工具')
    tcp=list(frame['pose']);reference='feedback_tool_configuration';query_error=''
    configured=pose_matrix(frame.get('tool_offset', [0,0,0,0,0,0]) if tool==0 else frame['tool_offset'])
    flange_matrix=pose_matrix(tcp)@np.linalg.inv(configured)
    flange=np.r_[flange_matrix[:3,3],Rotation.from_matrix(flange_matrix[:3,:3]).as_euler('xyz',degrees=True)].tolist()
    if query_controller:
        try:
            tcp=read_positive_kinematics(address,joints,0,tool)
            flange=read_positive_kinematics(address,joints,0,0) if tool!=0 else tcp
            reference='controller_positive_kinematics'
        except (OSError,ValueError) as exc:query_error=str(exc)
    tcp_matrix=pose_matrix(tcp);flange_matrix=pose_matrix(flange)
    model_frames=robot_frames(np.deg2rad(joints),(0,0,0))
    visual=model_frames['flange']
    feedback_error=compare_pose(tcp_matrix,pose_matrix(frame['pose']))
    visual_error=compare_pose(visual,flange_matrix)
    return {'schema_version':1,'read_only':True,'sample_received_at':frame['received_at'],
        'joints_deg':joints,'user_index':0,'tool_index':tool,'feedback_tcp':list(frame['pose']),
        'controller_tcp':tcp,'controller_flange':flange,'visual_flange_matrix':visual.tolist(),
        'visual_joint6_matrix':model_frames['J6'].tolist(),
        'joint6_frame_vs_reference':compare_pose(model_frames['J6'],flange_matrix),
        'flange_axis_convention':'DobotStudio TOOL rotation.z = 180deg; no fitted alignment',
        'feedback_vs_controller':feedback_error,'visual_vs_controller':visual_error,
        'configured_flange_to_tcp':(np.linalg.inv(flange_matrix)@tcp_matrix).tolist(),
        'display_chain_matches_sample':visual_error['position_mm']<1 and visual_error['orientation_deg']<.5,
        'feedback_matches_sample':(feedback_error['position_mm']<1 and feedback_error['orientation_deg']<.5) if reference=='controller_positive_kinematics' else None,
        'reference_source':reference,'controller_query_error':query_error,
        'physical_tool_calibration_verified':False,'motion_executed':False,
        'note':'单个姿态核对不能证明完整运动学或测球 TCP 标定有效。'}
