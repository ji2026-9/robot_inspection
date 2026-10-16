"""Unverified wall configuration for display only; no motion authorization."""
import math
from pathlib import Path
import json
from .probe_workspace import atomic_json

DEFAULT_WALL=dict(schema_version=1,frame='robot_b_base',units='mm',direction_confirmed=False,
                  yaw_deg=0.,distance_mm=330.,margin_mm=0.,width_mm=3000.,height_mm=2000.,
                  bottom_mm=0.,visible=False,geometry_verified=False,motion_enforced=False)


def validate_wall(data):
    if not isinstance(data,dict) or data.get('schema_version')!=1 or data.get('frame')!='robot_b_base' or data.get('units')!='mm':
        raise ValueError('安全墙草稿格式或坐标单位不兼容')
    result=dict(DEFAULT_WALL)
    bounds=dict(yaw_deg=(-180,180),distance_mm=(1,10000),margin_mm=(0,1000),
                width_mm=(1,20000),height_mm=(1,10000),bottom_mm=(-2000,10000))
    for key,(low,high) in bounds.items():
        value=data.get(key)
        if type(value) not in (int,float) or not math.isfinite(value) or not low<=value<=high:
            raise ValueError('安全墙参数无效：'+key)
        result[key]=float(value)
    for key in ('visible','direction_confirmed'):
        if type(data.get(key)) is not bool:raise ValueError('安全墙选项无效：'+key)
        result[key]=data[key]
    if result['margin_mm']>=result['distance_mm']:raise ValueError('预留距离必须小于底座中心到玻璃的距离')
    if result['visible'] and not result['direction_confirmed']:raise ValueError('请先选择玻璃相对底座坐标轴的方向')
    # A saved file can never certify geometry or authorize real motion.
    result.update(geometry_verified=False,motion_enforced=False)
    return result


def load_wall(path):
    path=Path(path)
    return validate_wall(json.loads(path.read_text(encoding='utf-8'))) if path.is_file() else dict(DEFAULT_WALL)


def save_wall(path,data):
    result=validate_wall(data);atomic_json(path,result);return result


def wall_vertices(data,boundary=False):
    wall=validate_wall(data)
    angle=math.radians(wall['yaw_deg']);nx,ny=math.cos(angle),math.sin(angle)
    distance=wall['distance_mm']-(wall['margin_mm'] if boundary else 0)
    center=(nx*distance,ny*distance)
    half=wall['width_mm']/2;z=wall['bottom_mm'];top=z+wall['height_mm']
    return [(center[0]-ny*t,center[1]+nx*t,h) for t,h in ((-half,z),(half,z),(half,top),(-half,top))]
