from pathlib import Path
import json
import shutil
import cv2
import numpy as np
from ultralytics import YOLO

BASE = Path(__file__).resolve().parent
SOURCE = Path(r'C:\训练照片（箱体）')
ORIGINAL = Path(r'C:\Users\86189\Documents\Codex\2026-10-05\files-pasted-by-the-user-project\outputs\engine_part_bore_yolo_seg_25')

def prepare():
    root = BASE / 'data' / 'part_only_25'
    audit = []
    for number in range(1, 26):
        name = f'{number:03d}'
        split = 'train' if number <= 20 else 'val'
        data = json.loads((SOURCE / (name+'.json')).read_text(encoding='utf-8'))
        part = [s for s in data['shapes'] if s['label'] == 'part']
        bore = [s for s in data['shapes'] if s['label'] == 'bore']
        assert len(part) == 1 and len(bore) == 4, name
        w, h = data['imageWidth'], data['imageHeight']
        original = (ORIGINAL/'labels'/split/(name+'.txt')).read_text().splitlines()
        exported = [np.array(list(map(float,row.split()[1:]))).reshape(-1,2) for row in original if row.split()[0]=='0']
        pts = np.array(part[0]['points'])
        assert len(exported)==1 and np.allclose(exported[0]*[w,h],pts,atol=.01), name
        poly = pts.astype(np.float32)
        inside = [cv2.pointPolygonTest(poly, tuple(np.mean(s['points'],axis=0)),False)>=0 for s in bore]
        audit.append({'image':name,'part_points':len(pts),'four_centers_inside':all(inside),'export_matches_json':True})
        image_dest = root/'images'/split/(name+'.jpg')
        label_dest = root/'labels'/split/(name+'.txt')
        image_dest.parent.mkdir(parents=True,exist_ok=True)
        label_dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(SOURCE/(name+'.jpg'),image_dest)
        coords = (pts/[w,h]).reshape(-1)
        label_dest.write_text('0 '+' '.join(f'{v:.8f}' for v in coords)+'\n')
    root.mkdir(parents=True,exist_ok=True)
    yaml = root/'dataset.yaml'
    yaml.write_text(f'path: {root.as_posix()}\ntrain: images/train\nval: images/val\nnames:\n  0: part\n')
    (BASE/'part_label_audit.json').write_text(json.dumps(audit,indent=2),encoding='utf-8')
    print('AUDIT', len(audit), 'export correct; centers inside',sum(a['four_centers_inside'] for a in audit),flush=True)
    return yaml

if __name__ == '__main__':
    yaml = prepare()
    model = YOLO(str(BASE/'runs'/'part_only_fix-2'/'weights'/'best.pt'))
    model.train(data=str(yaml),epochs=100,imgsz=640,batch=4,device=0,workers=0,
                optimizer='AdamW',lr0=.0003,nbs=4,warmup_bias_lr=.0003,patience=100,seed=43,
                mosaic=0,scale=.1,translate=.01,degrees=180,flipud=.5,
                overlap_mask=False,cache=False,amp=True,plots=True,
                project=str(BASE/'runs'),name='part_rotation_fix',exist_ok=False)
    print('PART BEST',model.trainer.best,flush=True)
