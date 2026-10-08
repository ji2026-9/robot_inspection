"""SDK calibration ABI and conservative camera-frame aperture estimates (mm)."""
import ctypes as C
import cv2
import numpy as np

class Intrinsic(C.Structure):
    _fields_=[(k,C.c_float) for k in ('fx','fy','cx','cy')]+[('width',C.c_int16),('height',C.c_int16)]
class Distortion(C.Structure):
    _fields_=[(k,C.c_float) for k in ('k1','k2','k3','k4','k5','k6','p1','p2')]+[('model',C.c_int)]
class Extrinsic(C.Structure):
    _fields_=[('rot',C.c_float*9),('trans',C.c_float*3)]
class CameraParam(C.Structure):
    _fields_=[('depthIntrinsic',Intrinsic),('rgbIntrinsic',Intrinsic),('depthDistortion',Distortion),('rgbDistortion',Distortion),('transform',Extrinsic),('isMirrored',C.c_bool)]

def camera_param_dict(param):
    def fields(obj):return {k:getattr(obj,k) for k,_ in obj._fields_}
    return {'depth':fields(param.depthIntrinsic),'color':fields(param.rgbIntrinsic),
            'depth_distortion':fields(param.depthDistortion),'color_distortion':fields(param.rgbDistortion),
            'rotation_depth_to_color':list(param.transform.rot),'translation_depth_to_color_mm':list(param.transform.trans),
            'mirrored':bool(param.isMirrored),'source':'OrbbecSDK active stream calibration'}

def parameters(calibration, sensor):
    info=calibration[sensor]
    k=np.array([[info['fx'],0,info['cx']],[0,info['fy'],info['cy']],[0,0,1]],float)
    if not np.isfinite(k).all() or min(k[0,0],k[1,1])<=0:raise ValueError('相机内参无效')
    distortion=calibration[sensor+'_distortion'];model=int(distortion['model'])
    if model==0:coeff=np.zeros(5)
    elif model in (3,4):
        coeff=np.array([distortion[n] for n in ('k1','k2','p1','p2','k3','k4','k5','k6')],float)
        if model==3:coeff=coeff[:5]
    else:raise ValueError('尚不支持该相机畸变模型，不提供三维坐标')
    if not np.isfinite(coeff).all():raise ValueError('畸变参数无效')
    return k,coeff

def color_points(depth_raw,scale,calibration,image_size):
    if calibration.get('mirrored'):raise ValueError('镜像标定尚未支持')
    if depth_raw.dtype!=np.uint16 or depth_raw.shape!=(calibration['depth']['height'],calibration['depth']['width']):raise ValueError('深度图尺寸与内参不一致')
    if list(image_size)!=[calibration['color']['width'],calibration['color']['height']]:raise ValueError('彩色图尺寸与内参不一致')
    if not np.isfinite(scale) or scale<=0:raise ValueError('深度单位无效')
    y,x=np.indices(depth_raw.shape);valid=(depth_raw>0)&(depth_raw*float(scale)>=100)&(depth_raw*float(scale)<=5000)
    pixels=np.column_stack([x[valid],y[valid]]).astype(float);z=depth_raw[valid].astype(float)*scale
    if len(z)<100:raise ValueError('有效深度点不足')
    kd,dd=parameters(calibration,'depth');kc,dc=parameters(calibration,'color')
    normalized=cv2.undistortPoints(pixels.reshape(-1,1,2),kd,dd).reshape(-1,2)
    xyz=np.column_stack([normalized*z[:,None],z])
    rotation=np.array(calibration['rotation_depth_to_color'],float).reshape(3,3)
    if not np.isfinite(rotation).all() or not np.allclose(rotation@rotation.T,np.eye(3),atol=.02) or np.linalg.det(rotation)<.95:raise ValueError('深度和彩色外参无效')
    translation=np.array(calibration['translation_depth_to_color_mm'],float)
    if not np.isfinite(translation).all():raise ValueError('深度和彩色平移无效')
    xyz=xyz@rotation.T+translation
    valid=xyz[:,2]>0;xyz=xyz[valid]
    uv=cv2.projectPoints(xyz,np.zeros(3),np.zeros(3),kc,dc)[0].reshape(-1,2)
    w,h=image_size;valid=np.isfinite(uv).all(axis=1)&(uv[:,0]>=0)&(uv[:,0]<w)&(uv[:,1]>=0)&(uv[:,1]<h)
    return xyz[valid],uv[valid]

