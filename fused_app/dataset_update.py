"""Build immutable datasets and train validated, versioned local models."""
from pathlib import Path
from datetime import datetime
import argparse
import hashlib
import json
import shutil
import traceback

BASE = Path(__file__).resolve().parent
ACTIVE = BASE / 'active_models.json'
SEED = Path(r'C:\训练照片（箱体）')
DEFAULT_BORE = BASE / 'models' / 'engine_part_bore_100.pt'
DEFAULT_PART = BASE / 'models' / 'engine_part_only_fixed.pt'
SEED_REGISTRY = BASE/'data'/'database_seed'/'registry.json'


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def active_models():
    if ACTIVE.exists():
        data = json.loads(ACTIVE.read_text(encoding='utf-8'))
        def resolve_paths(value):
            if isinstance(value, dict):
                return {key: str((BASE/child).resolve()) if key in ('image','annotation','bore','part','selected_bore','validation_job_path') and isinstance(child,str) and not Path(child).is_absolute() else resolve_paths(child) for key,child in value.items()}
            if isinstance(value,list):
                return [resolve_paths(child) for child in value]
            return value
        return resolve_paths(data)
    entries = json.loads(SEED_REGISTRY.read_text(encoding='utf-8')) if SEED_REGISTRY.exists() else []
    return {'bore': str(DEFAULT_BORE), 'part': str(DEFAULT_PART), 'entries': entries}


def read_pair(image):
    import numpy as np
    import cv2
    from PIL import Image
    annotation = image.with_suffix('.json')
    if not annotation.exists():
        raise ValueError(f'{image.name} 尚未保存同名 JSON 标注。')
    data = json.loads(annotation.read_text(encoding='utf-8-sig'))
    with Image.open(image) as opened:
        width, height = opened.size
    if data.get('imageWidth') != width or data.get('imageHeight') != height:
        raise ValueError(f'{image.name} 标注尺寸与照片不一致。')
    shapes = data.get('shapes', [])
    if sum(s.get('label') == 'part' for s in shapes) != 1:
        raise ValueError(f'{image.name} 必须标一个完整的 part。')
    if not 1 <= sum(s.get('label') == 'bore' for s in shapes) <= 4:
        raise ValueError(f'{image.name} 需要标 1～4 个可见目标 bore。')
    for shape in shapes:
        if shape.get('label') not in ('part', 'bore') or shape.get('shape_type', 'polygon') != 'polygon':
            raise ValueError(f'{image.name} 请只用多边形标注 part 和 bore。')
        points = np.asarray(shape.get('points', []), dtype=np.float32)
        if points.ndim != 2 or points.shape[1] != 2 or len(points) < 3 or not np.isfinite(points).all():
            raise ValueError(f'{image.name} 存在无效多边形。')
        if (points < 0).any() or (points > [width, height]).any() or abs(cv2.contourArea(points)) < 1:
            raise ValueError(f'{image.name} 标注越界或面积无效。')
    canonical = json.dumps(shapes, sort_keys=True, ensure_ascii=False).encode('utf-8')
    return {'image': str(image.resolve()), 'annotation': str(annotation.resolve()),
            'hash': hashlib.sha256(image.read_bytes()).hexdigest(),
            'label_hash': hashlib.sha256(canonical).hexdigest(), 'shapes': shapes,
            'width': width, 'height': height}


