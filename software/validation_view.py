from pathlib import Path
import json
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk

METRICS = [('bore_map','孔分割 mAP50–95'),('part_iou','part 平均轮廓重合度'),
           ('part_min_iou','part 最低轮廓重合度')]


def show_validation(root,job):
    job = Path(job)
    result = json.loads((job/'validation.json').read_text(encoding='utf-8'))
    status = json.loads((job/'status.json').read_text(encoding='utf-8')) if (job/'status.json').exists() else {}
    selection_path = job/'model_selection.json'
    if selection_path.exists():
        selection = json.loads(selection_path.read_text(encoding='utf-8'))
        status['message'] = selection['message']
    window = tk.Toplevel(root)
    window.title('训练验证结果 · '+job.name)
    window.geometry('1180x900')
    ttk.Label(window,text='训练前后验证对比',font=('Microsoft YaHei UI',15,'bold')).pack(anchor='w',padx=16,pady=10)
    ttk.Label(window,text=status.get('message','正在验证；最终启用状态尚未确定。'),wraplength=1100).pack(anchor='w',padx=16)
    table = ttk.Treeview(window,columns=('metric','before','after','difference'),show='headings',height=3)
    for key,title in [('metric','验证指标'),('before','训练前'),('after','训练后'),('difference','变化')]:
        table.heading(key,text=title)
        table.column(key,width=250)
    for key,title in METRICS:
        before,after = result['baseline'][key],result['candidate'][key]
        table.insert('','end',values=(title,f'{before:.4f}',f'{after:.4f}',f'{after-before:+.4f}'))
    table.pack(fill='x',padx=16,pady=10)
    ttk.Label(window,text='指标越高越好。mAP 是孔分割的综合指标，不是识别正确率或单个孔置信度。轮廓重合度是预测区域与人工标注的 IoU。\n当前启用规则：孔 mAP 和 part 平均 IoU 均不得下降（容许极小浮点误差），part 最低 IoU 下降不得超过 0.05。',
              wraplength=1120).pack(anchor='w',padx=16,pady=4)
    before_path,after_path = job/'evaluation'/'before_photos.json',job/'evaluation'/'after_photos.json'
    if not (before_path.exists() and after_path.exists()):
        ttk.Label(window,text='逐张对照图尚未生成。汇总指标已显示。').pack(pady=20)
        return window
    old = json.loads(before_path.read_text(encoding='utf-8'))
    new = {photo['image']:photo for photo in json.loads(after_path.read_text(encoding='utf-8'))}
    pairs = [(photo,new[photo['image']]) for photo in old if photo['image'] in new]
    if not pairs:
        return window
    index = [0]
    navigation = ttk.Frame(window,padding=8)
    navigation.pack(fill='x')
    title = tk.StringVar()
    summary = tk.StringVar()
    picture_area = ttk.Frame(window)
    picture_area.pack(fill='both',expand=True)
    labels = []
    for column,text in enumerate(('训练前','训练后')):
        frame=ttk.Frame(picture_area)
        frame.grid(row=0,column=column,sticky='nsew',padx=5)
        picture_area.columnconfigure(column,weight=1)
        ttk.Label(frame,text=text).pack()
        label=ttk.Label(frame,anchor='center')
        label.pack(fill='both',expand=True)
        labels.append(label)
    picture_area.rowconfigure(0,weight=1)
    ttk.Label(window,textvariable=summary,wraplength=1120).pack(padx=16,pady=5)
    ttk.Label(window,text='绿色：人工标注；青色：预测孔口轮廓（置信度 ≥0.5）；红色：预测 part 轮廓。此处展示分割验证，不进行圆心拟合。').pack(padx=12,pady=5)
    def display(number):
        index[0]=max(0,min(number,len(pairs)-1))
        pair=pairs[index[0]]
        title.set(f'{index[0]+1}/{len(pairs)} · {pair[0]["name"]}')
        for photo,label in zip(pair,labels):
            with Image.open(photo['preview']) as original:
                image=original.copy()
            image.thumbnail((550,450))
            label.image=ImageTk.PhotoImage(image)
            label.config(image=label.image)
        texts=[]
        for caption,photo in zip(('训练前','训练后'),pair):
            scores=', '.join(f'{score:.4f}' for score in photo['bore_confidences']) or '未检出'
            texts.append(f'{caption}：part IoU {photo["part_iou"]:.4f}；孔置信度（按分数排序）：{scores}')
        summary.set('\n'.join(texts))
    ttk.Button(navigation,text='上一张',command=lambda:display(index[0]-1)).pack(side='left')
    ttk.Label(navigation,textvariable=title).pack(side='left',padx=15)
    ttk.Button(navigation,text='下一张',command=lambda:display(index[0]+1)).pack(side='right')
    display(0)
    return window
