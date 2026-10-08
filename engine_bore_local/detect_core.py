from pathlib import Path
from datetime import datetime
import csv
import json
import cv2
import numpy as np
import torch
from PIL import Image
from ultralytics import YOLO
from robust_bore_ellipse import robust_bore_ellipse
from part_predictor import FullPartPredictor
from edge_bore_refinement import refine_aperture_edge, refine_multi_edge

BASE = Path(__file__).resolve().parent
DEFAULT_MODEL = BASE / 'models' / 'engine_part_bore_100.pt'
PART_MODEL = BASE / 'models' / 'engine_part_only_fixed.pt'
FRIEND_MODEL = BASE/'friend_package'/'package_v1'/'weights'/'best.pt'

def canonical_class(name):
    return 'bore' if name == 'cylinder_bore' else name

def points_to_original(points, turns, width, height):
    points = np.asarray(points, dtype=np.float32).reshape(-1, 2)
    x,y = points[:,0],points[:,1]
    if turns == 0:
        converted = points.copy()
    elif turns == 1:
        converted = np.column_stack([width-1-y,x])
    elif turns == 3:
        converted = np.column_stack([y,height-1-x])
    elif turns == 2:
        converted = np.column_stack([width-1-x,height-1-y])
    else:
        raise ValueError('Unsupported rotation')
    converted[:,0] = np.clip(converted[:,0],0,width-1)
    converted[:,1] = np.clip(converted[:,1],0,height-1)
    return converted.astype(np.float32)

def same_hole(first, second):
    a,b = np.asarray(first),np.asarray(second)
    intersection = np.prod(np.maximum(0,np.minimum(a[2:],b[2:])-np.maximum(a[:2],b[:2])))
    area_a,area_b = np.prod(a[2:]-a[:2]),np.prod(b[2:]-b[:2])
    return intersection/max(area_a+area_b-intersection,1) >= .3

def rotate_expanded(image, angle):
    """Rotate without cropping, returning the inverse pixel transform."""
    h,w = image.shape[:2]
    matrix = cv2.getRotationMatrix2D(((w-1)/2,(h-1)/2),angle,1)
    corners = cv2.transform(np.float32([[[0,0],[w-1,0],[w-1,h-1],[0,h-1]]]),matrix)[0]
    low,high = corners.min(axis=0),corners.max(axis=0)
    matrix[:,2] -= low
    size = tuple(np.ceil(high-low+1).astype(int))
    return cv2.warpAffine(image,matrix,size),cv2.invertAffineTransform(matrix)

