"""Camera acquisition and frozen-image target selection. No robot movement."""
import threading,time,math
import numpy as np
from PySide6.QtCore import QThread,Signal,Qt
from PySide6.QtWidgets import QLabel

class ClickablePhoto(QLabel):
    clicked=Signal(float,float)
    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton:self.clicked.emit(event.position().x(),event.position().y())
        super().mousePressEvent(event)

class CameraPreviewWorker(QThread):
    failed=Signal(str)
    def __init__(self,backend,parent=None):
        super().__init__(parent);self.backend=backend;self.stop_event=threading.Event();self.lock=threading.Lock();self.latest=None;self.received_at=0;self.received_wall=None;self.parameter_readback=None
    def run(self):
        try:
            if getattr(self.backend,'_inspection_parameter_busy',False):raise RuntimeError('相机参数操作尚未结束')
            self.backend._inspection_acquiring=True
            if not self.backend.start():raise RuntimeError('相机采集启动失败')
            if callable(getattr(self.backend,'get_parameters',None)):
                try:
                    self.parameter_readback={'received_at':time.time(),'values':self.backend.get_parameters()}
                except Exception as error:self.parameter_readback={'unavailable_reason':str(error)}
            while not self.stop_event.is_set():
                if not self.backend.is_connected():raise RuntimeError('相机连接已中断')
                frame=self.backend.get_frame()
                if frame is not None:
                    image=np.asarray(frame)
                    if image.ndim!=3 or image.shape[2]!=3 or image.dtype!=np.uint8:raise ValueError('相机驱动必须提供 uint8 BGR 三通道图像')
                    with self.lock:self.latest=image.copy();self.received_at=time.monotonic();self.received_wall=time.time()
                self.stop_event.wait(.03)
        except Exception as error:self.failed.emit(str(error))
        finally:
            self.backend._inspection_acquiring=False
            try:self.backend.stop()
            except Exception as error:self.failed.emit('相机停止失败：'+str(error))
    def snapshot(self):
        with self.lock:
            if self.latest is None or time.monotonic()-self.received_at>2:return None
            return self.latest.copy()
    def snapshot_packet(self):
        with self.lock:
            if self.latest is None or time.monotonic()-self.received_at>2:return None
            return {'frame':self.latest.copy(),'frame_received_at':self.received_wall,
                    'camera_parameters_actual':self.parameter_readback}
    def stop(self):self.stop_event.set()

def pick_hole(x,y,mapping,holes):
    if not mapping:return None
    if not(mapping['ox']<=x<mapping['ox']+mapping['tw'] and mapping['oy']<=y<mapping['oy']+mapping['th']):return None
    px=(x-mapping['ox'])/mapping['scale']+mapping['crop'][0]
    py=(y-mapping['oy'])/mapping['scale']+mapping['crop'][1]
    candidates=[]
    for hole in holes:
        e=hole.get('ellipse')
        if not e:continue
        cx,cy=e['center'];a,b=e['width']/2,e['height']/2
        if min(a,b)<=0:continue
        angle=math.radians(e['angle']);dx,dy=px-cx,py-cy
        u=dx*math.cos(angle)+dy*math.sin(angle);v=-dx*math.sin(angle)+dy*math.cos(angle)
        distance=(u/a)**2+(v/b)**2
        if distance<=1.15:candidates.append((distance,hole['id']))
    return min(candidates)[1] if candidates else None

def selected_targets(result,selected,automatic):
    reliable={h['id']:h for h in result.get('fitted_holes',[]) if h.get('reliable_center')}
    if automatic:
        if len(reliable)!=4 or result.get('detections')!=4:raise ValueError('自动全检需要识别四个孔并提供四个可靠圆心，请先复核漏检或拟合异常。')
        ids=sorted(reliable)
    else:
        ids=sorted(set(selected))
        if not ids:raise ValueError('请先选择本次要测的孔。')
        if any(hid not in reliable for hid in ids):raise ValueError('所选孔没有可靠圆心，请重新复核。')
    return [dict(reliable[hid]) for hid in ids]
