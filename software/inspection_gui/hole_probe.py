"""顶面竖直孔的自动接触测孔：参数校验、几何计算与离线可测的状态机。

这里只做“计划 + 判定”；真正下发运动仍走 ManualControl 的预览/执行/停止，
并且必须先由操作者启用本轮控制。任何异常都会停止并锁定，不自动跳下一个孔。
"""
from __future__ import annotations

import copy
import math
import time

from .contact_points import make_point

DIRECTIONS = (('X', 1, 'X+'), ('X', -1, 'X−'), ('Y', 1, 'Y+'), ('Y', -1, 'Y−'))
STAGES = ('idle', 'ascend', 'traverse', 'descend', 'probe', 'stopping', 'releasing',
          'relock', 'retract', 'retract_fail', 'center', 'ascend_out', 'await_continue',
          'park_traverse', 'park', 'done', 'failed')


def _number(value, name, low=-2500.0, high=2500.0):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(name + '需为有限数值')
    value = float(value)
    if not low <= value <= high:
        raise ValueError(f'{name}需在 {low:g}–{high:g} 之间')
    return value


def validate_hole(hole):
    if not isinstance(hole, dict):
        raise ValueError('孔位记录格式无效')
    result = copy.deepcopy(hole)
    result['id'] = str(hole.get('id') or '')
    if not result['id'] or len(result['id']) > 64:
        raise ValueError('孔位编号无效')
    result['name'] = str(hole.get('name') or '未命名孔位')[:64]
    pose = hole.get('pose')
    if not isinstance(pose, (list, tuple)) or len(pose) != 6:
        raise ValueError('孔位需要六维位姿')
    result['pose'] = [_number(v, '孔位姿态') for v in pose]
    result['xyz'] = [_number(v, '孔位坐标') for v in pose[:3]]
    result['diameter_mm'] = _number(hole.get('diameter_mm'), '孔径', 3.0, 200.0)
    result['note'] = str(hole.get('note') or '')[:200]
    return result


def validate_params(params, holes):
    if not isinstance(params, dict):
        raise ValueError('测孔参数格式无效')
    result = {
        'safe_z_mm': _number(params.get('safe_z_mm'), '安全高度 Z'),
        'search_limit_mm': _number(params.get('search_limit_mm'), '搜索上限', 0.2, 6.0),
        'probe_speed_mm_s': int(_number(params.get('probe_speed_mm_s'), '探测速度', 1, 5)),
        'travel_speed_mm_s': int(_number(params.get('travel_speed_mm_s'), '空移速度', 1, 100)),
        'retract_speed_mm_s': int(_number(params.get('retract_speed_mm_s'), '退离速度', 1, 20)),
        'release_mm': _number(params.get('release_mm'), '释放退让', 0.5, 3.0),
        'release_speed_mm_s': int(_number(params.get('release_speed_mm_s'), '释放速度', 1, 5)),
        'payload_kg': _number(params.get('payload_kg'), '工具总质量', 0.001, 5.0),
        'holes': [validate_hole(h) for h in (holes or [])],
    }
    if not result['holes']:
        raise ValueError('至少需要一个孔位')
    if len(result['holes']) > 50:
        raise ValueError('一次最多 50 个孔位')
    lowest = min(h['xyz'][2] for h in result['holes'])
    if result['safe_z_mm'] <= lowest:
        raise ValueError('安全高度 Z 需高于所有孔位的探测 Z')
    for hole in result['holes']:
        widest = min(result['search_limit_mm'], hole['diameter_mm'] / 2 - 1.0)
        if result['search_limit_mm'] > widest + 1e-9:
            raise ValueError(f'{hole["name"]}：搜索上限超过孔径允许值 {widest:.2f} mm')
    return result


def default_safe_z(holes, clearance_mm=20.0):
    if not holes:
        return 0.0
    return max(h['xyz'][2] for h in holes) + float(clearance_mm)


def endpoint_xyz(hole, axis, sign, search_limit):
    target = list(hole['xyz'])
    target[('X', 'Y', 'Z').index(axis)] += sign * search_limit
    return target


def pose_for(xyz, orientation):
    if not isinstance(orientation, (list, tuple)) or len(orientation) != 3:
        raise ValueError('姿态无效')
    return [float(v) for v in xyz] + [float(v) for v in orientation]


