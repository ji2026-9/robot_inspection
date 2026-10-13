"""Receive-only V4 feedback. No control/dashboard commands exist here.

Layout source: Dobot-Arm/TCP-IP-Python-V4, MyType in dobot_api.py.
https://github.com/Dobot-Arm/TCP-IP-Python-V4/blob/main/dobot_api.py
"""
import copy
import math
import socket
import struct
import threading
import time


def decode_frame(data):
    if len(data) != 1440 or struct.unpack_from('<H',data)[0] != 1440:
        raise ValueError('反馈包长度不兼容')
    if struct.unpack_from('<Q',data,48)[0] != 0x123456789abcdef:
        raise ValueError('反馈协议校验失败')
    joints = struct.unpack_from('<6d',data,432)
    pose = struct.unpack_from('<6d',data,624)
    if not all(math.isfinite(v) for v in joints+pose):
        raise ValueError('反馈坐标无效')
    return {'joints':list(joints),'pose':list(pose),
            'mode':struct.unpack_from('<Q',data,24)[0],
            'controller_timestamp_ms':struct.unpack_from('<Q',data,32)[0],
            'tool_index':data[1013], 'user_index':data[1012],
            'speed_percent':int(data[1016]),
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
        except (OSError,ValueError,ConnectionError) as error:
            with self.lock:
                if not stop.is_set() and generation==self.generation:self.error=str(error)
        finally:
            sock.close()
            with self.lock:
                if generation==self.generation:self.sock=None

    def is_connected(self):
        with self.lock:
            return bool(self.latest and not self.error and self.sock is not None
                and time.monotonic()-self.latest['received_monotonic']<2)

    def snapshot(self):
        with self.lock:return copy.deepcopy(self.latest) if self.is_connected() else None

    def disconnect(self):
        with self.lock:
            self.generation+=1;self.identity=None;self.identity_busy=False;self.address=None
            self.stop_event.set();sock=self.sock;worker=self.worker
            self.sock=None;self.worker=None;self.latest=None;self.error=''
        if sock:
            try:sock.shutdown(socket.SHUT_RDWR)
            except OSError:pass
            sock.close()
        if worker and worker is not threading.current_thread():worker.join(timeout=.3)


if __name__=='__main__':
    import json
    with socket.create_connection(('192.168.5.1',30004),timeout=3) as probe:
        probe.settimeout(3)
        print(json.dumps(receive_frame(probe)))