def prepare(folder, job, seed=SEED, previous=None):
    folder, job, seed = Path(folder), Path(job), Path(seed)
    job.mkdir(parents=True, exist_ok=True)
    previous = active_models() if previous is None else previous
    entries = list(previous.get('entries', []))
    if not entries:
        for number in range(1, 26):
            entry = read_pair(seed / f'{number:03d}.jpg')
            entry['split'] = 'train' if number <= 20 else 'val'
            entries.append(entry)
    images = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in ('.jpg','.jpeg','.png','.bmp'))
    if not images:
        raise ValueError('这个文件夹没有照片，请先放入新照片。')
    existing = {entry['hash']: entry for entry in entries}
    incoming = []
    errors = []
    for image in images:
        try:
            entry = read_pair(image)
            old = existing.get(entry['hash'])
            if old and old['label_hash'] == entry['label_hash']:
                continue
            if old and old['split'] == 'val':
                raise ValueError(f'{image.name} 属于固定验证集，不能作为新增训练照片或改写验证标注。')
            entry['split'] = old['split'] if old else 'train'
            if entry['hash'] in {e['hash'] for e in incoming}:
                raise ValueError(f'{image.name} 与本组另一张照片内容重复。')
            incoming.append(entry)
        except (ValueError, OSError, KeyError) as error:
            errors.append(str(error))
    if errors:
        raise ValueError('\n'.join(errors))
    if not incoming:
        raise ValueError('没有新增或修改的标注，本次无需重新训练。')
    new = sorted((e for e in incoming if e['hash'] not in existing), key=lambda e:e['hash'])
    if len(new) >= 5:
        for entry in new[:max(1,len(new)//5)]:
            entry['split'] = 'val'
    merged = {e['hash']: e for e in entries}
    merged.update({e['hash']: e for e in incoming})
    return materialize(list(merged.values()),job,previous,len(incoming))


def materialize(entries,job,previous,new_count):
    job=Path(job)
    job.mkdir(parents=True,exist_ok=True)
    snapshots = []
    for entry in entries:
        raw = job / 'raw'
        raw.mkdir(exist_ok=True)
        image = raw / (entry['hash'] + Path(entry['image']).suffix.lower())
        annotation = raw / (entry['hash'] + '.json')
        shutil.copy2(entry['image'], image)
        shutil.copy2(entry['annotation'], annotation)
        snapshot = dict(entry, image=str(image), annotation=str(annotation))
        snapshots.append(snapshot)
        for task in ('bore', 'part'):
            dataset = job / task
            image_dir, label_dir = dataset/'images'/entry['split'], dataset/'labels'/entry['split']
            image_dir.mkdir(parents=True, exist_ok=True)
            label_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(image, image_dir/image.name)
            lines = []
            for shape in entry['shapes']:
                if task == 'part' and shape['label'] != 'part':
                    continue
                category = 0 if shape['label'] == 'part' else 1
                coords = [coordinate/divisor for point in shape['points'] for coordinate,divisor in zip(point,(entry['width'],entry['height']))]
                lines.append(str(category)+' '+' '.join(f'{coordinate:.8f}' for coordinate in coords))
            (label_dir/(image.stem+'.txt')).write_text('\n'.join(lines)+'\n', encoding='utf-8')
    for task in ('bore', 'part'):
        dataset = job/task
        names = '  0: part\n  1: bore\n' if task == 'bore' else '  0: part\n'
        (dataset/'dataset.yaml').write_text(f'path: {dataset.as_posix()}\ntrain: images/train\nval: images/val\nnames:\n'+names, encoding='utf-8')
    plan = {'entries': snapshots, 'previous': previous, 'new_count': new_count,
            'train_count': sum(e['split']=='train' for e in snapshots),
            'val_count': sum(e['split']=='val' for e in snapshots)}
    write_json(job/'plan.json', plan)
    return plan


def gates_pass(baseline, candidate):
    tolerance = 1e-6
    return (candidate['bore_map'] >= baseline['bore_map']-tolerance and
            candidate['part_iou'] >= baseline['part_iou']-tolerance and
            candidate['part_min_iou'] >= baseline['part_min_iou']-.05)


def preserve_seed():
    if SEED_REGISTRY.exists():
        return
    folder = SEED_REGISTRY.parent
    folder.mkdir(parents=True, exist_ok=True)
    entries = []
    for number in range(1,26):
        entry = read_pair(SEED/f'{number:03d}.jpg')
        for key in ('image','annotation'):
            source = Path(entry[key])
            destination = folder/source.name
            shutil.copy2(source,destination)
            entry[key] = str(destination)
        entry['split'] = 'train' if number<=20 else 'val'
        entries.append(entry)
    write_json(SEED_REGISTRY,entries)


def evaluate(bore_path, part_path, plan, job, label):
    from ultralytics import YOLO
    from part_predictor import FullPartPredictor
    import cv2
    import numpy as np
    bore = YOLO(str(bore_path))
    result = bore.val(data=str(job/'bore'/'dataset.yaml'), imgsz=960, batch=1,
                      device=0, workers=0, plots=False, verbose=False,
                      project=str(job/'evaluation'), name=label)
    score = float(result.seg.maps[1])
    model = YOLO(str(part_path))
    scores = []
    photos = []
    from PIL import Image
    output = job/'evaluation'/label
    output.mkdir(parents=True,exist_ok=True)
    for entry in plan['entries']:
        if entry['split'] != 'val':
            continue
        prediction = model.predict(entry['image'], imgsz=640, rect=False, conf=.25,
                                   device=0, verbose=False, predictor=FullPartPredictor)[0]
        truth = np.zeros((entry['height'],entry['width']), dtype=np.uint8)
        points = next(s['points'] for s in entry['shapes'] if s['label']=='part')
        cv2.fillPoly(truth,[np.rint(points).astype(np.int32)],1)
        predicted = np.zeros_like(truth)
        if prediction.masks is not None and len(prediction.boxes):
            index = int(prediction.boxes.conf.argmax())
            cv2.fillPoly(predicted,[np.rint(prediction.masks.xy[index]).astype(np.int32)],1)
        scores.append(float(np.logical_and(predicted,truth).sum()/max(1,np.logical_or(predicted,truth).sum())))
        detected = bore.predict(entry['image'],imgsz=960,conf=.5,device=0,verbose=False)[0]
        canvas = prediction.orig_img.copy()
        scale = max(2,min(canvas.shape[:2])//500)
        for shape in entry['shapes']:
            cv2.polylines(canvas,[np.rint(shape['points']).astype(np.int32)],True,(0,180,0),scale)
        if detected.masks is not None:
            for index,box in enumerate(detected.boxes):
                if int(box.cls[0])==1:
                    polygon = np.rint(detected.masks.xy[index]).astype(np.int32)
                    cv2.polylines(canvas,[polygon],True,(255,255,0),scale)
        if prediction.masks is not None and len(prediction.boxes):
            cv2.polylines(canvas,[np.rint(prediction.masks.xy[int(prediction.boxes.conf.argmax())]).astype(np.int32)],True,(0,0,255),scale)
        preview = Image.fromarray(cv2.cvtColor(canvas,cv2.COLOR_BGR2RGB))
        preview.thumbnail((900,700))
        image_dest = output/(entry['hash']+'_comparison.jpg')
        preview.save(image_dest,quality=95)
        annotation = json.loads(Path(entry['annotation']).read_text(encoding='utf-8-sig'))
        photos.append({'image':entry['image'],'name':Path(annotation.get('imagePath',entry['image']).replace('\\','/')).name,
                       'preview':str(image_dest),'part_iou':scores[-1],
                       'bore_confidences':[float(box.conf[0]) for box in detected.boxes if int(box.cls[0])==1]})
    write_json(job/'evaluation'/(label+'_photos.json'),photos)
    return {'bore_map': score, 'part_iou': sum(scores)/len(scores), 'part_min_iou': min(scores)}


def run(folder, job, epochs, profile=None):
    import torch
    from ultralytics import YOLO
    job = Path(job)
    job.mkdir(parents=True, exist_ok=True)
    def status(stage, message, **extra):
        write_json(job/'status.json', {'stage':stage, 'message':message, **extra})
        print(message, flush=True)
    try:
        if not torch.cuda.is_available():
            raise ValueError('没有可用本地 GPU，请先检查显卡环境。旧模型保持可用。')
        status('checking', '正在检查标注并合并数据库…')
        if profile:
            from hybrid_annotations import prepare_profile
            plan=prepare_profile(profile,job)
        else:
            plan = prepare(folder, job)
        status('validating', f"合并完成：新增/修改 {plan['new_count']} 张，共 {plan['train_count']} 张训练、{plan['val_count']} 张验证。正在评估旧模型…")
        baseline = evaluate(plan['previous']['bore'],plan['previous']['part'],plan,job,'before')
        candidates = {'part':plan['previous']['part']} if profile else {}
        for task in (('bore',) if profile else ('bore', 'part')):
            name = '孔模型' if task=='bore' else 'part 模型'
            status('training', f'开始训练{name}，共 {epochs} 轮…')
            model = YOLO(plan['previous'][task])
            def progress(trainer, name=name):
                status('training', f'{name}：第 {trainer.epoch+1}/{epochs} 轮', epoch=trainer.epoch+1, epochs=epochs)
            model.add_callback('on_train_epoch_end', progress)
            model.train(data=str(job/task/'dataset.yaml'), epochs=epochs,
                        imgsz=960 if task=='bore' else 640, batch=2 if task=='bore' else 4,
                        device=0, workers=0, optimizer='AdamW', lr0=.0003,
                        warmup_bias_lr=.0003, nbs=2 if task=='bore' else 4,
                        mosaic=0, degrees=180, flipud=.5, scale=.1, translate=.01,
                        overlap_mask=False, patience=30, seed=43, cache=False,
                        plots=False, project=str(job/'training'), name=task)
            candidates[task] = str(Path(model.trainer.best).resolve())
            del model
            torch.cuda.empty_cache()
        status('validating', '孔模型训练完成，正在验证；part 模型保持原版本。' if profile else '训练完成，正在验证两个新模型…')
        candidate = evaluate(candidates['bore'],candidates['part'],plan,job,'after')
        write_json(job/'validation.json', {'baseline':baseline, 'candidate':candidate})
        if not gates_pass(baseline, candidate):
            status('rejected', '新模型验证表现下降，未启用；旧模型继续使用。新数据和训练结果已保留。', baseline=baseline,candidate=candidate)
            return
        if active_models() != plan['previous']:
            raise ValueError('启用模型版本在训练期间已发生变化，本次结果保留，请重新更新。')
        version = dict(candidates, entries=plan['entries'], version=job.name,
                       validation={'baseline':baseline, 'candidate':candidate})
        if ACTIVE.exists():
            shutil.copy2(ACTIVE,job/'previous_active_models.json')
        # Both model paths and dataset versions switch in one atomic manifest update.
        write_json(ACTIVE, version)
        status('complete', '更新成功：合并标注的新孔模型已验证并启用；沿用原 part 模型。' if profile else '更新成功：新孔模型和 part 模型已验证并启用。旧版本已保留。', version=job.name)
    except Exception as error:
        (job/'error.txt').write_text(traceback.format_exc(), encoding='utf-8')
        status('error', str(error)+'\n旧模型未改变，请修正后重试。')


if __name__=='__main__':
    parser = argparse.ArgumentParser()
    sources=parser.add_mutually_exclusive_group(required=True)
    sources.add_argument('--folder')
    sources.add_argument('--profile')
    parser.add_argument('--job', required=True)
    parser.add_argument('--epochs', type=int, default=100)
    args = parser.parse_args()
    run(args.folder,args.job,args.epochs,profile=args.profile)
