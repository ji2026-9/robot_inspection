"""Interactive 3D mesh projection; illustrative geometry, no hardware control."""
import math
import numpy as np
from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget


class Scene3D(QWidget):
    def __init__(self):
        super().__init__()
        self.phase = 0.0
        self.yaw, self.pitch, self.zoom = -0.68, 0.52, 1.0
        self.drag = None
        self.setMinimumSize(760, 430)
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def mousePressEvent(self, event):
        self.drag = event.position()

    def mouseMoveEvent(self, event):
        if self.drag is not None:
            delta = event.position() - self.drag
            self.yaw += delta.x() * 0.006
            self.pitch = float(np.clip(self.pitch + delta.y() * 0.004, 0.12, 1.25))
            self.drag = event.position()
            self.update()

    def mouseReleaseEvent(self, event):
        self.drag = None

    def wheelEvent(self, event):
        self.zoom = float(np.clip(self.zoom * (1.1 if event.angleDelta().y() > 0 else 0.9), 0.55, 1.8))
        self.update()

    def reset_view(self):
        self.yaw, self.pitch, self.zoom = -0.68, 0.52, 1.0
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor('#f4f6f9'))
        cy, sy = math.cos(self.yaw), math.sin(self.yaw)
        cp, sp = math.cos(self.pitch), math.sin(self.pitch)
        self.rotation = np.array([[cy, -sy, 0], [sy*sp, cy*sp, -cp], [sy*cp, cy*cp, sp]])
        self.scale = min(self.width()/1050, self.height()/680) * self.zoom
        self.faces = []
        def project(point):
            q = self.rotation @ np.asarray(point)
            factor = 1800 / (1800 + q[2])
            return QPointF(self.width()/2 + q[0]*self.scale*factor,
                           self.height()*0.62 + q[1]*self.scale*factor)
        self.project = project
        # Worktable, floor grid and base plates.
        self.box((-470,-285,-45), (470,285,-15), '#e2e7ee')
        for x in range(-450,451,60):
            for y in range(-270,271,60):
                self.cylinder((x,y,-14), (x,y,-12), 3, '#ccd4dd', 6)
        for x in (-355,355):
            self.box((x-75,-75,-14), (x+75,75,0), '#c3ccd7')
        # Four open cylindrical bores in a raised engine block.
        self.box((-205,-70,0), (205,70,90), '#a99a87', top=False)
        stage = min(7,int(self.phase))
        t = self.phase % 1
        selected = stage-3 if 3 <= stage <= 6 else -1
        for i,x in enumerate((-150,-50,50,150)):
            color = '#eab85b' if i == selected else ('#34c8a5' if stage == 7 or (selected >= 0 and i < selected) else '#bac4cd')
            self.ring(x,0,90,43,35,color)
            self.cylinder((x,0,35),(x,0,89),35,'#8d98a7',24, caps=False)
            self.disk(x,0,34,35,'#6f7a89')
        # Fill deck surface around the four rims without covering openings.
        self.box((-205,-70,86),(205,-44,90),'#c6b49b')
        self.box((-205,44,86),(205,70,90),'#c6b49b')
        for x in (-205,-105,-5,95,195):
            self.box((x,-44,86),(x+10,44,90),'#c6b49b')
        # Smooth approach to the illustrative capture / probe pose.
        parked_camera = np.array([-230.,-95.,300.])
        capture_camera = np.array([-45.,0.,320.])
        ease = (1-math.cos(math.pi*min(1,t*3)))/2
        camera = parked_camera*(1-ease)+capture_camera*ease if stage == 1 else (
            capture_camera if stage == 2 else (
                capture_camera*(1-ease)+parked_camera*ease if stage == 3 else parked_camera))
        target_x = (-150,-50,50,150)[max(0,selected)] if selected >= 0 else 260
        previous_x = 260 if selected <= 0 else (-150,-50,50,150)[selected-1]
        if selected >= 0:
            target_x = previous_x*(1-ease)+target_x*ease
        target_z = 140-22*math.sin(math.pi*max(0,(t-.33)/.67)) if selected >= 0 else 280
        if selected >= 0 and t < .33:
            target_z = 235-95*ease
        probe = np.array([target_x,0.,target_z])
        self.arm(-355,camera,'#438afa')
        self.arm(355,probe,'#657bfd')
        self.box(tuple(camera+[-23,-18,-18]),tuple(camera+[23,18,18]),'#273d56')
        self.cylinder(camera+[0,0,-18],camera+[0,0,-48],13,'#2ab6d0',16)
        self.cylinder(probe,probe+[0,0,-35],8,'#eef3fa',12)
        self.cylinder(probe+[0,0,-35],probe+[0,0,-65],2,'#f2bd5c',8)
        self.disk(target_x,0,54 if selected >= 0 else 205,4,'#f6ca76')
        for depth,poly,color in sorted(self.faces,key=lambda f:f[0]):
            # [local patch] thin edge so light parts stay readable
            p.setPen(QPen(QColor(120,132,150,80),0.6))
            p.setBrush(color)
            p.drawPolygon(QPolygonF([project(v) for v in poly]))
        if stage in (1,2):
            p.setPen(QPen(QColor('#40daf1'),1.5,Qt.PenStyle.DashLine))
            for v in [(-205,-70,90),(205,-70,90),(205,70,90),(-205,70,90)]:
                p.drawLine(project(camera+[0,0,-48]),project(v))
        p.setPen(QColor('#33415a'))
        p.drawText(20,30,'双 CR5A 风格机械臂 · 三维流程展示')
        p.setPen(QColor('#6b7a90'))
        p.drawText(20,53,'拖动旋转视角 · 滚轮缩放 · 示意模型／非实机轨迹')
        def _inside(q, right=104, bottom=18):
            # [local patch] keep scene labels inside the viewport
            x = min(max(q.x(), 16.0), max(16.0, self.width() - right))
            y = min(max(q.y(), 30.0), max(30.0, self.height() - bottom))
            return QPointF(x, y)
        for label,point in [('A · 工业相机',(-355,-100,15)),('B · 测针',(355,-100,15))]:
            p.setPen(QColor('#2563eb'))
            p.drawText(_inside(project(point), 104), label)
        for i,x in enumerate((-150,-50,50,150)):
            p.setPen(QColor('#b45309'))
            p.drawText(_inside(project((x,-43,105)), 46), f'H{i+1:02}')

    def face(self,poly,color):
        poly = np.asarray(poly,dtype=float)
        normal = np.cross(poly[1]-poly[0],poly[2]-poly[0])
        normal /= max(1e-9,np.linalg.norm(normal))
        light = 0.76 + 0.22*abs(float(normal @ np.array([.3,-.4,.86])))
        c = QColor(color)
        c = QColor(int(c.red()*light),int(c.green()*light),int(c.blue()*light))
        depth = float((self.rotation @ poly.mean(axis=0))[2])
        self.faces.append((depth,poly,c))

    def box(self,a,b,color,top=True):
        x,y,z=a; X,Y,Z=b
        v=[(x,y,z),(X,y,z),(X,Y,z),(x,Y,z),(x,y,Z),(X,y,Z),(X,Y,Z),(x,Y,Z)]
        for ids in [(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)]+([(4,5,6,7)] if top else []):
            self.face([v[i] for i in ids],color)

    def cylinder(self,a,b,r,color,n=16,caps=True):
        a,b=np.asarray(a,dtype=float),np.asarray(b,dtype=float)
        axis=b-a; axis/=max(np.linalg.norm(axis),1e-9)
        u=np.cross(axis,[0,0,1] if abs(axis[2])<.9 else [0,1,0]); u/=np.linalg.norm(u)
        v=np.cross(axis,u)
        offsets=[r*(math.cos(i*2*math.pi/n)*u+math.sin(i*2*math.pi/n)*v) for i in range(n)]
        for i in range(n):
            j=(i+1)%n
            self.face([a+offsets[i],a+offsets[j],b+offsets[j],b+offsets[i]],color)
        if caps:
            self.face([a+o for o in offsets],color)
            self.face([b+o for o in offsets],color)

    def disk(self,x,y,z,r,color):
        self.face([(x+r*math.cos(i*math.pi/12),y+r*math.sin(i*math.pi/12),z) for i in range(24)],color)

    def ring(self,x,y,z,outer,inner,color):
        for i in range(32):
            angles=[i*math.pi/16,(i+1)*math.pi/16]
            self.face([(x+r*math.cos(t),y+r*math.sin(t),z) for r,t in
                       [(outer,angles[0]),(outer,angles[1]),(inner,angles[1]),(inner,angles[0])]],color)

    def joint(self,center,radius,ring_color,half=30,bulge=5):
        # [local patch] CR5A-style joint hub with two blue rings
        c=np.asarray(center,dtype=float)
        self.cylinder(c+[0,-half,0],c+[0,half,0],radius,'#e6eaee',24)
        self.cylinder(c+[0,-half,0],c+[0,-half+5,0],radius+bulge,ring_color,24)
        self.cylinder(c+[0,half-5,0],c+[0,half,0],radius+bulge,ring_color,24)
        self.cylinder(c+[0,-half-3,0],c+[0,-half,0],radius*0.55,'#93a0ae',20)
        self.cylinder(c+[0,half,0],c+[0,half+3,0],radius*0.55,'#93a0ae',20)

    def taper(self,a,b,r1,r2,color,n=24,caps=True):
        # [local patch] cone-shaped link (the old arm used straight tubes)
        a,b=np.asarray(a,dtype=float),np.asarray(b,dtype=float)
        axis=b-a; axis/=max(float(np.linalg.norm(axis)),1e-9)
        u=np.cross(axis,[0,0,1] if abs(axis[2])<.9 else [0,1,0]); u/=np.linalg.norm(u)
        v=np.cross(axis,u)
        o1=[r1*(math.cos(i*2*math.pi/n)*u+math.sin(i*2*math.pi/n)*v) for i in range(n)]
        o2=[r2*(math.cos(i*2*math.pi/n)*u+math.sin(i*2*math.pi/n)*v) for i in range(n)]
        for i in range(n):
            j=(i+1)%n
            self.face([a+o1[i],a+o1[j],b+o2[j],b+o2[i]],color)
        if caps:
            self.face([a+o for o in o1],color)
            self.face([b+o for o in o2],color)

    def arm(self,base,target,color):
        # [local patch] CR5A-style arm: pedestal, tapered links, blue joint rings,
        # dark tool flange (geometry is still illustrative, not real kinematics)
        side=1 if base<0 else -1
        p1=np.array([base,0.,132.])
        p2=np.array([base+side*78,66.,352.])
        p3=target+np.array([-side*82,36,64])
        self.cylinder((base,0,0),(base,0,12),58,'#c5cbd3',32)
        self.cylinder((base,0,12),(base,0,58),46,'#eef1f4',32)
        self.cylinder((base,0,58),(base,0,70),51,color,32)
        self.joint(p1,40,color,30)
        self.taper(p1,p2,37,27,'#eef2f5',26)
        self.joint(p2,33,color,26)
        self.taper(p2,p3,28,21,'#e7ebef',26)
        d=(target-p3); L=max(float(np.linalg.norm(d)),1e-6); d=d/L
        for k,off in enumerate((0.0,26.0,50.0)):
            self.joint(p3+d*off,20-k*2,color,15,3)
        self.cylinder(target-d*14,target-d*4,17,'#d3d9df',20)
        self.cylinder(target-d*4,target+d*3,11,'#31363d',20)
