"""Lit OpenGL viewport using cached local DobotStudio display meshes.

Display kinematics and assumed workpiece geometry only; no device APIs.
"""
import json, math, os, ctypes, threading
from pathlib import Path
import numpy as np
from PySide6.QtCore import Qt, QPointF, QObject, Signal
from PySide6.QtGui import QColor,QPainter,QPen,QFont,QSurfaceFormat
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from .offline_planning import robot_frames,solve_visual_ik
try:
    from OpenGL import GL as gl
except ImportError:
    gl=None

def translation(x,y,z):
    t=np.eye(4);t[:3,3]=[x,y,z];return t

def mesh(vertices,faces,color):
    v=np.asarray(vertices,np.float32);f=np.asarray(faces,np.uint32)
    n=np.zeros_like(v);fn=np.cross(v[f[:,1]]-v[f[:,0]],v[f[:,2]]-v[f[:,0]])
    for i in range(3):np.add.at(n,f[:,i],fn)
    n/=np.maximum(np.linalg.norm(n,axis=1,keepdims=True),1e-9)
    return {'vertices':v,'normals':n,'faces':f,'color':color}

def box(a,b,color):
    x,y,z=a;X,Y,Z=b
    v=[(x,y,z),(X,y,z),(X,Y,z),(x,Y,z),(x,y,Z),(X,y,Z),(X,Y,Z),(x,Y,Z)]
    quads=[(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)]
    # Separate vertices retain crisp machined edges.
    vs=[];fs=[]
    for q in quads:
        k=len(vs);vs.extend(v[i] for i in q);fs.extend([(k,k+1,k+2),(k,k+2,k+3)])
    return mesh(vs,fs,color)

def cylinder(radius,length,color,inner=0,segments=48):
    v=[];f=[]
    for i in range(segments):
        a,b=i*2*np.pi/segments,(i+1)*2*np.pi/segments
        pa,pb=[radius*np.cos(a),radius*np.sin(a)],[radius*np.cos(b),radius*np.sin(b)]
        k=len(v);v.extend([pa+[0],pb+[0],pb+[length],pa+[length]])
        f.extend([(k,k+1,k+2),(k,k+2,k+3)])
        if inner:
            qa,qb=[inner*np.cos(a),inner*np.sin(a)],[inner*np.cos(b),inner*np.sin(b)]
            k=len(v);v.extend([qa+[0],qa+[length],qb+[length],qb+[0]])
            f.extend([(k,k+1,k+2),(k,k+2,k+3)])
            for zz in (0,length):
                k=len(v);v.extend([pa+[zz],pb+[zz],qb+[zz],qa+[zz]])
                f.extend([(k,k+1,k+2),(k,k+2,k+3)])
        else:
            for zz in (0,length):
                k=len(v);v.extend([[0,0,zz],pa+[zz],pb+[zz]]);f.append((k,k+1,k+2))
    return mesh(v,f,color)

def deck_cell(half_x,half_y,radius,color):
    v=[];f=[]
    # Include each rectangle corner direction so boundaries are exact.
    angles=np.unique(np.r_[np.linspace(0,2*np.pi,65),
        [math.atan2(y,x)%(2*np.pi) for x in (-half_x,half_x) for y in (-half_y,half_y)]])
    for a,b in zip(angles[:-1],angles[1:]):
        def point(t,outer):
            c,s=math.cos(t),math.sin(t)
            r=min(half_x/max(abs(c),1e-9),half_y/max(abs(s),1e-9)) if outer else radius
            return [r*c,r*s,0]
        k=len(v);v.extend([point(a,True),point(b,True),point(b,False),point(a,False)])
        f.extend([(k,k+1,k+2),(k,k+2,k+3)])
    return mesh(v,f,color)

class AssetSignals(QObject):
    loaded = Signal(object, object, str)


