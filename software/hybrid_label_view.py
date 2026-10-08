from pathlib import Path
import json
import os
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk
from hybrid_annotations import ROOT


def show_hybrid_labels(root,train_callback):
    profile=ROOT/'manifest.json'
    if not profile.exists():
        messagebox.showinfo('合并标注','尚未生成合并标注。')
        return
    manifest=json.loads(profile.read_text(encoding='utf-8'))
    window=tk.Toplevel(root)
    window.title('标注合并复核 · 你的 part + 朋友 bore')
    window.geometry('1160x920')
    ttk.Label(window,text=f"已整理 {len(manifest['entries'])} 张照片：{manifest['annotation_revision_count']} 张替换孔标注，part 保留原样。",font=('Microsoft YaHei UI',13,'bold')).pack(anchor='w',padx=12,pady=8)
    ttk.Label(window,text=f"仍为 {manifest['train_count']} 张训练、{manifest['val_count']} 张验证；新增3张照片保留自己的标注。红色是 part，青色是 bore。\n这是人工标注对照，不是模型预测。023 两个远端孔的双方标注差异较大，请重点核对；细致不代表必然更准确。",wraplength=1120).pack(anchor='w',padx=12,pady=5)
    navigation=ttk.Frame(window,padding=8)
    navigation.pack(fill='x')
    selector=ttk.Combobox(navigation,state='readonly',width=60,
        values=[f"{i+1}. {row['image']} · {'朋友孔标注' if row['bore_source']=='friend' else '本地新增标注'}" for i,row in enumerate(manifest['review'])])
    picture=ttk.Label(window,anchor='center')
    picture.pack(fill='both',expand=True)
    index=[0]
    def display(value):
        index[0]=max(0,min(value,len(manifest['review'])-1))
        selector.current(index[0])
        row=manifest['review'][index[0]]
        with Image.open(row['preview']) as original:
            image=original.copy()
        image.thumbnail((1120,640))
        picture.image=ImageTk.PhotoImage(image)
        picture.config(image=picture.image)
    ttk.Button(navigation,text='上一张',command=lambda:display(index[0]-1)).pack(side='left')
    selector.pack(side='left',padx=15)
    ttk.Button(navigation,text='下一张',command=lambda:display(index[0]+1)).pack(side='right')
    selector.bind('<<ComboboxSelected>>',lambda event:display(selector.current()))
    zoom=ROOT.parent.parent/'experiments'/'hybrid_labels_v1'/'spotcheck_images'/'023_far_bore_zoom.png'
    if zoom.exists():
        ttk.Button(window,text='查看 023 远端孔放大对照',command=lambda:os.startfile(str(zoom))).pack(anchor='e',padx=12,pady=3)
    actions=ttk.Frame(window,padding=12)
    actions.pack(fill='x')
    ttk.Label(actions,text='训练时仅更新孔模型，沿用当前独立 part 模型；会用同一份合并验证标注重新比较训练前后结果。',wraplength=760).pack(side='left')
    ttk.Button(actions,text='用这份标注更新孔模型',command=lambda:train_callback(profile)).pack(side='right')
    display(next((i for i,row in enumerate(manifest['review']) if row['image']=='023.jpg'),0))
    return window
