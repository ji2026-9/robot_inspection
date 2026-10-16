"""DI1 rising-edge samples for workflow checks; NOT hardware-latched metrology.

DI1 is bit zero of the V4 DigitalInputs uint64. Signal is active high in
this installation, to be confirmed against the actual touch/release test.
"""
import copy, json, math
from pathlib import Path
from datetime import datetime, timezone
from .probe_workspace import capture_position, atomic_json,validate_position


def di1_state(frame):
    if not frame or type(frame.get('digital_inputs')) is not int:
        return None
    value=frame['digital_inputs']
    return bool(value & 1) if 0 <= value < 2**64 else None


class ProbeEdgeTracker:
    def __init__(self):self.reset()

    def reset(self):
        self.previous=None;self.last_time=None;self.configuration=None;self.controller_time=None

    def feed(self,frame):
        state=di1_state(frame)
        if state is None:self.reset();return None
        now=frame['received_monotonic']
        if not math.isfinite(now):self.reset();return None
        config=(frame['user_index'],frame['tool_index'],tuple(frame['tool_offset']),tuple(frame['user_offset']))
        stamp=frame.get('controller_timestamp_ms')
        # Windows clock resolution / queued TCP frames can share a host tick.
        gap=self.last_time is None or not 0 <= now-self.last_time <= .25
        restart=stamp is not None and self.controller_time is not None and (stamp < self.controller_time or stamp-self.controller_time>250)
        changed=config!=self.configuration
        rising=not gap and not restart and not changed and self.previous is False and state
        interval=None if self.last_time is None else (now-self.last_time)*1000
        previous_stamp=self.controller_time
        self.previous=state;self.last_time=now;self.configuration=config;self.controller_time=stamp
        if not rising:return None
        record=capture_position('测头触发_'+datetime.fromtimestamp(frame['received_at']).strftime('%H%M%S_%f'),frame)
        record.update(event_type='probe_trigger',di_channel=1,active_level=1,
            digital_inputs=frame['digital_inputs'],digital_outputs=frame.get('digital_outputs'),
            controller_timestamp_ms=stamp,previous_controller_timestamp_ms=previous_stamp,
            feedback_interval_ms=interval,controller_latched=False,
            physical_contact_confirmed=False,calibration_sample_verified=False,
            timing_note='DI1 低→高后收到的第一帧位姿；不是控制器触发锁存坐标，可能漏掉短于反馈周期的脉冲。')
        return record


class TriggerJournal:
    """One atomic file per event; a failed save leaves the event pending for retry."""
    def __init__(self,directory):
        self.directory=Path(directory);self.records=[];self.load_errors=[]
        if self.directory.exists():
            for path in sorted(self.directory.glob('*.json')):
                try:
                    item=json.loads(path.read_text(encoding='utf-8'))
                    if item.get('event_type')!='probe_trigger':raise ValueError('不是触发记录')
                    item=validate_position(item)
                    interval=item.get('feedback_interval_ms')
                    if type(interval) not in (int,float) or not math.isfinite(interval) or not 0<=interval<=250:raise ValueError('触发间隔无效')
                    if item.get('di_channel')!=1 or item.get('active_level')!=1:raise ValueError('触发通道不兼容')
                    item.update(controller_latched=False,calibration_sample_verified=False,hardware_executable=False)
                    self.records.append(item)
                except (OSError,ValueError,AttributeError,KeyError,TypeError) as exc:self.load_errors.append(path.name+': '+str(exc))

    def save(self,event):
        item=copy.deepcopy(event);identifier=item['id']
        if not isinstance(identifier,str) or len(identifier)!=32 or any(c not in '0123456789abcdef' for c in identifier):
            raise ValueError('无效触发记录编号')
        if any(r['id']==identifier for r in self.records):return
        item.update(controller_latched=False,calibration_sample_verified=False,hardware_executable=False)
        atomic_json(self.directory/(identifier+'.json'),item)
        self.records.append(item)

    def export(self,path):
        atomic_json(path,dict(schema_version=1,exported_at=datetime.now(timezone.utc).isoformat(),
            source='received_feedback_di1_rising_edge',controller_latched=False,
            calibration_verified=False,hardware_executable=False,events=self.records))
