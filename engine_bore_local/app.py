from pathlib import Path
import argparse
import json
import os
import queue
import threading
import gc
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageTk
from experiment_records import ExperimentRecords, COLUMNS
from record_grid import RecordGrid

BASE = Path(__file__).resolve().parent
LAST_BATCH = BASE / 'last_batch.json'

def launch_management(validation_only=False):
    """Run just the existing management tools alongside the Qt shell."""
    root = tk.Tk()
    root.withdraw()
    root.title('训练数据管理')
    if validation_only:
        jobs = sorted((BASE/'updates').glob('*/validation.json'), reverse=True)
        if not jobs:
            messagebox.showinfo('训练验证结果', '尚无训练验证结果。', parent=root)
            root.destroy()
            return
        from validation_view import show_validation
        window = show_validation(root, jobs[0].parent)
        window.protocol('WM_DELETE_WINDOW', root.destroy)
        root.mainloop()
        return

    from dataset_window import DatasetWindow
    updating = [False]
    def lock():
        updating[0] = True
    def unlock():
        updating[0] = False
    manager = DatasetWindow(root, busy=lambda: updating[0], lock=lock, unlock=unlock)
    manager.show()
    def work_pending():
        return bool(manager.active or manager.copying or manager.label_process)
    def close_manager():
        if work_pending():
            manager.window.iconify()
        else:
            root.destroy()
    manager.window.protocol('WM_DELETE_WINDOW', close_manager)
    root.protocol('WM_DELETE_WINDOW', close_manager)
    def check_hidden():
        if manager.window.state() == 'withdrawn' and not work_pending():
            visible = any(isinstance(child, tk.Toplevel) and child.winfo_viewable()
                          for child in root.winfo_children())
            if not visible:
                root.destroy()
                return
        root.after(500, check_hidden)
    root.after(500, check_hidden)
    root.mainloop()

