from pathlib import Path
import json
import cv2
import numpy as np
from detect_core import EngineDetector, BASE

if __name__ == '__main__':
    detector = EngineDetector()
    rows = []
    for n in range(21,26):
        name = f'{n:03d}'
        r = detector.analyze(Path(r'C:\训练照片（箱体）')/(name+'.jpg'),BASE/'part_fix_check')
        row = {k:r[k] for k in ['part_max_confidence','bore_raw_count','bore_selected_count','part_constraint_applied','warnings','result_image','part_model']}
        row['image'] = name
        row['centers'] = len(r['centers'])
        rows.append(row)
        print(json.dumps(row,ensure_ascii=False),flush=True)
    (BASE/'part_fix_check'/'summary.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
