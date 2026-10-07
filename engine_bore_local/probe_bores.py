from pathlib import Path
import json
import numpy as np
from PIL import Image
from ultralytics import YOLO

BASE=Path(__file__).resolve().parent
if __name__=='__main__':
    batch=json.loads((BASE/'last_batch.json').read_text(encoding='utf-8'))
    dest=BASE/'bore_fix_inputs'; dest.mkdir(exist_ok=True)
    model=YOLO(str(BASE/'models'/'engine_part_bore_100.pt'))
    for number in [2,4,5]:
        report=batch[number-1]
        im=Image.open(report['image']).convert('RGB')
        target=dest/f'{number}.jpg'; im.save(target,quality=100)
        if number==5: continue
        proposals=[p for p in report['proposals'] if p['class']=='bore' and .15 <= p['confidence']<.3]
        p=min(proposals,key=lambda p:p['box_xyxy'][1])
        x1,y1,x2,y2=p['box_xyxy']; w=x2-x1; h=y2-y1
        crop=(max(0,int(x1-w*.5)),max(0,int(y1-h*.5)),min(im.width,int(x2+w*.5)),min(im.height,int(y2+h*.5)))
        roi=np.asarray(im.crop(crop))[...,::-1].copy()
        for k in [0,2]:
            r=model.predict(np.ascontiguousarray(np.rot90(roi,k)),imgsz=960,conf=.1,device=0,verbose=False)[0]
            print(number,'crop',k,[(r.names[int(r.boxes.cls[i])],round(float(r.boxes.conf[i]),4),[round(float(v)) for v in r.boxes.xyxy[i]]) for i in range(len(r.boxes))],flush=True)
            Image.fromarray(r.plot()[...,::-1]).save(dest/f'{number}_crop_{k}.jpg')
