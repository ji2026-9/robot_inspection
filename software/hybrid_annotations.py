"""Versioned friend-bore / local-part labels on the original local pixels."""
from pathlib import Path
from copy import deepcopy
import argparse
import hashlib
import json
import shutil
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from dataset_update import BASE, active_models, read_pair, write_json

ROOT=BASE/'data'/'hybrid_part_friend_bore_v1'
EXPERIMENT=BASE/'experiments'/'hybrid_labels_v1'
FRIEND=BASE/'friend_package'/'package_v1'/'dataset'/'box_yolo'


def fingerprint(image):
    gray=np.asarray(image.convert('L').resize((512,512)),dtype=np.float32)
    return gray


def friend_polygons(path):
    polygons=[]
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        values=line.split()
        if not values:continue
        if values[0]!='0' or len(values)<7 or len(values)%2!=1:
            raise ValueError(f'{path.name} 不是单类别 YOLO 多边形标注。')
        points=np.asarray([float(v) for v in values[1:]],dtype=np.float64).reshape(-1,2)
        if not np.isfinite(points).all() or (points<0).any() or (points>1).any():
            raise ValueError(f'{path.name} 有无效归一化坐标。')
        polygons.append(points)
    if len(polygons)!=4:
        raise ValueError(f'{path.name} 的孔数不是4个。')
    return polygons


def build():
    previous=active_models()
    source_entries=previous['entries']
    mapping={}
    for split in ('train','val','test'):
        for image in (FRIEND/'images'/split).glob('*.jpg'):
            if image.name in mapping:
                raise ValueError('朋友包中存在重复编号：'+image.name)
            mapping[image.name]=(image,FRIEND/'labels'/split/(image.stem+'.txt'))
    ROOT.mkdir(parents=True,exist_ok=True)
    labelme=ROOT/'labelme'
    labelme.mkdir(exist_ok=True)
    previews=ROOT/'review'
    previews.mkdir(exist_ok=True)
    result=[]
    audit=[]
    names=set()
    font=ImageFont.truetype(r'C:\Windows\Fonts\msyh.ttc',20)
    for entry in source_entries:
        annotation=json.loads(Path(entry['annotation']).read_text(encoding='utf-8-sig'))
        original=deepcopy(annotation)
        name=Path(annotation.get('imagePath',entry['image']).replace('\\','/')).name
        if name in names:raise ValueError('本地照片名称冲突：'+name)
        names.add(name)
        revision={'image':name,'split':entry['split'],'part_source':'local','bore_source':'local'}
        with Image.open(entry['image']) as im:
            local=im.convert('RGB')
        if name in mapping:
            image,label=mapping[name]
            with Image.open(image) as im:
                supplied=im.convert('RGB')
            if abs(local.width/local.height-supplied.width/supplied.height)>.001:
                raise ValueError(name+' 双方图片比例不一致，不能直接映射。')
            difference=float(np.abs(fingerprint(local)-fingerprint(supplied)).mean())
            if difference>2:
                raise ValueError(f'{name} 解码像素差异较大 ({difference:.2f})，需人工核对坐标。')
            polygons=friend_polygons(label)
            part=[deepcopy(s) for s in annotation['shapes'] if s['label']=='part']
            if len(part)!=1:raise ValueError(name+' 缺少唯一 part。')
            bores=[{'label':'bore','points':(points*[local.width,local.height]).tolist(),
                    'group_id':None,'shape_type':'polygon','flags':{},
                    'description':'朋友人工 bore 标注；从归一化坐标映射到本地原图。'} for points in polygons]
            annotation['shapes']=part+bores
            revision.update(bore_source='friend',pixel_mean_absolute_difference=difference,
                            friend_label=str(label),friend_image=str(image))
            assert part==[s for s in original['shapes'] if s['label']=='part']
        annotation['imagePath']=name
        annotation['imageData']=None
        destination=labelme/name
        shutil.copy2(entry['image'],destination)
        write_json(destination.with_suffix('.json'),annotation)
        checked=read_pair(destination)
        assert checked['hash']==entry['hash']
        checked['split']=entry['split']
        result.append(checked)
        panels=[]
        for data in (original,annotation):
            panel=np.asarray(local).copy()
            thickness=max(3,min(local.width,local.height)//450)
            for shape in data['shapes']:
                color=(230,45,35) if shape['label']=='part' else (0,210,230)
                cv2.polylines(panel,[np.rint(shape['points']).astype(np.int32)],True,color,thickness)
            preview=Image.fromarray(panel)
            preview.thumbnail((540,620))
            panels.append(preview)
        canvas=Image.new('RGB',(1100,680),'white')
        draw=ImageDraw.Draw(canvas)
        for index,(panel,title) in enumerate(zip(panels,('原标注','你的 part + 朋友 bore' if revision['bore_source']=='friend' else '新增照片：原标注保留'))):
            draw.text((index*550+12,8),title,font=font,fill='black')
            canvas.paste(panel,(index*550+(550-panel.width)//2,48))
        preview_path=previews/(Path(name).stem+'_labels.jpg')
        canvas.save(preview_path,quality=95)
        revision['preview']=str(preview_path)
        audit.append(revision)
    count=sum(item['bore_source']=='friend' for item in audit)
    if count!=25:raise ValueError(f'预期25张重复照片，实际匹配{count}张。')
    manifest={'previous':previous,'entries':result,'annotation_revision_count':count,
              'train_count':sum(e['split']=='train' for e in result),
              'val_count':sum(e['split']=='val' for e in result),'review':audit,
              'note':'仅合并人工标注；没有引入朋友训练权重。维持本地划分，比较模型时在同一份新标注上重新评估。'}
    write_json(ROOT/'manifest.json',manifest)
    EXPERIMENT.mkdir(parents=True,exist_ok=True)
    write_json(EXPERIMENT/'merge_audit.json',audit)
    print(f"MERGED {len(result)} images; {count} friend-bore revisions; {manifest['train_count']} train / {manifest['val_count']} val",flush=True)
    return manifest


def prepare_profile(profile,job):
    from dataset_update import materialize
    manifest=json.loads(Path(profile).read_text(encoding='utf-8'))
    previous=active_models()
    if previous!=manifest['previous']:
        raise ValueError('当前数据库或模型已更新，请重新生成合并标注，再进行训练。')
    existing={e['hash']:e for e in previous['entries']}
    entries=[]
    for recorded in manifest['entries']:
        checked=read_pair(Path(recorded['image']))
        if checked['hash'] not in existing or checked['hash']!=recorded['hash']:
            raise ValueError('合并照片内容变化，请重新核对。')
        old=existing[checked['hash']]
        if [s for s in old['shapes'] if s['label']=='part']!=[s for s in checked['shapes'] if s['label']=='part']:
            raise ValueError('part 标注发生变化；本次合并只允许替换 bore。')
        checked['split']=old['split']
        entries.append(checked)
    if {e['hash'] for e in entries}!=set(existing):
        raise ValueError('合并数据遗漏已有照片。')
    return materialize(entries,Path(job),previous,manifest['annotation_revision_count'])


if __name__=='__main__':build()
