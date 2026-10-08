import numpy as np
from inspection_gui.rgbd_geometry import color_points,estimate_aperture
intr=dict(fx=500.,fy=500.,cx=320.,cy=200.,width=640,height=400)
dist=dict(model=0)
cal=dict(depth=intr,color=intr,depth_distortion=dist,color_distortion=dist,rotation_depth_to_color=np.eye(3).ravel().tolist(),translation_depth_to_color_mm=[0,0,0],mirrored=False)
depth=np.full((400,640),1000,np.uint16)
y,x=np.indices(depth.shape)
depth[(x-320)**2+(y-200)**2<50**2]=1800
xyz,uv=color_points(depth,1,cal,[640,400])
hole=dict(id='H01',reliable_center=True,ellipse=dict(center=[320,200],width=100,height=100,angle=0))
fit=estimate_aperture(hole,xyz,uv,cal)
assert np.linalg.norm(np.array(fit['center_camera_mm'])-[0,0,1000])<.01,fit
assert abs(fit['radius_estimate_mm']-100)<.01,fit
assert fit['robot_ready'] is False
try:color_points(np.zeros_like(depth),1,cal,[640,400])
except ValueError:pass
else:raise AssertionError('empty depth accepted')
print('PASS known aperture center, background inside hole ignored, empty depth rejected')

import cv2,tempfile,json
from pathlib import Path
from inspection_gui.capture_archive import save_capture
from inspection_gui.camera_3d import add_camera_3d
# Tilted aperture: depth comes from the face plane, not the background in hole.
normal=np.array([0.,.35,-1.]);normal/=np.linalg.norm(normal)
center=np.array([35.,-25.,1100.]);e1=np.array([1.,0.,0.]);e2=np.cross(normal,e1)
t=np.linspace(0,2*np.pi,360,endpoint=False)
border=center+100*(np.cos(t)[:,None]*e1+np.sin(t)[:,None]*e2)
pix=cv2.projectPoints(border,np.zeros(3),np.zeros(3),np.array([[500.,0,320.],[0,500.,200.],[0,0,1.]]),np.zeros(5))[0].astype(np.float32)
(cxy,axes,ang)=cv2.fitEllipse(pix)
hole2=dict(id='H02',reliable_center=True,ellipse=dict(center=cxy,width=axes[0],height=axes[1],angle=ang))
rays=np.stack([(x-320)/500,(y-200)/500,np.ones_like(x)],axis=-1)
z=(normal@center)/(rays@normal)
d2=np.rint(z).astype(np.uint16)
p3,u3=color_points(d2,1,cal,[640,400]);fit2=estimate_aperture(hole2,p3,u3,cal)
assert np.linalg.norm(np.array(fit2['center_camera_mm'])-center)<.5,fit2
with tempfile.TemporaryDirectory() as temp:
 packet=dict(depth_raw=depth,depth_scale_mm=1,calibration=cal,color_timestamp_us=100000,depth_timestamp_us=100000,timestamp_delta_ms=0)
 photo,side,info=save_capture(temp,np.zeros((400,640,3),np.uint8),rgbd_packet=packet)
 result=dict(raw_report={},fitted_holes=[hole],holes=[hole],image_size=[640,400])
 add_camera_3d(result,photo)
 assert len(result['camera_3d'])==1,result
 side_depth=photo.parent/info['depth_archive']['file'];side_depth.write_bytes(b'corrupt')
 add_camera_3d(result,photo)
 assert not result['camera_3d'] and result['camera_3d_notes'],result
print('PASS tilted circle, archive roundtrip, corrupted depth rejection')
