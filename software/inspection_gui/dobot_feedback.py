"""V4 feedback receiver; optional stop-only monitor is disabled by default.

Layout source: Dobot-Arm/TCP-IP-Python-V4, MyType in dobot_api.py.
https://github.com/Dobot-Arm/TCP-IP-Python-V4/blob/main/dobot_api.py
"""
import copy
import math
import socket
import struct
import threading
import time
from collections import deque
from .probe_trigger import ProbeEdgeTracker
from .probe_stop import ProbeStopMonitor,PoseStabilityTracker


def decode_frame(data):
    if len(data) != 1440 or struct.unpack_from('<H',data)[0] != 1440:
        raise ValueError('反馈包长度不兼容')
    if struct.unpack_from('<Q',data,48)[0] != 0x123456789abcdef:
        raise ValueError('反馈协议校验失败')
    joints = struct.unpack_from('<6d',data,432)
    pose = struct.unpack_from('<6d',data,624)
    user_offset = struct.unpack_from('<6d',data,1200)
    tool_offset = struct.unpack_from('<6d',data,1248)
    joint_speeds = struct.unpack_from('<6d',data,480)
    tcp_speeds = struct.unpack_from('<6d',data,672)
    # Official V4 layout: SpeedScaling is a float64 at byte 64.
    # VelocityRatio (byte 1016) is a distinct field and can be zero while
    # SpeedScaling still reports the active controller global percentage.
    speed_scaling=struct.unpack_from('<d',data,64)[0]
    speed_percent=speed_scaling if math.isfinite(speed_scaling) and 0<=speed_scaling<=100 else None
    if not all(math.isfinite(v) for v in joints+pose+user_offset+tool_offset+joint_speeds+tcp_speeds):
        raise ValueError('反馈坐标无效')
    return {'joints':list(joints),'pose':list(pose),
            'joint_speeds':list(joint_speeds),'tcp_speeds':list(tcp_speeds),
            'digital_inputs':struct.unpack_from('<Q',data,8)[0],
            'digital_outputs':struct.unpack_from('<Q',data,16)[0],
            'user_offset':list(user_offset),'tool_offset':list(tool_offset),
            'mode':struct.unpack_from('<Q',data,24)[0],
            'controller_timestamp_ms':struct.unpack_from('<Q',data,32)[0],
            'tool_index':data[1013], 'user_index':data[1012],
            'speed_percent':speed_percent,'velocity_ratio_raw':int(data[1016]),
            'enabled':bool(data[1026]), 'running':bool(data[1028]),
            'error':bool(data[1029]), 'received_at':time.time(),
            'received_monotonic':time.monotonic()}


def receive_frame(sock):
    data=bytearray()
    while len(data)<1440:
        chunk=sock.recv(1440-len(data))
        if not chunk:
            raise ConnectionError('反馈连接已关闭')
        data.extend(chunk)
    return decode_frame(data)


class DobotFeedback:
    """Receive-only connection with generation-scoped socket lifetime."""
    def __init__(self):
        self.sock=None;self.latest=None;self.error='';self.worker=None
        self.identity=None;self.address=None;self.generation=0;self.identity_busy=False
        self.stop_event=threading.Event();self.lock=threading.RLock()
        self.probe_tracker=ProbeEdgeTracker();self.probe_events=deque(maxlen=512);self.probe_sequence=0
        self.stop_monitor=ProbeStopMonitor()
        self.pose_stability=PoseStabilityTracker()
        self.manual_control=None

    def _observe_probe(self,frame):
        # Called under receiver lock for EVERY frame, not the slower GUI timer.
        frame['pose_stable']=self.pose_stability.feed(frame)
        if self.manual_control is not None:
            active=self.stop_monitor.snapshot()['state'] in ('armed','pending','acknowledged')
            self.manual_control.observe(frame,self.generation,active)
        self.stop_monitor.observe(frame,self.generation)
        event=self.probe_tracker.feed(frame)
        if event is not None:
            self.probe_sequence+=1;event.update(event_sequence=self.probe_sequence,
                feedback_generation=self.generation,controller_address=self.address)
            self.probe_events.append(event)

    def probe_events_since(self,sequence):
        with self.lock:
            oldest=self.probe_events[0]['event_sequence'] if self.probe_events else self.probe_sequence+1
            return dict(events=copy.deepcopy([e for e in self.probe_events if e['event_sequence']>sequence]),
                latest_sequence=self.probe_sequence,missed_events=max(0,oldest-sequence-1))

    def connect(self,settings):
        port=int(settings.get('port') or 30004)
        if port!=30004:raise ValueError('只读反馈仅允许端口 30004，不连接控制端口。')
        self.disconnect()
        with self.lock:generation=self.generation
        sock=socket.create_connection((settings['address'],30004),timeout=2)
        sock.settimeout(2)
        try:first=receive_frame(sock)
        except Exception:
            sock.close();raise
        with self.lock:
            if generation!=self.generation:
                sock.close();return False
            self.sock=sock;self.address=settings['address'];self.latest=first;self.error=''
            self._observe_probe(first)
            stop=threading.Event();self.stop_event=stop
            self.worker=threading.Thread(target=self._receive,args=(sock,generation,stop),daemon=True,name='robot-feedback-receiver')
            self.worker.start()
        self.refresh_identity();return True

    def refresh_identity(self):
        with self.lock:
            if self.identity_busy or not self.is_connected():return
            generation=self.generation;address=self.address;self.identity_busy=True
        def query():
            from .robot_identity import read_identity
            try:result=read_identity(address)
            except Exception as error:
                result={'address':address,'received_at':time.time(),'responses':{},'errors':{'identity':str(error)}}
            with self.lock:
                if generation==self.generation:self.identity=result;self.identity_busy=False
        threading.Thread(target=query,daemon=True,name='robot-identity-read').start()

    def _receive(self,sock,generation,stop):
        try:
            while not stop.is_set():
                frame=receive_frame(sock)
                with self.lock:
                    if generation!=self.generation:return
                    self.latest=frame
                    self._observe_probe(frame)
        except (OSError,ValueError,ConnectionError) as error:
            with self.lock:
                if not stop.is_set() and generation==self.generation:self.error=str(error)
        finally:
            sock.close()
            with self.lock:
                if generation==self.generation:
                    if self.manual_control is not None:self.manual_control.request_stop('只读反馈断开')
                    self.stop_monitor.disconnected();self.sock=None

    def is_connected(self):
        with self.lock:
            return bool(self.latest and not self.error and self.sock is not None
                and 0<=time.monotonic()-self.latest['received_monotonic']<2)

    def snapshot(self):
        with self.lock:return copy.deepcopy(self.latest) if self.is_connected() else None

    def disconnect(self):
        with self.lock:
            if self.manual_control is not None:self.manual_control.close()
            self.stop_monitor.disconnected()
            self.generation+=1;self.identity=None;self.identity_busy=False;self.address=None
            self.stop_event.set();sock=self.sock;worker=self.worker
            self.sock=None;self.worker=None;self.latest=None;self.error=''
            self.probe_tracker.reset()
            self.pose_stability.reset()
        if sock:
            try:sock.shutdown(socket.SHUT_RDWR)
            except OSError:pass
            sock.close()
        if worker and worker is not threading.current_thread():worker.join(timeout=.3)
        if self.manual_control is not None:self.manual_control.shutdown()


if __name__=='__main__':
    import json
    with socket.create_connection(('192.168.5.1',30004),timeout=3) as probe:
        probe.settimeout(3)
        print(json.dumps(receive_frame(probe)))
