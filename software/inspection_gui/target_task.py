"""Validated portable base-frame target tasks. Loading never authorizes motion."""
import copy,json,math,time
from .probe_workspace import atomic_json
BUILD_ID='2026.10.17-standard-workbench'
def validate_task(data):
    if not isinstance(data,dict) or data.get('schema_version')!=1 or data.get('frame')!='robot_b_base' or data.get('units')!='mm':raise ValueError('任务格式无效：需要基座坐标0、单位mm的版本1任务')
    points=data.get('targets');selected=data.get('selected');speed=data.get('speed')
    if not isinstance(points,list) or not 1<=len(points)<=20:raise ValueError('任务须包含1–20个目标')
    for xyz in points:
        if not isinstance(xyz,list) or len(xyz)!=3 or any(type(v) not in (int,float) or not math.isfinite(v) or abs(v)>2500 for v in xyz):raise ValueError('目标XYZ必须为−2500至2500 mm内的有限数值')
    if not isinstance(selected,list) or len(selected)!=len(points) or any(type(v) is not bool for v in selected):raise ValueError('任务勾选状态无效')
    if type(speed) is not int or speed<1:raise ValueError('任务速度需为正整数mm/s')
    if not isinstance(data.get('metadata',{}),dict):raise ValueError('任务配置快照格式无效')
    result=copy.deepcopy(data);result['motion_authorized']=False;result['hardware_executable']=False
    return result
def save_task(path,points,selected,speed,metadata=None):
    data=validate_task(dict(schema_version=1,frame='robot_b_base',units='mm',targets=points,selected=selected,speed=speed,
        saved_at=time.time(),build_id=BUILD_ID,metadata=metadata or {},motion_authorized=False))
    atomic_json(path,data);return data
def load_task(path):return validate_task(json.loads(path.read_text(encoding='utf-8-sig')))