def center_from_contacts(hole, contacts):
    """四个方向的球心位置求中点；不需要测球半径，也抵消对称停止延迟。"""
    if not isinstance(contacts, list) or len(contacts) < 4:
        raise ValueError('需要四个方向的接触点')
    pairs = {}
    for item in contacts:
        key = (item.get('axis'), item.get('sign'))
        if key not in pairs:
            pairs[key] = [float(v) for v in item['xyz']]
    required = {(axis, sign) for axis, sign, _ in DIRECTIONS}
    missing = required - set(pairs)
    if missing:
        raise ValueError('缺少方向接触点：' + ', '.join(f'{a}{"+" if s > 0 else "−"}' for a, s in sorted(missing)))
    x_plus, x_minus = pairs[('X', 1)], pairs[('X', -1)]
    y_plus, y_minus = pairs[('Y', 1)], pairs[('Y', -1)]
    center = [(x_plus[0] + x_minus[0]) / 2, (y_plus[1] + y_minus[1]) / 2, float(hole['xyz'][2])]
    spans = {
        'x_mm': math.dist(x_plus, x_minus),
        'y_mm': math.dist(y_plus, y_minus),
    }
    return {
        'center': center,
        'offset_x_mm': center[0] - hole['xyz'][0],
        'offset_y_mm': center[1] - hole['xyz'][1],
        'spans_mm': spans,
        'probe_radius_compensated': False,
    }


class ProbeError(RuntimeError):
    pass


