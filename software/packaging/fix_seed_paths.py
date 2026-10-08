import json
from pathlib import Path

root = Path(__file__).resolve().parent/'payload'
manifest = json.loads((root/'active_models.json').read_text(encoding='utf-8'))
for entry in manifest['entries']:
    path = root/entry['annotation']
    annotation = json.loads(path.read_text(encoding='utf-8-sig'))
    annotation['imagePath'] = Path(entry['image']).name
    annotation['imageData'] = None
    path.write_text(json.dumps(annotation,ensure_ascii=False,indent=2),encoding='utf-8')
print('Repaired all bundled annotation image paths')
