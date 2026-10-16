"""Exploratory contact analysis; no robot control or calibration write-back.

With fixed orientation, an unknown constant TCP offset translates the cloud.
The fitted radius combines reference-ball radius and effective stylus radius;
the fitted centre is in the configured TCP feedback coordinates, not a verified
physical ball centre. Fit residuals/repeatability are NOT absolute accuracy.
"""
import copy,json,math,time,uuid
from pathlib import Path
from datetime import datetime,timezone
import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation
from scipy.spatial.distance import pdist
from .probe_workspace import atomic_json,validate_position

ORIENTATION_TOL_DEG=.2
FLAGS=dict(calibration_verified=False,accuracy_verified=False,controller_latched=False,
           hardware_executable=False,tcp_calibrated=False)

ENGRAVED_REFERENCE=dict(diameter_mm=20.0005,source='engraving',
    source_note='用户提供的球杆铭刻照片：Ø20.0005 mm；证书未核验',
    certificate_verified=False,uncertainty_mm=None)


def validate_reference(reference):
    if reference is None:return None
    if not isinstance(reference,dict):raise ValueError('参考球参数格式无效')
    diameter=reference.get('diameter_mm')
    if type(diameter) not in (int,float) or not math.isfinite(diameter) or not 0<diameter<=1000:
        raise ValueError('参考球直径必须为 0–1000 mm 之间的有限正数')
    source=reference.get('source');note=reference.get('source_note')
    if source not in ('engraving','manual') or not isinstance(note,str) or not note.strip() or len(note)>500:
        raise ValueError('参考球尺寸来源无效')
    # This workflow has not verified a calibration certificate or uncertainty.
    return dict(diameter_mm=float(diameter),source=source,source_note=note,
                certificate_verified=False,uncertainty_mm=None)


def load_reference(path):
    path=Path(path)
    if path.exists():
        if path.stat().st_size>16384:raise ValueError('参考球参数文件过大')
        reference=validate_reference(json.loads(path.read_text(encoding='utf-8')))
        if reference is None:raise ValueError('参考球参数为空')
        return reference
    reference=validate_reference(ENGRAVED_REFERENCE);atomic_json(path,reference);return reference


def configuration(record):
    return (record['user_index'],record['tool_index'],tuple(record.get('tool_offset') or []),
            tuple(record.get('user_offset') or []),record.get('controller_address'))


def orientation_difference(a,b):
    ra=Rotation.from_euler('xyz',a['tcp_pose'][3:],degrees=True)
    rb=Rotation.from_euler('xyz',b['tcp_pose'][3:],degrees=True)
    return float(np.rad2deg((ra.inv()*rb).magnitude()))


