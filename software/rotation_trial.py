import json
import time
from pathlib import Path
from detect_core import EngineDetector

old = [json.loads(path.read_text(encoding='utf-8')) for path in sorted(Path('results/gui_batches/20261007_124026_185274').glob('*.json'))]
detector = EngineDetector()
summary = []
for number, item in enumerate(old, 1):
    start = time.time()
    result = detector.analyze(item['image'], 'experiments/rotation_trial')
    row = dict(number=number, old_count=item['bore_selected_count'],
               new_count=result['bore_selected_count'], centers=len(result['centers']),
               seconds=round(time.time()-start, 2), angles=result['rotation_angles_tried'],
               checks=result['center_consistency_diagnostics'], warnings=result['warnings'])
    summary.append(row)
    print(row, flush=True)
Path('experiments/rotation_trial/summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
