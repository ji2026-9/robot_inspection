"""In-panel Cartesian preview. Only the owner may explicitly dispatch motion."""
import bisect,copy,math,threading,time
from pathlib import Path
import numpy as np
from PySide6.QtCore import QObject,Signal,QTimer,Qt,QSize
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QSlider,QApplication,QFrame,QToolButton,QSizePolicy
from .coordinate_target import validate_start,wall_fingerprint
from .safety_wall import load_wall
from .probe_workspace import cartesian_frames
from .joint_preview import compile_joint_preview,tcp_matrix
from .readonly_kinematics import pose_matrix
from .offline_planning import robot_frames


def fit_preview_view(frames,width,height,yaw=-58.,pitch=29.):
    """Fit the whole arm throughout the path, including conservative body padding."""
    points=[]
    for frame in frames[::max(1,len(frames)//24)]+frames[-1:]:
        points.extend(t[:3,3] for t in robot_frames(frame['joints'],(0,0,0)).values())
        points.append(np.asarray(frame['tip']))
    points=np.asarray(points);low=points.min(axis=0)-110;high=points.max(axis=0)+110
    corners=np.array([[x,y,z] for x in (low[0],high[0]) for y in (low[1],high[1]) for z in (low[2],high[2])])
    center=(low+high)/2;az,el=np.deg2rad([yaw,pitch])
    z=np.array([math.cos(az)*math.cos(el),math.sin(az)*math.cos(el),math.sin(el)])
    x=np.cross([0,0,1],z);x/=np.linalg.norm(x);y=np.cross(z,x)
    view=(corners-center)@np.array([x,y,z]).T
    tangent=math.tan(math.radians(37)/2);aspect=max(.1,width/max(1,height))
    distance=float(np.max(view[:,2]+np.maximum(np.abs(view[:,1])/tangent,np.abs(view[:,0])/(tangent*aspect))))+100
    return center,max(600.,distance)


def estimate_timing(distance,speed,scale):
    if type(speed) not in (int,float) or not math.isfinite(speed) or speed<1 or not float(speed).is_integer():
        raise ValueError('目标速度需为正整数 mm/s，实际允许值由控制器校验')
    known=type(scale) in (int,float) and math.isfinite(scale) and 0<scale<=100
    if type(scale) in (int,float) and scale==0:
        return dict(speed_mm_s=float(speed),speed_percent=0,effective_mm_s=0.,
            duration_seconds=None,scale_known=True)
    percent=float(scale) if known else 100.
    effective=speed*percent/100
    return dict(speed_mm_s=float(speed),speed_percent=scale,effective_mm_s=effective,
        duration_seconds=distance/effective,scale_known=known)


def build_preview(frame,xyz,generation,wall,mesh_path,cancelled=lambda:False,speed=5,*,validation_time=None):
    start=copy.deepcopy(validate_start(frame,now=validation_time));xyz=list(xyz)
    if len(xyz)!=3 or any(type(v) not in (int,float) or not math.isfinite(v) or abs(v)>2500 for v in xyz):
        raise ValueError('目标XYZ需为−2500至2500 mm内的有限数值')
    target=xyz+start['pose'][3:];distance=math.dist(xyz,start['pose'][:3])
    if distance<.01:raise ValueError(f'目标与当前起点重合或过近（距离 {distance:.4f} mm，小于0.01 mm），无需重复移动')
    if distance>2000:raise ValueError(f'目标距离 {distance:.2f} mm，超过单段2000 mm范围')
    timing=estimate_timing(distance,speed,start.get('speed_percent'))
    task=dict(schema_version=1,coordinate_frame='robot_b_base',user_index=0,preview_only=True,hardware_executable=False,tool_index=start['tool_index'],
        waypoints=[dict(stage='起点',tcp_pose=start['pose']),dict(stage='目标',tcp_pose=target)])
    samples=max(2,math.ceil(distance/4))
    frames,report=compile_joint_preview(cartesian_frames(task,samples=samples),start['tool_offset'],start['joints'],cancelled=cancelled)
    if cancelled() or report.get('cancelled'):raise InterruptedError('已取消预览')
    if not report.get('complete') or not frames:
        raise ValueError('无法生成完整连续关节路径：'+str((report.get('failure') or {}).get('reason','逆解不完整')))
    q=np.deg2rad(start['joints'])
    model=tcp_matrix(q,pose_matrix(start['tool_offset']))
    gap=float(np.linalg.norm(model[:3,3]-np.asarray(start['pose'][:3])))
    # Start exactly at the observed joints, rather than quietly substituting IK.
    seed=dict(frames[0],joints=q,tip=np.asarray(start['pose'][:3]),rotation=pose_matrix(start['pose'])[:3,:3],stage='实测起点',ik_valid=True)
    frames=[seed]+frames;report['tool_offset']=start['tool_offset'];task['joint_preview_report']=report
    task['preview_tool_offset']=start['tool_offset'];collision=None
    if wall['direction_confirmed']:
        from .wall_collision import load_collision_meshes,check_path
        meshes=load_collision_meshes(mesh_path)
        radius=wall['tool_radius_mm']+gap if wall.get('tool_envelope_confirmed') else None
        collision=check_path(meshes,[f['joints'] for f in frames],wall,start['tool_offset'],radius,cancelled=cancelled)
        if collision['collision'] or collision['minimum_clearance_mm']<max(15,wall['stop_reserve_mm']):
            raise ValueError(f"预览路径接近或进入安全墙禁区，最小显示模型间隙 {collision['minimum_clearance_mm']:.2f} mm")
    return dict(start=start,target=target,generation=generation,task=task,frames=frames,
        distance=distance,model_gap_mm=gap,wall_fingerprint=wall_fingerprint(wall),wall=wall,collision=collision,
        timing=timing,complete=True,hardware_executable=False)


def build_route_preview(frame,targets,generation,wall,mesh_path,cancelled=lambda:False,speed=5):
    if not isinstance(targets,list) or not 1<=len(targets)<=20:raise ValueError('请添加1–20个目标位置')
    validation_time=time.monotonic();validate_start(frame,now=validation_time)
    current=copy.deepcopy(frame);parts=[]
    for index,xyz in enumerate(targets):
        try:part=build_preview(current,xyz,generation,wall,mesh_path,cancelled,speed,validation_time=validation_time)
        except ValueError as exc:raise ValueError(f'第 {index+1} 个执行目标（XYZ：{xyz}）：{exc}') from exc
        for f in part['frames']:f['stage']=f'目标 {index+1}'
        parts.append(part);current=copy.deepcopy(current)
        current['pose']=part['target'][:];current['joints']=np.rad2deg(part['frames'][-1]['joints']).tolist()
    result=dict(parts[0]);result['targets']=[part['target'] for part in parts]
    result['target']=parts[-1]['target'];result['distance']=sum(part['distance'] for part in parts)
    result['frames']=[f for part in parts for f in part['frames']]
    result['task']=dict(parts[0]['task'],waypoints=[parts[0]['task']['waypoints'][0]]+[dict(stage=f'目标 {i+1}',tcp_pose=part['target']) for i,part in enumerate(parts)])
    result['timing']=estimate_timing(result['distance'],speed,frame.get('speed_percent'))
    return result


def validate_preview(plan,frame,generation,wall=None):
    validate_start(frame)
    if not plan or not plan.get('complete') or not plan.get('frames'):raise ValueError('请先生成完整预览')
    if plan['generation']!=generation:raise ValueError('连接已变化，请重新预览')
    start=plan['start']
    if plan.get('timing') and frame.get('speed_percent')!=plan['timing']['speed_percent']:
        raise ValueError('控制器全局倍率已变化，请重新预览运行时间')
    for key in ('user_index','tool_index','tool_offset','user_offset'):
        if frame[key]!=start[key]:raise ValueError('工具或坐标配置已变化，请重新预览')
    if math.dist(frame['pose'][:3],start['pose'][:3])>.1 or max(abs(a-b) for a,b in zip(frame['joints'],start['joints']))>.1:
        raise ValueError('实际起点已变化，请重新预览')
    if max(abs((a-b+180)%360-180) for a,b in zip(frame['pose'][3:],start['pose'][3:]))>.1:
        raise ValueError('实际姿态已变化，请重新预览')
    if wall is not None and wall_fingerprint(wall)!=plan['wall_fingerprint']:raise ValueError('安全墙设置已变化，请重新预览')
    return plan['target'][:]


class PreviewSignals(QObject):
    completed=Signal(int,object,str)


class HeadlessScene(QWidget):
    """No GPU allocation on the Qt offscreen test platform."""
    def __init__(self):super().__init__();self.manual_active=False;self.live_frame=None
    def set_live_frame(self,frame,enabled):self.live_frame=frame
    def set_manual_preview(self,task,frames,seed):self.manual_active=task is not None;self.manual_task=task;self.manual_frames=frames;self.manual_index=0
    def set_safety_wall(self,wall):self.safety_wall=wall
    def set_wall_test_result(self,result):pass
    def reset_view(self):pass


def viewport_rect(width,height,aspect=None):
    """Fit a regular CAD viewport without stretching the camera projection."""
    width=max(1,int(width));height=max(1,int(height))
    aspect=max(1.2,min(2.2,width/height)) if aspect is None else aspect
    w=min(width,max(1,round(height*aspect)));h=min(height,max(1,round(w/aspect)))
    return (width-w)//2,(height-h)//2,w,h

class PreviewViewport(QFrame):
    def __init__(self,scene,parent=None):
        super().__init__(parent);self.scene=scene;scene.setParent(self);scene.show()
        self.setObjectName('previewViewport');self.setAccessibleName('三维路径视口')
        self.setStyleSheet('QFrame#previewViewport{background:#eaf0f6;border:1px solid #dbe4ee;border-radius:8px;}')
        self.setMinimumSize(280,180);self.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Expanding)
    def sizeHint(self):return QSize(800,500)
    def resizeEvent(self,event):
        super().resizeEvent(event);self.scene.setGeometry(*viewport_rect(self.width(),self.height()))

class ManualPreview(QWidget):
    changed=Signal()
    expand_requested=Signal(bool)
    feedback=Signal(str,bool)
    def __init__(self,workspace,parent=None):
        super().__init__(parent);self.workspace=workspace;self.plan=None;self.busy=False;self.revision=0;self.closed=False
        self.wall_path=workspace.storage_path.parent/'safety_wall.json'
        self.mesh_path=Path(__file__).parent/'assets/local_dobot_cr5.npz'
        self.signals=PreviewSignals(self);self.signals.completed.connect(self.finished)
        self.clock=time.monotonic;self.elapsed=0.;self.anchor=0.;self.duration=0.;self.distances=[]
        root=QVBoxLayout(self);root.setContentsMargins(8,8,8,8);root.setSpacing(6)
        head=QHBoxLayout();title=QLabel('姿态与路径预览 · 仅模型，不驱动实机');title.setObjectName('section');head.addWidget(title);head.addStretch()
        self.live_button=QPushButton('实时姿态');self.live_button.clicked.connect(lambda:self.clear('已返回实时姿态；指定坐标需重新预览'))
        head.addWidget(self.live_button);reset=QPushButton('恢复视角');head.addWidget(reset)
        self.expand_button=QPushButton('放大预览');self.expand_button.setCheckable(True);self.expand_button.toggled.connect(self.expand_requested.emit);head.addWidget(self.expand_button)
        self.details_button=QToolButton();self.details_button.setText('详情');self.details_button.setCheckable(True);head.addWidget(self.details_button)
        for button in (self.live_button,reset,self.expand_button):button.setStyleSheet('padding:6px 8px;font-size:12px;')
        root.addLayout(head)
        if QApplication.platformName()=='offscreen':self.scene=HeadlessScene()
        else:
            from .simulation_scene3d import Scene3D
            self.scene=Scene3D()
        self.scene.probe_only=True;self.scene.distance=1900;self.scene.setMinimumSize(1,1)
        from .global_wall import wall_service
        self.wall_service=wall_service(self.wall_path);self.wall_service.attach_scene(self.scene)
        reset.setText('适配视角');reset.clicked.connect(self.fit_view);self.viewport=PreviewViewport(self.scene);root.addWidget(self.viewport,1)
        row=QHBoxLayout();self.play=QPushButton('播放路径');self.play.clicked.connect(self.toggle);self.play.setEnabled(False);row.addWidget(self.play)
        self.slider=QSlider(Qt.Horizontal);self.slider.valueChanged.connect(self.seek);self.slider.setRange(0,0);row.addWidget(self.slider,1)
        self.progress=QLabel('0.0 / 0.0 秒');row.addWidget(self.progress);root.addLayout(row)
        self.virtual_pose=QLabel('生成路径后显示虚拟 TCP 坐标与已移动距离')
        self.virtual_pose.setWordWrap(True);self.virtual_pose.setStyleSheet('color:#214567;font-size:12px;font-weight:600;')
        root.addWidget(self.virtual_pose)
        self.summary=QLabel('显示实时姿态；生成路径后可按预计时间播放。');self.summary.setWordWrap(True);self.summary.setStyleSheet('color:#52677f;font-size:12px;');root.addWidget(self.summary)
        self.note=QLabel('实时显示当前关节；指定坐标模式下可先生成并播放路径。');self.note.setWordWrap(True);self.note.setObjectName('muted');root.addWidget(self.note);self.note.hide()
        self.details_button.toggled.connect(self.note.setVisible)
        self.timer=QTimer(self);self.timer.setInterval(33);self.timer.timeout.connect(self.tick)
        self.wall_service.changed.connect(self.wall_changed)

    def wall_changed(self,_):self.clear('全局安全墙已更新，请重新生成预览')

    def clear(self,message='参数已变化，请重新生成预览'):
        self.revision+=1;self.plan=None;self.busy=False;self.timer.stop();self.play.setText('播放路径');self.play.setEnabled(False)
        self.elapsed=0.;self.duration=0.;self.progress.setText('0.0 / 0.0 秒')
        self.virtual_pose.setText('生成路径后显示虚拟 TCP 坐标与已移动距离')
        self.scene.set_manual_preview(None,[],None);self.slider.setRange(0,0);self.note.setText(message);self.summary.setText(message);self.changed.emit()

    def generate(self,frame,xyz,generation,speed=5,*,purpose='targets',reference=None):
        self.clear('正在后台生成关节姿态与直线路径…');token=self.revision;self.busy=True
        start=copy.deepcopy(frame);target=list(xyz);signals=self.signals;wall_path=self.wall_path;mesh=self.mesh_path
        def work():
            try:
                builder=build_route_preview if target and isinstance(target[0],(list,tuple)) else build_preview
                plan=builder(start,target,generation,load_wall(wall_path),mesh,lambda:token!=self.revision or self.closed,speed=speed);plan['purpose']=purpose;plan['reference']=copy.deepcopy(reference);error=''
            except Exception as exc:plan=None;error=str(exc)
            try:signals.completed.emit(token,plan,error)
            except RuntimeError:pass
        threading.Thread(target=work,daemon=True,name='manual-target-preview').start();self.changed.emit()

    def finished(self,token,plan,error):
        if token!=self.revision or self.closed:return
        self.busy=False;self.timer.stop()
        if error:
            self.note.setText('预览未完成，不能执行；原因和处理方法见上方红色提示。')
            self.summary.setText('预览未完成；请按上方红色提示修正目标后重试。')
            self.feedback.emit('路径预览失败：'+error,True)
            if '安全墙禁区' in error:self.wall_service.warn(error,'虚拟预览')
            self.changed.emit();return
        self.plan=plan
        timing=plan.get('timing') or estimate_timing(plan['distance'],5,plan['start'].get('speed_percent'))
        self.duration=timing['duration_seconds'];self.elapsed=0.
        self.distances=[0.]
        for a,b in zip(plan['frames'],plan['frames'][1:]):
            self.distances.append(self.distances[-1]+float(np.linalg.norm(np.asarray(b['tip'])-np.asarray(a['tip']))))
        self.scene.set_manual_preview(plan['task'],plan['frames'],dict(joints_deg=plan['start']['joints']))
        stopped=self.duration is None
        self.slider.setRange(0,10000);self.slider.setValue(0);self.slider.setEnabled(not stopped)
        self.render_progress(0.);self.play.setEnabled(not stopped)
        self.fit_view()
        self.play.setText('倍率0% · 保持静止' if stopped else '播放路径')
        wall_note=('已检查连杆与已确认工具包络的安全墙间隙' if plan['collision'].get('tool_checked') else '已检查连杆安全墙间隙；工具包络未核验') if plan['collision'] else '安全墙未配置；未做工具碰撞检查'
        scale_note=f"全局倍率 {timing['speed_percent']:g}%" if timing['scale_known'] else '未读到全局倍率，暂按100%估算'
        time_note=('路径已生成；全局倍率为0，模型停在起点，不自动播放。' if stopped else f'预计 {self.duration:.1f} 秒，按1倍时间播放；未计控制器加减速及限速。')
        self.note.setText(f"路径 {plan['distance']:.2f} mm · 目标 {timing['speed_mm_s']:g} mm/s · {scale_note}\n{time_note}\n{wall_note}。模型预览不等于控制器实际插补。")
        self.summary.setText(f"路径 {plan['distance']:.2f} mm · {scale_note} · "+('倍率为0，保持静止' if stopped else f'预计 {self.duration:.1f} 秒（未计加减速）'))
        self.summary.setToolTip(self.note.text());self.details_button.setToolTip('展开速度、碰撞检查范围和模型限制说明')
        self.note.setToolTip(f"起点显示模型与反馈TCP差：{plan['model_gap_mm']:.3f} mm；软件模型未完成实物验证。")
        self.feedback.emit(f'路径预览已生成：'+('回到已保存原点 · ' if plan.get('purpose')=='origin' else '')+f'{len(plan.get("targets",[plan["target"]]))} 个目标，路径 {plan["distance"]:.2f} mm。',False)
        self.changed.emit()

    def update_live(self,frame):
        if self.plan is None:self.scene.set_live_frame(frame,True)

    def seek(self,value):
        if self.plan:
            if self.duration is None:
                self.elapsed=0.;self.render_progress(0.);return
            self.elapsed=self.duration*value/10000
            self.anchor=self.clock()-self.elapsed;self.render_progress(value/10000)

    def render_progress(self,fraction):
        if not self.plan:return
        frames=self.plan['frames'];position=self.distances[-1]*fraction
        index=max(0,min(len(frames)-2,bisect.bisect_right(self.distances,position)-1))
        length=self.distances[index+1]-self.distances[index]
        weight=(position-self.distances[index])/length if length>1e-10 else 1.
        a,b=frames[index:index+2];current=dict(a)
        # Interpolate verified adjacent samples; keep the original samples immutable.
        for key in ('joints','tip'):current[key]=np.asarray(a[key])*(1-weight)+np.asarray(b[key])*weight
        if fraction<=0:current=dict(frames[0])
        self.scene.manual_frames=[current];self.scene.manual_index=0;self.scene.update()
        tip=current['tip'];distance=self.plan['distance']*fraction
        self.virtual_pose.setText(f'虚拟 TCP：X {tip[0]:.2f}   Y {tip[1]:.2f}   Z {tip[2]:.2f} mm  ·  已移动 {distance:.2f} / {self.plan["distance"]:.2f} mm')
        self.virtual_pose.setToolTip('虚拟关节角（°）：'+' / '.join(f'{v:.2f}' for v in np.rad2deg(current['joints'])))
        self.progress.setText('倍率0% · 预计不运动' if self.duration is None else f'{self.elapsed:.1f} / {self.duration:.1f} 秒')

    def fit_view(self):
        frames=self.plan['frames'] if self.plan else []
        if not frames:
            self.scene.reset_view();return
        self.scene.yaw=-58.;self.scene.pitch=29.
        center,distance=fit_preview_view(frames,self.scene.width(),self.scene.height())
        self.scene.pan=center-np.array([0.,0.,450.]);self.scene.distance=distance;self.scene.update()

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if self.plan:QTimer.singleShot(0,self.fit_view)

    def toggle(self):
        if self.duration is None:return
        if self.timer.isActive():self.tick();self.timer.stop();self.play.setText('继续播放' if self.elapsed<self.duration else '重新播放')
        elif self.plan:
            if self.elapsed>=self.duration:self.seek(0);self.slider.setValue(0)
            self.anchor=self.clock()-self.elapsed;self.timer.start();self.play.setText('暂停预览')

    def tick(self):
        if not self.plan or self.duration is None:return
        self.elapsed=min(self.duration,max(0.,self.clock()-self.anchor))
        fraction=self.elapsed/self.duration
        self.slider.blockSignals(True);self.slider.setValue(round(fraction*10000));self.slider.blockSignals(False)
        self.render_progress(fraction)
        if self.elapsed>=self.duration:self.timer.stop();self.play.setText('重新播放')

    def hideEvent(self,event):self.timer.stop();super().hideEvent(event)
    def shutdown(self):self.closed=True;self.revision+=1;self.timer.stop()
