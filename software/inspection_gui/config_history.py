"""Versioned configuration snapshots. No implicit restore or controller writes."""
import hashlib,json,time
from .probe_workspace import atomic_json
from .target_task import BUILD_ID
KINDS={'origin':'manual_origin.json','wall':'safety_wall.json'}
def archive_config(path,kind):
    if kind not in KINDS:raise ValueError('未知配置类型')
    if not path.exists():return None
    raw=path.read_bytes()
    if len(raw)>2_000_000:raise ValueError('配置文件过大，拒绝覆盖；请先检查文件')
    target=path.parent/'config_versions'/kind/(str(time.time_ns())+'.json')
    atomic_json(target,dict(schema_version=1,kind=kind,sha256=hashlib.sha256(raw).hexdigest(),
        content_text=raw.decode('utf-8'),archived_at=time.time(),build_id=BUILD_ID))
    return target

def read_revision(path):
    record=json.loads(path.read_text(encoding='utf-8'))
    if record.get('kind') not in KINDS or not isinstance(record.get('content_text'),str):raise ValueError('配置版本格式无效')
    if hashlib.sha256(record['content_text'].encode('utf-8')).hexdigest()!=record.get('sha256'):raise ValueError('配置版本校验失败，拒绝恢复')
    return record,json.loads(record['content_text'])
