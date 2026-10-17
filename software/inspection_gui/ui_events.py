"""Bounded diagnostic history; disk writes run outside UI/feedback/stop paths."""
import copy,json,threading,queue,time
from collections import deque
from datetime import datetime,timezone,timedelta
from .target_task import BUILD_ID
class EventJournal:
    def __init__(self):
        self.events=deque(maxlen=500);self.lock=threading.RLock();self.revision=0;self.path=None
        self.pending=queue.Queue(maxsize=512);self.worker=None;self.save_error='';self.dropped=0;self.last={}
    def configure(self,path):
        with self.lock:
            if path==self.path:return
            self.path=path;self.events.clear();self.last.clear();self.revision+=1
        if self.worker is None:
            self.worker=threading.Thread(target=self._write,daemon=True,name='ui-event-log');self.worker.start()
        self.pending.put_nowait((path,None))
    def record(self,message,level='info',source='软件',hint='',details=None):
        source={'ManualControlDialog':'实机控制','ProbeWorkspaceDialog':'测头任务','SafetyWallDialog':'安全墙','SphereAnalysisDialog':'白球分析','CircleMeasurementPage':'圆孔测量','DevicePage':'设备连接','EventHistoryPage':'运行日志','ConfigHistoryPage':'配置版本'}.get(source,source)
        key=(source,level,str(message));now=time.monotonic()
        with self.lock:
            if now-self.last.get(key,-10)<5:return
            self.last[key]=now
            if len(self.last)>1000:self.last={key:now}
            event=dict(time=datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds'),level=level,source=source,
                message=str(message),next_step=hint or '',details=copy.deepcopy(details),build_id=BUILD_ID)
            self.events.append(event);self.revision+=1;path=self.path
        if path:
            try:self.pending.put_nowait((path,event))
            except queue.Full:self.dropped+=1;self.save_error='诊断日志队列已满，请导出内存中的事件记录'
    def snapshot(self):
        with self.lock:return copy.deepcopy(list(self.events))
    def _write(self):
        while True:
            path,event=self.pending.get()
            try:
                if event is None:
                    if path.exists():
                        previous=[]
                        with path.open('r',encoding='utf-8') as stream:
                            for line in deque(stream,maxlen=500):
                                try:
                                    value=json.loads(line)
                                    if isinstance(value,dict) and all(isinstance(value.get(k),str) for k in ('time','level','source','message')):previous.append(value)
                                except (ValueError,TypeError):pass
                        with self.lock:
                            if self.path==path:
                                self.events=deque(previous+list(self.events),maxlen=500);self.revision+=1
                    continue
                path.parent.mkdir(parents=True,exist_ok=True)
                with path.open('a',encoding='utf-8') as stream:stream.write(json.dumps(event,ensure_ascii=False,allow_nan=False)+'\n')
                self.save_error=''
            except (OSError,ValueError,TypeError) as exc:self.save_error=str(exc)
            finally:self.pending.task_done()
_journal=EventJournal()
def journal():return _journal
