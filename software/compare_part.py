from pathlib import Path
import json
import cv2
import numpy as np
from ultralytics import YOLO
from part_predictor import FullPartPredictor

BASE = Path(__file__).resolve().parent
SOURCE = Path(r'C:\训练照片（箱体）')

def evaluate(model_path, numbers, imgsz=960, rect=True, full_part=False):
    model = YOLO(str(model_path))
    rows = []
    for n in numbers:
        name = f'{n:03d}'
        data = json.loads((SOURCE/(name+'.json')).read_text(encoding='utf-8'))
        h,w = data['imageHeight'],data['imageWidth']
        truth = np.zeros((h,w),np.uint8)
        poly = [s['points'] for s in data['shapes'] if s['label']=='part'][0]
        cv2.fillPoly(truth,[np.array(poly,np.int32)],1)
        options = {'predictor': FullPartPredictor} if full_part else {}
        r = model.predict(str(SOURCE/(name+'.jpg')),imgsz=imgsz,rect=rect,conf=.01,device=0,verbose=False,**options)[0]
        ids = [i for i,c in enumerate(r.boxes.cls.tolist()) if r.names[int(c)]=='part']
        i = max(ids,key=lambda i:float(r.boxes.conf[i])) if ids else None
        score = float(r.boxes.conf[i]) if i is not None else 0
        prediction = np.zeros_like(truth)
        if i is not None and r.masks is not None:
            cv2.fillPoly(prediction,[r.masks.xy[i].astype(np.int32)],1)
        intersection = np.count_nonzero(truth & prediction)
        union = np.count_nonzero(truth | prediction)
        outer = np.zeros_like(truth)
        if i is not None and r.masks is not None:
            cv2.fillPoly(outer,[cv2.convexHull(r.masks.xy[i].astype(np.int32))],1)
        coverage = []
        for shape in data['shapes']:
            if shape['label']=='bore':
                m = np.zeros_like(truth)
                cv2.fillPoly(m,[np.array(shape['points'],np.int32)],1)
                coverage.append(np.count_nonzero(m & outer)/max(np.count_nonzero(m),1))
        rows.append({'image':name,'confidence':score,'mask_iou':intersection/max(union,1),'minimum_bore_coverage':min(coverage)})
    print(str(model_path),json.dumps(rows),flush=True)
    return rows

if __name__ == '__main__':
    import sys
    candidate = Path(sys.argv[1])
    report = {'validation_old':evaluate(BASE/'models'/'engine_part_bore_100.pt',range(21,26)),
              'validation_new':evaluate(candidate,range(21,26),640,False,True)}
    (BASE/'part_comparison.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
