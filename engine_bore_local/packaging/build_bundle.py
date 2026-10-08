"""Build relocatable Windows payload, without local experiment/device history."""
import json
import shutil
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
DEST = BASE / 'packaging' / 'payload'
DEST.mkdir(parents=True,exist_ok=True)
PYTHON = Path(sys.base_prefix)

def copy(source, target):
    target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(source,target)

def ignore(folder,names):
    return [name for name in names if name in ('__pycache__','.git','.pytest_cache') or name.endswith('.pyc')]

modules = ['app.py','dataset_window.py','dataset_update.py','detect_core.py',
           'edge_bore_refinement.py','experiment_records.py','record_grid.py',
           'part_predictor.py','robust_bore_ellipse.py','validation_view.py',
           'hybrid_annotations.py','hybrid_label_view.py','fusion_view.py','runtime_paths.py',
           'labelme_training.yaml']
for module in modules:
    copy(BASE/module,DEST/module)
shutil.copytree(BASE/'inspection_gui',DEST/'inspection_gui',dirs_exist_ok=True,
                ignore=lambda folder,names:ignore(folder,names)+[name for name in names if name in ('device_settings.json','robot_verified_info.json')])

for environment in ('.venv','.labelme_env'):
    target = DEST/environment
    target.mkdir(exist_ok=True)
    for source in PYTHON.iterdir():
        if source.name in ('Lib','Scripts','include','libs'):
            continue
        if source.is_dir():
            shutil.copytree(source,target/source.name,dirs_exist_ok=True,ignore=ignore)
        else:
            copy(source,target/source.name)
    shutil.copytree(PYTHON/'Lib',target/'Lib',dirs_exist_ok=True,
                    ignore=lambda folder,names:ignore(folder,names)+(['site-packages'] if Path(folder)==PYTHON/'Lib' else []))
    shutil.copytree(BASE/environment/'Lib'/'site-packages',target/'Lib'/'site-packages',dirs_exist_ok=True,ignore=ignore)
    for pattern in ('msvcp140*.dll','vcruntime140*.dll','concrt140*.dll'):
        for dll in (target/'Lib'/'site-packages'/'PySide6').glob(pattern):
            copy(dll,target/dll.name)
    # The copied interpreter is a complete standalone install, not a venv stub.
    print('Runtime copied:',environment,flush=True)

active = json.loads((BASE/'active_models.json').read_text(encoding='utf-8'))
for task in ('bore','part'):
    relative = f'models/{task}_best.pt'
    copy(Path(active[task]),DEST/relative)
    active[task] = relative
entries = active['entries']
for entry in entries:
    for key in ('image','annotation'):
        source = Path(entry[key])
        relative = f'data/database_seed/{source.name}'
        copy(source,DEST/relative)
        entry[key] = relative
    annotation = DEST/entry['annotation']
    label = json.loads(annotation.read_text(encoding='utf-8-sig'))
    label['imagePath'] = Path(entry['image']).name
    label['imageData'] = None
    annotation.write_text(json.dumps(label,ensure_ascii=False,indent=2),encoding='utf-8')
active.pop('selection',None)
(DEST/'active_models.json').write_text(json.dumps(active,ensure_ascii=False,indent=2),encoding='utf-8')
(DEST/'data'/'database_seed'/'registry.json').write_text(json.dumps(entries,ensure_ascii=False,indent=2),encoding='utf-8')
for task,name in [('bore','engine_part_bore_100.pt'),('part','engine_part_only_fixed.pt')]:
    copy(DEST/active[task],DEST/'models'/name)
print('Payload ready:',DEST, 'dataset entries:',len(entries),flush=True)
