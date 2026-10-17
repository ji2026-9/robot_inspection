"""User-defined base-frame return position; never changes controller coordinates."""
import json,math,time
from .coordinate_target import validate_start
from .probe_workspace import atomic_json

def xyz_values(values):
    if not isinstance(values,(list,tuple)) or len(values)!=3 or any(type(v) not in (int,float) or not math.isfinite(v) or abs(v)>2500 for v in values):
        raise ValueError('原点 XYZ 必须是 −2500 至 2500 mm 内的有限数值')
    return list(values)

def context(frame,address):
    return dict(address=str(address or ''),user_index=frame['user_index'],tool_index=frame['tool_index'],
                tool_offset=list(frame['tool_offset']),user_offset=list(frame['user_offset']))

def save_origin(path,xyz,frame,address):
    validate_start(frame)
    if not address:raise ValueError('无法确认反馈机械臂地址，请先连接只读反馈')
    data=dict(schema_version=1,frame='robot_b_base',units='mm',xyz=xyz_values(xyz),context=context(frame,address),saved_at=time.time())
    from .config_history import archive_config
    archive_config(path,'origin');atomic_json(path,data);return data

def load_origin(path):
    if not path.exists():return None
    return validate_origin(json.loads(path.read_text(encoding='utf-8')))

def validate_origin(data):
    if not isinstance(data,dict) or data.get('schema_version')!=1 or data.get('frame')!='robot_b_base' or data.get('units')!='mm':raise ValueError('原点记录格式不正确，请重新设置')
    xyz_values(data.get('xyz'));c=data.get('context')
    if not isinstance(c,dict) or not isinstance(c.get('address'),str) or not c['address'] or type(c.get('user_index')) is not int or c.get('user_index')!=0 or type(c.get('tool_index')) is not int:raise ValueError('原点缺少有效的机械臂及工具配置，请重新设置')
    for key in ('tool_offset','user_offset'):
        a=c.get(key)
        if not isinstance(a,list) or len(a)!=6 or any(type(v) not in (int,float) or not math.isfinite(v) for v in a):raise ValueError('原点工具配置无效，请重新设置')
    return data

def origin_position(data,frame,address):
    validate_start(frame)
    if not data:raise ValueError('请先设置自定义原点')
    if data['context']!=context(frame,address):raise ValueError('机械臂地址、工具或用户坐标配置与保存原点时不同，请核对并重新设置原点')
    return xyz_values(data['xyz'])
