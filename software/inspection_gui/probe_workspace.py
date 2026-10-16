"""Position records and Cartesian previews. No hardware execution API."""
from pathlib import Path
from datetime import datetime, timezone
import copy, json, math, os, time, uuid
import numpy as np
from scipy.spatial.transform import Rotation, Slerp


def vector6(value, name='位姿'):
    if not isinstance(value, (list, tuple)) or len(value) != 6:
        raise ValueError(name+'必须包含六个数值')
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in value):
        raise ValueError(name+'必须为有限数值')
    return [float(v) for v in value]


def index(value, name):
    if type(value) is not int or not 0 <= value <= 255:
        raise ValueError(name+'编号无效')
    return value


def title(value):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 64:
        raise ValueError('名称请填写 1–64 个字符')
    return value.strip()


def atomic_json(path, data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with temporary.open('x',encoding='utf-8') as stream:
            json.dump(data,stream,ensure_ascii=False,indent=2,allow_nan=False)
            stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:
        if temporary.exists():temporary.unlink()


def capture_position(name, frame, metadata=None):
    if not isinstance(frame,dict):raise ValueError('未收到有效反馈，不能记录位置')
    age=(time.monotonic()-frame['received_monotonic']) if 'received_monotonic' in frame else time.time()-frame.get('received_at',0)
    if age<0 or age>2:raise ValueError('反馈已过期，请重新连接后记录')
    return validate_position({'id':uuid.uuid4().hex,'name':title(name),
        'recorded_at':datetime.now(timezone.utc).isoformat(),
        'feedback_received_at':float(frame['received_at']),
        'joints_deg':vector6(frame['joints'],'关节角'),'tcp_pose':vector6(frame['pose']),
        'user_index':index(frame['user_index'],'用户坐标'),'tool_index':index(frame['tool_index'],'工具'),
        'tool_offset':vector6(frame['tool_offset']) if 'tool_offset' in frame else None,
        'user_offset':vector6(frame['user_offset']) if 'user_offset' in frame else None,
        'source':'controller_feedback','units':{'position':'mm','angle':'deg'},
        'controller':copy.deepcopy(metadata or {}),'state':{k:frame.get(k) for k in ('mode','enabled','running','error')},
        'archived':False,'tool_calibration_verified':False,'hardware_executable':False})


def validate_position(record):
    if not isinstance(record,dict):raise ValueError('位置记录格式无效')
    if not isinstance(record.get('id'),str) or not record['id'] or len(record['id'])>64:raise ValueError('位置编号无效')
    if record.get('source')!='controller_feedback':raise ValueError('位置来源必须为控制器反馈')
    if record.get('units')!={'position':'mm','angle':'deg'}:raise ValueError('位置单位必须为 mm / deg')
    timestamp=record.get('recorded_at')
    if not isinstance(timestamp,str) or datetime.fromisoformat(timestamp).tzinfo is None:raise ValueError('记录时间必须带时区')
    received=record.get('feedback_received_at')
    if isinstance(received,bool) or not isinstance(received,(int,float)) or not math.isfinite(received):raise ValueError('采样时间无效')
    if type(record.get('archived',False)) is not bool:raise ValueError('归档状态无效')
    result=copy.deepcopy(record);result['name']=title(record.get('name'))
    result['joints_deg']=vector6(record.get('joints_deg'),'关节角');result['tcp_pose']=vector6(record.get('tcp_pose'))
    for field,label in (('user_index','用户坐标'),('tool_index','工具')):result[field]=index(record.get(field),label)
    for field in ('tool_offset','user_offset'):
        if result.get(field) is not None:result[field]=vector6(result[field],'坐标偏移')
    result['archived']=record.get('archived',False)
    result['tool_calibration_verified']=False;result['hardware_executable']=False
    return result


class PositionLibrary:
    def __init__(self,path):
        self.path=Path(path);self.records=[]
        if self.path.exists():self.records=self.read(self.path)

    @staticmethod
    def read(path):
        p=Path(path)
        if p.stat().st_size>8*1024*1024:raise ValueError('位置库过大，最大 8 MB')
        data=json.loads(p.read_text(encoding='utf-8-sig'))
        if not isinstance(data,dict) or data.get('schema_version')!=1 or not isinstance(data.get('positions'),list):raise ValueError('不兼容的位置库格式')
        if len(data['positions'])>1000:raise ValueError('位置库最多保存 1000 个位置')
        records=[validate_position(r) for r in data['positions']]
        if len({r['id'] for r in records})!=len(records):raise ValueError('位置编号重复')
        return records

    def _commit(self,records):
        if len(records)>1000:raise ValueError('位置库最多保存 1000 个位置')
        atomic_json(self.path,{'schema_version':1,'positions':records})
        self.records=records

    def add(self,record):
        record=validate_position(record)
        if any(r['id']==record['id'] for r in self.records):raise ValueError('位置编号重复')
        self._commit(self.records+[record]);return record

    def change(self,identifier,**changes):
        if set(changes)-{'name','archived'}:raise ValueError('不能修改记录中的原始坐标')
        records=copy.deepcopy(self.records)
        for i,r in enumerate(records):
            if r['id']==identifier:
                r.update(changes);records[i]=validate_position(r);self._commit(records);return
        raise ValueError('找不到该位置记录')

    def export(self,path):atomic_json(path,{'schema_version':1,'positions':self.records})

    def import_file(self,path):
        incoming=self.read(path);records=copy.deepcopy(self.records);known={r['id']:r for r in records};count=0
        for record in incoming:
            if record['id'] in known:
                if known[record['id']]!=record:raise ValueError('同一位置编号存在不同内容，导入已取消')
                continue
            records.append(record);known[record['id']]=record;count+=1
        self._commit(records);return count


def manual_task(start_pose,target_pose,tool_index,clearance_mm=50,name='手动任务',source=None):
    start=np.array(vector6(start_pose),float);target=np.array(vector6(target_pose),float)
    tool=index(tool_index,'工具');name=title(name)
    if isinstance(clearance_mm,bool) or not isinstance(clearance_mm,(int,float)) or not math.isfinite(clearance_mm) or not 0<clearance_mm<=1000:raise ValueError('预览退让距离须在 0–1000 mm 之间')
    axis=Rotation.from_euler('xyz',target[3:],degrees=True).as_matrix()[:,2]
    approach=target.copy();approach[:3]-=axis*clearance_mm
    points=[('起点',start),('孔外候选点',approach),('目标点',target),('退回候选点',approach)]
    return {'schema_version':1,'task_id':uuid.uuid4().hex,'name':name,
        'created_at':datetime.now(timezone.utc).isoformat(),'source':copy.deepcopy(source or {'type':'manual_input'}),
        'coordinate_frame':'robot_b_base','user_index':0,'tool_index':tool,'units':{'position':'mm','angle':'deg'},
        'preview_only':True,'hardware_executable':False,'tool_calibration_verified':False,
        'kinematics_verified':False,'collision_verified':False,'clearance_mm':float(clearance_mm),
        'waypoints':[{'stage':stage,'tcp_pose':p.tolist()} for stage,p in points],
        'warnings':['沿目标工具 +Z 的反方向构造候选接近点，尚未验证测针轴方向',
                    '显示的是 TCP 笛卡尔路径，未计算关节路径、可达性或碰撞','没有视觉定位或工具标定依据，不可用于实机执行']}


def cartesian_frames(task,samples=24):
    if task.get('coordinate_frame')!='robot_b_base' or type(task.get('user_index')) is not int or task['user_index']!=0:raise ValueError('预览只接受 B 基座坐标（用户坐标 0）')
    points=task.get('waypoints',[])
    if not isinstance(points,list) or not 2<=len(points)<=100:raise ValueError('任务须包含 2–100 个路径点')
    frames=[]
    for a,b in zip(points,points[1:]):
        pa=np.array(vector6(a['tcp_pose']));pb=np.array(vector6(b['tcp_pose']))
        if max(np.max(np.abs(pa[:3])),np.max(np.abs(pb[:3])))>100000 or max(np.max(np.abs(pa[3:])),np.max(np.abs(pb[3:])))>3600:
            raise ValueError('任务坐标超过预览支持的数值范围')
        rotations=Rotation.from_euler('xyz',np.stack([pa[3:],pb[3:]]),degrees=True);slerp=Slerp([0,1],rotations)
        for fraction in np.linspace(0,1,samples,endpoint=False):
            point=pa[:3]+fraction*(pb[:3]-pa[:3]);rotation=slerp([fraction])[0].as_matrix()
            frames.append({'tip':point,'rotation':rotation,'stage':b['stage']})
    last=points[-1];pose=vector6(last['tcp_pose'])
    frames.append({'tip':np.array(pose[:3]),'rotation':Rotation.from_euler('xyz',pose[3:],degrees=True).as_matrix(),'stage':'预览完成'})
    return frames
