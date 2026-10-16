"""Simulated vision -> B-base Cartesian preview. No device/control dependencies."""
import copy, json, math, re, uuid
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
from .probe_workspace import vector6, index, title

FRAMES=('camera','robot_a_base')
MAX_HOLES=12
PREVIEW_RADIUS_MM=1500.  # Numerical preview guard, NOT a reachability certificate.
DEMO_START=[-280.,-100.,800.,180.,0.,0.]

def load_json(path):
    path=Path(path)
    if path.stat().st_size>1024*1024:raise ValueError('文件过大，最大 1 MB')
    return json.loads(path.read_text(encoding='utf-8-sig'))

def vector3(value,label):
    if not isinstance(value,(list,tuple)) or len(value)!=3:raise ValueError(label+'须包含三个数值')
    if any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) for x in value):raise ValueError(label+'须为有限数值')
    return np.asarray(value,dtype=float)

def validate_input(data):
    if not isinstance(data,dict) or type(data.get('schema_version')) is not int or data['schema_version']!=1:raise ValueError('视觉数据格式不兼容')
    if data.get('source')!='simulated_vision':raise ValueError('此入口只接受标记为 simulated_vision 的模拟数据')
    if data.get('units')!={'position':'mm','angle':'deg'}:raise ValueError('视觉数据单位必须明确为 mm / deg')
    if data.get('coordinate_frame') not in FRAMES:raise ValueError('须明确坐标来源：camera 或 robot_a_base')
    holes=data.get('holes')
    if not isinstance(holes,list) or not 1<=len(holes)<=MAX_HOLES:raise ValueError(f'模拟任务须包含 1–{MAX_HOLES} 个孔')
    normalized=[];seen=set()
    for hole in holes:
        if not isinstance(hole,dict):raise ValueError('孔数据格式无效')
        identifier=hole.get('id')
        if not isinstance(identifier,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,32}',identifier):raise ValueError('孔号须为 1–32 位字母、数字、下划线或短横线')
        if identifier.casefold() in seen:raise ValueError('孔号重复：'+identifier)
        seen.add(identifier.casefold())
        point=vector3(hole.get('position_mm'),identifier+' 坐标')
        if np.max(np.abs(point))>10000:raise ValueError(identifier+' 坐标超出模拟输入范围')
        direction=vector3(hole.get('approach_direction'),identifier+' 接近方向')
        length=np.linalg.norm(direction)
        if not .999<=length<=1.001:raise ValueError(identifier+' 接近方向须为单位向量，不能为零')
        normalized.append({'id':identifier,'position_mm':point.tolist(),'approach_direction':(direction/length).tolist()})
    return {'schema_version':1,'source':'simulated_vision','coordinate_frame':data['coordinate_frame'],
            'units':{'position':'mm','angle':'deg'},'holes':normalized}

def validate_transform(data,source_frame):
    if not isinstance(data,dict):raise ValueError('缺少坐标转换参数；当前没有真实标定，请载入明确标注的模拟转换')
    if type(data.get('schema_version')) is not int or data['schema_version']!=1:raise ValueError('坐标转换格式不兼容')
    if data.get('kind')!='simulation' or data.get('calibration_verified') is not False:raise ValueError('本入口只接受明确未标定的 simulation 转换')
    if data.get('source_frame')!=source_frame or data.get('target_frame')!='robot_b_base':raise ValueError('转换方向必须与输入坐标一致，并指向 robot_b_base')
    if data.get('units')!={'position':'mm','angle':'deg'}:raise ValueError('转换单位必须为 mm / deg')
    values=data.get('matrix')
    if not isinstance(values,list) or len(values)!=4 or any(not isinstance(row,list) or len(row)!=4 for row in values):raise ValueError('转换矩阵须为 4×4')
    if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for row in values for v in row):raise ValueError('转换矩阵须为有限数值')
    matrix=np.asarray(values,dtype=float);rotation=matrix[:3,:3]
    if not np.allclose(matrix[3],[0,0,0,1],atol=1e-8,rtol=0):raise ValueError('转换矩阵最后一行须为 [0,0,0,1]')
    if not np.allclose(rotation.T@rotation,np.eye(3),atol=1e-6,rtol=0) or abs(np.linalg.det(rotation)-1)>1e-6:raise ValueError('转换矩阵旋转部分无效，不能含缩放或镜像')
    if np.linalg.norm(matrix[:3,3])>10000:raise ValueError('模拟转换平移量超出范围')
    return matrix

