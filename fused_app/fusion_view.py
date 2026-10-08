from pathlib import Path
import json
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk
from record_grid import RecordGrid

BASE=Path(__file__).resolve().parent
OUT=BASE/'experiments'/'friend_fusion_v1'


def show_comparison(root):
    if not (OUT/'comparison.json').exists():
        messagebox.showinfo('模型对照','尚未生成模型对照结果。')
        return
    reports=json.loads((OUT/'comparison.json').read_text(encoding='utf-8'))
    summary=json.loads((OUT/'summary.json').read_text(encoding='utf-8'))
    window=tk.Toplevel(root)
    window.title('当前模型 · 朋友模型 · 融合试验对照')
    window.geometry('1320x890')
    ttk.Label(window,text='当前这七张照片上，融合没有增加收益；默认继续使用当前模型。',font=('Microsoft YaHei UI',13,'bold')).pack(anchor='w',padx=12,pady=8)
    table=RecordGrid(window,columns=['mode','complete','centers','minimum'])
    for key,title in [('mode','检测方案'),('complete','保留四孔的图片数'),('centers','拟合四圆心的图片数'),('minimum','最低保留置信度')]:
        table.heading(key,text=title)
        table.column(key,width=300)
    table.pack(fill='x',padx=12)
    table.body.configure(height=105)
    for mode,title in [('own','当前模型（960）'),('friend','朋友孔模型（640，原尺寸掩膜）'),('fusion','双模型融合试验')]:
        row=summary[mode]
        table.insert('','end',values=[title,f"{row['four_detections']}/{row['images']}",f"{row['four_centers']}/{row['images']}",f"{row['minimum_confidence']:.4f}"])
    ttk.Label(window,text='第二组实验 3 张 + 朋友提供的测试照片 4 张。固定阈值 0.5；同用本地 part 筛选、旋转复查和拟合方法。\n数量和置信度不能证明圆心更准确；这些新图尚无人工圆心真值，也未计算正式 mAP。编号是图像内顺序。',wraplength=1280).pack(anchor='w',padx=12,pady=5)
    navigation=ttk.Frame(window,padding=8)
    navigation.pack(fill='x')
    selector=ttk.Combobox(navigation,state='readonly',width=65,
        values=[f"{index+1}. {Path(r['image']).name}" for index,r in enumerate(reports['own'])])
    picture=ttk.Label(window,anchor='center')
    picture.pack(fill='both',expand=True)
    index=[0]
    def display(value):
        index[0]=max(0,min(value,len(reports['own'])-1))
        selector.current(index[0])
        with Image.open(OUT/f'comparison_{index[0]+1:02d}.jpg') as original:
            image=original.copy()
        image.thumbnail((1280,570))
        picture.image=ImageTk.PhotoImage(image)
        picture.config(image=picture.image)
    ttk.Button(navigation,text='上一张',command=lambda:display(index[0]-1)).pack(side='left')
    selector.pack(side='left',padx=15)
    ttk.Button(navigation,text='下一张',command=lambda:display(index[0]+1)).pack(side='right')
    selector.bind('<<ComboboxSelected>>',lambda event:display(selector.current()))
    display(0)
    return window
