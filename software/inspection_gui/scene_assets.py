"""One shared background load for read-only display geometry per asset file."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import threading,json
import numpy as np

_executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='shared-display-assets')
_lock=threading.Lock()
_futures={}

def load_display_assets(path):
    from .simulation_scene3d import cylinder
    from .offline_planning import solve_visual_ik
    models=[];label='程序化备用模型'
    path=Path(path)
    try:
        if path.is_file():
            with np.load(path,allow_pickle=False) as a:
                for i,meta in enumerate(json.loads(str(a['metadata']))):
                    models.append({'joint':meta['joint'],'color':meta['color'],
                        'vertices':np.ascontiguousarray(a[f'v{i}'],dtype=np.float32),
                        'normals':np.ascontiguousarray(a[f'n{i}'],dtype=np.float32),
                        'faces':np.ascontiguousarray(a[f'f{i}'],dtype=np.uint32)})
            label='本机 DobotStudio CR5 系列显示模型'
    except (OSError,ValueError,KeyError) as exc:
        label='显示资源不可用，使用备用模型：'+str(exc)
    if not models:
        from .offline_planning import JOINT_OFFSETS
        for i,joint in enumerate(['base','J1','J2','J3','J4','J5','J6']):
            body=cylinder(48 if i<2 else 30,65,[.82,.85,.88]);body['joint']=joint;models.append(body)
            if 0<i<6:
                offset=JOINT_OFFSETS[i];length=float(np.linalg.norm(offset));axis=offset/length
                u=np.cross([0,0,1],axis)
                if np.linalg.norm(u)<1e-8:u=np.array([1.,0,0])
                u/=np.linalg.norm(u);v=np.cross(axis,u);r=np.column_stack([u,v,axis])
                link=cylinder(25,length,[.83,.86,.9]);link['vertices']=np.ascontiguousarray(link['vertices']@r.T,dtype=np.float32)
                link['normals']=np.ascontiguousarray(link['normals']@r.T,dtype=np.float32)
                link['joint']=joint;models.append(link)
    q,_=solve_visual_ik([-200,-240,580],[-480,100,0],100)
    for model in models:
        for field in ('vertices','normals','faces'):model[field].setflags(write=False)
    return models,q,label

def display_assets(path):
    path=Path(path).resolve()
    try:
        stat=path.stat();key=(str(path),stat.st_mtime_ns,stat.st_size)
    except OSError:key=(str(path),None,None)
    with _lock:
        if key not in _futures:
            if len(_futures)>=2:
                old=next(iter(_futures));_futures.pop(old)
            _futures[key]=_executor.submit(load_display_assets,path)
        return _futures[key]