def analyze_contacts(records,mode='sphere',excluded_ids=(),reference=None):
    reference=validate_reference(reference)
    if mode not in ('sphere','repeat'):raise ValueError('未知分析方式')
    if len(records)>500:raise ValueError('每组最多 500 点')
    selected=[validate_position(r) for r in records if r['id'] not in excluded_ids]
    count=len(selected);minimum=9 if mode=='sphere' else 5
    if count<minimum:raise ValueError(f'需要至少 {minimum} 个有效点，目前 {count} 个')
    if len({r['id'] for r in selected})!=count:raise ValueError('记录编号重复')
    first=selected[0]
    if first['user_index']!=0:raise ValueError('只支持用户坐标 0 的反馈数据')
    if any(configuration(r)!=configuration(first) for r in selected):raise ValueError('不能混合不同控制器、用户坐标或工具配置')
    drift=max(orientation_difference(first,r) for r in selected)
    if drift>ORIENTATION_TOL_DEG:raise ValueError('测头朝向变化超过 0.2°，不能按固定朝向分析')
    points=np.array([r['tcp_pose'][:3] for r in selected],float)
    report=dict(schema_version=1,analysis_mode=mode,sample_count=count,raw_count=len(records),
                excluded_ids=sorted(set(excluded_ids)),source_ids=[r['id'] for r in selected],
                max_orientation_drift_deg=drift,reference_ball_metadata=reference,**FLAGS)
    if mode=='repeat':
        mean=points.mean(axis=0);distances=np.linalg.norm(points-mean,axis=1)
        report.update(mean_configured_tcp_mm=mean.tolist(),axis_std_mm=points.std(axis=0,ddof=1).tolist(),
            rms_spread_mm=float(np.sqrt(np.mean(distances**2))),max_distance_from_mean_mm=float(distances.max()),
            max_pair_distance_mm=float(pdist(points).max()),
            note='仅在确认同一球面位置、同一接近方向和朝向时代表该次实验的重复性；不能据此认定绝对精度。')
        return report
    # Centre the solve for stability at large base-coordinate offsets.
    mean=points.mean(axis=0);local=points-mean
    distinct=[]
    for p in local:
        if not distinct or min(np.linalg.norm(p-q) for q in distinct)>.05:distinct.append(p)
    if len(distinct)<9:raise ValueError('分布位置不足：需至少 9 个相距超过 0.05 mm 的接触位置，不能用原地轻触代替')
    a=np.c_[2*local,np.ones(count)];b=np.sum(local**2,axis=1)
    solution,_,rank,singular=np.linalg.lstsq(a,b,rcond=None)
    if rank<4:raise ValueError('点位共面或退化，不能稳定拟合球面')
    c0=solution[:3];radius0=math.sqrt(max(0,float(solution[3]+c0@c0)))
    if radius0<=0:raise ValueError('球面半径无效')
    fit=least_squares(lambda v:np.linalg.norm(local-v[:3],axis=1)-v[3],np.r_[c0,radius0],
        bounds=([-np.inf]*3+[1e-6],[np.inf]*4),max_nfev=200)
    if not fit.success:raise ValueError('球面拟合未收敛')
    centre=fit.x[:3]+mean;radius=float(fit.x[3]);lengths=np.linalg.norm(points-centre,axis=1)
    if np.min(lengths)<1e-6:raise ValueError('存在落在拟合球心附近的异常点，请检查采点')
    normals=(points-centre)/lengths[:,None]
    jac=np.c_[-normals,-np.ones(count)];s=np.linalg.svd(jac,compute_uv=False)
    condition=float(s[0]/max(s[-1],1e-15))
    if condition>50:raise ValueError('点位覆盖过窄，球心和半径不稳定；需增加不同高度及周向位置')
    residual=np.linalg.norm(points-centre,axis=1)-radius
    rms=float(np.sqrt(np.mean(residual**2)));worst=float(np.max(np.abs(residual)))
    warnings=['组合半径含白球和测针有效半径，未分离；不能作为白球真实直径。',
              '球心基于当前配置的 TCP 反馈，未标定 TCP 时不能当作物理球心。',
              '残差只是模型对采点的贴合程度，不是实际测量精度。']
    if worst>.5 or rms>.2:warnings.append('拟合残差较大：检查接触位置、固定状态、朝向和异常点；未自动删点。')
    report.update(fitted_centre_configured_tcp_mm=centre.tolist(),combined_radius_mm=radius,
        combined_diameter_mm=radius*2,reference_ball_diameter_mm=None,stylus_effective_radius_mm=None,
        rms_radial_residual_mm=rms,max_abs_radial_residual_mm=worst,
        radial_residuals_mm=residual.tolist(),fit_condition=condition,warnings=warnings)
    report.update(estimated_stylus_effective_radius_mm=None,estimated_stylus_effective_diameter_mm=None,
                  estimation_status='reference_unknown')
    if reference is not None:
        reference_radius=reference['diameter_mm']/2
        report.update(reference_ball_diameter_mm=reference['diameter_mm'],reference_ball_radius_mm=reference_radius)
        estimate=radius-reference_radius
        report['warnings'][0]='参考球采用所录铭刻值，证书及尺寸不确定度未核验；测针结果只作初步估算。'
        if estimate<=0:
            report.update(estimation_status='blocked',estimation_reason='组合半径不大于参考球半径，不能得到有效的正测针半径；请检查采点和参考尺寸。')
        elif worst>.5 or rms>.2:
            report.update(estimation_status='blocked',estimation_reason='球面拟合残差较大，暂不输出测针有效半径；请检查采点。')
        else:
            report.update(estimated_stylus_effective_radius_mm=estimate,
                estimated_stylus_effective_diameter_mm=estimate*2,estimation_status='provisional',
                estimation_formula='combined_radius_mm - reference_ball_diameter_mm / 2')
        if report.get('estimation_reason'):report['warnings'].append(report['estimation_reason'])
    return report


