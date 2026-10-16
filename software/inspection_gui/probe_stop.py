"""Experimental, one-shot stop-only monitor. Never enables or moves a robot.

PC/network latency and probe overtravel are not bounded by this module.
No safety-rated or hardware-latched behaviour is implied.
"""
import copy
import ipaddress
import math
import re
import socket
import threading
import time
from collections import deque
from .probe_trigger import di1_state
from .probe_workspace import atomic_json


STOP_COMMANDS = ('MoveJog()', 'Stop()')


class PoseStabilityTracker:
    """Static communication test only: bounded, continuous 0.4–0.5 s history.

    Does not establish zero velocity, braking performance or metrology accuracy.
    """
    def __init__(self):self.reset()

    def reset(self):self.frames=deque(maxlen=256)

    def feed(self, frame):
        try:
            now=frame['received_monotonic']
            config=(frame['user_index'],frame['tool_index'],tuple(frame['user_offset']),tuple(frame['tool_offset']))
            values=list(frame['pose'])+list(frame['joints'])
            if (frame.get('mode')!=5 or frame.get('running') is not False or frame.get('error') is not False
                    or len(values)!=12 or not all(math.isfinite(v) for v in values) or not math.isfinite(now)):
                self.reset();return False
            stamp=frame.get('controller_timestamp_ms')
            if self.frames:
                previous=self.frames[-1]
                if (not 0<=now-previous[0]<=.1 or config!=previous[1]
                    or (stamp is not None and previous[3] is not None and not 0<=stamp-previous[3]<=100)):
                    self.reset()
            self.frames.append((now,config,values,stamp))
            while self.frames and now-self.frames[0][0]>.5:self.frames.popleft()
            if len(self.frames)<3 or now-self.frames[0][0]<.4:return False
            ranges=[max(f[2][i] for f in self.frames)-min(f[2][i] for f in self.frames) for i in range(12)]
            return all(v<(.02 if i<3 else .01) for i,v in enumerate(ranges))
        except (KeyError,TypeError,ValueError):
            self.reset();return False


def send_stop_only(address):
    """Dedicated bounded connection, no control takeover, retry or motion command."""
    ipaddress.ip_address(address)
    replies = []
    mode_blocked = False
    sock = None
    connection_failed = False
    for command in STOP_COMMANDS:
        if mode_blocked or connection_failed:
            replies.append({'command': command, 'accepted': False, 'sent': False,
                'control_mode_blocked': mode_blocked, 'error': '控制连接不可用，跳过后续停止请求'})
            continue
        phase = 'connect'
        sent = False
        data = bytearray()
        try:
            if sock is None:
                sock = socket.create_connection((address, 29999), timeout=.4)
                sock.settimeout(.4)
            if sock is not None:
                phase = 'send'
                sock.sendall(command.encode('ascii'))
                sent = True
                phase = 'receive'
                deadline = time.monotonic() + .6
                while b';' not in data:
                    if time.monotonic() >= deadline:
                        raise TimeoutError('停止响应超时')
                    part = sock.recv(1024)
                    if not part:
                        raise ConnectionError('停止响应不完整')
                    data.extend(part)
                    if b'control mode is not tcp' in data.lower():
                        mode_blocked = True
                        raise ValueError('控制器不在 TCP 模式；不会自动切换或接管控制权')
                    if b'connection refused' in data.lower() or b'has been occupied' in data.lower():
                        connection_failed = True
                        raise ValueError('控制器拒绝控制连接或端口已占用；不会接管或自动重连')
                    if len(data) > 4096:
                        raise ValueError('停止响应过大')
                reply = data.decode('ascii').strip()
                phase = 'parse'
                pattern = r'0,\{[^{}]*\},' + re.escape(command) + r';'
                if not re.fullmatch(pattern, reply):
                    raise ValueError('停止请求未获明确成功应答：' + reply[:200])
                replies.append({'command': command, 'accepted': True, 'sent': True, 'reply': reply})
        except (OSError, ValueError) as exc:
            if phase != 'parse':
                connection_failed = True
            replies.append({'command': command, 'accepted': False, 'error': str(exc),
                'phase': phase, 'sent': sent, 'control_mode_blocked': mode_blocked,
                'raw_reply': data.decode('ascii', errors='replace')[:500]})
    if sock is not None:
        sock.close()
    return replies


