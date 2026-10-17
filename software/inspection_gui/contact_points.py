"""接触点记录：单次会话与持续点位库。只保存数据，不发送运动。"""
from __future__ import annotations

import copy
import csv
import json
import math
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .probe_workspace import atomic_json, capture_position

LIBRARY_NAME = 'contact_points.json'
SESSION_DIR = 'contact_sessions'
MAX_LIBRARY_POINTS = 5000
MAX_SESSION_POINTS = 500


def _finite(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(name + '无效')
    return float(value)


def _xyz(values):
    if not isinstance(values, (list, tuple)) or len(values) != 3:
        raise ValueError('XYZ 需要三个数值')
    result = [_finite(v, 'XYZ') for v in values]
    if any(abs(v) > 2500 for v in result):
        raise ValueError('XYZ 超出 ±2500 mm')
    return result


def make_point(frame, *, name='接触点', note='', hole_id=None, direction=None, source='DI_1'):
    """把一帧反馈转成接触点；复用位置记录校验，但不授予运动权限。"""
    record = capture_position(name, frame, metadata={'source': source, 'hole_id': hole_id, 'direction': direction})
    point = {
        'id': record['id'],
        'name': record['name'],
        'note': str(note or '')[:200],
        'hole_id': hole_id,
        'direction': direction,
        'xyz': record['tcp_pose'][:3],
        'pose': record['tcp_pose'],
        'joints_deg': record['joints_deg'],
        'user_index': record['user_index'],
        'tool_index': record['tool_index'],
        'recorded_at': record['recorded_at'],
        'feedback_received_at': record['feedback_received_at'],
        'source': source,
        'controller_latched': False,
        'precision_verified': False,
    }
    return validate_point(point)


def validate_point(point):
    if not isinstance(point, dict):
        raise ValueError('接触点格式无效')
    if not isinstance(point.get('id'), str) or not 1 <= len(point['id']) <= 64:
        raise ValueError('接触点编号无效')
    result = copy.deepcopy(point)
    result['xyz'] = _xyz(point.get('xyz'))
    pose = point.get('pose')
    if not isinstance(pose, (list, tuple)) or len(pose) != 6:
        raise ValueError('接触点位姿需要六个数值')
    result['pose'] = [_finite(v, '位姿') for v in pose]
    result['note'] = str(point.get('note') or '')[:200]
    result['hole_id'] = point.get('hole_id')
    result['direction'] = point.get('direction')
    result['source'] = str(point.get('source') or 'DI_1')[:32]
    result['controller_latched'] = False
    result['precision_verified'] = False
    return result


def new_session(*, hole_id=None, params=None):
    return {
        'schema_version': 1,
        'kind': 'contact_session',
        'id': uuid.uuid4().hex,
        'started_at': datetime.now(timezone.utc).isoformat(),
        'ended_at': None,
        'hole_id': hole_id,
        'params': copy.deepcopy(params or {}),
        'points': [],
    }


def export_csv(path, points):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ('id', 'hole_id', 'direction', 'name', 'x', 'y', 'z',
              'user_index', 'tool_index', 'recorded_at', 'note')
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(fields)
        for point in points:
            item = validate_point(point)
            writer.writerow([item['id'], item.get('hole_id') or '', item.get('direction') or '',
                             item['name'], *[f'{v:.6f}' for v in item['xyz']],
                             item.get('user_index', ''), item.get('tool_index', ''),
                             item.get('recorded_at', ''), item['note']])
    return path


class ContactStore:
    """点位库 + 会话文件；写入失败抛出，由界面显示，不吞掉。"""

    def __init__(self, directory):
        self.directory = Path(directory)
        self.library_path = self.directory / LIBRARY_NAME
        self.session_directory = self.directory / SESSION_DIR
        self.points = []
        self.load_errors = []
        self._load_library()

    def _load_library(self):
        if not self.library_path.is_file():
            return
        try:
            data = json.loads(self.library_path.read_text(encoding='utf-8-sig'))
            if not isinstance(data, dict) or data.get('kind') != 'contact_library':
                raise ValueError('不是接触点库格式')
            values = data.get('points')
            if not isinstance(values, list):
                raise ValueError('接触点列表无效')
            if len(values) > MAX_LIBRARY_POINTS:
                raise ValueError('接触点库超过上限')
            points = [validate_point(v) for v in values]
            if len({p['id'] for p in points}) != len(points):
                raise ValueError('接触点编号重复')
            self.points = points
        except (OSError, ValueError, TypeError, KeyError) as exc:
            self.load_errors.append(str(exc))

    def save_library(self):
        data = {
            'schema_version': 1,
            'kind': 'contact_library',
            'updated_at': datetime.now(timezone.utc).isoformat(),
            'points': self.points,
        }
        atomic_json(self.library_path, data)

    def append(self, point):
        item = validate_point(point)
        if any(p['id'] == item['id'] for p in self.points):
            return False
        if len(self.points) >= MAX_LIBRARY_POINTS:
            raise ValueError('接触点库已满，请先导出并清理')
        self.points.append(item)
        self.save_library()
        return True

    def update_note(self, point_id, note):
        for point in self.points:
            if point['id'] == point_id:
                point['note'] = str(note or '')[:200]
                self.save_library()
                return True
        return False

    def remove(self, point_ids):
        wanted = set(point_ids)
        before = len(self.points)
        self.points = [p for p in self.points if p['id'] not in wanted]
        if len(self.points) != before:
            self.save_library()
        return before - len(self.points)

    def save_session(self, session):
        points = session.get('points') or []
        if len(points) > MAX_SESSION_POINTS:
            raise ValueError('单次会话点数超过上限')
        data = copy.deepcopy(session)
        data['points'] = [validate_point(p) for p in points]
        data['ended_at'] = data.get('ended_at') or datetime.now(timezone.utc).isoformat()
        name = time.strftime('%Y%m%d_%H%M%S_') + data['id'][:8] + '.json'
        target = self.session_directory / name
        atomic_json(target, data)
        return target