class Scene3D(QOpenGLWidget):
    def __init__(self,parent=None):
        super().__init__(parent)
        fmt=QSurfaceFormat();fmt.setVersion(2,1);fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CompatibilityProfile)
        fmt.setDepthBufferSize(24);fmt.setSamples(4);self.setFormat(fmt)
        self.setMinimumSize(280,240);self.setMouseTracking(True)
        self.yaw=-58.;self.pitch=29.;self.distance=2150.;self.pan=np.zeros(3)
        self.drag=None;self.phase=0.;self.plan=None;self.trajectory=[];self.frame_index=0
        self.meshes=[];self.parts=[];self.buffers={};self.ready=False;self.render_error=''
        self.live_frame=None;self.live_mode=False;self.geometry_key=None
        self.probe_only=False;self.manual_active=False;self.manual_task=None;self.manual_frames=[];self.manual_index=0;self.manual_seed=None;self.pose_audit=None
        self.asset_label='正在后台加载显示模型'
        self.camera_q=np.deg2rad([60,-65,105,50,90,0])
        self.asset_signals=AssetSignals(self)
        self.asset_signals.loaded.connect(self._assets_loaded)
        signals=self.asset_signals
        def load():
            models=[];label='程序化备用模型'
            path=Path(os.environ.get('INSPECTION_ROBOT_MESH',str(Path(__file__).parent/'assets'/'local_dobot_cr5.npz')))
            try:
                if path.is_file():
                    with np.load(path,allow_pickle=False) as a:
                        for i,meta in enumerate(json.loads(str(a['metadata']))):
                            models.append({'joint':meta['joint'],'color':meta['color'],
                                'vertices':np.ascontiguousarray(a[f'v{i}'],dtype=np.float32),
                                'normals':np.ascontiguousarray(a[f'n{i}'],dtype=np.float32),
                                'faces':np.ascontiguousarray(a[f'f{i}'],dtype=np.uint32)})
                    label='本机 DobotStudio CR5 系列显示模型'
            except (OSError,ValueError,KeyError) as exc:
                label='显示资源不可用，使用备用模型：'+str(exc)
            if not models:
                from .offline_planning import JOINT_OFFSETS
                for i,joint in enumerate(['base','J1','J2','J3','J4','J5','J6']):
                    body=cylinder(48 if i<2 else 30,65,[.82,.85,.88]);body['joint']=joint;models.append(body)
                    if 0<i<6:
                        offset=JOINT_OFFSETS[i];length=float(np.linalg.norm(offset));axis=offset/length
                        u=np.cross([0,0,1],axis)
                        if np.linalg.norm(u)<1e-8:u=np.array([1.,0,0])
                        u/=np.linalg.norm(u);v=np.cross(axis,u);r=np.column_stack([u,v,axis])
                        link=cylinder(25,length,[.83,.86,.9]);link['vertices']=np.ascontiguousarray(link['vertices']@r.T,dtype=np.float32)
                        link['normals']=np.ascontiguousarray(link['normals']@r.T,dtype=np.float32)
                        link['joint']=joint;models.append(link)
            q,_=solve_visual_ik([-200,-240,580],[-480,100,0],100)
            try:signals.loaded.emit(models,q,label)
            except RuntimeError:pass  # Window closed while loading.
        threading.Thread(target=load,daemon=True,name='robot-display-assets').start()

    def _assets_loaded(self,models,q,label):
        self.meshes=models;self.camera_q=q;self.asset_label=label;self.update()

    def set_live_frame(self,frame,enabled):
        self.live_mode=bool(enabled);self.live_frame=frame if enabled else None
        self.update()

    def set_manual_preview(self,task,frames,seed):
        self.manual_task=task;self.manual_frames=frames;self.manual_index=0;self.manual_seed=seed
        self.manual_active=task is not None
        if self.manual_active:self.live_mode=False
        self.update()

    def reset_view(self):
        self.yaw=-58.;self.pitch=29.;self.distance=2200. if self.probe_only else 2150.;self.pan[:]=0;self.update()

    def view_top(self):
        self.yaw=-90.;self.pitch=86.;self.distance=1500.;self.update()

    def mousePressEvent(self,e):self.drag=e.position();self.drag_button=e.button()
    def mouseReleaseEvent(self,e):self.drag=None
    def mouseMoveEvent(self,e):
        if self.drag is None:return
        d=e.position()-self.drag;self.drag=e.position()
        if self.drag_button==Qt.MouseButton.RightButton:
            self.pan[0]-=d.x()*self.distance/1100;self.pan[2]+=d.y()*self.distance/1100
        else:self.yaw+=d.x()*.4;self.pitch=float(np.clip(self.pitch+d.y()*.3,6,87))
        self.update()
    def wheelEvent(self,e):
        self.distance=float(np.clip(self.distance*(.88 if e.angleDelta().y()>0 else 1.12),600,4200));self.update()

    def set_plan(self,plan,trajectory):
        self.plan=plan;self.trajectory=trajectory;self.frame_index=0
        key=json.dumps(plan['config'],sort_keys=True) if plan else None
        if key!=self.geometry_key:
            self.parts=self._workpiece(plan) if plan else []
            self.geometry_key=key
        self.update()

    def initializeGL(self):
        self.buffers={};self.ready=False
        self.context().aboutToBeDestroyed.connect(self.cleanup_gl)
        if gl is None:self.render_error='缺少 PyOpenGL，请安装 requirements-simulation.txt';return
        try:
            gl.glEnable(gl.GL_DEPTH_TEST);gl.glEnable(gl.GL_NORMALIZE);gl.glEnable(gl.GL_MULTISAMPLE)
            gl.glEnable(gl.GL_LIGHTING);gl.glEnable(gl.GL_LIGHT0);gl.glEnable(gl.GL_LIGHT1)
            gl.glEnable(gl.GL_COLOR_MATERIAL);gl.glColorMaterial(gl.GL_FRONT_AND_BACK,gl.GL_AMBIENT_AND_DIFFUSE)
            gl.glLightModelfv(gl.GL_LIGHT_MODEL_AMBIENT,[.40,.40,.43,1])
            gl.glLightModeli(gl.GL_LIGHT_MODEL_TWO_SIDE,1)
            gl.glLightfv(gl.GL_LIGHT0,gl.GL_DIFFUSE,[.70,.70,.68,1]);gl.glLightfv(gl.GL_LIGHT1,gl.GL_DIFFUSE,[.25,.28,.34,1])
            gl.glMaterialfv(gl.GL_FRONT_AND_BACK,gl.GL_SPECULAR,[.3,.3,.3,1]);gl.glMaterialf(gl.GL_FRONT_AND_BACK,gl.GL_SHININESS,38)
            self.ready=True
        except Exception as exc:self.render_error=str(exc)

    def cleanup_gl(self):
        self.makeCurrent()
        if gl is not None:
            for entry in self.buffers.values():
                gl.glDeleteLists(entry['list'],1);gl.glDeleteBuffers(3,entry['ids'])
        self.buffers.clear();self.ready=False;self.doneCurrent()

    def _prune_buffers(self):
        keep={id(m) for m in self.meshes}
        keep.update(id(m) for m,_ in self.parts)
        keep.update(id(m) for m,_ in getattr(self,'camera_parts',[]))
        keep.update(id(m) for m,_ in getattr(self,'probe_parts',[]))
        for key in list(self.buffers):
            if key not in keep:
                entry=self.buffers.pop(key)
                gl.glDeleteLists(entry['list'],1);gl.glDeleteBuffers(3,entry['ids'])

    def _display(self,m):
        key=id(m)
        if key in self.buffers:
            gl.glCallList(self.buffers[key]['list']);return
        if key not in self.buffers:
            ids=gl.glGenBuffers(3)
            for bid,field,target,dtype in zip(ids,('vertices','normals','faces'),
                    (gl.GL_ARRAY_BUFFER,gl.GL_ARRAY_BUFFER,gl.GL_ELEMENT_ARRAY_BUFFER),
                    (np.float32,np.float32,np.uint32)):
                data=np.ascontiguousarray(m[field],dtype=dtype)
                gl.glBindBuffer(target,int(bid));gl.glBufferData(target,data.nbytes,data,gl.GL_STATIC_DRAW)
            self.buffers[key]={'ids':ids,'mesh':m,'count':np.asarray(m['faces']).size,'list':gl.glGenLists(1)}
        entry=self.buffers[key];v,n,f=entry['ids']
        gl.glEnableClientState(gl.GL_VERTEX_ARRAY);gl.glEnableClientState(gl.GL_NORMAL_ARRAY)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER,int(v));gl.glVertexPointer(3,gl.GL_FLOAT,0,ctypes.c_void_p(0))
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER,int(n));gl.glNormalPointer(gl.GL_FLOAT,0,ctypes.c_void_p(0))
        gl.glBindBuffer(gl.GL_ELEMENT_ARRAY_BUFFER,int(f))
        # The driver compiles indexed arrays directly; no Python triangle loop.
        gl.glNewList(entry['list'],gl.GL_COMPILE)
        gl.glDrawElements(gl.GL_TRIANGLES,entry['count'],gl.GL_UNSIGNED_INT,ctypes.c_void_p(0))
        gl.glEndList()
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER,0);gl.glBindBuffer(gl.GL_ELEMENT_ARRAY_BUFFER,0)
        gl.glDisableClientState(gl.GL_NORMAL_ARRAY);gl.glDisableClientState(gl.GL_VERTEX_ARRAY)
        gl.glCallList(entry['list'])

    def _draw(self,m,t,shadow=False):
        gl.glPushMatrix();gl.glMultMatrixf(np.asarray(t.T,np.float32))
        if shadow:gl.glColor3f(.82,.84,.87)
        else:gl.glColor3fv(m['color'])
        self._display(m);gl.glPopMatrix()

    def _workpiece(self,p):
        c=p['config'];pitch=c['bore_pitch_mm'];width=c['block_width_mm'];r=c['bore_diameter_mm']/2;z=c['deck_height_mm'];bottom=z-c['block_height_mm']
        parts=[]
        def put(m,t=np.eye(4)):parts.append((m,t))
        # Fixture and cast housing sides, open deck and genuinely hollow bores.
        put(box((-270,-120,80),(270,120,bottom),[.34,.39,.44]))
        for x in (-235,235):put(box((x-12,-90,0),(x+12,90,80),[.47,.51,.55]))
        half=2*pitch
        put(box((-half,-width/2,bottom),(half,-width/2+12,z-5),[.25,.29,.30]))
        put(box((-half,width/2-12,bottom),(half,width/2,z-5),[.25,.29,.30]))
        for x in (-half,half-12):put(box((x,-width/2,bottom),(x+12,width/2,z-5),[.3,.34,.35]))
        for h in p['holes']:
            x=h['center_world_mm'][0]
            put(deck_cell(pitch/2,width/2,r+2,[.72,.72,.68]),translation(x,0,z))
            put(cylinder(r+2,c['block_height_mm']-15,[.48,.51,.52],inner=r),translation(x,0,bottom+15))
            put(cylinder(r,1,[.09,.12,.14]),translation(x,0,bottom+14))
            put(cylinder(r+4,2,[.79,.79,.74],inner=r+1),translation(x,0,z-2))
            for yy in (-width/2+12,width/2-12):
                for xx in (-pitch*.32,pitch*.32):
                    put(cylinder(5.5,1.2,[.10,.13,.15]),translation(x+xx,yy,z+.1))
            for yy in (-width/2-5,width/2-12):
                put(box((x-12,yy,bottom+8),(x+12,yy+17,z-16),[.3,.34,.35]))
        self.camera_parts=[(box((-62,-14.5,50),(62,14.5,100),[.15,.19,.23]),np.eye(4)),
             (box((-52,-40,0),(52,-32,95),[.07,.36,.61]),np.eye(4))]
        for x in (-47.5,0,23.75,47.5):self.camera_parts.append((cylinder(6,1.5,[.04,.08,.12]),translation(x,0,100)))
        self.probe_parts=[(cylinder(21,65,[.63,.68,.72]),np.eye(4)),(cylinder(5,78,[.78,.79,.80]),translation(0,0,65)),(cylinder(c['probe_ball_diameter_mm']/2,2,[.85,.15,.24]),translation(0,0,143))]
        return parts

    def paintGL(self):
        if not self.ready:return
        self._prune_buffers()
        # QPainter's overlay changes GL state; restore it on every frame.
        gl.glUseProgram(0);gl.glDisable(gl.GL_SCISSOR_TEST);gl.glDisable(gl.GL_CULL_FACE)
        gl.glDepthMask(True);gl.glEnable(gl.GL_DEPTH_TEST);gl.glDepthFunc(gl.GL_LESS)
        gl.glEnable(gl.GL_NORMALIZE);gl.glEnable(gl.GL_LIGHTING)
        gl.glEnable(gl.GL_LIGHT0);gl.glEnable(gl.GL_LIGHT1);gl.glEnable(gl.GL_COLOR_MATERIAL)
        gl.glClearColor(.966,.977,.987,1);gl.glClear(gl.GL_COLOR_BUFFER_BIT|gl.GL_DEPTH_BUFFER_BIT)
        gl.glViewport(0,0,int(self.width()*self.devicePixelRatioF()),int(self.height()*self.devicePixelRatioF()))
        aspect=self.width()/max(1,self.height());gl.glMatrixMode(gl.GL_PROJECTION);gl.glLoadIdentity()
        n=10;half=n*math.tan(math.radians(37)/2);gl.glFrustum(-half*aspect,half*aspect,-half,half,n,8000)
        yaw,pitch=np.deg2rad([self.yaw,self.pitch]);target=np.array([0,0,450 if self.probe_only else 340])+self.pan
        eye=target+self.distance*np.array([math.cos(yaw)*math.cos(pitch),math.sin(yaw)*math.cos(pitch),math.sin(pitch)])
        z=(eye-target);z/=np.linalg.norm(z);x=np.cross([0,0,1],z);x/=np.linalg.norm(x);y=np.cross(z,x)
        view=np.eye(4);view[:3,:3]=[x,y,z];view[:3,3]=-view[:3,:3]@eye
        gl.glMatrixMode(gl.GL_MODELVIEW);gl.glLoadMatrixf(view.T.astype(np.float32));self.view=view
        gl.glLightfv(gl.GL_LIGHT0,gl.GL_POSITION,[-900,-1000,1700,1]);gl.glLightfv(gl.GL_LIGHT1,gl.GL_POSITION,[900,800,1500,1])
        gl.glDisable(gl.GL_LIGHTING)
        gl.glColor3f(.94,.95,.97);gl.glBegin(gl.GL_QUADS)
        for v in [(-2500,-2500,-2),(2500,-2500,-2),(2500,2500,-2),(-2500,2500,-2)]:gl.glVertex3f(*v)
        gl.glEnd();gl.glColor3f(.85,.88,.91);gl.glLineWidth(1);gl.glBegin(gl.GL_LINES)
        for k in range(-2000,2001,100):
            gl.glVertex3f(k,-2000,0);gl.glVertex3f(k,2000,0);gl.glVertex3f(-2000,k,0);gl.glVertex3f(2000,k,0)
        gl.glEnd()
        frame=self.trajectory[min(self.frame_index,len(self.trajectory)-1)] if self.trajectory and not self.live_mode else None
        manual=self.manual_frames[min(self.manual_index,len(self.manual_frames)-1)] if self.manual_active and self.manual_frames else None
        moving=manual is not None and manual.get('ik_valid',False) and 'joints' in manual
        qb=manual['joints'] if moving else (np.deg2rad(self.manual_seed['joints_deg']) if self.manual_active and self.manual_seed else (np.deg2rad(self.live_frame['joints']) if self.live_mode and self.live_frame else (frame['joints'] if frame else np.deg2rad([130,-50,100,40,90,0]))))
        robots=[robot_frames(self.camera_q,(-480,100,0)),robot_frames(qb,(480,100,0))]
        if self.live_mode and not self.live_frame:robots=robots[:1]
        if self.probe_only:
            robots=[robot_frames(qb,(0,0,0))] if moving or (self.live_mode and self.live_frame) or (self.manual_active and self.manual_seed) else []
        shadow=np.eye(4);shadow[0,2]=-.35;shadow[1,2]=.15;shadow[2,:]=[0,0,0,1.2]
        for m,t in self.parts:self._draw(m,shadow@t,True)
        for frames in robots:
            for m in self.meshes:self._draw(m,shadow@frames[m['joint']],True)
        gl.glEnable(gl.GL_LIGHTING)
        for m,t in self.parts:self._draw(m,t)
        for frames in robots:
            for m in self.meshes:self._draw(m,frames[m['joint']])
        if not self.probe_only:
            for m,t in getattr(self,'camera_parts',[]):self._draw(m,robots[0]['J6']@t)
        if not self.live_mode and not self.probe_only:
            for m,t in getattr(self,'probe_parts',[]):self._draw(m,robots[1]['J6']@t)
        gl.glDisable(gl.GL_LIGHTING);gl.glLineWidth(2.3)
        if self.live_mode and self.live_frame and self.live_frame['user_index']==0:
            # Controller TCP in user 0; workstation base placement remains assumed.
            pose=self.live_frame['pose'];point=np.array(pose[:3])+(np.zeros(3) if self.probe_only else [480,100,0])
            from scipy.spatial.transform import Rotation
            rotation=Rotation.from_euler('xyz',pose[3:],degrees=True).as_matrix()
            gl.glPointSize(9);gl.glColor3f(.85,.15,.35);gl.glBegin(gl.GL_POINTS);gl.glVertex3fv(point);gl.glEnd()
            gl.glBegin(gl.GL_LINES)
            for i,color in enumerate(([1,0,0],[0,.7,0],[0,.3,1])):
                gl.glColor3fv(color);gl.glVertex3fv(point);gl.glVertex3fv(point+rotation[:,i]*65)
            gl.glEnd()
        if self.probe_only and self.live_frame and self.live_mode and self.pose_audit:
            report=self.pose_audit
            if np.allclose(self.live_frame['joints'],report['joints_deg'],atol=.1):
                actual=np.array(report['controller_flange'][:3]);visual=np.array(report['visual_flange_matrix'])[:3,3]
                gl.glPointSize(10);gl.glBegin(gl.GL_POINTS)
                gl.glColor3f(.05,.65,.75);gl.glVertex3fv(actual);gl.glColor3f(1,.48,.1);gl.glVertex3fv(visual);gl.glEnd()
                gl.glColor3f(.55,.65,.72);gl.glBegin(gl.GL_LINES);gl.glVertex3fv(actual);gl.glVertex3fv(self.live_frame['pose'][:3]);gl.glEnd()
        if self.manual_active and self.manual_task:
            gl.glColor3f(.08,.61,.74);gl.glBegin(gl.GL_LINE_STRIP)
            for point in self.manual_task['waypoints']:gl.glVertex3fv(point['tcp_pose'][:3])
            gl.glEnd()
            failure=self.manual_task.get('joint_preview_report',{}).get('failure')
            if failure:
                gl.glColor3f(1,.15,.1);gl.glPointSize(14);gl.glBegin(gl.GL_POINTS);gl.glVertex3fv(failure['tip_mm']);gl.glEnd()
            if self.manual_frames:
                f=self.manual_frames[min(self.manual_index,len(self.manual_frames)-1)];point=f['tip']
                if moving:
                    flange=robot_frames(qb,(0,0,0))['flange'][:3,3]
                    gl.glColor3f(.95,.6,.12);gl.glLineWidth(4);gl.glBegin(gl.GL_LINES);gl.glVertex3fv(flange);gl.glVertex3fv(point);gl.glEnd();gl.glLineWidth(2.3)
                gl.glPointSize(10);gl.glColor3f(.9,.25,.35);gl.glBegin(gl.GL_POINTS);gl.glVertex3fv(point);gl.glEnd()
                gl.glBegin(gl.GL_LINES)
                for i,color in enumerate(([1,0,0],[0,.7,0],[0,.3,1])):
                    gl.glColor3fv(color);gl.glVertex3fv(point);gl.glVertex3fv(point+f['rotation'][:,i]*55)
                gl.glEnd()
        if self.plan and not self.live_mode:
            gl.glColor3f(.08,.61,.74);gl.glBegin(gl.GL_LINE_STRIP)
            for item in self.plan['waypoints']:gl.glVertex3fv(item['tip_world_mm'])
            gl.glEnd()
            for hole in self.plan['holes']:
                if not hole['selected']:continue
                active=frame and frame['hole_id']==hole['id']
                gl.glColor3fv([1,.55,.1] if active else [.1,.74,.52]);gl.glBegin(gl.GL_LINE_LOOP)
                xx,yy,zz=hole['center_world_mm'];rr=self.plan['config']['bore_diameter_mm']/2-3
                for t in np.linspace(0,2*np.pi,65):gl.glVertex3f(xx+rr*np.cos(t),yy+rr*np.sin(t),zz+1.5)
                gl.glEnd()
        gl.glEnable(gl.GL_LIGHTING)

    def paintEvent(self,event):
        super().paintEvent(event)
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QColor('#1c3653'));p.setFont(QFont('Microsoft YaHei',10))
        joint_preview=self.manual_active and self.manual_task and 'joint_preview_report' in self.manual_task
        p.drawText(18,28,('虚拟机械臂跟随 · 不控制实机' if joint_preview else 'TCP 几何预览 · 关节待求解') if self.manual_active else ('实时姿态' if self.live_mode and self.live_frame else ('等待实时反馈' if self.live_mode else '路径预览')))
        if self.render_error:p.setPen(QColor('#b45309'));p.drawText(18,50,self.render_error)
        if self.plan and hasattr(self,'view'):
            aspect=self.width()/max(1,self.height());f=1/math.tan(math.radians(37)/2)
            for h in self.plan['holes']:
                v=self.view@np.r_[h['center_world_mm'],1];v[1]+=22
                if v[2]<-10:
                    xx=self.width()/2+v[0]/(-v[2])*f/aspect*self.width()/2
                    yy=self.height()/2-v[1]/(-v[2])*f*self.height()/2
                    p.setPen(QColor('#b46513' if h['selected'] else '#63788c'));p.drawText(QPointF(xx,yy),h['id'])
        p.end()
