import cv2
import numpy as np
from robust_bore_ellipse import ellipse_residual

def refine_aperture_edge(image, initial, polarity='positive'):
    gray = cv2.GaussianBlur(cv2.cvtColor(image,cv2.COLOR_BGR2GRAY),(0,0),2).astype(np.float32)
    gx = cv2.Sobel(gray,cv2.CV_32F,1,0,ksize=3)/8
    gy = cv2.Sobel(gray,cv2.CV_32F,0,1,ksize=3)/8
    (cx,cy),(a,b),angle = initial
    minor = min(a,b)
    t = np.linspace(0,2*np.pi,360,endpoint=False)
    c,s = np.cos(np.deg2rad(angle)),np.sin(np.deg2rad(angle))
    rx,ry = a/2,b/2
    u,v = rx*np.cos(t),ry*np.sin(t)
    x,y = cx+c*u-s*v,cy+s*u+c*v
    nx,ny = np.cos(t)/rx,np.sin(t)/ry
    norm = np.hypot(nx,ny); nx,ny = nx/norm,ny/norm
    dx,dy = c*nx-s*ny,s*nx+c*ny
    radius = min(110,max(8,.13*minor))
    offsets = np.arange(-radius,radius+1,1,dtype=np.float32)
    mx=(x[:,None]+dx[:,None]*offsets).astype(np.float32)
    my=(y[:,None]+dy[:,None]*offsets).astype(np.float32)
    gradient = cv2.remap(gx,mx,my,cv2.INTER_LINEAR)*dx[:,None]+cv2.remap(gy,mx,my,cv2.INTER_LINEAR)*dy[:,None]
    if polarity == 'either':
        gradient = np.abs(gradient)
    score = gradient * np.exp(-.5*(offsets/(radius*.75))**2)[None]
    indices = np.argmax(score,axis=1)
    strength = gradient[np.arange(len(t)),indices]
    points = np.column_stack([mx[np.arange(len(t)),indices],my[np.arange(len(t)),indices]])
    usable = strength>2.5
    points = points[usable].astype(np.float32)
    if len(points)<180:
        return initial, {'used':False,'reason':'孔口边缘支持不足'}
    rng=np.random.default_rng(46)
    tolerance=max(2,.009*minor)
    best=None; best_score=(-1,-np.inf)
    for iteration in range(350):
        p=points if iteration==0 else points[rng.choice(len(points),8,replace=False)]
        try: fit=cv2.fitEllipseDirect(p.reshape(-1,1,2))
        except cv2.error: continue
        center,axes,_=fit
        if np.linalg.norm(np.array(center)-[cx,cy])>.16*minor or not .7<min(axes)/minor<1.35:
            continue
        if not .65 < np.prod(axes)/(a*b)<1.5: continue
        residual,_=ellipse_residual(points,fit)
        comparison=(int(np.sum(residual<tolerance)),-float(np.median(residual)))
        if comparison>best_score: best,best_score=fit,comparison
    if best is None: return initial,{'used':False,'reason':'边缘椭圆不稳定'}
    for _ in range(3):
        residual,_=ellipse_residual(points,best)
        inliers=residual<tolerance
        if inliers.sum()<5: break
        best=cv2.fitEllipseDirect(points[inliers].reshape(-1,1,2))
    residual,angles=ellipse_residual(points,best)
    inliers=residual<tolerance
    bins=np.floor((angles[inliers]+np.pi)/(2*np.pi)*36).astype(int)%36
    coverage=len(np.unique(bins))/36
    support=float(inliers.mean())
    if support<.55 or coverage<.75:
        return initial,{'used':False,'reason':'边缘拟合覆盖不足','support':support,'coverage':coverage}
    shift=float(np.linalg.norm(np.array(best[0])-[cx,cy]))
    if shift>.16*minor or not .65<np.prod(best[1])/(a*b)<1.5:
        return initial,{'used':False,'reason':'边缘修正幅度过大'}
    return best,{'used':True,'support':support,'coverage':coverage,'median_residual_px':float(np.median(residual[inliers])),
                 'center_shift_px':shift,'points':points[inliers]}

