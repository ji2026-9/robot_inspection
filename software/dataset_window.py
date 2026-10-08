from pathlib import Path
from datetime import datetime
import json
import os
import subprocess
import shutil
import threading
import queue
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

BASE = Path(__file__).resolve().parent
IMPORTS = BASE/'data'/'incoming_photos'


def copy_photos(paths, folder):
    folder.mkdir(parents=True, exist_ok=False)
    for path in paths:
        source = Path(path)
        if not source.is_file():
            raise OSError(f'无法读取 {source.name}，请先在手机连接中另存到电脑，再选择。')
        destination = folder/source.name
        number = 2
        while destination.exists():
            destination = folder/f'{source.stem}_{number}{source.suffix}'
            number += 1
        shutil.copy2(source,destination)
        annotation = source.with_suffix('.json')
        if annotation.is_file():
            data = json.loads(annotation.read_text(encoding='utf-8-sig'))
            data['imagePath'] = destination.name
            destination.with_suffix('.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    return folder


class DatasetWindow:
    def __init__(self, root, busy, lock, unlock):
        self.root, self.busy, self.lock, self.unlock = root, busy, lock, unlock
        self.window = None
        self.label_process = None
        self.train_process = None
        self.log_file = None
        self.job = None
        self.folder = None
        self.active = False
        self.auto_session = False
        self.last_status = ''
        self.copying = False
        self.copy_messages = queue.Queue()
        root.after(700, self.poll)

    def show(self):
        if self.window and self.window.winfo_exists():
            self.window.deiconify()
            self.window.lift()
            return
        self.window = tk.Toplevel(self.root)
        self.window.title('添加训练照片 · 标注与自动更新')
        self.window.geometry('860x590')
        self.window.protocol('WM_DELETE_WINDOW', self.window.withdraw)
        box = ttk.Frame(self.window, padding=16)
        box.pack(fill='both', expand=True)
        ttk.Label(box, text='添加训练照片', font=('Microsoft YaHei UI',15,'bold')).pack(anchor='w')
        ttk.Label(box, text='① 点击“选择新照片”，照片自动复制到本机；也可选择电脑中的照片文件夹。\n② Labelme 打开后，每张照片标完整 part 和全部可见 bore。\n③ 保存全部标注，关闭 Labelme；软件自动检查、训练并验证新模型。',
                  wraplength=740, justify='left').pack(anchor='w', pady=12)
        self.folder_text = tk.StringVar(value=str(self.folder) if self.folder else '尚未选择新照片文件夹')
        ttk.Label(box,textvariable=self.folder_text,wraplength=740).pack(anchor='w',pady=6)
        tools = ttk.Frame(box)
        tools.pack(fill='x',pady=6)
        self.photos_button = ttk.Button(tools,text='选择新照片（复制到本机）',command=self.select_photos)
        self.photos_button.pack(side='left',padx=3)
        self.open_button = ttk.Button(tools,text='选择电脑文件夹',command=self.open_labelme)
        self.open_button.pack(side='left',padx=3)
        self.retry_button = ttk.Button(tools,text='已有标注 / 重试更新',command=self.retry)
        self.retry_button.pack(side='left',padx=3)
        self.stop_button = ttk.Button(tools,text='停止更新',command=self.stop,state='disabled')
        self.stop_button.pack(side='left',padx=3)
        options = ttk.Frame(box)
        options.pack(fill='x',pady=6)
        self.auto = tk.BooleanVar(value=True)
        ttk.Checkbutton(options,text='关闭 Labelme 后自动更新',variable=self.auto).pack(side='left')
        ttk.Label(options,text='  每个模型训练轮数：').pack(side='left')
        self.epochs = tk.StringVar(value='100')
        ttk.Spinbox(options,from_=1,to=300,textvariable=self.epochs,width=5).pack(side='left')
        ttk.Label(box,text='更新需要训练两个模型，耗时明显长于测试照片。训练时暂停检测；旧模型和实验记录保留。\n验证通过后才启用新模型；验证下降时保留旧模型。请保持检测软件打开；关闭此小窗口仍可继续训练。',
                  wraplength=740).pack(anchor='w',pady=8)
        self.status = tk.StringVar(value=self.last_status or '准备就绪。照片只在本机保存和处理。')
        ttk.Label(box,textvariable=self.status,wraplength=740).pack(anchor='w',pady=8)
        self.details = tk.Text(box,height=8,wrap='word')
        self.details.pack(fill='both',expand=True)
        ttk.Button(box,text='打开本机照片文件夹',command=self.open_photos_folder).pack(anchor='e',pady=3)
        ttk.Button(box,text='查看训练前后验证结果',command=self.show_validation).pack(anchor='e',pady=3)
        ttk.Button(box,text='打开本次更新文件夹',command=self.open_job).pack(anchor='e',pady=5)
        self.set_controls()

    def message(self, text):
        self.last_status = text
        if self.window and self.window.winfo_exists():
            self.status.set(text)
            self.details.insert('end',datetime.now().strftime('%H:%M:%S')+' '+text+'\n')
            self.details.see('end')

    def set_controls(self):
        if self.window and self.window.winfo_exists():
            disabled = self.active or self.label_process or self.copying
            self.photos_button.config(state='disabled' if disabled else 'normal')
            self.open_button.config(state='disabled' if disabled else 'normal')
            self.retry_button.config(state='disabled' if disabled else 'normal')
            self.stop_button.config(state='normal' if self.active else 'disabled')

    def pick_folder(self):
        IMPORTS.mkdir(parents=True,exist_ok=True)
        folder = filedialog.askdirectory(parent=self.window,title='选择电脑中的实际照片文件夹（手机照片请用“选择新照片”）',initialdir=str(IMPORTS))
        if folder:
            self.folder = Path(folder)
            self.folder_text.set(folder)
        return bool(folder)

    def open_labelme(self):
        if self.busy():
            messagebox.showinfo('请稍候','请等当前照片检测完成后再添加训练数据。',parent=self.window)
            return
        if not self.pick_folder():
            return
        self.launch_labelme()

    def select_photos(self):
        if self.busy():
            self.message('请等当前检测完成后再添加照片。')
            return
        paths = filedialog.askopenfilenames(parent=self.window,title='选择新增训练照片（可以多选）',
            filetypes=[('图片','*.jpg *.jpeg *.png *.bmp')])
        if not paths:
            return
        folder = IMPORTS/datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        self.copying = True
        self.set_controls()
        self.message(f'正在将 {len(paths)} 张照片复制到本机…')
        def worker():
            try:
                self.copy_messages.put(('ready',copy_photos(paths,folder)))
            except Exception as error:
                self.copy_messages.put(('error',f'照片复制未完成：{error}\n已复制文件保留在 {folder}'))
        threading.Thread(target=worker,daemon=True).start()

    def launch_labelme(self):
        from runtime_paths import python_executable
        executable = python_executable(labelme=True, windowless=True)
        if not executable.exists():
            self.message('Labelme 未安装完成，请联系修复安装环境。')
            return
        try:
            self.label_process = subprocess.Popen([str(executable),'-m','labelme',str(self.folder),
                '--output',str(self.folder),'--labels','part,bore','--validate-label','exact','--config',str(BASE/'labelme_training.yaml')],cwd=BASE)
            self.auto_session = self.auto.get()
            self.message('Labelme 已打开。请保存每张图的标注，全部完成后关闭 Labelme 窗口。')
            self.set_controls()
        except OSError as error:
            self.message('Labelme 打开失败：'+str(error))

    def retry(self):
        if not self.folder and not self.pick_folder():
            return
        self.start_training()

    def start_training(self, profile=None):
        if self.active or self.busy():
            self.message('检测或更新仍在进行，请完成后重试。')
            return
        try:
            epochs = int(self.epochs.get())
            if not 1 <= epochs <= 300:
                raise ValueError()
        except ValueError:
            self.message('训练轮数请填写 1～300 的整数。')
            return
        self.job = BASE/'updates'/datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        self.job.mkdir(parents=True)
        self.lock()
        self.active = True
        try:
            self.log_file = (self.job/'training.log').open('w',encoding='utf-8')
            env = dict(os.environ,PYTHONIOENCODING='utf-8',PYTHONUNBUFFERED='1')
            source_args=['--profile',str(profile)] if profile else ['--folder',str(self.folder)]
            from runtime_paths import python_executable
            self.train_process = subprocess.Popen([str(python_executable()),'-u',
                str(BASE/'dataset_update.py'),*source_args,'--job',str(self.job),'--epochs',str(epochs)],
                cwd=BASE,env=env,stdout=self.log_file,stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW)
            self.message('开始合并标注实验：仅训练孔模型，沿用原 part 模型，保持23张训练/5张验证。' if profile else '开始自动更新：先检查全部标注，检查通过后才进行训练…')
        except OSError as error:
            self.finish('更新启动失败：'+str(error))
        self.set_controls()

    def finish(self, message):
        self.train_process = None
        if self.log_file:
            self.log_file.close()
            self.log_file = None
        self.active = False
        self.unlock()
        self.message(message)
        self.set_controls()
        if self.job and (self.job/'validation.json').exists():
            self.show_validation()

    def show_validation(self):
        job = self.job
        if not job or not (job/'validation.json').exists():
            jobs = sorted((BASE/'updates').glob('*/validation.json'),reverse=True)
            job = jobs[0].parent if jobs else None
        if job is None:
            self.message('尚无验证结果，请等本次训练和验证完成。')
            return
        from validation_view import show_validation
        show_validation(self.root,job)

    def stop(self):
        if self.train_process and self.train_process.poll() is None:
            self.train_process.terminate()
            self.train_process.wait(timeout=10)
        if self.active:
            self.finish('更新已停止。已启用模型保持可用；本次照片、标注和训练文件保留。')

    def poll(self):
        while not self.copy_messages.empty():
            kind,payload = self.copy_messages.get()
            self.copying = False
            self.set_controls()
            if kind=='ready':
                self.folder = payload
                self.folder_text.set(str(payload))
                self.launch_labelme()
            else:
                self.message(payload)
        if self.label_process and self.label_process.poll() is not None:
            code = self.label_process.returncode
            self.label_process = None
            self.set_controls()
            if code == 0 and self.auto.get():
                self.start_training()
            else:
                self.message('Labelme 已关闭。需要更新时点击“已有标注 / 重试更新”。')
        if self.train_process:
            status = {}
            path = self.job/'status.json'
            if path.exists():
                try:
                    status = json.loads(path.read_text(encoding='utf-8'))
                    if status['message'] != self.last_status:
                        self.message(status['message'])
                except (OSError,ValueError,KeyError):
                    pass
            if self.train_process.poll() is not None:
                self.finish(status.get('message','更新进程已退出，请查看本次更新文件夹中的 training.log。'))
        self.root.after(700,self.poll)

    def open_job(self):
        folder = self.job or BASE/'updates'
        folder.mkdir(exist_ok=True)
        os.startfile(str(folder))

    def open_photos_folder(self):
        folder = self.folder or IMPORTS
        folder.mkdir(parents=True,exist_ok=True)
        os.startfile(str(folder))
