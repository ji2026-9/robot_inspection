"""One applied wall per workspace; software checks, never hardware certification."""
import copy,hashlib,json,threading,weakref,time
from pathlib import Path
from PySide6.QtCore import QObject,Signal,QTimer
from shiboken6 import isValid
from .safety_wall import DEFAULT_WALL,load_wall,validate_wall,save_wall

DEFAULT_PATH=Path(__file__).resolve().parents[1]/'data/probe_workspace/safety_wall.json'
_services={}

def wall_service(path=None):
    key=str(Path(path or DEFAULT_PATH).resolve())
    if key not in _services:_services[key]=GlobalWall(Path(key))
    return _services[key]

class GlobalWall(QObject):
    changed=Signal(object)
    status_changed=Signal()
    alert=Signal(object)
    def __init__(self,path):
        super().__init__();self.path=path;self.lock=threading.RLock();self.wall=dict(DEFAULT_WALL)
        self.error='';self.revision=0;self.callbacks=[];self.last_clearance=None;self.last_checked=0.;self.last_notice=''
        self.load();self.stamp=self.file_stamp()
        self.timer=QTimer(self);self.timer.setInterval(500);self.timer.timeout.connect(self.reload_if_changed);self.timer.start()
    def file_stamp(self):
        try:s=self.path.stat();return s.st_mtime_ns,s.st_size
        except OSError:return None
    def snapshot(self):
        with self.lock:return copy.deepcopy(self.wall)
    def display(self):
        wall=self.snapshot();wall['visible']=bool(wall['direction_confirmed']);return wall
    def reason(self):
        with self.lock:
            w=self.wall
            if self.error:return '安全墙配置读取失败：'+self.error
            if not w['direction_confirmed'] or not w['wall_confirmed']:return '墙位置未确认，本软件实机运动锁定'
            if not w['tool_envelope_confirmed']:return '工具包络未确认，本软件实机运动锁定'
            return ''
    def summary(self):
        reason=self.reason()
        if reason:return '全局安全墙 · '+reason
        if self.last_notice:return '全局安全墙预警 · '+self.last_notice
        w=self.snapshot();return f"全局安全墙 · 软件检查已配置（非控制器安全平面） · {w['yaw_deg']:g}° / {w['distance_mm']:g} mm · 停止预留 {w['stop_reserve_mm']:g} mm"
    def publish(self,data,error=''):
        with self.lock:
            self.wall=validate_wall(data);self.error=error;self.revision+=1;self.last_clearance=None;self.last_notice=''
            callbacks=list(self.callbacks)
        # Never keep the configuration lock while requesting a controller stop.
        for callback in callbacks:callback()
        self.changed.emit(self.display());self.status_changed.emit()
    def report_check(self,clearance,notice=''):
        with self.lock:
            notify=notice!=self.last_notice;self.last_notice=notice
            self.last_clearance=clearance;self.last_checked=time.monotonic()
        if notify:self.status_changed.emit()
    def warn(self,message,source='实机运动'):
        # Signals are queued to the GUI; never wait for acknowledgement here.
        self.alert.emit(dict(message=str(message),source=source))
    def load(self):
        try:self.publish(load_wall(self.path))
        except (OSError,ValueError,TypeError) as exc:self.publish(dict(DEFAULT_WALL),str(exc))
    def apply(self,data):
        result=save_wall(self.path,data);self.stamp=self.file_stamp();self.publish(result);return result
    def reload_if_changed(self):
        stamp=self.file_stamp()
        if stamp!=self.stamp:self.stamp=stamp;self.load()
    def attach_scene(self,scene):
        previous=getattr(scene,'_global_wall_service',None)
        if previous is self:return
        if previous is not None:
            try:previous.changed.disconnect(scene._wall_receiver)
            except (RuntimeError,TypeError):pass
        reference=weakref.ref(scene)
        def receive(data):
            obj=reference()
            if obj is not None and isValid(obj):obj.set_safety_wall(data)
        scene._global_wall_service=self;scene._wall_receiver=receive
        self.changed.connect(receive);scene.set_safety_wall(self.display())
    def bind_controller(self,controller):
        ref=weakref.ref(controller)
        def changed():
            obj=ref()
            if obj is not None and (obj.permit or obj.resume_context or obj.phase in ('queued','moving')):
                obj.request_stop('全局安全墙配置变化，原目标已取消')
        self.callbacks.append(changed)
