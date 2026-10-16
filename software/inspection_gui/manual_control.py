"""Experimental fixed-orientation, bounded TCP moves. Never auto-enables.

Protocol: https://github.com/Dobot-Arm/TCP-IP-Python-V4/blob/main/dobot_api.py
Software limits are not safety-rated and cannot bound braking overtravel.
"""
import copy
import ipaddress
import math
from pathlib import Path
import queue
import re
import socket
import threading
import time
import uuid
from .probe_workspace import atomic_json


class ControlChannel:
    def __init__(self, address):
        ipaddress.ip_address(address)
        self.sock = socket.create_connection((address, 29999), timeout=.4)
        self.sock.settimeout(.4)

    def _exchange(self, command):
        self.sock.sendall(command.encode('ascii'))
        data = bytearray()
        deadline = time.monotonic()+.6
        while b';' not in data:
            if time.monotonic()>deadline:
                raise TimeoutError('控制响应超时；不自动重试')
            part = self.sock.recv(1024)
            if not part:
                raise ConnectionError('控制连接已关闭')
            data.extend(part)
            if len(data)>4096:
                raise ValueError('控制响应过大')
            lowered = data.lower()
            if b'control mode is not tcp' in lowered:
                raise ValueError('当前不是 TCP 模式；不会自动切换')
            if b'connection refused' in lowered or b'has been occupied' in lowered:
                raise ValueError('控制端口被占用；不会接管或重连')
        reply = data.decode('ascii').strip()
        match = re.fullmatch(r'0,\{([^{}]*)\},'+re.escape(command)+r';', reply)
        if not match:
            raise ValueError('控制器未明确接受：'+reply[:250])
        return match.group(1)

    def check(self):
        result = self._exchange('RobotMode()')
        if result.strip()!='5':
            raise ValueError('需已使能、无报警的待机状态，当前模式：'+result)

    def move(self, plan):
        target = plan['target']
        if len(target)!=6 or not all(math.isfinite(x) for x in target):
            raise ValueError('目标坐标无效')
        if type(plan['speed']) is not int or not 1<=plan['speed']<=20 or not .01<=plan['distance']<=100:
            raise ValueError('移动参数超出范围')
        if plan['user']!=0 or type(plan['tool']) is not int or not 0<=plan['tool']<=255:
            raise ValueError('坐标系编号无效')
        command = 'MovL(pose={'+','.join(f'{x:.6f}' for x in target)+'},user='+str(plan['user'])+',tool='+str(plan['tool'])+',a=1,speed='+str(plan['speed'])+',cp=0)'
        self.motion_kind='step'
        self._exchange(command)
        return command

    def stop(self):
        replies=[]
        errors=[]
        # Stop the MovL queue FIRST. A rejected jog cancellation must never
        # prevent dispatch of Stop(). Jog needs its own cancellation as well.
        commands=('Stop()', 'MoveJog()') if getattr(self,'motion_kind',None)=='jog' else ('Stop()',)
        for command in commands:
            try:
                self._exchange(command)
                replies.append(command)
            except Exception as exc:
                errors.append(command+': '+str(exc))
        self.last_stop_attempt=dict(commands=list(commands),acknowledged=replies,errors=errors)
        if errors:raise ValueError('停止指令未全部确认：'+'；'.join(errors))
        return replies

    def jog(self, plan, cancelled):
        """V4 native jog. SpeedFactor is a percentage, not an absolute speed.

        Leave the selected low global ratio in effect; never restore a higher
        speed automatically. A release during the speed ACK cancels MoveJog.
        """
        if plan['axis'] not in ('X','Y','Z') or type(plan['sign']) is not int or plan['sign'] not in (-1,1):
            raise ValueError('点动方向无效')
        if type(plan['ratio']) is not int or not 1<=plan['ratio']<=10:
            raise ValueError('点动倍率范围为1%–10%')
        if plan['user']!=0 or type(plan['tool']) is not int or not 0<=plan['tool']<=9:
            raise ValueError('点动仅支持用户0及工具0–9')
        if cancelled():return None
        self._exchange(f"SpeedFactor({plan['ratio']})")
        if cancelled():return None
        direction=plan['axis']+('+' if plan['sign']>0 else '-')
        command=f"MoveJog({direction},coordtype=1,user=0,tool={plan['tool']})"
        self.motion_kind='jog'
        self._exchange(command)
        return command

    def close(self):
        self.sock.close()