class EngineDetector:
    def __init__(self, model_path=DEFAULT_MODEL, bore_mode='own', imgsz=None, retina_masks=None):
        if bore_mode not in ('own','friend','fusion'):
            raise ValueError('未知检测方案')
        self.bore_mode = bore_mode
        self.imgsz = imgsz or (640 if bore_mode=='friend' else 960)
        self.retina_masks = (bore_mode=='friend') if retina_masks is None else retina_masks
        self.model_path = Path(model_path)
        auxiliary = PART_MODEL
        use_default = self.model_path.resolve() == DEFAULT_MODEL.resolve()
        if use_default and (BASE/'active_models.json').exists():
            from dataset_update import active_models
            active = active_models()
            self.model_path = Path(active['bore'])
            auxiliary = Path(active['part'])
        self.own_model_path = self.model_path
        if bore_mode == 'friend':
            self.model_path = FRIEND_MODEL
        self.model = YOLO(str(self.model_path))
        self.device = 0 if torch.cuda.is_available() else 'cpu'
        self.device_name = torch.cuda.get_device_name(0) if self.device == 0 else 'CPU'
        self.part_model = None
        self.part_model_path = auxiliary
        if use_default and auxiliary.exists():
            self.part_model = YOLO(str(auxiliary))
        self.friend_model = YOLO(str(FRIEND_MODEL)) if bore_mode == 'fusion' else None

    def analyze(self, image_path, output_dir=None):
        image_path = Path(image_path)
        result = self.model.predict(str(image_path), imgsz=self.imgsz, conf=.5 if self.bore_mode=='friend' else .01,
                                    retina_masks=self.retina_masks,
                                    max_det=100, device=self.device, verbose=False)[0]
        canvas = result.orig_img.copy()
        height, width = canvas.shape[:2]
        masks = list(result.masks.xy) if result.masks is not None else []
        boxes = result.boxes
        proposals = []
        for i in range(len(boxes)):
            proposals.append({'index': i, 'class': canonical_class(result.names[int(boxes.cls[i])]),
                              'source_model': self.bore_mode if self.bore_mode=='friend' else 'own',
                              'confidence': float(boxes.conf[i]),
                              'box_xyxy': [float(v) for v in boxes.xyxy[i]]})
        part_speed = None
        if self.part_model is not None:
            part_result = self.part_model.predict(str(image_path), imgsz=640, rect=False, conf=.01,
                                                  max_det=10, device=self.device, verbose=False,
                                                  predictor=FullPartPredictor)[0]
            proposals = [p for p in proposals if p['class'] != 'part']
            part_speed = part_result.speed
            if part_result.masks is not None:
                for i in range(len(part_result.boxes)):
                    if part_result.names[int(part_result.boxes.cls[i])] != 'part':
                        continue
                    index = len(masks)
                    masks.append(part_result.masks.xy[i])
                    proposals.append({'index': index, 'class': 'part',
                                      'confidence': float(part_result.boxes.conf[i]),
                                      'box_xyxy': [float(v) for v in part_result.boxes.xyxy[i]]})
        parts = [p for p in proposals if p['class'] == 'part' and p['index'] < len(masks) and len(masks[p['index']]) >= 3]
        bores = [p for p in proposals if p['class'] == 'bore' and p['confidence'] >= 0.5 and p['index'] < len(masks) and len(masks[p['index']]) >= 3]
        warnings = []
        part_score = max((p['confidence'] for p in parts), default=0.0)
        part_hull = cv2.convexHull(np.asarray(masks[max(parts,key=lambda p:p['confidence'])['index']],dtype=np.float32)) if parts else None
        initial_bore_count = len(bores)
        fusion_added = 0
        fusion_replaced = 0
        if self.friend_model is not None:
            extra = self.friend_model.predict(str(image_path),imgsz=640,conf=.5,retina_masks=True,
                max_det=100,device=self.device,verbose=False)[0]
            if extra.masks is not None:
                for i,points in enumerate(extra.masks.xy):
                    if canonical_class(extra.names[int(extra.boxes.cls[i])])!='bore' or len(points)<5:
                        continue
                    points=np.asarray(points,dtype=np.float32)
                    box=[float(v) for v in extra.boxes.xyxy[i]]
                    matched=next((b for b in bores if same_hole(box,b['box_xyxy'])),None)
                    replace=False
                    if matched:
                        # Only replace an unstable contour with a strongly supported
                        # fit. Scores from separate models are never averaged.
                        try:
                            old_support=robust_bore_ellipse(masks[matched['index']])[-1]
                        except (ValueError,cv2.error):
                            old_support=0
                        try:
                            new_support=robust_bore_ellipse(points)[-1]
                        except (ValueError,cv2.error):
                            new_support=0
                        replace=old_support<.85 and new_support>=.90 and new_support>old_support+.1
                        if not replace:
                            matched['second_model_confidence']=float(extra.boxes.conf[i])
                            continue
                    elif len(bores)>=4 or part_hull is None or part_score<.25:
                        continue
                    if part_hull is not None and part_score>=.25:
                        center=tuple((np.asarray(box[:2])+box[2:])/2)
                        ratio=cv2.contourArea(points)/max(cv2.contourArea(part_hull),1)
                        _,_,pw,ph=cv2.boundingRect(part_hull)
                        if cv2.pointPolygonTest(part_hull,center,True)<-.02*max(pw,ph) or not .01<=ratio<=.25:
                            continue
                    proposal={'index':len(masks),'class':'bore','confidence':float(extra.boxes.conf[i]),
                              'box_xyxy':box,'source_model':'friend'}
                    masks.append(points)
                    proposals.append(proposal)
                    if replace:
                        proposal['second_model_confidence']=matched['confidence']
                        bores[bores.index(matched)]=proposal
                        fusion_replaced+=1
                    else:
                        bores.append(proposal)
                        fusion_added+=1
        rotations_tried = []
        scales_tried = []
        center_checks = []
        recovered = 0
        def valid_candidate_count():
            # Small false detections must not prevent recovery of a missing bore.
            # Preserve the existing coverage guard when part is incomplete.
            if part_hull is None or part_score < .25:
                return len(bores)
            area = max(cv2.contourArea(part_hull), 1)
            coverage = []
            for bore in bores:
                if bore['confidence'] >= .85 or len(bores) == 4:
                    hull = cv2.convexHull(np.asarray(masks[bore['index']], dtype=np.float32))
                    overlap, _ = cv2.intersectConvexConvex(part_hull, hull)
                    coverage.append(max(0., float(overlap)) / max(cv2.contourArea(hull), 1))
            if coverage and min(coverage) < .9:
                return len(bores)
            _, _, pw, ph = cv2.boundingRect(part_hull)
            valid = 0
            for bore in bores:
                x1,y1,x2,y2 = bore['box_xyxy']
                center = ((x1+x2)/2, (y1+y2)/2)
                ratio = cv2.contourArea(np.asarray(masks[bore['index']], dtype=np.float32)) / area
                valid += int(cv2.pointPolygonTest(part_hull, center, True) >= -.02*max(pw,ph)
                             and .01 <= ratio <= .25)
            return valid

        if valid_candidate_count() < 4:
            recovery_passes = ([(0,640)] if self.imgsz != 640 else []) + [(1,self.imgsz),(3,self.imgsz),(2,self.imgsz)]
            if part_hull is not None and part_score >= .25:
                corners = cv2.boxPoints(cv2.minAreaRect(part_hull))
                edges = np.roll(corners,-1,axis=0)-corners
                axis = edges[np.argmax(np.linalg.norm(edges,axis=1))]
                angle = (float(np.degrees(np.arctan2(axis[1],axis[0])))+90)%180-90
                if abs(angle)>5:
                    recovery_passes += [(None,640),(None,self.imgsz)]
            for turns, recovery_size in recovery_passes:
                inverse = None
                if turns is None:
                    rotations_tried.append(round(angle,2))
                    rotated,inverse = rotate_expanded(result.orig_img,angle)
                elif turns:
                    rotations_tried.append(turns*90)
                else:
                    scales_tried.append(recovery_size)
                if turns is not None:
                    rotated = np.ascontiguousarray(np.rot90(result.orig_img,turns))
                extra = self.model.predict(rotated,imgsz=recovery_size,rect=False,conf=.5,retina_masks=self.retina_masks,
                                           max_det=100,device=self.device,verbose=False)[0]
                if extra.masks is None:
                    continue
                for i,points in enumerate(extra.masks.xy):
                    if canonical_class(extra.names[int(extra.boxes.cls[i])]) != 'bore' or len(points)<5:
                        continue
                    if inverse is not None:
                        points = cv2.transform(np.asarray(points,dtype=np.float32).reshape(1,-1,2),inverse)[0]
                    else:
                        points = points_to_original(points,turns,width,height)
                    low,high = points.min(axis=0),points.max(axis=0)
                    box = [float(v) for v in np.r_[low,high]]
                    matched = next((b for b in bores if same_hole(box,b['box_xyxy'])),None)
                    if matched:
                        try:
                            old = robust_bore_ellipse(masks[matched['index']])[0]
                            new = robust_bore_ellipse(points)[0]
                            distance = float(np.linalg.norm(np.asarray(old[0])-new[0]))
                            center_checks.append({'proposal_index':matched['index'], 'center_difference_px':round(distance,2),
                                                  'relative_difference':round(distance/max(min(old[1]),1),4),
                                                  'angle':angle if turns is None else turns*90, 'imgsz':recovery_size})
                        except (ValueError,cv2.error):
                            pass
                        continue
                    # Detection and ellipse fitting have separate quality checks.
                    # Keep a detected hole even when its center cannot be fitted reliably.
                    if part_hull is not None and part_score >= .25:
                        center = tuple((low+high)/2)
                        ratio = cv2.contourArea(points)/max(cv2.contourArea(part_hull),1)
                        _,_,pw,ph = cv2.boundingRect(part_hull)
                        if cv2.pointPolygonTest(part_hull,center,True)<-.02*max(pw,ph) or not .01<=ratio<=.25:
                            continue
                    index=len(masks)
                    masks.append(points)
                    proposal={'index':index,'class':'bore','confidence':float(extra.boxes.conf[i]),
                              'box_xyxy':box,'source_rotation_deg':angle if turns is None else turns*90,'source_imgsz':recovery_size}
                    proposal['source_model']='friend' if self.bore_mode=='friend' else 'own'
                    proposals.append(proposal)
                    bores.append(proposal)
                    recovered+=1
                if valid_candidate_count()>=4:
                    break
        constraint = False
        selected = bores[:]
        if parts:
            main = max(parts, key=lambda p: p['confidence'])
            part_hull = cv2.convexHull(np.asarray(masks[main['index']], dtype=np.float32))
            if part_score >= 0.25:
                part_area = cv2.contourArea(part_hull)
                coverage = []
                for bore in bores:
                    if bore['confidence'] >= .85 or len(bores) == 4:
                        hull = cv2.convexHull(np.asarray(masks[bore['index']], dtype=np.float32))
                        overlap, _ = cv2.intersectConvexConvex(part_hull, hull)
                        coverage.append(max(0.0, float(overlap)) / max(cv2.contourArea(hull), 1))
                if coverage and min(coverage) < .9:
                    warnings.append(f'part 未覆盖完整候选孔（最低覆盖 {min(coverage):.0%}），跳过位置约束。')
                else:
                    _, _, w, h = cv2.boundingRect(part_hull)
                    margin = .02 * max(w, h)
                    selected = []
                    for bore in bores:
                        x1, y1, x2, y2 = bore['box_xyxy']
                        center = ((x1+x2)/2, (y1+y2)/2)
                        ratio = cv2.contourArea(np.asarray(masks[bore['index']], dtype=np.float32)) / max(part_area, 1)
                        if cv2.pointPolygonTest(part_hull, center, True) >= -margin and .01 <= ratio <= .25:
                            selected.append(bore)
                    constraint = True
            else:
                warnings.append(f'part 最高分 {part_score:.4f} 低于 0.25，跳过位置约束。')
        else:
            warnings.append('未得到可用 part 轮廓，跳过位置约束。')
        if len(selected) > 4:
            warnings.append(f'候选孔超过四个（{len(selected)} 个），本轮只拟合最高分四个，请复核误检。')
        selected = sorted(selected, key=lambda p: p['confidence'], reverse=True)[:4]
        selected.sort(key=lambda p: (p['box_xyxy'][0]+p['box_xyxy'][2]) if width >= height else (p['box_xyxy'][1]+p['box_xyxy'][3]))
        # Keep part filtering above; show only bores and their fitted centers.
        centers = []
        for number, bore in enumerate(selected, 1):
            points = np.asarray(masks[bore['index']], dtype=np.float32)
            cv2.polylines(canvas, [points.astype(np.int32).reshape(-1,1,2)], True, (255,255,0), 2)
            fit_source = 'segmentation_contour'
            edge_info = {}
            try:
                try:
                    ellipse, samples, inliers, residual, support = robust_bore_ellipse(points)
                except (cv2.error, ValueError):
                    # A partial contour only initializes the search. Original-image
                    # edge evidence must independently pass the refinement checks.
                    seed, samples, inliers, residual, support = robust_bore_ellipse(
                        points,min_support=.60,min_coverage=.90)
                    ellipse,edge_info = refine_aperture_edge(result.orig_img,seed)
                    if not edge_info['used']:
                        raise ValueError('原图边缘复核失败：'+edge_info['reason'])
                    fit_source = 'image_edge_verified'
                    residual = edge_info['median_residual_px']
                if fit_source == 'segmentation_contour' and support < .85:
                    refined,verification = refine_multi_edge(result.orig_img,ellipse)
                    if verification['used']:
                        ellipse = refined
                        edge_info = verification
                        residual = verification['median_residual_px']
                        fit_source = 'image_edge_verified'
                    else:
                        warnings.append(f"孔 {number} 分割轮廓不稳定，原图边缘修正未通过：{verification['reason']}；请复核圆心。")
                (cx, cy), (a, b), angle = ellipse
                if not (0 <= cx < width and 0 <= cy < height):
                    raise ValueError('拟合中心超出原图')
            except (cv2.error, ValueError) as error:
                warnings.append(f'孔 {number} 拟合质量不足：{error}')
                continue
            cv2.ellipse(canvas, ellipse, (0,255,255), max(2,min(height,width)//500))
            center = (round(cx), round(cy))
            cv2.drawMarker(canvas, center, (0,0,255), cv2.MARKER_CROSS, max(20,min(height,width)//60), 3)
            cv2.putText(canvas, str(number), (center[0]+15, center[1]-15), cv2.FONT_HERSHEY_SIMPLEX, max(.7,min(height,width)/1500), (0,0,255), 3)
            for point in samples[~inliers]:
                cv2.circle(canvas, tuple(np.rint(point).astype(int)), 3, (255,0,255), -1)
            centers.append({'hole_id': number, 'center_x_px': round(cx,2), 'center_y_px': round(cy,2),
                            'fit_source': fit_source, 'edge_support': edge_info.get('support'),
                            'edge_angle_coverage': edge_info.get('coverage'),
                            'edge_method': edge_info.get('method','single_image_edge') if edge_info else None,
                            'edge_center_spread_px': edge_info.get('center_spread_px'),
                            'source_rotation_deg': bore.get('source_rotation_deg',0),
                            'confidence': round(bore['confidence'],4),
                            'source_model':bore.get('source_model','own'),
                            'second_model_confidence':bore.get('second_model_confidence'),
                            'fit_median_residual_px': round(residual,3),
                            'contour_support': round(support,4), 'ellipse_axis1_px': round(a,2),
                            'ellipse_axis2_px': round(b,2), 'ellipse_angle_deg': round(angle,2)})
        if len(centers) != 4:
            warnings.append(f'有效拟合中心为 {len(centers)} 个，请人工复核。')
        output_dir = Path(output_dir or BASE / 'results')
        output_dir.mkdir(parents=True, exist_ok=True)
        prefix = output_dir / (image_path.stem + '_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
        image_dest = prefix.with_suffix('.jpg')
        Image.fromarray(cv2.cvtColor(canvas,cv2.COLOR_BGR2RGB)).save(image_dest, quality=95)
        csv_dest = prefix.with_suffix('.csv')
        keys = ['hole_id','center_x_px','center_y_px','confidence','source_rotation_deg','fit_source','edge_support','edge_angle_coverage','edge_method','edge_center_spread_px','fit_median_residual_px','contour_support','ellipse_axis1_px','ellipse_axis2_px','ellipse_angle_deg']
        keys.extend(['source_model','second_model_confidence'])
        with csv_dest.open('w',newline='',encoding='utf-8-sig') as file:
            writer = csv.DictWriter(file,fieldnames=keys)
            writer.writeheader()
            writer.writerows(centers)
        report = {'image': str(image_path.resolve()), 'model': str(self.model_path.resolve()),
                  'bore_mode':self.bore_mode,'fusion_added_count':fusion_added,
                  'inference_imgsz':self.imgsz,'retina_masks':self.retina_masks,
                  'fusion_replaced_count':fusion_replaced,
                  'friend_model':str(FRIEND_MODEL) if self.bore_mode in ('friend','fusion') else None,
                  'initial_bore_count': initial_bore_count, 'rotation_angles_tried': rotations_tried,
                  'recovery_scales_tried': scales_tried,
                  'center_consistency_diagnostics': center_checks,
                  'rotation_recovered_count': recovered,
                  'part_model': str(self.part_model_path) if self.part_model is not None else None,
                  'device': self.device_name, 'image_size': [width,height], 'part_max_confidence': part_score,
                  'bore_raw_count': len(bores), 'bore_selected_count': len(selected), 'part_constraint_applied': constraint,
                  'selected_bores': [{'hole_id': number, 'confidence': round(bore['confidence'],4), 'box_xyxy': bore['box_xyxy']}
                                     for number, bore in enumerate(selected, 1)],
                  'centers': centers, 'warnings': warnings, 'proposals': proposals,
                  'prediction_speed_ms': result.speed, 'result_image': str(image_dest), 'result_csv': str(csv_dest),
                  'part_prediction_speed_ms': part_speed,
                  'coordinate_note': '原图像素拟合中心；不是经过标定的实际孔中心或机械臂坐标。'}
        prefix.with_suffix('.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        return report