def launch(open_dataset=False, open_validation=False, open_records=False):
    root = tk.Tk()
    root.title('箱体孔检测 · 本地 GPU')
    root.geometry('1080x900')
    try:
        records = ExperimentRecords()
    except (OSError, ValueError, KeyError) as error:
        messagebox.showerror('实验记录读取失败', f'原记录文件已保留，请检查：\n{error}')
        root.destroy()
        return
    if not records.groups and LAST_BATCH.exists():
        try:
            history = json.loads(LAST_BATCH.read_text(encoding='utf-8'))
            if history:
                group_id = records.begin([r['image'] for r in history], history[0].get('model', ''))
                records.groups[-1]['time'] = '历史结果（导入）'
                for report in history:
                    records.update(group_id, report=report)
                records.update(group_id, status='历史已完成')
        except (OSError, ValueError, KeyError) as error:
            messagebox.showwarning('历史记录导入提示', str(error))
    active_group = [None]
    model_path = tk.StringVar(value=str(BASE/'models'/'engine_part_bore_100.pt'))
    model_summary = tk.StringVar()
    def refresh_model_summary():
        if Path(model_path.get()).resolve() == (BASE/'models'/'engine_part_bore_100.pt').resolve():
            active_file = BASE/'active_models.json'
            try:
                active = json.loads(active_file.read_text(encoding='utf-8'))
                model_summary.set(f"当前正式模型：{active['version']}（自动选择验证表现较好的模型）")
            except (OSError, ValueError, KeyError):
                model_summary.set('当前模型：内置模型')
        else:
            model_summary.set(f'当前模型：{Path(model_path.get()).name}')
    refresh_model_summary()
    state = tk.StringVar(value='选择照片即可检测。首次加载模型可能稍慢。')
    header = ttk.Frame(root, padding=12)
    header.pack(fill='x')
    button = ttk.Button(header,text='选择照片并检测')
    button.pack(side='left',padx=4)
    def choose_model():
        selected = filedialog.askopenfilename(title='选择模型 .pt',filetypes=[('模型','*.pt')])
        if selected:
            model_path.set(selected)
            refresh_model_summary()
    model_button = ttk.Button(header,text='更换模型',command=choose_model)
    model_button.pack(side='left',padx=4)
    def open_results():
        folder = BASE/'results'
        folder.mkdir(exist_ok=True)
        os.startfile(str(folder))
    ttk.Button(header,text='打开结果文件夹',command=open_results).pack(side='left',padx=4)
    ttk.Label(root,textvariable=model_summary,wraplength=1000).pack(anchor='w',padx=16)
    if (BASE/'models'/'engine_part_only_fixed.pt').exists():
        ttk.Label(root,text='默认模型启用独立 part 检测；自动更新后，下次检测使用最新通过验证的版本。').pack(anchor='w',padx=16)
    ttk.Label(root,textvariable=state,wraplength=1000).pack(anchor='w',padx=16,pady=8)
    tabs = ttk.Notebook(root)
    tabs.pack(fill='both', expand=True, padx=12, pady=4)
    result_tab = ttk.Frame(tabs)
    record_tab = ttk.Frame(tabs)
    tabs.add(result_tab, text='检测图片')
    tabs.add(record_tab, text='实验记录表')
    if open_records:
        root.after(200,lambda:tabs.select(record_tab))
    record_tools = ttk.Frame(record_tab, padding=8)
    record_tools.pack(fill='x')
    record_summary = tk.StringVar()
    ttk.Label(record_tools, textvariable=record_summary).pack(side='left')
    def export_records():
        destination = filedialog.asksaveasfilename(title='导出全部实验记录',
            initialfile='箱体孔实验记录.csv', defaultextension='.csv', filetypes=[('CSV 表格', '*.csv')])
        if destination:
            try:
                records.export(destination)
                state.set(f'实验记录已导出：{destination}')
            except OSError as error:
                messagebox.showerror('导出失败', str(error))
    ttk.Button(record_tools, text='导出全部记录（Excel / WPS）', command=export_records).pack(side='right')
    ttk.Label(record_tab, text='每次选择的一批照片为一组；新组追加保存。空白表示没有保留该孔。孔号按图像位置排序，并非固定物理孔编号。',
              wraplength=1000).pack(anchor='w', padx=8, pady=4)
    table_frame = ttk.Frame(record_tab)
    table_frame.pack(fill='both', expand=True)
    visible_columns = COLUMNS[:15]
    table = RecordGrid(table_frame, columns=[key for key, label in visible_columns])
    for key, label in visible_columns:
        table.heading(key, text=label)
        table.column(key, width=110, minwidth=65, stretch=False)
    table.column('photo', width=235)
    table.column('time', width=165)
    table.column('warnings', width=480)
    vertical = ttk.Scrollbar(table_frame, orient='vertical', command=table.yview)
    horizontal = ttk.Scrollbar(table_frame, orient='horizontal', command=table.xview)
    table.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
    table.grid(row=0, column=0, sticky='nsew')
    vertical.grid(row=0, column=1, sticky='ns')
    horizontal.grid(row=1, column=0, sticky='ew')
    table_frame.rowconfigure(0, weight=1)
    table_frame.columnconfigure(0, weight=1)
    def refresh_records():
        table.delete(*table.get_children())
        for row in records.rows():
            table.insert('', 'end', values=[row.get(key, '') for key, label in visible_columns])
        record_summary.set(f'累计 {len(records.groups)} 组，{len(records.rows())} 张图片；双击记录打开检测图片。')
        children = table.get_children()
        if children:
            table.see(children[-1])
    def open_record(event):
        item = table.identify_row(event.y)
        if item:
            index = table.index(item)
            path = records.rows()[index]['result_image']
            if path and Path(path).is_file():
                os.startfile(path)
    table.bind('<Double-1>', open_record)
    refresh_records()
    navigation = ttk.Frame(result_tab, padding=(12, 4))
    navigation.pack(fill='x')
    previous_button = ttk.Button(navigation, text='上一张', state='disabled')
    previous_button.pack(side='left',padx=4)
    selector = ttk.Combobox(navigation, state='readonly', width=48)
    selector.pack(side='left',padx=4,fill='x',expand=True)
    next_button = ttk.Button(navigation, text='下一张', state='disabled')
    next_button.pack(side='left',padx=4)
    page = tk.StringVar(value='尚无结果')
    ttk.Label(navigation,textvariable=page).pack(side='left',padx=8)
    log = tk.Text(result_tab,height=9,wrap='word',font=('Microsoft YaHei UI',10))
    log.pack(fill='x',padx=16)
    preview = ttk.Label(result_tab,anchor='center')
    preview.pack(fill='both',expand=True,padx=12,pady=8)
    ttk.Label(result_tab,text='青色：模型孔轮廓；黄色：拟合椭圆；红色十字：图像拟合中心。像素坐标不直接用于机械臂。').pack(pady=6)
    mailbox = queue.Queue()
    cached = {}
    reports = []
    current = [0]
    expected = [0]
    training_busy = [False]
    def release_detector():
        cached.clear()
        gc.collect()
        torch = sys.modules.get('torch')
        if torch and torch.cuda.is_available():
            torch.cuda.empty_cache()
    def lock_training():
        training_busy[0] = True
        button.config(state='disabled')
        model_button.config(state='disabled')
        release_detector()
        state.set('正在更新训练数据库和模型；可在“添加训练照片”窗口查看进度。')
    def unlock_training():
        training_busy[0] = False
        release_detector()
        button.config(state='normal')
        model_button.config(state='normal')
        refresh_model_summary()
        state.set('更新流程已结束，详情请查看添加训练照片窗口。默认模型在下次检测时重新加载。')
    from dataset_window import DatasetWindow
    dataset_window = DatasetWindow(root,
        busy=lambda: training_busy[0] or str(button['state'])=='disabled',
        lock=lock_training,unlock=unlock_training)
    ttk.Button(header,text='添加训练照片 / 自动更新',command=dataset_window.show).pack(side='left',padx=4)
    if open_dataset:
        root.after(200,dataset_window.show)
    if open_validation:
        root.after(400,dataset_window.show_validation)
    def close_application():
        if training_busy[0]:
            if not messagebox.askyesno('更新正在进行','关闭软件会停止本次训练。确定关闭吗？'):
                return
            dataset_window.stop()
        root.destroy()
    root.protocol('WM_DELETE_WINDOW',close_application)
    def show_report(index):
        if not reports: return
        current[0] = max(0,min(index,len(reports)-1))
        report = reports[current[0]]
        selector['values'] = [f'{i+1}. {Path(r["image"]).name}' for i,r in enumerate(reports)]
        selector.current(current[0])
        page.set(f'{current[0]+1}/{len(reports)} 张')
        previous_button.config(state='normal' if current[0]>0 else 'disabled')
        next_button.config(state='normal' if current[0]<len(reports)-1 else 'disabled')
        log.delete('1.0','end')
        log.insert('end',f"照片：{Path(report['image']).name}；设备：{report['device']}\npart 最高分：{report['part_max_confidence']:.4f}；孔数量：{report['bore_raw_count']}；拟合中心：{len(report['centers'])}\n")
        log.insert('end',f"part 位置筛选：{'已执行' if report['part_constraint_applied'] else '已跳过，请复核'}\n")
        if report.get('rotation_angles_tried'):
            log.insert('end',f"旋转复查：补检 {report.get('rotation_recovered_count',0)} 个孔（置信度 ≥0.5）。\n")
        for center in report['centers']:
            log.insert('end',f"孔 {center['hole_id']}：x={center['center_x_px']}, y={center['center_y_px']} px；置信度 {center['confidence']}\n")
            if center.get('fit_source') == 'image_edge_verified':
                log.insert('end','  圆心已通过原图孔口边缘复核。\n')
        for warning in report['warnings']: log.insert('end',warning+'\n')
        with Image.open(report['result_image']) as original:
            image = original.copy()
        image.thumbnail((1000,620))
        photo = ImageTk.PhotoImage(image)
        preview.config(image=photo)
        preview.image = photo
    previous_button.config(command=lambda: show_report(current[0]-1))
    next_button.config(command=lambda: show_report(current[0]+1))
    selector.bind('<<ComboboxSelected>>',lambda event: show_report(selector.current()))
    def save_batch():
        LAST_BATCH.write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding='utf-8')
    def update_record(**changes):
        try:
            records.update(active_group[0], **changes)
        except OSError as error:
            messagebox.showerror('实验记录保存失败', f'本次记录暂未写入磁盘，请保留软件窗口。\n{error}')
    def worker(paths,model):
        try:
            from detect_core import EngineDetector
            if cached.get('path') != model:
                release_detector()
                cached['detector'] = EngineDetector(model)
                cached['path'] = model
            detector = cached['detector']
            for position,path in enumerate(paths,1):
                mailbox.put(('status',f'{detector.device_name}：正在处理 {position}/{len(paths)} {Path(path).name}'))
                mailbox.put(('result',detector.analyze(path)))
            mailbox.put(('done',None))
        except Exception as error:
            import traceback
            mailbox.put(('error',traceback.format_exc()))
    def choose():
        paths = filedialog.askopenfilenames(title='选择测试照片',initialdir=r'C:\训练照片（箱体）',filetypes=[('图片','*.jpg *.jpeg *.png *.bmp')])
        if not paths: return
        try:
            active_group[0] = records.begin(paths, model_path.get())
        except OSError as error:
            messagebox.showerror('记录保存失败', str(error))
            return
        refresh_records()
        tabs.select(result_tab)
        reports.clear()
        current[0] = 0
        expected[0] = len(paths)
        selector['values'] = []
        selector.set('')
        page.set(f'0/{len(paths)} 张已完成')
        previous_button.config(state='disabled'); next_button.config(state='disabled')
        preview.config(image=''); preview.image = None
        log.delete('1.0','end')
        button.config(state='disabled')
        model_button.config(state='disabled')
        state.set('正在加载模型并准备检测…')
        threading.Thread(target=worker,args=(paths,model_path.get()),daemon=True).start()
    button.config(command=choose)
    def poll():
        while not mailbox.empty():
            kind,payload = mailbox.get()
            if kind=='status': state.set(payload)
            elif kind=='result':
                reports.append(payload)
                update_record(report=payload)
                refresh_records()
                save_batch()
                show_report(current[0])
            elif kind=='done':
                update_record(status='已完成')
                refresh_records()
                tabs.select(record_tab)
                state.set(f'检测完成：{len(reports)}/{expected[0]} 张。用上一张、下一张或下拉列表查看，全部结果已保存。')
                button.config(state='normal'); model_button.config(state='normal')
            elif kind=='error':
                update_record(status='未完成，请复核')
                refresh_records()
                state.set('检测失败，请查看下方信息。')
                log.insert('end',payload)
                button.config(state='normal'); model_button.config(state='normal')
        root.after(100,poll)
    if LAST_BATCH.exists():
        try:
            reports.extend(r for r in json.loads(LAST_BATCH.read_text(encoding='utf-8')) if Path(r['result_image']).is_file())
            if reports:
                show_report(0)
                state.set(f'已恢复上次的 {len(reports)} 张结果，可以逐张查看，或选择新照片检测。')
        except (OSError,ValueError,KeyError):
            reports.clear()
    root.after(100,poll)
    root.mainloop()

if __name__=='__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--image')
    parser.add_argument('--out')
    parser.add_argument('--model',default=str(BASE/'models'/'engine_part_bore_100.pt'))
    parser.add_argument('--dataset',action='store_true')
    parser.add_argument('--validation',action='store_true')
    parser.add_argument('--records',action='store_true')
    parser.add_argument('--simulation',action='store_true')
    parser.add_argument('--dataset-only',action='store_true')
    parser.add_argument('--validation-only',action='store_true')
    args = parser.parse_args()
    if args.image:
        from detect_core import EngineDetector
        report = EngineDetector(args.model).analyze(args.image,args.out)
        print(json.dumps(report,ensure_ascii=False,indent=2))
    elif args.dataset_only or args.dataset:
        launch_management()
    elif args.validation_only or args.validation:
        launch_management(validation_only=True)
    else:
        from inspection_gui.main import main
        raise SystemExit(main(open_records=args.records, open_simulation=args.simulation))