class ManualControl:
    def __init__(self, audit_directory, channel_factory=ControlChannel, clock=time.monotonic):
        self.clock=clock;self.factory=channel_factory;self.directory=Path(audit_directory)
        self.lock=threading.RLock();self.stop_event=threading.Event();self.closing=threading.Event()
        self.wake_event=threading.Event()
        self.tasks=queue.Queue(maxsize=1);self.worker=None;self.channel=None
        self.latest=None;self.generation=None;self.connected=False;self.phase='locked'
        self.reason='未连接控制；运动锁定';self.permit=None;self.plan=None;self.events=[]
        self.audit=None;self.external_monitor=False;self.stop_handled=False;self.accepted_at=None;self.hold_until=0
        self.stop_state='none';self.stop_reason='';self.stop_ack_at=None
        self.stop_frames=[];self.stop_configuration=None
        self.resume_context=None
        self.interactive=False;self.auto_rearm=False

    @staticmethod
    def validate_feedback(f):
        if not isinstance(f,dict):raise ValueError('反馈不可用')
        for key in ('received_monotonic',):
            if type(f.get(key)) not in (int,float) or not math.isfinite(f[key]):
                raise ValueError('反馈时间无效')
        for key in ('pose','user_offset','tool_offset'):
            values=f.get(key)
            if (not isinstance(values,(list,tuple)) or len(values)!=6
                or any(type(v) not in (int,float) or not math.isfinite(v) for v in values)):
                raise ValueError('反馈坐标或工具参数无效')
        for key in ('enabled','running','error','pose_stable'):
            if type(f.get(key)) is not bool:raise ValueError('反馈状态缺失：'+key)
        for key in ('mode','digital_inputs','user_index','tool_index'):
            if type(f.get(key)) is not int or f[key]<0:raise ValueError('反馈状态无效：'+key)
        if f['user_index']>255 or f['tool_index']>255:raise ValueError('坐标系编号无效')

    @staticmethod
    def config(f):
        return (f['user_index'], f['tool_index'], tuple(f['user_offset']), tuple(f['tool_offset']))

    def _fresh(self, require_idle=True):
        f=self.latest
        self.validate_feedback(f)
        if not f or not 0<=self.clock()-f['received_monotonic']<=.15:
            raise ValueError('需要新鲜反馈（不超过150 ms）')
        if f['error'] or not f['enabled'] or f['digital_inputs']&1:
            raise ValueError('需要已使能、无报警且测头已松开')
        if require_idle and (f.get('mode')!=5 or f.get('running') or f.get('pose_stable') is not True):
            raise ValueError('需要待机且位姿持续稳定')
        if self.external_monitor:
            raise ValueError('请先结束独立的触发停止测试，避免控制端口冲突')
        values=f.get('pose',[])
        if len(values)!=6 or not all(math.isfinite(v) for v in values):
            raise ValueError('反馈位姿无效')
        if f.get('user_index')!=0:
            raise ValueError('当前控制界面仅支持基座用户坐标系0')
        return f

    def _record(self, event, **fields):
        self.events.append(dict(time=time.time(),event=event,**copy.deepcopy(fields)))
        # Avoid filesystem flushes in the motion/feedback path. The in-memory
        # move acknowledgement is flushed with the subsequent stop/close event.
        if self.audit and self.phase not in ('moving','stopping'):
            atomic_json(self.audit,dict(safety_verified=False,events=self.events))

    def snapshot(self):
        with self.lock:
            ok=True;detail='反馈条件满足'
            try:self._fresh()
            except (ValueError,TypeError,KeyError) as exc:ok=False;detail=str(exc)
            age=None
            if isinstance(self.latest,dict) and type(self.latest.get('received_monotonic')) in (float,int):
                value=(self.clock()-self.latest['received_monotonic'])*1000
                if math.isfinite(value):age=max(0,value)
            return dict(connected=self.connected,phase=self.phase,reason=self.reason,
                        unlocked=self.permit is not None, plan=copy.deepcopy(self.plan),
                        interactive=self.interactive,
                        motion_kind=getattr(self,'active_plan',{}).get('kind','step') if self.phase=='moving' else None,
                        resumable=self.resume_context is not None,
                        can_unlock=self.connected and self.phase=='locked' and ok,
                        safety=dict(feedback_ok=ok,feedback_reason=detail,feedback_age_ms=age,
                            stop_state=self.stop_state,stop_reason=self.stop_reason,
                            can_reset=self.connected and self.phase=='latched' and self.stop_state=='verified' and ok,
                            can_resume=self.connected and self.phase=='latched' and self.stop_state=='verified' and ok
                                and self.resume_context is not None and self.clock()<self.expires and (self.interactive or self.used_distance<5),
                            remaining_seconds=max(0,self.expires-self.clock()) if self.permit or self.resume_context else 0,
                            remaining_distance_mm=max(0,5-self.used_distance) if self.permit or self.resume_context else 0))

    def resume_control(self):
        """Explicitly restore input permission after an ordinary stop; never move.

        Keep the original time, travel and configuration budget. Old targets and
        queued moves cannot be replayed. Protective stops require a new session.
        """
        with self.lock:
            self._fresh()
            if not self.snapshot()['safety']['can_resume']:
                raise ValueError('不能继续本轮；请核对停止结果或结束本轮后重新启用')
            if self.generation!=self.connection_generation or self.config(self.latest)!=self.configuration:
                raise ValueError('连接或工具配置已变化，需要重新确认')
            self._record('ordinary_stop_resumed',motion_started=False,
                         remaining_seconds=self.expires-self.clock(),used_distance_mm=self.used_distance)
            while not self.tasks.empty():
                try:self.tasks.get_nowait()
                except queue.Empty:break
            self.resume_context=None;self.permit=uuid.uuid4().hex;self.plan=None
            self.auto_rearm=False
            self.stop_event.clear();self.stop_handled=False;self.stop_state='none'
            self.stop_ack_at=None;self.stop_frames=[];self.stop_reason=''
            self.accepted_at=None;self.hold_until=0;self.phase='ready'
            self.reason='控制已恢复；请选择新的方向，原移动不会继续'

    def reset_safety(self):
        with self.lock:
            self._fresh()
            if not self.connected or self.phase!='latched' or self.stop_state!='verified':
                raise ValueError('停止尚未完成反馈核对，不能复位')
            if self.generation!=self.connection_generation or self.config(self.latest)!=self.stop_configuration:
                raise ValueError('停止后连接或坐标配置发生变化，请重新连接检查')
            self._record('safety_reset',motion_started=False)
            self.resume_context=None
            self.auto_rearm=False
            self.stop_state='none';self.stop_reason='';self.stop_ack_at=None
            self.stop_frames=[];self.stop_event.clear();self.stop_handled=False
            self.phase='locked';self.reason='已复位到锁定状态；需要重新确认、解锁和预览'

    def connect(self, address, generation):
        with self.lock:
            if self.worker and self.worker.is_alive():raise ValueError('已有控制连接或正在关闭')
            self._fresh(); self.address=address; self.connection_generation=generation
            if generation!=self.generation:raise ValueError('反馈连接已变化')
            self.stop_state='none';self.stop_reason='';self.stop_ack_at=None;self.stop_frames=[]
            self.resume_context=None
            self.auto_rearm=False
            self.channel=None;self.events=[];self.permit=None;self.plan=None
            while not self.tasks.empty():
                try:self.tasks.get_nowait()
                except queue.Empty:break
            self.audit=self.directory/(str(time.time_ns())+'.json')
            self._record('connect_requested',address=address)
            self.reason='正在检查 TCP 模式（不使能、不启动运动）'
            self.closing.clear();self.stop_event.clear();self.stop_handled=False
            self.worker=threading.Thread(target=self._run,daemon=True,name='bounded-manual-control')
            self.worker.start()

    def unlock(self, confirmations, payload_kg, *, interactive=False):
        with self.lock:
            f=self._fresh()
            if not self.connected or self.phase!='locked':raise ValueError('请先连接并检查控制通道')
            if confirmations is not True or not math.isfinite(payload_kg) or not 0<payload_kg<=5:
                raise ValueError('需确认实际负载、重心配置及现场条件')
            self._record('manual_unlock',declared_payload_kg=payload_kg,configuration=self.config(f))
            self.anchor=f['pose'][:];self.configuration=self.config(f)
            self.interactive=interactive is True;self.auto_rearm=False
            self.permit=uuid.uuid4().hex;self.expires=self.clock()+(600 if self.interactive else 60);self.used_distance=0
            self.resume_context=None
            self.stop_event.clear();self.stop_handled=False;self.phase='ready'
            self.reason='点动控制已启用；按住方向移动，松开停止' if self.interactive else '已解锁60秒；先预览，再按住执行'

    def start_jog(self, axis, sign, ratio=1, max_distance_mm=100):
        with self.lock:
            f=self._fresh()
            if not self.interactive or self.phase!='ready' or not self.permit or self.clock()>=self.expires:
                raise ValueError('请先启用点动控制；停止反馈未完成时请松手后重新按下')
            if axis not in ('X','Y','Z') or type(sign) is not int or sign not in (-1,1):
                raise ValueError('点动方向无效')
            if type(ratio) is not int or not 1<=ratio<=10 or not 0<=f['tool_index']<=9:
                raise ValueError('点动倍率或工具编号不支持')
            if type(max_distance_mm) not in (int,float) or not math.isfinite(max_distance_mm) or not .01<=max_distance_mm<=100:
                raise ValueError('点动单次距离上限为0.01–100 mm')
            if self.config(f)!=self.configuration:raise ValueError('工具或用户配置已变化')
            self.plan=dict(id=uuid.uuid4().hex,kind='jog',axis=axis,sign=sign,ratio=ratio,
                max_distance_mm=max_distance_mm,
                start=f['pose'][:],distance=0,user=0,tool=f['tool_index'],config=self.configuration,
                generation=self.connection_generation,permit=self.permit,created=self.clock())
            self.execute(self.plan['id'])

    def preview(self, axis, delta, speed=1):
        with self.lock:
            f=self._fresh()
            if self.phase!='ready' or not self.permit or self.clock()>=self.expires:
                raise ValueError('运动锁定或授权到期')
            max_distance=100 if self.interactive else 1
            max_speed=20 if self.interactive else 5
            if axis not in ('X','Y','Z') or not math.isfinite(delta) or not .01<=abs(delta)<=max_distance or type(speed) is not int or not 1<=speed<=max_speed:
                raise ValueError(f'仅允许 XYZ 单轴0.01–{max_distance} mm、1–{max_speed} mm/s')
            if self.config(f)!=self.configuration:raise ValueError('工具或用户配置已变化')
            target=f['pose'][:];target[('X','Y','Z').index(axis)]+=delta
            if not self.interactive and (math.dist(target[:3],self.anchor[:3])>5 or self.used_distance+abs(delta)>5):
                raise ValueError('本次解锁累计行程或距起点超过5 mm；需结束并重新检查现场')
            self.plan=dict(id=uuid.uuid4().hex,target=target,start=f['pose'][:],axis=axis,delta=delta,
                speed=speed,distance=abs(delta),user=f['user_index'],tool=f['tool_index'],
                config=self.configuration,generation=self.connection_generation,permit=self.permit,created=self.clock())
            return copy.deepcopy(self.plan)

    def execute(self, plan_id):
        with self.lock:
            if self.phase!='ready':raise ValueError('已有移动或停止请求未结束')
            self._validate_plan(plan_id)
            self._record('move_requested',plan=self.plan)
            self.tasks.put_nowait(copy.deepcopy(self.plan));self.hold_until=self.clock()+.2
            self.phase='queued';self.reason='等待发送单条定距移动'
            self.wake_event.set()

    def maintain_hold(self):
        with self.lock:
            if self.phase in ('queued','moving') and self.permit:
                self.hold_until=self.clock()+.2

    def _validate_plan(self, plan_id):
        f=self._fresh();p=self.plan
        if not self.permit or not p or p['id']!=plan_id or p['permit']!=self.permit or self.stop_event.is_set():
            raise ValueError('预览已失效或运动锁定')
        if self.clock()>=self.expires or self.clock()-p['created']>10:
            raise ValueError('预览或解锁已到期，请重新预览')
        if self.generation!=self.connection_generation or self.config(f)!=p['config']:
            raise ValueError('连接或坐标配置已变化')
        if any(abs(a-b)>(.05 if i<3 else .01) for i,(a,b) in enumerate(zip(f['pose'],p['start']))):
            raise ValueError('当前位置已变化，请重新预览')

    def request_stop(self, reason='人工停止', *, recoverable=False, auto_rearm=False):
        self.stop_event.set()
        self.wake_event.set()
        with self.lock:
            if self.connected and not self.stop_handled and self.stop_state=='none':
                # Memory only: never block the feedback/stop path on disk I/O.
                self.events.append(dict(time=time.time(),event='stop_requested',reason=reason,
                    requested_monotonic=self.clock(),
                    digital_inputs=self.latest.get('digital_inputs') if self.latest else None))
            if recoverable and self.permit:
                self.resume_context={'configuration':self.configuration,'generation':self.connection_generation}
                self.auto_rearm=auto_rearm is True
            elif not recoverable:
                self.resume_context=None
                self.auto_rearm=False
            elif not auto_rearm:
                self.auto_rearm=False
            self.permit=None;self.plan=None
            if self.connected and not self.stop_handled:
                if self.stop_state=='none':self.stop_reason=reason
                self.stop_state='requested'
                self.phase='stopping';self.reason=reason+'；请求停止中'

    def _verify_stop(self, frame, generation):
        # Only samples received AFTER both stop replies can support this check.
        # This is observed pose stability, never a safety-rated stop assertion.
        try:
            self.validate_feedback(frame)
            now=frame['received_monotonic']
            if not 0<=self.clock()-now<=.15 or now<=self.stop_ack_at:return
            if generation!=self.connection_generation or self.config(frame)!=self.stop_configuration:
                raise ValueError('停止后连接或坐标配置变化')
            if frame['mode']!=5 or frame['running'] or frame['error'] or not frame['enabled']:
                self.stop_frames=[];return
            if self.stop_frames:
                previous=self.stop_frames[-1]
                if now<=previous[0]:return
                if now-previous[0]>.1:self.stop_frames=[]
            self.stop_frames.append((now,frame['pose'][:]))
            while self.stop_frames and now-self.stop_frames[0][0]>.5:self.stop_frames.pop(0)
            if len(self.stop_frames)<4 or now-self.stop_frames[0][0]<.3:return
            ranges=[max(p[1][i] for p in self.stop_frames)-min(p[1][i] for p in self.stop_frames) for i in range(6)]
            if all(v<(.02 if i<3 else .01) for i,v in enumerate(ranges)):
                self.stop_state='verified';self.phase='latched'
                self.reason=('已停止，反馈稳定；点击“继续控制”后重新选择方向' if self.resume_context else
                    '保护锁定；反馈稳定，处理原因后可解除锁定')
                self._record('stop_feedback_stable',confirmed_stopped=False,observed_pose_stable=True)
        except (ValueError,KeyError,TypeError,OSError) as exc:
            self.resume_context=None
            self.stop_state='unconfirmed';self.phase='fault';self.reason='无法确认停止，请使用实体急停：'+str(exc)

    def observe(self, frame, generation, external_monitor=False):
        with self.lock:
            self.latest=copy.deepcopy(frame);self.generation=generation;self.external_monitor=external_monitor
            if (isinstance(frame,dict) and type(frame.get('digital_inputs')) is int
                and frame['digital_inputs']&1 and (self.permit or self.resume_context)):
                self.request_stop('测头 DI_1 触发')
            if self.resume_context is not None:
                try:
                    self._fresh(require_idle=False)
                    if (generation!=self.connection_generation or self.config(frame)!=self.configuration
                        or self.clock()>=self.expires):raise ValueError('原会话已失效')
                except (ValueError,KeyError,TypeError):self.resume_context=None
            if self.stop_state=='acknowledged':self._verify_stop(frame,generation)
            elif self.stop_state=='verified':
                try:
                    self.validate_feedback(frame)
                    reference=self.stop_frames[-1][1]
                    if (generation!=self.connection_generation or self.config(frame)!=self.stop_configuration
                        or frame['mode']!=5 or frame['running'] or frame['error']
                        or any(abs(a-b)>(.05 if i<3 else .02) for i,(a,b) in enumerate(zip(frame['pose'],reference)))):
                        raise ValueError('核对停止后状态或位姿发生变化')
                except (ValueError,KeyError,TypeError) as exc:
                    self.resume_context=None
                    self.stop_state='unconfirmed';self.phase='fault'
                    self.reason='无法确认停止，请使用实体急停：'+str(exc)
            if self.auto_rearm and self.snapshot()['safety']['can_resume']:
                try:
                    self.resume_control()
                    self.reason='已停止；可以再次按方向点动，不会自动续走'
                except (ValueError,OSError) as exc:
                    self.resume_context=None;self.auto_rearm=False
                    self.reason='停止后未恢复输入：'+str(exc)
            if not self.permit:return
            try:
                f=self._fresh(require_idle=False)
                if generation!=self.connection_generation or self.config(f)!=self.configuration:
                    raise ValueError('连接或坐标配置变化')
                jogging=self.phase=='moving' and self.active_plan.get('kind')=='jog'
                if (f['mode'] not in ((5,8) if jogging else (5,7))
                    or (f['mode'] in (7,8) and self.phase!='moving')
                    or (not self.interactive and math.dist(f['pose'][:3],self.anchor[:3])>5)):
                    raise ValueError('运行模式异常或距起点超过5 mm')
                if self.phase=='moving' and self.accepted_at is not None:
                    p=self.active_plan
                    axis=('X','Y','Z').index(p['axis'])
                    along=f['pose'][axis]-p['start'][axis]
                    if jogging:outside=not -.2<=along*p['sign']<=100
                    else:outside=not min(p['start'][axis],p['target'][axis])-.2<=f['pose'][axis]<=max(p['start'][axis],p['target'][axis])+.2
                    if (any(abs(f['pose'][i]-p['start'][i])>.2 for i in range(3) if i!=axis)
                        or any(abs((f['pose'][i]-p['start'][i]+180)%360-180)>.5 for i in range(3,6))
                        or outside):
                        raise ValueError('反馈偏离预览方向或姿态')
                    if jogging and along*p['sign']>=p.get('max_distance_mm',100):
                        self.request_stop('已到本次点动距离上限',recoverable=True,auto_rearm=True);return
                    if (not jogging and self.clock()>self.accepted_at and f['mode']==5 and not f['running']
                        and f.get('pose_stable') and math.dist(f['pose'][:3],p['target'][:3])<=.05):
                        self.phase='ready';self.plan=None;self.reason='反馈到达目标；下一步需重新预览'
            except (ValueError,KeyError,TypeError) as exc:
                self.request_stop(str(exc))

    def _run(self):
        try:
            self.channel=self.factory(self.address);self.channel.check()
            with self.lock:
                self.connected=True;self.phase='locked';self.reason='TCP控制已连接；运动锁定'
                self._record('tcp_connected')
            while True:
                self.wake_event.clear()
                with self.lock:
                    if self.resume_context and (not self.latest or self.clock()-self.latest['received_monotonic']>.2 or self.clock()>=self.expires):
                        self.resume_context=None
                    if self.stop_state=='acknowledged' and self.clock()-self.stop_ack_at>2:
                        self.resume_context=None
                        self.stop_state='unconfirmed';self.phase='fault'
                        self.reason='无法确认停止：停止后未收到连续稳定反馈，请使用实体急停'
                    if self.permit and (not self.latest or self.clock()-self.latest['received_monotonic']>.2 or self.clock()>=self.expires):
                        self.request_stop('反馈中断或本次控制授权到期')
                    if self.phase=='moving' and self.clock()>self.motion_deadline:
                        self.request_stop('单次运动超时')
                    if self.phase in ('queued','moving') and self.clock()>self.hold_until:
                        self.request_stop('按住执行信号中断')
                if self.stop_event.is_set() and not self.stop_handled:
                    self.stop_handled=True
                    replies=self.channel.stop()
                    with self.lock:
                        self.stop_ack_at=self.clock();self.stop_frames=[]
                        self.stop_configuration=self.config(self.latest) if self.latest else None
                        self.stop_state='acknowledged';self.phase='verifying_stop'
                        self.reason='停止指令已应答；正在检查后续反馈，保持锁定'
                        self._record('stop_acknowledged',commands=replies,confirmed_stopped=False)
                if self.closing.is_set():break
                try:plan=self.tasks.get_nowait()
                except queue.Empty:
                    self.wake_event.wait(.02)
                    continue
                with self.lock:
                    if self.stop_event.is_set() or not self.permit:continue
                    try:self._validate_plan(plan['id'])
                    except ValueError as exc:
                        self.plan=None;self.phase='ready';self.reason=str(exc);continue
                    if plan.get('kind')=='jog':duration=30
                    elif self.interactive:
                        scale=self.latest.get('speed_percent',100)
                        scale=scale if type(scale) is int and 1<=scale<=100 else 100
                        duration=min(600,max(5,plan['distance']/plan['speed']/(scale/100)*1.5+5))
                    else:duration=5
                    self.active_plan=plan;self.accepted_at=None;self.motion_deadline=self.clock()+duration
                    self.phase='moving';self.used_distance+=plan['distance']
                # Recheck cancellation directly before dispatch; no command is retried.
                if self.stop_event.is_set():continue
                if plan.get('kind')=='jog':
                    command=self.channel.jog(plan,lambda:self.stop_event.is_set() or self.closing.is_set() or self.clock()>self.hold_until)
                    if command is None:continue
                else:command=self.channel.move(plan)
                with self.lock:
                    self.accepted_at=self.clock();self.reason='移动指令已应答；等待真实反馈，松开可停止'
                    self._record('move_acknowledged',command=command)
        except Exception as exc:
            self.permit=None;self.plan=None;self.resume_context=None
            # A lost/malformed response makes delivery uncertain. Attempt stop
            # once on the SAME channel, never reconnect or resend a move.
            if self.channel and self.connected and not self.stop_handled:
                try:self.channel.stop()
                except Exception:pass
            with self.lock:
                self.stop_state='unconfirmed'
                self.phase='fault';self.reason='控制故障，不能确认停止：'+str(exc)
                try:self._record('fault',error=str(exc),stop_attempt=getattr(self.channel,'last_stop_attempt',None))
                except OSError:pass
        finally:
            if self.channel:
                try:self.channel.close()
                except OSError:pass
            with self.lock:self.connected=False;self.permit=None;self.plan=None

    def close(self):
        self.request_stop('关闭控制界面');self.closing.set()

    def shutdown(self):
        self.close()
        if self.worker and self.worker is not threading.current_thread():
            self.worker.join(timeout=2)