class ContactSession:
    def __init__(self,directory,data):self.directory=Path(directory);self.data=data

    @classmethod
    def create(cls,directory,mode,name,baseline_ids,anchor=None,reference=None):
        if mode not in ('sphere','repeat'):raise ValueError('采集方式无效')
        data=dict(schema_version=1,id=uuid.uuid4().hex,name=name[:64],mode=mode,
            started_at=time.time(),status='collecting',baseline_ids=list(baseline_ids),
            records=[],excluded_ids=[],stop_reason='',analysis=None,anchor=copy.deepcopy(anchor),
            reference_ball=validate_reference(reference),**FLAGS)
        session=cls(directory,data);session.commit(data);return session

    @property
    def path(self):return self.directory/(self.data['id']+'.json')

    def commit(self,data):
        atomic_json(self.path,data);self.data=copy.deepcopy(data)

    def stop(self,reason='采集结束'):
        data=copy.deepcopy(self.data);data.update(status='stopped',stop_reason=reason);self.commit(data)

    def append(self,event):
        data=self.data
        if data['status']!='collecting':return False
        if event['id'] in data['baseline_ids'] or event['feedback_received_at']<data['started_at']:return False
        if any(r['id']==event['id'] for r in data['records']):return False
        event=validate_position(event)
        if event.get('event_type')!='probe_trigger':raise ValueError('不是测头触发记录')
        if data['records'] or data.get('anchor'):
            first=data.get('anchor') or data['records'][0]
            if configuration(first)!=configuration(event):self.stop('工具或坐标配置变化，已停止本组');return False
            if orientation_difference(first,event)>ORIENTATION_TOL_DEG:self.stop('测头朝向变化超过 0.2°，已停止本组');return False
        if len(data['records'])>=500:self.stop('已到本组 500 点上限');return False
        new=copy.deepcopy(data);new['records'].append(event);new['analysis']=None;self.commit(new);return True

    def exclude(self,identifier):
        if self.data['status']=='collecting':raise ValueError('先结束本组采集，再标记排除点')
        if not any(r['id']==identifier for r in self.data['records']):raise ValueError('未找到采点')
        new=copy.deepcopy(self.data);excluded=set(new['excluded_ids'])
        if identifier in excluded:excluded.remove(identifier)
        else:excluded.add(identifier)
        new['excluded_ids']=sorted(excluded);new['analysis']=None;self.commit(new)

    def analyze(self):
        if self.data['status']=='collecting':raise ValueError('请先结束本组采集')
        result=analyze_contacts(self.data['records'],self.data['mode'],self.data['excluded_ids'],self.data.get('reference_ball'))
        new=copy.deepcopy(self.data);new['analysis']=result;self.commit(new);return result

    @classmethod
    def load(cls,path):
        path=Path(path)
        if path.stat().st_size>8*1024*1024:raise ValueError('采集文件过大')
        data=json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data,dict):raise ValueError('采集格式必须为对象')
        if data.get('schema_version')!=1 or data.get('mode') not in ('sphere','repeat'):raise ValueError('采集格式无效')
        identifier=data.get('id','')
        if len(identifier)!=32 or any(c not in '0123456789abcdef' for c in identifier):raise ValueError('采集编号无效')
        if len(data.get('records',[]))>500:raise ValueError('采集点数量过多')
        data['records']=[validate_position(r) for r in data['records']]
        if len({r['id'] for r in data['records']})!=len(data['records']):raise ValueError('采集记录重复')
        if not isinstance(data.get('excluded_ids'),list):raise ValueError('排除点格式无效')
        data['reference_ball']=validate_reference(data.get('reference_ball'))
        data.update(FLAGS);data['analysis']=None
        if data['status']=='collecting':data.update(status='stopped',stop_reason='上次采集被中断，恢复为已停止，需新建组继续')
        return cls(path.parent,data)
