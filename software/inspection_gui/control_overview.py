"""Presentation only. This module never authorizes or sends robot commands."""
import math,time

def workflow_state(state,mode,preview=False,executable=False,busy=False):
    phase=state['phase'];safety=state['safety']
    if safety.get('stop_state')=='unconfirmed':return '停止未确认','使用实体急停并检查设备反馈；不要继续操作。','error'
    if phase in ('stopping','verifying_stop'):return '正在停止并核对','等待实机反馈确认；旧目标不会自动续跑。','warning'
    if phase=='queued':return '运动请求核验中','等待控制器处理；可随时点击停止。','warning'
    if phase=='moving':return '实机运动中','观察实物及反馈；停止按钮始终可用。','warning'
    if phase in ('latched','fault'):return ('已停止' if phase=='latched' else '控制异常'),state['reason'],'warning' if phase=='latched' else 'error'
    if busy:return '正在生成模型预览','仅计算模型路径，尚未发送运动。','info'
    if not state['connected']:return '控制未连接',('模型预览已生成；实机执行仍需连接并满足控制条件。' if preview else '先连接控制；可以独立查看实时反馈或模型预览。'),'info'
    if phase=='locked':return '待启用控制','核对工具和现场，再启用本轮控制。','info'
    if not safety.get('feedback_ok'):return '反馈条件未满足',safety.get('feedback_reason','检查反馈连接。'),'warning'
    if safety.get('wall_reason'):return '安全墙条件未满足',safety['wall_reason'],'warning'
    if executable:return '可执行','核对目标和路径后，点击执行。' if mode==2 else '按住执行，松开请求停止。','ready'
    if mode==0:return '可点动','按住方向移动，松开即请求停止。','ready'
    if preview:return '预览已生成 · 暂不可执行','检查下方提示与控制条件；播放模型不会驱动实机。','info'
    return '尚未预览','设置目标并规划预览。' if mode==2 else '设置距离和速度，再选择方向。','info'

def target_summary(frame,target,now=None):
    try:
        values=list(target)[:3]
        if len(values)!=3 or not all(math.isfinite(float(x)) for x in values):raise ValueError()
        text='X %.3f   Y %.3f   Z %.3f mm'%tuple(values)
        stamp=frame['received_monotonic'];age=(time.monotonic() if now is None else now)-stamp
        if not math.isfinite(age) or not 0<=age<=.2:return text+'\n反馈已过期，距离不可用'
        distance=math.dist(frame['pose'][:3],values)
        return text+f'\n距当前反馈位置 {distance:.3f} mm（直线距离）'
    except (ValueError,TypeError,KeyError,OverflowError):return '目标或当前反馈不可用'