class ProbeRunner:
    """由界面每 50 ms 调用一次 step()；不自行创建线程或定时器。"""

    def __init__(self, controller, params, *, park=None, confirm_each_hole=True,
                 clock=time.monotonic, point_factory=make_point):
        self.controller = controller
        self.params = params
        self.holes = params['holes']
        self.park = list(park) if park else None
        self.confirm_each_hole = confirm_each_hole is True
        self.clock = clock
        self.point_factory = point_factory
        self.stage = 'idle'
        self.hole_index = 0
        self.direction_index = 0
        self.contacts = []
        self.results = []
        self.waiting = False
        self.deadline = 0.0
        self.orientation = None
        self.di_previous = False
        self.pending_contact = None
        self.message = '尚未开始'
        self.failure = ''
        self.session_points = []
        self.started_at = None
        self.last_pose = None
        self._target = None
        self._timeout = 60.0

    # ---- 对外接口 -----------------------------------------------------
    def start(self, state, frame):
        if self.stage != 'idle':
            raise ValueError('本次测孔已经开始')
        if not isinstance(state, dict) or not state.get('connected'):
            raise ValueError('请先在实机控制页连接控制')
        if not state.get('unlocked'):
            raise ValueError('请先在实机控制页勾选确认并启用本轮控制')
        if state.get('phase') != 'ready':
            raise ValueError('控制未处于可预览状态：' + str(state.get('reason')))
        safety = state.get('safety') or {}
        if not safety.get('feedback_ok') or not safety.get('wall_ok'):
            raise ValueError(safety.get('wall_reason') or safety.get('feedback_reason') or '反馈或安全墙未就绪')
        if not isinstance(frame, dict):
            raise ValueError('没有新鲜反馈')
        if frame.get('digital_inputs', 0) & 1:
            raise ValueError('测针已处于触发状态，请先退离释放')
        self.orientation = [float(v) for v in frame['pose'][3:6]]
        self.last_pose = [float(v) for v in frame['pose']]
        self.started_at = self.clock()
        self.stage = 'ascend'
        self.message = '先升到安全高度'
        target = pose_for([frame['pose'][0], frame['pose'][1], self.params['safe_z_mm']], self.orientation)
        self._move(target, self.params['travel_speed_mm_s'], 'ascend')

    def continue_next(self):
        if self.stage != 'await_continue':
            return False
        self.stage = 'traverse'
        self.message = f'移动到第 {self.hole_index + 1} 个孔'
        self._move(self._hole_safe_target(self.hole_index), self.params['travel_speed_mm_s'], 'traverse')
        return True

    def abort(self, reason='操作者中止自动测孔'):
        if self.stage in ('done', 'failed'):
            return
        try:
            self.controller.request_stop(reason)
        except Exception:
            pass
        self.stage = 'failed'
        self.failure = reason
        self.message = reason

    def status(self):
        hole = self.holes[self.hole_index] if self.hole_index < len(self.holes) else None
        direction = None
        if 0 <= self.direction_index < len(DIRECTIONS):
            direction = DIRECTIONS[self.direction_index][2]
        return {
            'stage': self.stage,
            'hole_index': self.hole_index,
            'hole_count': len(self.holes),
            'hole_name': hole['name'] if hole else None,
            'direction': direction,
            'contacts': len(self.contacts),
            'message': self.message,
            'failure': self.failure,
            'results': copy.deepcopy(self.results),
            'points': copy.deepcopy(self.session_points),
            'running': self.stage not in ('idle', 'done', 'failed', 'await_continue'),
        }

    # ---- 状态机 -------------------------------------------------------
    def step(self, now, state, frame):
        if self.stage in ('idle', 'done', 'failed'):
            return
        if not isinstance(frame, dict) or not isinstance(state, dict):
            self._fail('反馈不可用'); return
        if isinstance(frame.get('pose'), (list, tuple)) and len(frame['pose']) == 6:
            self.last_pose = [float(v) for v in frame['pose']]
        rising = bool(frame.get('digital_inputs', 0) & 1) and not self.di_previous
        self.di_previous = bool(frame.get('digital_inputs', 0) & 1)

        if self.stage == 'probe' and self.pending_contact is None:
            reason = (state.get('safety') or {}).get('stop_reason') or ''
            if rising or (state.get('phase') in ('stopping', 'verifying_stop', 'latched') and 'DI' in reason):
                self._capture_contact(frame)
        if (state.get('phase') == 'fault' or (state.get('safety') or {}).get('stop_state') == 'unconfirmed'):
            self._fail('控制故障或停止未确认：' + str((state.get('safety') or {}).get('stop_reason') or state.get('reason')))
            return
        if now > self.deadline and self.stage not in ('await_continue',):
            self._fail('步骤超时：' + self.message); return

        if self.stage == 'stopping':
            safety = state.get('safety') or {}
            if state.get('phase') == 'latched' and safety.get('stop_state') == 'verified':
                self._begin_release()
            return
        if self.stage == 'releasing':
            if state.get('phase') == 'fault':
                self._fail('释放退让失败：' + str(state.get('reason'))); return
            if state.get('phase') == 'locked':
                self._relock_and_retract(frame)
            return
        if self.stage == 'relock':
            return
        if self.waiting and state.get('phase') == 'ready' and state.get('plan') is None:
            self._arrived()

    # ---- 动作 ---------------------------------------------------------
    def _move(self, target, speed, stage):
        self._target = list(target)
        self.stage = stage
        self.waiting = True
        self.message = {
            'ascend': '升到安全高度', 'traverse': '平移到孔位上方', 'descend': '下降到孔内探测位置',
            'probe': '慢速外探，等待接触', 'retract': '退回孔内起点', 'center': '移动到计算中心',
            'ascend_out': '退出到安全高度', 'park_traverse': '平移到撤离点上方', 'park': '移动到撤离点',
            'retract_fail': '未接触，退回孔内起点',
        }.get(stage, '移动中')
        try:
            if self.last_pose and math.dist(list(target)[:3], self.last_pose[:3]) < 0.005:
                self.stage = stage; self.waiting = False
                self._arrived(); return
            plan = self.controller.preview_target(list(target), int(speed))
            self.controller.execute(plan['id'])
        except Exception as exc:
            self._fail('无法执行移动：' + str(exc)); return
        distance = math.dist(self._target[:3], self.last_pose[:3]) if self.last_pose else 0.0
        scale = distance / max(1, int(speed))
        self.deadline = self.clock() + max(20.0, min(180.0, scale * 3 + 15))

    def _capture_contact(self, frame):
        try:
            point = self.point_factory(frame, name='接触点', hole_id=self.holes[self.hole_index]['id'],
                                       direction=DIRECTIONS[self.direction_index][2])
        except Exception as exc:
            self._fail('接触点保存失败：' + str(exc)); return
        axis, sign, _ = DIRECTIONS[self.direction_index]
        contact = {'axis': axis, 'sign': sign, 'xyz': list(frame['pose'][:3]), 'pose': list(frame['pose']),
                   'frame': copy.deepcopy(frame), 'point': point}
        self.contacts.append(contact)
        self.session_points.append(point)
        self.pending_contact = contact
        self.waiting = False
        self.stage = 'stopping'
        self.message = '已接触，等待停止核对'
        self.deadline = self.clock() + 12.0
        if (self.controller.snapshot().get('phase') not in ('stopping', 'verifying_stop', 'latched')):
            try:
                self.controller.request_stop('测头接触', recoverable=True)
            except Exception:
                pass

    def _begin_release(self):
        axis, sign, _ = DIRECTIONS[self.direction_index]
        self.message = '停止已核对，反向小步退让释放测针'
        self.stage = 'releasing'
        self.deadline = self.clock() + 25.0
        try:
            self.controller.release_probe(axis, -sign, self.params['release_mm'],
                                          self.params['release_speed_mm_s'])
        except Exception as exc:
            self._fail('释放测针失败：' + str(exc))

    def _relock_and_retract(self, frame):
        if bool(frame.get('digital_inputs', 0) & 1):
            self._fail('测针仍未释放，请检查接触点或使用实体急停'); return
        self.stage = 'relock'
        self.message = '重新启用本轮控制并退回孔内起点'
        try:
            self.controller.unlock(True, self.params['payload_kg'], interactive=True)
        except Exception as exc:
            self._fail('重新启用控制失败：' + str(exc)); return
        hole = self.holes[self.hole_index]
        self._move(pose_for(hole['xyz'], self.orientation), self.params['retract_speed_mm_s'], 'retract')

    def _arrived(self):
        self.waiting = False
        stage = self.stage
        if stage == 'ascend':
            self._move(self._hole_safe_target(0), self.params['travel_speed_mm_s'], 'traverse')
        elif stage == 'traverse':
            hole = self.holes[self.hole_index]
            self._move(pose_for(hole['xyz'], self.orientation), self.params['travel_speed_mm_s'], 'descend')
        elif stage == 'descend':
            self.direction_index = 0
            self._probe_current_direction()
        elif stage == 'probe':
            # 到达搜索上限仍未接触：退回起点后停止，不自动继续。
            hole = self.holes[self.hole_index]
            self._move(pose_for(hole['xyz'], self.orientation), self.params['retract_speed_mm_s'], 'retract_fail')
        elif stage == 'retract_fail':
            self._fail(f'{self.holes[self.hole_index]["name"]}：{DIRECTIONS[self.direction_index][2]} 方向未接触，已退回孔内')
        elif stage == 'retract':
            self.direction_index += 1
            if self.direction_index < len(DIRECTIONS):
                self._probe_current_direction()
            else:
                self._move_to_center()
        elif stage == 'center':
            self._move(self._hole_safe_target(self.hole_index), self.params['retract_speed_mm_s'], 'ascend_out')
        elif stage == 'ascend_out':
            self._finish_hole()
        elif stage == 'park_traverse':
            self._move(self.park, self.params['retract_speed_mm_s'], 'park')
        elif stage == 'park':
            self.stage = 'done'; self.message = '全部孔位测完并撤到保存位置'; self.waiting = False

    def _probe_current_direction(self):
        hole = self.holes[self.hole_index]
        axis, sign, label = DIRECTIONS[self.direction_index]
        target = endpoint_xyz(hole, axis, sign, self.params['search_limit_mm'])
        self.pending_contact = None
        self.di_previous = False
        self.message = f'{hole["name"]} · {label} 外探（上限 {self.params["search_limit_mm"]:.2f} mm）'
        self._move(pose_for(target, self.orientation), self.params['probe_speed_mm_s'], 'probe')

    def _move_to_center(self):
        try:
            result = center_from_contacts(self.holes[self.hole_index], self.contacts)
        except Exception as exc:
            self._fail(str(exc)); return
        self.result = result
        self.message = '四个方向完成，移动到计算中心'
        self._move(pose_for(result['center'], self.orientation), self.params['retract_speed_mm_s'], 'center')

    def _finish_hole(self):
        hole = self.holes[self.hole_index]
        result = getattr(self, 'result', None) or center_from_contacts(hole, self.contacts)
        self.results.append({'hole_id': hole['id'], 'hole_name': hole['name'], **result,
                             'contacts': copy.deepcopy(self.contacts), 'status': 'ok'})
        self.contacts = []
        self.result = None
        self.hole_index += 1
        if self.hole_index >= len(self.holes):
            if self.park:
                park = [float(v) for v in self.park]
                if abs(park[2] - self.params['safe_z_mm']) > 0.01:
                    self._move(pose_for([park[0], park[1], self.params['safe_z_mm']], self.orientation),
                               self.params['travel_speed_mm_s'], 'park_traverse')
                else:
                    self._move(park, self.params['retract_speed_mm_s'], 'park')
            else:
                self.stage = 'done'; self.message = '全部孔位测完，停在安全高度'
            return
        if self.confirm_each_hole:
            self.stage = 'await_continue'
            self.waiting = False
            self.message = f'第 {self.hole_index} 个孔完成；确认后继续下一个孔'
        else:
            self._move(self._hole_safe_target(self.hole_index), self.params['travel_speed_mm_s'], 'traverse')

    def _hole_safe_target(self, index):
        hole = self.holes[index]
        return pose_for([hole['xyz'][0], hole['xyz'][1], self.params['safe_z_mm']], self.orientation)

    def _fail(self, reason):
        if self.stage == 'failed':
            return
        self.stage = 'failed'
        self.failure = str(reason)
        self.message = str(reason)
        self.waiting = False
        try:
            self.controller.request_stop(str(reason))
        except Exception:
            pass
