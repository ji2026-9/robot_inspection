from pathlib import Path
import gc
import json
import time
import torch
from PIL import Image, ImageDraw, ImageFont
from detect_core import EngineDetector, FRIEND_MODEL, canonical_class

BASE=Path(__file__).resolve().parent
OUT=BASE/'experiments'/'friend_fusion_v1'


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    groups=json.loads((BASE/'experiment_records.json').read_text(encoding='utf-8'))
    images=[Path(r['image']) for r in next(g for g in groups if g['number']==2)['reports']]
    images+=sorted((FRIEND_MODEL.parent.parent/'test_images').glob('*.jpg'))
    reports={}
    for mode in ('own','friend','fusion'):
        detector=EngineDetector(bore_mode=mode)
        results=[]
        for image in images:
            start=time.perf_counter()
            report=detector.analyze(image,OUT/mode)
            report['elapsed_seconds']=round(time.perf_counter()-start,3)
            results.append(report)
            print(mode,image.name,'raw',report['initial_bore_count'],'selected',report['bore_selected_count'],
                  'centers',len(report['centers']),'fusion',report['fusion_added_count'],report['fusion_replaced_count'],flush=True)
        reports[mode]=results
        del detector
        gc.collect()
        torch.cuda.empty_cache()
    (OUT/'comparison.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding='utf-8')
    font=ImageFont.truetype(r'C:\Windows\Fonts\msyh.ttc',20)
    for index,image in enumerate(images):
        canvas=Image.new('RGB',(1260,630),'white')
        draw=ImageDraw.Draw(canvas)
        for column,(mode,title) in enumerate(zip(('own','friend','fusion'),('当前模型','朋友孔模型 + 本地 part','双模型融合试验'))):
            report=reports[mode][index]
            preview=Image.open(report['result_image']).copy()
            preview.thumbnail((410,520))
            x=column*420+(420-preview.width)//2
            canvas.paste(preview,(x,65))
            scores=', '.join(f"{b['confidence']:.3f}" for b in report['selected_bores'])
            draw.text((column*420+8,5),title,font=font,fill='black')
            draw.text((column*420+8,32),f"孔 {report['bore_selected_count']} / 圆心 {len(report['centers'])}",font=font,fill='black')
            draw.text((column*420+8,590),scores,font=font,fill='black')
        canvas.save(OUT/f'comparison_{index+1:02d}.jpg',quality=95)
    summary={mode:{'images':len(values),'four_detections':sum(r['bore_selected_count']==4 for r in values),
                   'four_centers':sum(len(r['centers'])==4 for r in values),
                   'initial_four':sum(r['initial_bore_count']==4 for r in values),
                   'minimum_confidence':min(b['confidence'] for r in values for b in r['selected_bores']),
                   'average_seconds':sum(r['elapsed_seconds'] for r in values)/len(values)} for mode,values in reports.items()}
    (OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__':main()
