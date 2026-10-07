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
        p.fillRect(self.rect(), QColor('#101c30'))
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
        self.box((-470,-285,-45), (470,285,-15), '#52647b')
        for x in range(-450,451,60):
            for y in range(-270,271,60):
                self.cylinder((x,y,-14), (x,y,-12), 3, '#26364d', 6)
        for x in (-355,355):
            self.box((x-75,-75,-14), (x+75,75,0), '#344862')
        # Four open cylindrical bores in a raised engine block.
        self.box((-205,-70,0), (205,70,90), '#87796a', top=False)
        stage = min(7,int(self.phase))
        t = self.phase % 1
        selected = stage-3 if 3 <= stage <= 6 else -1
        for i,x in enumerate((-150,-50,50,150)):
            color = '#eab85b' if i == selected else ('#34c8a5' if stage == 7 or (selected >= 0 and i < selected) else '#bac4cd')
            self.ring(x,0,90,43,35,color)
            self.cylinder((x,0,35),(x,0,89),35,'#273448',24, caps=False)
            self.disk(x,0,34,35,'#101827')
        # Fill deck surface around the four rims without covering openings.
        self.box((-205,-70,86),(205,-44,90),'#b4a28b')
        self.box((-205,44,86),(205,70,90),'#b4a28b')
        for x in (-205,-105,-5,95,195):
            self.box((x,-44,86),(x+10,44,90),'#b4a28b')
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
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            p.drawPolygon(QPolygonF([project(v) for v in poly]))
        if stage in (1,2):
            p.setPen(QPen(QColor('#40daf1'),1.5,Qt.PenStyle.DashLine))
            for v in [(-205,-70,90),(205,-70,90),(205,70,90),(-205,70,90)]:
                p.drawLine(project(camera+[0,0,-48]),project(v))
        p.setPen(QColor('#c8dcf7'))
        p.drawText(20,30,'双 CR5A 风格机械臂 · 三维流程展示')
        p.setPen(QColor('#8399b7'))
        p.drawText(20,53,'拖动旋转视角 · 滚轮缩放 · 示意模型／非实机轨迹')
        for label,point in [('A · 工业相机',(-355,-100,15)),('B · 测针',(355,-100,15))]:
            q = project(point)
            p.setPen(QColor('#8ad8ff'))
            p.drawText(q,label)
        for i,x in enumerate((-150,-50,50,150)):
            p.setPen(QColor('#f3ddad'))
            p.drawText(project((x,-43,105)),f'H{i+1:02}')

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

    def arm(self,base,target,color):
        side=1 if base<0 else -1
        points=[np.array([base,0.,20.]),np.array([base,0.,130.]),
                np.array([base+side*75,65.,350.]),target+np.array([-side*80,35,60]),target]
        self.cylinder((base,0,0),(base,0,75),48,'#e4eaf2')
        for i,(a,b) in enumerate(zip(points,points[1:])):
            self.cylinder(a,b,29 if i<2 else 22,'#e3e9ef')
        for point in points[1:]:
            self.cylinder(point+[0,-30,0],point+[0,30,0],34,'#edf2f6')
            self.cylinder(point+[0,-32,0],point+[0,-28,0],35,color)
            self.cylinder(point+[0,28,0],point+[0,32,0],35,color)
            self.cylinder(point+[0,-34,0],point+[0,-32,0],19,'#657788')
