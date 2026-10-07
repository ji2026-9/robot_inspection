# -*- coding: utf-8 -*-
"""
Apply our two local improvements to the friend's engine_bore_local install.

Measured on the project's 4 held-out test images:

1) FITTING (applied by default): his policy only runs the aperture-edge refinement
   when the mask support < 0.85, which happened on 1 of 16 holes -> the other 15
   stayed on the YOLO mask boundary. Always trying the refinement lifts the
   edge-alignment p25 from 2.03 to 13.32 (6.6x).

2) MODEL (NOT swapped by default - opt in with --swap-model):
   his bore model and our fusion_v1 are trained on the same 28 photos, and in OUR
   pipeline (imgsz 640, retina_masks=True) ours has the better margin
   (worst hole 0.775 vs 0.676). BUT inside HIS pipeline (imgsz 960,
   retina_masks=False) the swap REGRESSED 测试3 from 4/4 to 2/4, because his
   model's masks are cleaner under his own settings. Each software therefore keeps
   its own bore model. His part model is never touched - we do not have one.

The script is IDEMPOTENT and always backs up before editing. Re-run it after any
`git archive` refresh of his code.

Usage:
    E:\\robot_project\\robot_inspection\\.venv\\Scripts\\python.exe scripts\\patch_friend_engine.py
    ... --engine "E:\\robot_project\\inspection_app"
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

PROJ = Path(__file__).resolve().parents[1]
DEFAULT_ENGINE = Path("E:/robot_project/inspection_app")
OUR_MODEL = PROJ / "weights" / "best.pt"
DEPLOYED_NAME = "fusion_v1_best.pt"

MARK = "# [local patch] always try the aperture-edge refinement"
ICON_MARK = "# [local patch] application icon"
ICON_NAME = "app_icon.ico"


def patch_detect_core(engine: Path) -> str:
    f = engine / "detect_core.py"
    if not f.is_file():
        return "detect_core.py 不存在"
    text = f.read_text(encoding="utf-8")
    old = ("                if fit_source == 'segmentation_contour' and support < .85:\n"
           "                    refined,verification = refine_multi_edge(result.orig_img,ellipse)\n"
           "                    if verification['used']:\n"
           "                        ellipse = refined\n"
           "                        edge_info = verification\n"
           "                        residual = verification['median_residual_px']\n"
           "                        fit_source = 'image_edge_verified'\n"
           "                    else:")
    new = ("                # [local patch] always try the aperture-edge refinement\n"
           "                # (was: and support < .85 - that skipped 15 of 16 holes)\n"
           "                if fit_source == 'segmentation_contour':\n"
           "                    refined,verification = refine_multi_edge(result.orig_img,ellipse)\n"
           "                    if verification['used']:\n"
           "                        ellipse = refined\n"
           "                        edge_info = verification\n"
           "                        residual = verification['median_residual_px']\n"
           "                        fit_source = 'image_edge_verified'\n"
           "                    elif support < .85:")
    if MARK in text:
        return "已打过补丁（跳过）"
    if old not in text:
        return "没找到目标代码行（他的代码可能改过），请人工检查"
    shutil.copy2(f, f.with_suffix(".py.bak"))
    f.write_text(text.replace(old, new, 1), encoding="utf-8")
    return "已修改（原文件备份为 detect_core.py.bak）"


def deploy_model(engine: Path) -> str:
    if not OUR_MODEL.is_file():
        return "找不到 {} ".format(OUR_MODEL)
    dst = engine / "models" / DEPLOYED_NAME
    if dst.is_file() and dst.stat().st_size == OUR_MODEL.stat().st_size:
        return "模型已是最新（{}）".format(DEPLOYED_NAME)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(OUR_MODEL, dst)
    return "已复制 {} -> models/{}".format(OUR_MODEL.name, DEPLOYED_NAME)


def patch_app_icon(engine: Path) -> str:
    """Give the window/taskbar a real application icon (python.exe's icon is ugly)."""
    src = PROJ.parent / ICON_NAME
    if not src.is_file():
        src = PROJ / ICON_NAME
    dst = engine / ICON_NAME
    if src.is_file() and (not dst.is_file() or dst.stat().st_size != src.stat().st_size):
        shutil.copy2(src, dst)

    f = engine / "inspection_gui" / "main.py"
    if not f.is_file():
        return "找不到 inspection_gui/main.py"
    text = f.read_text(encoding="utf-8")
    if ICON_MARK in text:
        return "已打过补丁（跳过）"
    anchor = "    application.setApplicationName('Engine Bore Inspection')\n"
    if anchor not in text:
        return "找不到 setApplicationName 那一行，请人工检查"
    block = anchor + (
        "    # [local patch] application icon\n"
        "    _icon_file = Path(__file__).resolve().parents[1] / '{}'\n"
        "    if _icon_file.is_file():\n"
        "        from PySide6.QtGui import QIcon\n"
        "        application.setWindowIcon(QIcon(str(_icon_file)))\n").format(ICON_NAME)
    shutil.copy2(f, f.with_suffix(".py.bak"))
    f.write_text(text.replace(anchor, block, 1), encoding="utf-8")
    return "已加入应用图标（原文件备份为 main.py.bak）"


def patch_dark_mode(engine: Path) -> str:
    """Fix white-on-white text.

    Windows is in DARK mode here, so the system text colour is white. The app sets
    white table backgrounds but never sets the text colour, so every data row renders
    white-on-white (table headers have their own colour, which is why only the data
    looked "empty"). Same for the combo box popup and the progress bar text.
    """
    edits = [
        (engine / "inspection_gui" / "gui.py", [
            ("QMainWindow, QDialog { background: #f1f5f9; color: #172b4d; }",
             "QMainWindow, QDialog { background: #f1f5f9; color: #172b4d; }\n"
             "QLabel { color: #172b4d; }"),
            ("QTableWidget { background: white; alternate-background-color: #f1f6fc; gridline-color: #b7c7d9; }",
             "QTableWidget { background: white; color: #172b4d; alternate-background-color: #f1f6fc; "
             "gridline-color: #b7c7d9; }\n"
             "QTableWidget::item { color: #172b4d; }"),
            ("QHeaderView::section { background: #e8eff8; padding: 6px; border: 1px solid #b7c7d9; font-weight: 600; }",
             "QHeaderView::section { background: #e8eff8; color: #24466e; padding: 6px; "
             "border: 1px solid #b7c7d9; font-weight: 600; }"),
            ("QComboBox { padding: 5px; background: white; border: 1px solid #bdccde; border-radius: 4px; }",
             "QComboBox { padding: 5px; background: white; color: #17365c; "
             "border: 1px solid #bdccde; border-radius: 4px; }\n"
             "QComboBox QAbstractItemView { background: white; color: #17365c; "
             "selection-background-color: #dbeafe; }"),
            ("QProgressBar { border: 1px solid #cbd5e1; border-radius: 5px; text-align: center; min-height: 17px; }",
             "QProgressBar { border: 1px solid #cbd5e1; border-radius: 5px; text-align: center; "
             "min-height: 17px; color: #172b4d; }"),
        ]),
        (engine / "inspection_gui" / "records_view.py", [
            ("QTableWidget { gridline-color: #b8c2cf; alternate-background-color: #f3f6fa; }",
             "QTableWidget { background: white; color: #172b4d; gridline-color: #b8c2cf; "
             "alternate-background-color: #f3f6fa; }"),
        ]),
        (engine / "inspection_gui" / "devices_view.py", [
            ("background: white; gridline-color: #d5deea; border: 1px solid #d5deea;",
             "background: white; color: #234369; gridline-color: #d5deea; border: 1px solid #d5deea;"),
        ]),
    ]
    applied, skipped, missing = [], [], []
    for path, pairs in edits:
        if not path.is_file():
            missing.append(path.name)
            continue
        text = path.read_text(encoding="utf-8")
        original = text
        for old, new in pairs:
            if new in text:
                skipped.append(path.name)
                continue
            if old in text:
                text = text.replace(old, new, 1)
            else:
                missing.append("{}:{}".format(path.name, old[:28]))
        if text != original:
            shutil.copy2(path, path.with_suffix(".py.bak"))
            path.write_text(text, encoding="utf-8")
            applied.append(path.name)
    out = []
    if applied:
        out.append("已修复: " + ", ".join(sorted(set(applied))))
    if skipped:
        out.append("已是最新: " + ", ".join(sorted(set(skipped))))
    if missing:
        out.append("未匹配: " + "; ".join(missing[:4]))
    return "；".join(out) or "无需修改"


def patch_photo_dir(engine: Path) -> str:
    """The photo picker opened the PROGRAM folder because a hard-coded path from the
    author's machine does not exist. Remember the last used folder instead."""
    f = engine / "app.py"
    if not f.is_file():
        return "找不到 app.py"
    text = f.read_text(encoding="utf-8")
    if "last_photo_dir.txt" in text:
        return "已打过补丁（跳过）"
    old_dir = "initialdir=r'C:\\训练照片（箱体）'"
    new_dir = "initialdir=str(_default_photo_dir())"
    if old_dir not in text:
        return "没找到写死的 initialdir"

    helper = (
        "def _default_photo_dir():\n"
        "    # [local patch] remember the last folder instead of a path from another PC\n"
        "    marker = BASE / 'last_photo_dir.txt'\n"
        "    try:\n"
        "        if marker.is_file():\n"
        "            chosen = Path(marker.read_text(encoding='utf-8').strip())\n"
        "            if chosen.is_dir():\n"
        "                return chosen\n"
        "    except Exception:\n"
        "        pass\n"
        "    pictures = Path.home() / 'Pictures'\n"
        "    return pictures if pictures.is_dir() else BASE\n"
        "\n"
        "\n"
    )
    if "def _default_photo_dir()" not in text:
        if "def choose():" not in text:
            return "没找到 choose() 函数"
        text = text.replace("    def choose():", helper + "    def choose():", 1)
    text = text.replace(old_dir, new_dir, 1)
    remember = (
        "        if not paths: return\n"
        "        try:  # [local patch] remember this folder for next time\n"
        "            (BASE / 'last_photo_dir.txt').write_text(str(Path(paths[0]).parent), encoding='utf-8')\n"
        "        except Exception:\n"
        "            pass\n"
    )
    if "remember this folder for next time" not in text:
        text = text.replace("        if not paths: return\n", remember, 1)
    shutil.copy2(f, f.with_suffix(".py.bak"))
    f.write_text(text, encoding="utf-8")
    return "已改为记住上次文件夹（原文件备份为 app.py.bak）"


def patch_tk_dark_mode(engine: Path) -> str:
    """The management windows are Tkinter and use ttk defaults, so in Windows dark
    mode their labels draw white text on the app's light background (invisible).
    Set explicit ttk colours once, right after each Tk root is created."""
    f = engine / "app.py"
    if not f.is_file():
        return "找不到 app.py"
    text = f.read_text(encoding="utf-8")
    if "dark-mode fix" in text:
        return "已打过补丁（跳过）"
    anchor = "    root = tk.Tk()\n"
    if anchor not in text:
        return "找不到 root = tk.Tk()"
    block = anchor + (
        "    # [local patch] dark-mode fix: ttk defaults to the system text colour\n"
        "    # (white in Windows dark mode) on our light background -> invisible labels\n"
        "    try:\n"
        "        _style = ttk.Style(root)\n"
        "        for _name, _opts in (\n"
        "            ('TLabel', {'foreground': '#172b4d', 'background': '#f1f5f9'}),\n"
        "            ('TButton', {'foreground': '#17365c'}),\n"
        "            ('TCheckbutton', {'foreground': '#172b4d', 'background': '#f1f5f9'}),\n"
        "            ('TRadiobutton', {'foreground': '#172b4d', 'background': '#f1f5f9'}),\n"
        "            ('TCombobox', {'foreground': '#17365c'}),\n"
        "            ('TLabelframe', {'background': '#f1f5f9'}),\n"
        "            ('TLabelframe.Label', {'foreground': '#24466e', 'background': '#f1f5f9'}),\n"
        "            ('TNotebook.Tab', {'foreground': '#17365c'}),\n"
        "            ('Treeview', {'background': 'white', 'fieldbackground': 'white', 'foreground': '#172b4d'}),\n"
        "            ('Treeview.Heading', {'foreground': '#24466e'}),\n"
        "        ):\n"
        "            _style.configure(_name, **_opts)\n"
        "        root.configure(bg='#f1f5f9')\n"
        "    except Exception:\n"
        "        pass\n")
    text = text.replace(anchor, block)
    shutil.copy2(f, f.with_suffix(".py.bak"))
    f.write_text(text, encoding="utf-8")
    return "已加入 ttk 深色模式配色（原文件备份为 app.py.bak）"


def patch_ui_layout(engine: Path) -> str:
    """Three layout problems found while running the app:

    1. the hole table used five FIXED column widths (~510 px) inside a panel that is
       often narrower -> the last column was clipped and a horizontal scrollbar
       appeared. Let the small columns fit their content and give the coordinate
       column the remaining space.
    2. the 3D scene drew its labels at projected positions that can fall outside the
       viewport -> labels were cut at the edges. Clamp them inside.
    3. the device dialog asked for a 760 px height with a fixed-height table, so on a
       864 px screen the bottom row was clipped. Make it screen-aware and let the
       table be a bit shorter.
    """
    edits = [
        (engine / "inspection_gui" / "gui.py", [
            ("        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)\n"
             "        self.table.horizontalHeader().setStretchLastSection(True)\n"
             "        for column, width in enumerate((60, 80, 160, 110, 100)):\n"
             "            self.table.setColumnWidth(column, width)\n",
             "        # [local patch] fit the panel instead of five fixed widths (was clipped)\n"
             "        _header = self.table.horizontalHeader()\n"
             "        _header.setStretchLastSection(False)\n"
             "        for _column in (0, 1, 3, 4):\n"
             "            _header.setSectionResizeMode(_column, QHeaderView.ResizeMode.ResizeToContents)\n"
             "        _header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)\n"),
            ("        scroll.setMinimumWidth(420)",
             "        scroll.setMinimumWidth(360)   # [local patch] allow a narrower panel"),
            ("        split.setSizes([900, 580])",
             "        split.setSizes([880, 560])      # [local patch]\n"
             "        split.setStretchFactor(0, 3)\n"
             "        split.setStretchFactor(1, 2)"),
        ]),
        (engine / "inspection_gui" / "simulation_scene3d.py", [
            ("        for label,point in [('A · 工业相机',(-355,-100,15)),('B · 测针',(355,-100,15))]:\n"
             "            q = project(point)\n"
             "            p.setPen(QColor('#8ad8ff'))\n"
             "            p.drawText(q,label)\n"
             "        for i,x in enumerate((-150,-50,50,150)):\n"
             "            p.setPen(QColor('#f3ddad'))\n"
             "            p.drawText(project((x,-43,105)),f'H{i+1:02}')\n",
             "        def _inside(q, right=104, bottom=18):\n"
             "            # [local patch] keep scene labels inside the viewport\n"
             "            x = min(max(q.x(), 16.0), max(16.0, self.width() - right))\n"
             "            y = min(max(q.y(), 30.0), max(30.0, self.height() - bottom))\n"
             "            return QPointF(x, y)\n"
             "        for label,point in [('A · 工业相机',(-355,-100,15)),('B · 测针',(355,-100,15))]:\n"
             "            p.setPen(QColor('#8ad8ff'))\n"
             "            p.drawText(_inside(project(point), 104), label)\n"
             "        for i,x in enumerate((-150,-50,50,150)):\n"
             "            p.setPen(QColor('#f3ddad'))\n"
             "            p.drawText(_inside(project((x,-43,105)), 46), f'H{i+1:02}')\n"),
        ]),
        (engine / "inspection_gui" / "devices_view.py", [
            ("        self.fields.setFixedHeight(273)",
             "        self.fields.setFixedHeight(214)   # [local patch] was 273 -> bottom row got clipped"),
            ("        self.resize(720, 760)\n        self.setMinimumSize(600, 700)",
             "        # [local patch] screen-aware size so the bottom buttons are never cut off\n"
             "        _screen = self.screen()\n"
             "        _height = min(820, _screen.availableGeometry().height() - 70) if _screen else 780\n"
             "        self.resize(720, _height)\n"
             "        self.setMinimumSize(560, 620)"),
        ]),
    ]
    applied, skipped, missing = [], [], []
    for path, pairs in edits:
        if not path.is_file():
            missing.append(path.name)
            continue
        text = path.read_text(encoding="utf-8")
        original = text
        for old, new in pairs:
            if new in text:
                skipped.append(path.name)
                continue
            if old in text:
                text = text.replace(old, new, 1)
            else:
                missing.append("{}:{}".format(path.name, old.strip()[:26]))
        if text != original:
            shutil.copy2(path, path.with_suffix(".py.bak"))
            path.write_text(text, encoding="utf-8")
            applied.append(path.name)
    out = []
    if applied:
        out.append("已优化: " + ", ".join(sorted(set(applied))))
    if skipped:
        out.append("已是最新: " + ", ".join(sorted(set(skipped))))
    if missing:
        out.append("未匹配: " + "; ".join(missing[:4]))
    return "；".join(out) or "无需修改"


def patch_3d_scene(engine: Path) -> str:
    """Redraw the simulated arm as a CR5A-style collaborative robot (reference:
    DobotStudio Pro) and lighten the scene to match that look.

    The old arm was straight cylinders with flat bands; a CR5A has a pedestal base,
    tapered links, rounded joint hubs with blue rings and a dark tool flange.
    """
    f = engine / "inspection_gui" / "simulation_scene3d.py"
    if not f.is_file():
        return "找不到 simulation_scene3d.py"
    text = f.read_text(encoding="utf-8")
    if "CR5A-style" in text:
        return "已打过补丁（跳过）"

    old_arm = (
        "    def arm(self,base,target,color):\n"
        "        side=1 if base<0 else -1\n"
        "        points=[np.array([base,0.,20.]),np.array([base,0.,130.]),\n"
        "                np.array([base+side*75,65.,350.]),target+np.array([-side*80,35,60]),target]\n"
        "        self.cylinder((base,0,0),(base,0,75),48,'#e4eaf2')\n"
        "        for i,(a,b) in enumerate(zip(points,points[1:])):\n"
        "            self.cylinder(a,b,29 if i<2 else 22,'#e3e9ef')\n"
        "        for point in points[1:]:\n"
        "            self.cylinder(point+[0,-30,0],point+[0,30,0],34,'#edf2f6')\n"
        "            self.cylinder(point+[0,-32,0],point+[0,-28,0],35,color)\n"
        "            self.cylinder(point+[0,28,0],point+[0,32,0],35,color)\n"
        "            self.cylinder(point+[0,-34,0],point+[0,-32,0],19,'#657788')\n")
    new_arm = (
        "    def joint(self,center,radius,ring_color,half=30,bulge=5):\n"
        "        # [local patch] CR5A-style joint hub with two blue rings\n"
        "        c=np.asarray(center,dtype=float)\n"
        "        self.cylinder(c+[0,-half,0],c+[0,half,0],radius,'#e6eaee',24)\n"
        "        self.cylinder(c+[0,-half,0],c+[0,-half+5,0],radius+bulge,ring_color,24)\n"
        "        self.cylinder(c+[0,half-5,0],c+[0,half,0],radius+bulge,ring_color,24)\n"
        "        self.cylinder(c+[0,-half-3,0],c+[0,-half,0],radius*0.55,'#93a0ae',20)\n"
        "        self.cylinder(c+[0,half,0],c+[0,half+3,0],radius*0.55,'#93a0ae',20)\n"
        "\n"
        "    def taper(self,a,b,r1,r2,color,n=24,caps=True):\n"
        "        # [local patch] cone-shaped link (the old arm used straight tubes)\n"
        "        a,b=np.asarray(a,dtype=float),np.asarray(b,dtype=float)\n"
        "        axis=b-a; axis/=max(float(np.linalg.norm(axis)),1e-9)\n"
        "        u=np.cross(axis,[0,0,1] if abs(axis[2])<.9 else [0,1,0]); u/=np.linalg.norm(u)\n"
        "        v=np.cross(axis,u)\n"
        "        o1=[r1*(math.cos(i*2*math.pi/n)*u+math.sin(i*2*math.pi/n)*v) for i in range(n)]\n"
        "        o2=[r2*(math.cos(i*2*math.pi/n)*u+math.sin(i*2*math.pi/n)*v) for i in range(n)]\n"
        "        for i in range(n):\n"
        "            j=(i+1)%n\n"
        "            self.face([a+o1[i],a+o1[j],b+o2[j],b+o2[i]],color)\n"
        "        if caps:\n"
        "            self.face([a+o for o in o1],color)\n"
        "            self.face([b+o for o in o2],color)\n"
        "\n"
        "    def arm(self,base,target,color):\n"
        "        # [local patch] CR5A-style arm: pedestal, tapered links, blue joint rings,\n"
        "        # dark tool flange (geometry is still illustrative, not real kinematics)\n"
        "        side=1 if base<0 else -1\n"
        "        p1=np.array([base,0.,132.])\n"
        "        p2=np.array([base+side*78,66.,352.])\n"
        "        p3=target+np.array([-side*82,36,64])\n"
        "        self.cylinder((base,0,0),(base,0,12),58,'#c5cbd3',32)\n"
        "        self.cylinder((base,0,12),(base,0,58),46,'#eef1f4',32)\n"
        "        self.cylinder((base,0,58),(base,0,70),51,color,32)\n"
        "        self.joint(p1,40,color,30)\n"
        "        self.taper(p1,p2,37,27,'#eef2f5',26)\n"
        "        self.joint(p2,33,color,26)\n"
        "        self.taper(p2,p3,28,21,'#e7ebef',26)\n"
        "        d=(target-p3); L=max(float(np.linalg.norm(d)),1e-6); d=d/L\n"
        "        for k,off in enumerate((0.0,26.0,50.0)):\n"
        "            self.joint(p3+d*off,20-k*2,color,15,3)\n"
        "        self.cylinder(target-d*14,target-d*4,17,'#d3d9df',20)\n"
        "        self.cylinder(target-d*4,target+d*3,11,'#31363d',20)\n")
    if old_arm not in text:
        return "没找到原来的 arm() 代码，请人工检查"
    text = text.replace(old_arm, new_arm, 1)

    # lighten the scene to the DobotStudio look (white grid floor, light table)
    theme = [
        ("QColor('#101c30')", "QColor('#f4f6f9')"),
        ("(470,285,-15), '#52647b'", "(470,285,-15), '#e2e7ee'"),
        ("3, '#26364d', 6", "3, '#ccd4dd', 6"),
        ("(x+75,75,0), '#344862'", "(x+75,75,0), '#c3ccd7'"),
        ("(205,70,90), '#87796a', top=False", "(205,70,90), '#a99a87', top=False"),
        ("(x,0,89),35,'#273448',24, caps=False", "(x,0,89),35,'#8d98a7',24, caps=False"),
        ("self.disk(x,0,34,35,'#101827')", "self.disk(x,0,34,35,'#6f7a89')"),
        ("'#b4a28b'", "'#c6b49b'"),
        ("QColor('#c8dcf7')", "QColor('#33415a')"),
        ("QColor('#8399b7')", "QColor('#6b7a90')"),
        ("QColor('#8ad8ff')", "QColor('#2563eb')"),
        ("QColor('#f3ddad')", "QColor('#b45309')"),
        ("            p.setPen(Qt.PenStyle.NoPen)\n            p.setBrush(color)",
         "            # [local patch] thin edge so light parts stay readable\n"
         "            p.setPen(QPen(QColor(120,132,150,80),0.6))\n"
         "            p.setBrush(color)"),
    ]
    for old, new in theme:
        text = text.replace(old, new)
    shutil.copy2(f, f.with_suffix(".py.bak"))
    f.write_text(text, encoding="utf-8")
    return "机械臂已改为 CR5A 样式，场景改为浅色（原文件备份为 simulation_scene3d.py.bak）"


NEW_STYLE = '''
QMainWindow, QDialog { background: #eef2f7; color: #22324a; }
QLabel { color: #22324a; }
#topBar { background: #0f3d78; }
#appTitle { color: #ffffff; font-size: 21px; font-weight: 700; }
#appSub { color: #aecbf0; font-size: 12px; }
#modelChip { color: #d9e8ff; font-size: 12px; }
QGroupBox { background: #ffffff; border: 1px solid #dde5ee; border-radius: 10px;
            margin-top: 14px; padding: 12px 12px 10px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; color: #17457f; }
QPushButton { background: #ffffff; border: 1px solid #c7d5e5; border-radius: 8px;
              padding: 8px 12px; color: #16324f; font-weight: 600; }
QPushButton:hover { background: #eef5ff; border-color: #7ba7dd; }
QPushButton:pressed { background: #deeafa; }
QPushButton:disabled { background: #f3f6fa; color: #9aa8ba; border-color: #e3e9f1; }
QPushButton#primary { background: #1256a8; border-color: #1256a8; color: #ffffff;
                      padding: 11px 12px; font-size: 14px; }
QPushButton#primary:hover { background: #0e4a93; }
QPushButton#primary:disabled { background: #b9cbe4; border-color: #b9cbe4; }
QPushButton#flat { background: transparent; border: none; color: #35618f; padding: 4px 8px; }
QPushButton#flat:hover { color: #1256a8; }
QComboBox { background: #ffffff; color: #16324f; border: 1px solid #c7d5e5;
            border-radius: 7px; padding: 5px 8px; }
QComboBox QAbstractItemView { background: #ffffff; color: #16324f; selection-background-color: #dbeafe; }
QCheckBox, QRadioButton { color: #22324a; }
QLabel#bigCount { font-size: 15px; font-weight: 700; color: #17457f; }
QLabel#systemState { font-size: 15px; font-weight: 700; color: #12805a; }
QLabel#warnNote { color: #9a6212; font-size: 11px; }
QLabel#hintNote, QLabel#legend { color: #6d7f96; font-size: 11px; }
QLabel#canvas { background: #f7f9fc; border: 1px solid #dde5ee; border-radius: 8px; color: #8a97a8; }
QTableWidget { background: #ffffff; color: #22324a; alternate-background-color: #f5f8fc;
               border: none; gridline-color: #e6ecf3; }
QTableWidget::item { color: #22324a; padding: 4px; }
QHeaderView::section { background: #eef3fa; color: #17457f; padding: 7px;
                       border: none; border-bottom: 1px solid #d8e2ee; font-weight: 600; }
QProgressBar { border: 1px solid #d8e2ee; border-radius: 7px; background: #f4f7fb;
               text-align: center; color: #17457f; min-height: 18px; }
QProgressBar::chunk { background: #2f7fd6; border-radius: 6px; }
QScrollArea { border: none; background: transparent; }
QPlainTextEdit#log { background: #0f2438; color: #d7e6f7; border-radius: 8px;
                     padding: 5px; font-size: 11px; }
QFrame#statusBar { background: #f3f6fa; border-top: 1px solid #dde5ee; }
QLabel#deviceLine { color: #8b4b30; font-weight: 600; }
'''

NEW_BUILD_UI = '''    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- 顶部标题栏 ----
        top = QFrame()
        top.setObjectName('topBar')
        top.setFixedHeight(62)
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(20, 8, 20, 8)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        app_title = QLabel('双机械臂孔检测系统')
        app_title.setObjectName('appTitle')
        app_sub = QLabel('工业箱体孔位识别 · 椭圆拟合 · 孔心定位')
        app_sub.setObjectName('appSub')
        titles.addWidget(app_title)
        titles.addWidget(app_sub)
        top_layout.addLayout(titles)
        top_layout.addStretch(1)
        self.model_label = QLabel()
        self.model_label.setObjectName('modelChip')
        self.model_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        top_layout.addWidget(self.model_label)
        root.addWidget(top)

        # ---- 主体：左操作 / 中图像 / 右结果 ----
        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(14, 12, 14, 10)
        body_layout.setSpacing(12)
        root.addWidget(body, 1)

        left = QWidget()
        left.setFixedWidth(238)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)

        actions = QGroupBox('操作')
        actions_layout = QVBoxLayout(actions)
        actions_layout.setSpacing(8)
        self.btn_select = QPushButton('① 选择照片')
        self.btn_select.setObjectName('primary')
        self.btn_detect = QPushButton('② 开始检测')
        self.btn_detect.setObjectName('primary')
        self.btn_send = QPushButton('③ 发送测量任务')
        self.btn_send.setEnabled(False)
        self.btn_send.setToolTip('设备连接、三维坐标、孔轴方向和标定验证完成后才能下发测量任务。')
        for _button in (self.btn_select, self.btn_detect, self.btn_send):
            actions_layout.addWidget(_button)
        left_layout.addWidget(actions)

        photos = QGroupBox('本组照片')
        photos_layout = QVBoxLayout(photos)
        photos_layout.setSpacing(6)
        self.page_label = QLabel('未选择照片')
        self.page_label.setObjectName('bigCount')
        self.selector = QComboBox()
        navigation = QHBoxLayout()
        self.previous_button = QPushButton('上一张')
        self.next_button = QPushButton('下一张')
        navigation.addWidget(self.previous_button)
        navigation.addWidget(self.next_button)
        self.batch_progress = QProgressBar()
        self.batch_progress.setRange(0, 1)
        self.batch_progress.setValue(0)
        self.batch_progress.setFormat('本组进度 %v/%m')
        photos_layout.addWidget(self.page_label)
        photos_layout.addWidget(self.selector)
        photos_layout.addLayout(navigation)
        photos_layout.addWidget(self.batch_progress)
        left_layout.addWidget(photos)

        others = QGroupBox('其他功能')
        others_layout = QVBoxLayout(others)
        others_layout.setSpacing(6)
        self.btn_devices = QPushButton('设备连接')
        self.btn_records = QPushButton('实验记录')
        self.btn_models = QPushButton('模型与数据管理')
        self.btn_simulation = QPushButton('模拟测量动画')
        self.btn_results = QPushButton('打开结果文件夹')
        for _button in (self.btn_devices, self.btn_records, self.btn_models,
                        self.btn_simulation, self.btn_results):
            others_layout.addWidget(_button)
        left_layout.addWidget(others)
        left_layout.addStretch(1)
        body_layout.addWidget(left)

        visual = QGroupBox('视觉检测区')
        visual_layout = QVBoxLayout(visual)
        visual_layout.setSpacing(8)
        self.image_label = QLabel('请选择一组测试照片')
        self.image_label.setObjectName('canvas')
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumSize(420, 260)
        self.image_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        visual_layout.addWidget(self.image_label, 1)
        image_tools = QHBoxLayout()
        self.image_info = QLabel('尚未选择照片')
        self.chk_fit = QCheckBox('适应孔区域')
        self.chk_fit.setChecked(True)
        self.sld_zoom = QSlider(Qt.Orientation.Horizontal)
        self.sld_zoom.setRange(100, 300)
        self.sld_zoom.setValue(100)
        self.sld_zoom.setMaximumWidth(150)
        self.lbl_zoom = QLabel('100%')
        image_tools.addWidget(self.image_info, 1)
        image_tools.addWidget(self.chk_fit)
        image_tools.addWidget(QLabel('缩放'))
        image_tools.addWidget(self.sld_zoom)
        image_tools.addWidget(self.lbl_zoom)
        visual_layout.addLayout(image_tools)
        legend = QLabel('青色：孔轮廓　黄色：拟合椭圆　红色十字：图像圆心')
        legend.setObjectName('legend')
        visual_layout.addWidget(legend)
        body_layout.addWidget(visual, 1)

        right = QWidget()
        right.setFixedWidth(376)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(10)

        status_box = QGroupBox('AI 检测状态')
        status_layout = QVBoxLayout(status_box)
        status_layout.setSpacing(6)
        self.lbl_system = QLabel('● 系统就绪')
        self.lbl_system.setObjectName('systemState')
        self.lbl_detected = QLabel('已识别：— / 4')
        self.lbl_centers = QLabel('圆心：—')
        self.lbl_avg = QLabel('平均置信度：—')
        self.lbl_part = QLabel('part 置信度：—')
        self.lbl_constraint = QLabel('part 位置筛选：—')
        self.lbl_engine = QLabel('设备：本地 GPU / CPU')
        self.lbl_engine.setWordWrap(True)
        status_grid = QGridLayout()
        status_grid.addWidget(self.lbl_detected, 0, 0)
        status_grid.addWidget(self.lbl_centers, 0, 1)
        status_grid.addWidget(self.lbl_avg, 1, 0)
        status_grid.addWidget(self.lbl_constraint, 1, 1)
        status_layout.addWidget(self.lbl_system)
        status_layout.addLayout(status_grid)
        right_layout.addWidget(status_box)

        task_box = QGroupBox('孔位与测量准备')
        task_layout = QVBoxLayout(task_box)
        task_layout.setSpacing(6)
        self.task_note = QLabel('孔号按当前图像位置排序；尚未建立固定物理孔身份。')
        self.task_note.setObjectName('warnNote')
        self.task_note.setWordWrap(True)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(['孔号', '置信度', '图像圆心 px', '定位状态', '三维坐标'])
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(30)
        _header = self.table.horizontalHeader()
        _header.setStretchLastSection(False)
        for _column in (0, 1, 3, 4):
            _header.setSectionResizeMode(_column, QHeaderView.ResizeMode.ResizeToContents)
        _header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        task_layout.addWidget(self.task_note)
        task_layout.addWidget(self.table, 1)
        self.coordinate_note = QLabel('当前圆心为图像像素坐标；三维定位与测量机械臂坐标待标定。')
        self.coordinate_note.setObjectName('hintNote')
        self.coordinate_note.setWordWrap(True)
        task_layout.addWidget(self.coordinate_note)
        right_layout.addWidget(task_box, 1)
        body_layout.addWidget(right)

        # ---- 模型与数据管理弹窗（保留原功能）----
        self.model_dialog = QDialog(self)
        self.model_dialog.setWindowTitle('模型与数据管理')
        self.model_dialog.resize(560, 230)
        management = QVBoxLayout(self.model_dialog)
        note = QLabel('添加照片并标注 → 训练候选模型 → 查看验证结果\\n'
                      '正式模型仍按验证结果选择，验证通过后才启用。')
        note.setWordWrap(True)
        management.addWidget(note)
        self.btn_dataset = QPushButton('添加训练数据 / 自动更新')
        self.btn_validation = QPushButton('训练验证结果')
        management.addWidget(self.btn_dataset)
        management.addWidget(self.btn_validation)

        # ---- 底部状态栏 ----
        bottom = QFrame()
        bottom.setObjectName('statusBar')
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(16, 6, 16, 8)
        bottom_layout.setSpacing(4)
        bar = QHBoxLayout()
        self.connection_line = QLabel('工业相机：未连接　｜　拍照机械臂 A：未连接　｜　测量机械臂 B：未连接')
        self.connection_line.setObjectName('deviceLine')
        diagnostics_toggle = QPushButton('▶ 诊断信息')
        diagnostics_toggle.setObjectName('flat')
        diagnostics_toggle.setCheckable(True)
        bar.addWidget(self.connection_line, 1)
        bar.addWidget(diagnostics_toggle)
        bottom_layout.addLayout(bar)
        self.diagnostics = QWidget()
        diagnostics_layout = QVBoxLayout(self.diagnostics)
        diagnostics_layout.setContentsMargins(0, 0, 0, 0)
        details = QHBoxLayout()
        details.addWidget(self.lbl_part)
        details.addWidget(self.lbl_engine, 1)
        diagnostics_layout.addLayout(details)
        self.logbox = QPlainTextEdit()
        self.logbox.setObjectName('log')
        self.logbox.setReadOnly(True)
        self.logbox.setMaximumHeight(110)
        diagnostics_layout.addWidget(self.logbox)
        self.diagnostics.hide()
        bottom_layout.addWidget(self.diagnostics)
        root.addWidget(bottom)

        self.device_states = {}

        # ---- 信号 ----
        self.btn_select.clicked.connect(self.select_images)
        self.btn_detect.clicked.connect(self.start_batch)
        self.btn_devices.clicked.connect(self.show_device_panel)
        self.btn_records.clicked.connect(self.show_records)
        self.btn_dataset.clicked.connect(self.bridge.open_dataset)
        self.btn_validation.clicked.connect(self.bridge.open_validation)
        self.btn_results.clicked.connect(self.open_results)
        self.btn_models.clicked.connect(self.show_model_management)
        self.btn_simulation.clicked.connect(self.show_simulation)
        self.previous_button.clicked.connect(lambda: self.show_index(self.current_index - 1))
        self.next_button.clicked.connect(lambda: self.show_index(self.current_index + 1))
        self.selector.currentIndexChanged.connect(self.show_index)
        self.chk_fit.toggled.connect(self.render_view)
        self.sld_zoom.valueChanged.connect(self.render_view)
        self.table.cellDoubleClicked.connect(self.open_current_result)
        diagnostics_toggle.toggled.connect(self.diagnostics.setVisible)
        diagnostics_toggle.toggled.connect(lambda expanded: diagnostics_toggle.setText(
            '▼ 诊断信息' if expanded else '▶ 诊断信息'))
        QShortcut(QKeySequence('Ctrl+O'), self, activated=self.select_images)
        QShortcut(QKeySequence('F5'), self, activated=self.start_batch)

'''


def patch_ui_redesign(engine: Path) -> str:
    """Full main-window redesign: blue header bar, left action column, centre image
    card, right result column, bottom status bar (reference: DobotStudio look)."""
    f = engine / "inspection_gui" / "gui.py"
    if not f.is_file():
        return "找不到 gui.py"
    text = f.read_text(encoding="utf-8")
    if "[redesign]" in text or "#topBar" in text:
        return "已打过补丁（跳过）"

    # 1) QFrame is needed by the new layout
    if "QFrame," not in text:
        text = text.replace(
            "    QSizePolicy, QSlider, QSplitter, QTableWidget, QTableWidgetItem,",
            "    QFrame, QSizePolicy, QSlider, QSplitter, QTableWidget, QTableWidgetItem,", 1)

    # 2) replace the stylesheet
    style_start = text.find('STYLE = """')
    if style_start < 0:
        return "没找到 STYLE 块"
    style_end = text.find('"""', style_start + 10) + 3
    text = text[:style_start] + 'STYLE = r"""' + NEW_STYLE + '"""' + text[style_end:]

    # 3) replace the whole _build_ui method
    ui_start = text.find("    def _build_ui(self):")
    ui_end = text.find("    def log(self, message):")
    if ui_start < 0 or ui_end < 0 or ui_end <= ui_start:
        return "没找到 _build_ui 方法边界"
    text = text[:ui_start] + NEW_BUILD_UI + text[ui_end:]

    shutil.copy2(f, f.with_suffix(".py.bak"))
    f.write_text(text, encoding="utf-8")
    return "界面已整体重排（原文件备份为 gui.py.bak）"


def patch_canvas_theme(engine: Path) -> str:
    """The photo canvas was a dark slate gradient, which clashed with the new light
    UI. Make it light (like the reference software's white work area) and give the
    header bar a little more room."""
    edits = [
        (engine / "inspection_gui" / "view_render.py", [
            ("def _gradient_canvas(h, w, top=(42, 23, 15), bottom=(59, 41, 30)):",
             "def _gradient_canvas(h, w, top=(252, 249, 246), bottom=(240, 245, 250)):"),
            ("    Colours are slate blue: #0f172a (top) -> #1e293b (bottom).",
             "    [local patch] light grey-blue: #f6f9fc (top) -> #f0f5fa (bottom),\n"
             "    to match the light application theme."),
        ]),
        (engine / "inspection_gui" / "gui.py", [
            ("        top.setFixedHeight(62)", "        top.setFixedHeight(70)   # [local patch]"),
            ("        titles.setSpacing(0)", "        titles.setSpacing(3)      # [local patch]"),
            ("        right.setFixedWidth(376)", "        right.setFixedWidth(424)  # [local patch] table needs room"),
            ("        left.setFixedWidth(238)", "        left.setFixedWidth(232)   # [local patch]"),
        ]),
    ]
    applied, skipped, missing = [], [], []
    for path, pairs in edits:
        if not path.is_file():
            missing.append(path.name)
            continue
        text = path.read_text(encoding="utf-8")
        original = text
        for old, new in pairs:
            if new in text:
                skipped.append(path.name)
                continue
            if old in text:
                text = text.replace(old, new, 1)
            else:
                missing.append("{}:{}".format(path.name, old.strip()[:24]))
        if text != original:
            shutil.copy2(path, path.with_suffix(".py.bak"))
            path.write_text(text, encoding="utf-8")
            applied.append(path.name)
    out = []
    if applied:
        out.append("已改: " + ", ".join(sorted(set(applied))))
    if skipped:
        out.append("已是最新: " + ", ".join(sorted(set(skipped))))
    if missing:
        out.append("未匹配: " + "; ".join(missing[:4]))
    return "；".join(out) or "无需修改"


def point_registry(engine: Path) -> str:
    f = engine / "active_models.json"
    if not f.is_file():
        return "active_models.json 不存在"
    text = f.read_text(encoding="utf-8")
    target = '"bore": "models/{}"'.format(DEPLOYED_NAME)
    if target in text:
        return "已经指向 {}（跳过）".format(DEPLOYED_NAME)
    old = '"bore": "models/bore_best.pt"'
    if old not in text:
        return '找不到 "bore": "models/bore_best.pt"，请人工确认'
    shutil.copy2(f, f.with_suffix(".json.bak"))
    f.write_text(text.replace(old, target, 1), encoding="utf-8")
    return "已把 bore 指向 {}（part 仍是他的 part_best.pt）".format(DEPLOYED_NAME)


def restore_registry(engine: Path) -> str:
    """Point the registry back at HIS own bore model (the default)."""
    f = engine / "active_models.json"
    if not f.is_file():
        return "active_models.json 不存在"
    text = f.read_text(encoding="utf-8")
    swapped = '"bore": "models/{}"'.format(DEPLOYED_NAME)
    if swapped not in text:
        return "已经是他的 bore_best.pt（无需恢复）"
    text = text.replace(swapped, '"bore": "models/bore_best.pt"', 1)
    f.write_text(text, encoding="utf-8")
    return "已恢复为他的 models/bore_best.pt（我们的模型仍留在 models/{}）".format(DEPLOYED_NAME)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", default=str(DEFAULT_ENGINE))
    ap.add_argument("--swap-model", action="store_true",
                    help="同时把 bore 模型换成我们的 fusion_v1（实测在他的管线里会变差，默认不做）")
    args = ap.parse_args()
    engine = Path(args.engine)
    if not (engine / "app.py").is_file():
        print("不是他的 engine_bore_local 目录:", engine)
        return 2

    print("engine :", engine)
    print("1) 拟合策略 :", patch_detect_core(engine))
    print("2) 部署模型 :", deploy_model(engine))
    print("3) 应用图标 :", patch_app_icon(engine))
    print("4) 深色模式 :", patch_dark_mode(engine))
    print("5) 照片目录 :", patch_photo_dir(engine))
    print("6) Tk 配色  :", patch_tk_dark_mode(engine))
    print("7) 界面布局 :", patch_ui_layout(engine))
    print("8) 3D 场景  :", patch_3d_scene(engine))
    print("9) 界面重排 :", patch_ui_redesign(engine))
    print("9b) 画布配色:", patch_canvas_theme(engine))
    if args.swap_model:
        print("10) 模型注册:", point_registry(engine))
    else:
        print("10) 模型注册:", restore_registry(engine))

    reg = engine / "active_models.json"
    if reg.is_file():
        data = json.loads(reg.read_text(encoding="utf-8"))
        print()
        print("当前生效的模型：")
        print("   bore :", data.get("bore"))
        print("   part :", data.get("part"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