class ProbeStopMonitor:
    def __init__(self, sender=send_stop_only, clock=time.monotonic):
        self.sender = sender
        self.clock = clock
        self.lock = threading.RLock()
        self.state = 'off'
        self.live = False
        self.token = 0
        self.report = {'state': 'off', 'reason': '停止联锁未启用', 'safety_verified': False}
        self.audit_path = None

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(self.report)

    @staticmethod
    def config(frame):
        return (frame['user_index'], frame['tool_index'], tuple(frame['user_offset']), tuple(frame['tool_offset']))

    @staticmethod
    def stationary(frame):
        values = frame.get('joint_speeds', []) + frame.get('tcp_speeds', [])
        return (len(values) == 12 and all(type(v) in (float, int) and math.isfinite(v) and abs(v) < .01 for v in values)
                and frame.get('mode') in (4, 5, 10) and not frame.get('running'))

    def _save(self):
        self.report['state'] = self.state
        if self.audit_path:
            try:
                atomic_json(self.audit_path, self.report)
            except OSError as exc:
                self.report['save_error'] = str(exc)

    def arm(self, frame, address, generation, *, live=False, confirmations=False, audit_path=None, static_only=False):
        with self.lock:
            if self.state in ('armed', 'pending', 'acknowledged'):
                raise ValueError('已有监控或停止请求未结束')
            now = self.clock()
            if not frame or not 0 <= now-frame['received_monotonic'] <= .15 or di1_state(frame) is not False:
                raise ValueError('需要新鲜反馈且 DI_1=0')
            if static_only:
                if frame.get('pose_stable') is not True or frame.get('mode')!=5 or frame.get('running') or frame.get('error'):
                    raise ValueError('需要待机、无报警且连续位姿稳定至少 0.4 秒；请保持不动后重试')
            elif not self.stationary(frame) or frame.get('error'):
                raise ValueError('需要机械臂静止且无报警')
            if live and (confirmations is not True or audit_path is None):
                raise ValueError('实机模式需要现场条件确认和日志路径')
            ipaddress.ip_address(address)
            self.token += 1
            self.live = live
            self.static_only = static_only
            self.address, self.generation = address, generation
            self.configuration = self.config(frame)
            self.last_frame = frame['received_monotonic']
            self.last_stamp = frame.get('controller_timestamp_ms')
            self.expires = now + 30
            self.quiet_frames = 0
            self.audit_path = audit_path
            self.report = dict(state='armed', live=live, static_only=static_only, address=address, generation=generation,
                armed_at=time.time(), reason='等待 DI_1 触发；30 秒有效', safety_verified=False,
                hardware_latched=False, confirmed_stopped=False, replies=[])
            self.state = 'armed'
            self._save()
            if self.report.get('save_error'):
                self.state = 'failed'
                self.report['state'] = self.state
                raise ValueError('日志保存失败，未启用')
            token = self.token
        threading.Thread(target=self._watch, args=(token,), daemon=True, name='probe-stop-watch').start()

    def _watch(self, token):
        while True:
            time.sleep(.02)
            with self.lock:
                if token != self.token or self.state not in ('armed', 'pending', 'acknowledged'):
                    return
                self.check_time()

    def check_time(self):
        with self.lock:
            now = self.clock()
            if self.state == 'armed':
                if now-self.last_frame > .2:
                    self._request('反馈超过 200 ms 未更新')
                elif now >= self.expires:
                    self._request('30 秒监控到期')
            elif self.state == 'pending' and now >= self.send_deadline:
                self.state = 'failed'
                self.report['reason'] = '停止请求处理超时，无法确认停住'
                self._save()
            elif self.state == 'acknowledged' and now >= self.verify_deadline:
                self.state = 'failed'
                self.report['reason'] = '停止已应答，但未在 2 秒内确认静止'
                self._save()

    def observe(self, frame, generation):
        with self.lock:
            if self.state not in ('armed', 'acknowledged'):
                return
            if self.state == 'armed':
                stamp = frame.get('controller_timestamp_ms')
                gap = frame['received_monotonic']-self.last_frame
                stamp_gap = None if stamp is None or self.last_stamp is None else stamp-self.last_stamp
                if generation != self.generation or self.config(frame) != self.configuration:
                    self._request('连接代次或工具 / 用户配置变化')
                elif (not 0 <= self.clock()-frame['received_monotonic'] <= .15 or not 0 <= gap <= .2
                      or (stamp_gap is not None and not 0 <= stamp_gap <= 200)):
                    self._request('反馈间隔异常或控制器时间回退')
                elif di1_state(frame) is not False:
                    self._request('DI_1 触发或输入无效', frame)
                elif frame.get('error'):
                    self._request('控制器报警')
                elif self.static_only and (frame.get('pose_stable') is not True or frame.get('mode')!=5 or frame.get('running')):
                    self._request('静止通信测试期间检测到运动，终止测试并请求停止')
                self.last_frame, self.last_stamp = frame['received_monotonic'], stamp
            else:
                # A command ACK is not evidence of stopping. Require three NEW frames.
                now = self.clock()
                if (generation != self.generation or self.config(frame) != self.configuration
                        or not 0 <= now-frame['received_monotonic'] <= .15
                        or frame['received_monotonic'] < self.last_confirm_frame
                        or frame['received_monotonic']-self.last_confirm_frame > .2):
                    self.quiet_frames = 0
                    self.last_confirm_frame = max(self.last_confirm_frame, frame['received_monotonic'])
                    return
                # Windows monotonic ticks may span multiple 8 ms feedback packets.
                # Do not count an equal-time packet as new, or let it erase the
                # valid distinct-time frames already collected. A motion or
                # invalid stability observation must still break the sequence.
                if frame['received_monotonic'] == self.last_confirm_frame:
                    stable = (frame.get('pose_stable') is True and frame.get('mode')==5
                              and not frame.get('running') and not frame.get('error')) if self.static_only else self.stationary(frame)
                    if not stable:
                        self.quiet_frames = 0
                    return
                self.last_confirm_frame = frame['received_monotonic']
                stable = (frame.get('pose_stable') is True and frame.get('mode')==5
                          and not frame.get('running') and not frame.get('error')) if self.static_only else self.stationary(frame)
                self.quiet_frames = self.quiet_frames+1 if stable else 0
                if self.quiet_frames >= 3:
                    self.state = 'confirmed'
                    self.report.update(confirmed_stopped=True, reason='应答后连续 3 帧反馈显示静止；需人工确认现场')
                    if self.static_only:
                        self.report.update(confirmed_stopped=False, communication_verified=True)
                        self.report['reason'] = '静止通信测试：停止请求获应答，反馈保持静止；未验证运动停止能力'
                    self._save()

    def _request(self, reason, frame=None):
        # Called under lock; network I/O always runs outside the receiver thread.
        if self.state != 'armed':
            return
        self.report.update(reason=reason, requested_at=time.time(), trigger=copy.deepcopy(frame))
        if not self.live:
            self.state = 'simulated'
            self.report['reason'] = '演练命中：'+reason+'；未发送任何指令'
            self._save()
            return
        self.state = 'pending'
        self.report['state'] = self.state
        self.send_deadline = self.clock()+3
        # Disk persistence must never delay dispatch of a stop request.
        threading.Thread(target=self._send, args=(self.token,), daemon=True, name='probe-stop-send').start()

    def _send(self, token):
        try:
            replies = self.sender(self.address)
        except Exception as exc:
            replies = [{'accepted': False, 'error': str(exc)}]
        with self.lock:
            if token != self.token or self.state != 'pending':
                return
            self.report['replies'] = replies
            ok = len(replies) == 2 and all(r.get('accepted') is True for r in replies)
            self.state = 'acknowledged' if ok else 'failed'
            self.report['reason'] = ('两条停止请求已应答，等待静止反馈' if ok else
                '停止请求失败或被拒绝，不能确认停住；请现场处理')
            if any(r.get('control_mode_blocked') for r in replies):
                self.report['reason'] = '当前不是 TCP 控制模式，停止请求不被支持；未切换模式或接管控制权'
            self.verify_deadline = self.clock()+2
            self.last_confirm_frame = self.clock()
            self._save()

    def disarm(self):
        with self.lock:
            if self.state == 'armed' and self.live:
                self._request('人工结束监控，先请求停止')
            elif self.state == 'armed':
                self.state = 'off'
                self.report['reason'] = '演练已关闭'
                self._save()

    def disconnected(self):
        with self.lock:
            if self.state == 'armed':
                self._request('反馈断开或窗口关闭')


def run_simulation():
    now = time.monotonic()
    f = dict(digital_inputs=0, received_monotonic=now, mode=5, running=False, error=False,
        joint_speeds=[0.]*6, tcp_speeds=[0.]*6, user_index=0, tool_index=1,
        user_offset=[0.]*6, tool_offset=[0.]*6, controller_timestamp_ms=1)
    monitor = ProbeStopMonitor(sender=lambda _: (_ for _ in ()).throw(AssertionError('演练不得联网')))
    monitor.arm(f, '127.0.0.1', 0)
    f.update(digital_inputs=1, received_monotonic=time.monotonic(), controller_timestamp_ms=9)
    monitor.observe(f, 0)
    return monitor.snapshot()
