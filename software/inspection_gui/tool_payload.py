"""保存“工具总质量”这个人工确认值，重启后自动恢复。

这里保存的只是操作者声明的工具总质量，用于本轮控制前的人工核对记录：

* 恢复该值不会解锁运动，也不代表本轮已经确认；
* 不会写入控制器的负载/工具参数；
* 每轮仍需重新勾选现场确认并点击“启用本轮控制”。

文件放在用户数据目录（与 manual_origin.json、safety_wall.json 同级），
默认不进 Git；读取失败或数值无效时按“未保存”处理，不阻止界面启动。
"""
from __future__ import annotations

import json
import math
import os
import tempfile
import time
from pathlib import Path

FILE_NAME = 'tool_payload.json'
MAX_MASS_KG = 5.0
SCHEMA_VERSION = 1


def _valid(value) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and 0 < value <= MAX_MASS_KG)


def load_payload(path) -> dict | None:
    """返回 {'mass_kg': float, 'updated_at': str}；无记录或损坏时返回 None。"""
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    mass = data.get('declared_tool_mass_kg')
    if not _valid(mass):
        return None
    return {'mass_kg': float(mass), 'updated_at': str(data.get('updated_at') or '')}


def save_payload(path, mass_kg) -> dict:
    """原子写入声明的工具总质量；无效数值抛 ValueError。"""
    if not _valid(mass_kg):
        raise ValueError(f'工具总质量需为 0–{MAX_MASS_KG:g} kg 内的有限数值')
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        'schema_version': SCHEMA_VERSION,
        'declared_tool_mass_kg': round(float(mass_kg), 3),
        'updated_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
    }
    handle, temporary = tempfile.mkstemp(dir=str(path.parent), prefix='.tool_payload-', suffix='.tmp')
    try:
        with os.fdopen(handle, 'w', encoding='utf-8') as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return payload