def estimate_aperture(hole,xyz,uv,calibration):
    if not hole.get('reliable_center'):raise ValueError('二维圆心尚未通过复核')
    ellipse=hole['ellipse'];cx,cy=ellipse['center'];a,b=ellipse['width']/2,ellipse['height']/2
    angle=np.deg2rad(ellipse['angle']);c,s=np.cos(angle),np.sin(angle)
    dx,dy=uv[:,0]-cx,uv[:,1]-cy;u=(dx*c+dy*s)/a;v=(-dx*s+dy*c)/b
    radius=np.hypot(u,v);ring=(radius>=1.10)&(radius<=1.30)
    points=xyz[ring];angles=np.arctan2(v[ring],u[ring]);bins=((angles+np.pi)/(2*np.pi)*24).astype(int)%24
    if len(points)<100 or len(np.unique(bins))/24<.75:raise ValueError('孔口周围有效深度覆盖不足')
    rng=np.random.default_rng(812);sample=points[rng.choice(len(points),min(3000,len(points)),replace=False)]
    best=None
    for _ in range(100):
        p=sample[rng.choice(len(sample),3,replace=False)];normal=np.cross(p[1]-p[0],p[2]-p[0]);norm=np.linalg.norm(normal)
        if norm<1e-6:continue
        normal/=norm;mask=np.abs((sample-p[0])@normal)<2
        if best is None or mask.sum()>best.sum():best=mask
    if best is None or best.mean()<.70:raise ValueError('孔口端面深度不稳定或反光过强')
    plane=sample[best];origin=plane.mean(axis=0);_,_,vectors=np.linalg.svd(plane-origin,full_matrices=False);normal=vectors[-1]
    if normal@origin>0:normal=-normal
    offset=normal@origin;distance=np.abs(points@normal-offset);good=distance<2
    coverage=len(np.unique(bins[good]))/24
    residual=float(np.sqrt(np.mean(distance[good]**2)))
    if good.mean()<.70 or coverage<.75 or residual>1.5:raise ValueError('平面残差或深度覆盖未通过检查')
    t=np.linspace(0,2*np.pi,180,endpoint=False)
    border=np.column_stack([cx+a*np.cos(t)*c-b*np.sin(t)*s,cy+a*np.cos(t)*s+b*np.sin(t)*c])
    k,d=parameters(calibration,'color');rays=cv2.undistortPoints(border.reshape(-1,1,2),k,d).reshape(-1,2);rays=np.column_stack([rays,np.ones(len(rays))])
    denom=rays@normal
    if np.any(np.abs(denom)<.1):raise ValueError('视角过于倾斜')
    z=offset/denom
    if np.any(z<=0):raise ValueError('孔口平面交点无效')
    border3d=rays*z[:,None];basis=vectors[:2];xy=(border3d-origin)@basis.T
    design=np.column_stack([2*xy,np.ones(len(xy))]);solution=np.linalg.lstsq(design,np.sum(xy*xy,axis=1),rcond=None)[0]
    rr=solution[2]+np.dot(solution[:2],solution[:2])
    if rr<=0:raise ValueError('三维圆拟合失败')
    r=np.sqrt(rr);circle_error=float(np.sqrt(np.mean((np.linalg.norm(xy-solution[:2],axis=1)-r)**2)))
    if circle_error>max(1,.02*r):raise ValueError('孔口边缘投影不符合圆形，需要复核')
    center=origin+solution[:2]@basis
    return {'id':hole['id'],'center_camera_mm':center.tolist(),'normal_camera':normal.tolist(),
            'radius_estimate_mm':float(r),'plane_rmse_mm':residual,'circle_rmse_mm':circle_error,
            'depth_coverage':coverage,'plane_inlier_ratio':float(good.mean()),'status':'camera_estimate_review_required',
            'coordinate_frame':'color_camera','robot_ready':False,
            'note':'孔口端面与二维孔口边缘联合估计；不是精密孔径测量或已标定机械臂坐标。'}