def refine_multi_edge(image, initial):
    """Fit an aperture using several local edge candidates per normal, one vote per ray."""
    (cx,cy),(a,b),angle=initial
    minor=min(a,b)
    radius=min(110,max(10,.14*minor))
    margin=radius+10
    x0=max(0,int(cx-max(a,b)/2-margin)); y0=max(0,int(cy-max(a,b)/2-margin))
    x1=min(image.shape[1],int(cx+max(a,b)/2+margin+1)); y1=min(image.shape[0],int(cy+max(a,b)/2+margin+1))
    gray=cv2.GaussianBlur(cv2.cvtColor(image[y0:y1,x0:x1],cv2.COLOR_BGR2GRAY),(0,0),1.6).astype(np.float32)
    gx=cv2.Sobel(gray,cv2.CV_32F,1,0,ksize=3)/8
    gy=cv2.Sobel(gray,cv2.CV_32F,0,1,ksize=3)/8
    t=np.linspace(0,2*np.pi,360,endpoint=False)
    c,s=np.cos(np.deg2rad(angle)),np.sin(np.deg2rad(angle))
    u,v=a/2*np.cos(t),b/2*np.sin(t)
    x,y=cx+c*u-s*v,cy+s*u+c*v
    nx,ny=np.cos(t)/(a/2),np.sin(t)/(b/2)
    length=np.hypot(nx,ny); nx,ny=nx/length,ny/length
    dx,dy=c*nx-s*ny,s*nx+c*ny
    offsets=np.arange(-radius,radius+1,dtype=np.float32)
    mx=(x[:,None]+dx[:,None]*offsets).astype(np.float32)
    my=(y[:,None]+dy[:,None]*offsets).astype(np.float32)
    gradient=cv2.remap(gx,mx-x0,my-y0,cv2.INTER_LINEAR)*dx[:,None]+cv2.remap(gy,mx-x0,my-y0,cv2.INTER_LINEAR)*dy[:,None]
    peaks=np.zeros_like(gradient,dtype=bool)
    peaks[:,1:-1]=(gradient[:,1:-1]>gradient[:,:-2])&(gradient[:,1:-1]>=gradient[:,2:])
    probe=max(7,.025*minor)
    outer=cv2.remap(gray,(mx-x0+dx[:,None]*probe).astype(np.float32),(my-y0+dy[:,None]*probe).astype(np.float32),cv2.INTER_LINEAR)
    inner=cv2.remap(gray,(mx-x0-dx[:,None]*probe).astype(np.float32),(my-y0-dy[:,None]*probe).astype(np.float32),cv2.INTER_LINEAR)
    contrast=outer-inner
    # Keep weak but continuous aperture edges as well as strong nearby grooves.
    eligible=peaks&(gradient>1.0)&(contrast>12)
    ranked=np.where(eligible,gradient*np.exp(-.5*(offsets/(radius*.85))**2),-1)
    ids=np.argsort(ranked,axis=1)[:,-8:]
    rays=np.arange(len(t))[:,None]
    candidates=np.stack([mx[rays,ids],my[rays,ids]],axis=-1)
    valid=ranked[rays,ids]>0
    tolerance=max(2,.008*minor)
    best=None; best_rank=(-np.inf,)
    def plausible(fit):
        center,axes,_=fit
        return (np.isfinite(np.r_[center,axes]).all() and min(axes)>0 and
                np.linalg.norm(np.array(center)-[cx,cy])<.12*minor and
                .80<np.prod(axes)/(a*b)<1.30 and
                .75<min(axes)/minor<1.25 and max(axes)/min(axes)<12)
    for sx in (-.06,-.03,0,.03,.06):
        for sy in (-.06,-.03,0,.03,.06):
            for scale in (.98,1.05,1.10):
                fit=((cx+sx*minor,cy+sy*minor),(a*scale,b*scale),angle)
                for _ in range(6):
                    distances,_=ellipse_residual(candidates.reshape(-1,2),fit)
                    distances=distances.reshape(valid.shape)
                    distances[~valid]=1e6
                    pick=np.argmin(distances,axis=1)
                    near=distances[np.arange(len(t)),pick]
                    inliers=near<tolerance*1.5
                    if inliers.sum()<140: break
                    points=candidates[np.arange(len(t)),pick]
                    updated=cv2.fitEllipseDirect(points[inliers].astype(np.float32).reshape(-1,1,2))
                    if not plausible(updated): break
                    fit=updated
                if not plausible(fit): continue
                distances,angles=ellipse_residual(candidates.reshape(-1,2),fit)
                distances=distances.reshape(valid.shape); distances[~valid]=1e6
                pick=np.argmin(distances,axis=1)
                near=distances[np.arange(len(t)),pick]
                inliers=near<tolerance
                if not inliers.any(): continue
                points=candidates[np.arange(len(t)),pick]
                strength=gradient[rays,ids][np.arange(len(t)),pick]
                # Prefer a continuous, nearby boundary, rather than the stronger outer ring.
                shift=np.linalg.norm(np.array(fit[0])-[cx,cy])/minor
                area=np.prod(fit[1])/(a*b)
                rank=(int(inliers.sum())-30*shift-30*abs(area-1),-float(np.median(near[inliers])))
                if rank>best_rank:
                    best_rank=rank; best=(fit,points,inliers,near,strength)
    if best is None: return initial,{'used':False,'reason':'多边缘拟合未收敛'}
    fit,points,inliers,near,strength=best
    _,angles=ellipse_residual(points,fit)
    bins=np.floor((angles[inliers]+np.pi)/(2*np.pi)*36).astype(int)%36
    coverage=len(np.unique(bins))/36
    support=float(inliers.mean())
    if support<.65 or coverage<.85:
        return initial,{'used':False,'reason':'多边缘支持不足','support':support,'coverage':coverage,'candidate_ellipse':fit}
    evidence=points[inliers].astype(np.float32)
    rng=np.random.default_rng(73)
    trials=[]
    for _ in range(40):
        sample=evidence[rng.choice(len(evidence),int(.75*len(evidence)),replace=False)]
        check=cv2.fitEllipseDirect(sample.reshape(-1,1,2))
        trials.append(np.r_[check[0],sorted(check[1])])
    trials=np.asarray(trials)
    center_spread=float(np.percentile(np.linalg.norm(trials[:,:2]-np.median(trials[:,:2],axis=0),axis=1),95))
    axis_spread=float(np.max(np.std(trials[:,2:],axis=0)))
    if center_spread>max(1,.006*minor) or axis_spread>.01*minor:
        return initial,{'used':False,'reason':'边缘拟合对采样变化不稳定','center_spread_px':center_spread}
    return fit,{'used':True,'support':support,'coverage':coverage,
                'median_residual_px':float(np.median(near[inliers])),
                'center_shift_px':float(np.linalg.norm(np.array(fit[0])-[cx,cy])),
                'center_spread_px':center_spread,'axis_spread_px':axis_spread,
                'points':points[inliers],'method':'multiple_image_edges'}