def orientation_from_direction(direction):
    z=np.asarray(direction,dtype=float)
    helper=np.array([1.,0,0]) if abs(z[0])<.9 else np.array([0.,1,0])
    x=helper-z*np.dot(helper,z);x/=np.linalg.norm(x);y=np.cross(z,x)
    return Rotation.from_matrix(np.column_stack([x,y,z])).as_euler('xyz',degrees=True).tolist()

def check_preview_point(point,label):
    if np.linalg.norm(point)>PREVIEW_RADIUS_MM:raise ValueError(label+' 超出 1500 mm 预览范围；此筛选不代表机械臂可达性')

def build_preview(data,transform,start_pose=DEMO_START,tool_index=0,clearance_mm=50,name='模拟视觉四孔任务',start_source='example'):
    data=validate_input(data);matrix=validate_transform(transform,data['coordinate_frame'])
    start=vector6(start_pose,'预览起点');tool=index(tool_index,'工具');name=title(name)
    if isinstance(clearance_mm,bool) or not isinstance(clearance_mm,(int,float)) or not math.isfinite(clearance_mm) or not 1<=clearance_mm<=500:raise ValueError('接近 / 退回距离须为 1–500 mm')
    check_preview_point(start[:3],'起点')
    points=[{'stage':'模拟 · 起点','tcp_pose':start}];converted=[]
    for hole in data['holes']:
        target=matrix[:3,:3]@np.asarray(hole['position_mm'])+matrix[:3,3]
        direction=matrix[:3,:3]@np.asarray(hole['approach_direction'])
        approach=target-direction*clearance_mm;angles=orientation_from_direction(direction)
        check_preview_point(target,hole['id']+' 目标');check_preview_point(approach,hole['id']+' 接近点')
        converted.append({'id':hole['id'],'position_mm':target.tolist(),'approach_direction':direction.tolist()})
        for stage,point in [('接近候选点',approach),('测量候选点',target),('退回候选点',approach)]:
            points.append({'stage':'模拟 · '+hole['id']+' · '+stage,'hole_id':hole['id'],'tcp_pose':point.tolist()+angles})
    return {'schema_version':1,'task_id':uuid.uuid4().hex,'name':name,'created_at':datetime.now(timezone.utc).isoformat(),
        'coordinate_frame':'robot_b_base','user_index':0,'tool_index':tool,'units':{'position':'mm','angle':'deg'},
        'source':{'type':'simulated_vision','input':data,'start_source':start_source,
                  'transform':{'kind':'simulation','source_frame':data['coordinate_frame'],'target_frame':'robot_b_base','matrix':matrix.tolist(),'calibration_verified':False}},
        'simulation_only':True,'preview_only':True,'hardware_executable':False,'calibration_verified':False,
        'tool_calibration_verified':False,'kinematics_verified':False,'collision_verified':False,
        'clearance_mm':float(clearance_mm),'holes_in_b_base':converted,'waypoints':points,
        'warnings':['坐标转换使用模拟参数，不是真实视觉标定','孔中心暂作为 TCP 候选目标，未补偿实际测球接触位置',
                    '接近方向定义为工具 +Z 指向孔，滚转角为示例约定','孔间连线未验证逆解、可达性、避障或碰撞，不能下发实机']}

def example_data():
    holes=[{'id':f'H{i+1:02}','position_mm':list(point),'approach_direction':[0,0,-1]} for i,point in enumerate(((0,0,0),(40,0,0),(40,35,0),(0,35,0)))]
    matrix=np.eye(4);matrix[:3,:3]=Rotation.from_euler('z',15,degrees=True).as_matrix();matrix[:3,3]=[-300,-100,600]
    return ({'schema_version':1,'source':'simulated_vision','coordinate_frame':'camera','units':{'position':'mm','angle':'deg'},'holes':holes},
            {'schema_version':1,'kind':'simulation','source_frame':'camera','target_frame':'robot_b_base',
             'units':{'position':'mm','angle':'deg'},'calibration_verified':False,'matrix':matrix.tolist()})
