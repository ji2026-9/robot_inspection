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
        for entry in pairs:
            # 兼容两种写法：(old, new) 或者 (old, new, 幂等标记)
            old, new = entry[0], entry[1]
            marker = entry[2] if len(entry) > 2 else None
            if marker and marker in text:
                skipped.append(path.name)
                continue
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


def patch_qt_photo_dir(engine: Path) -> str:
    """The Qt UI keeps its own `last_dir` (defaults to a folder that does not exist,
    so the picker opened the program directory) and never persisted it. Load it from
    the marker file and save it after each selection."""
    f = engine / "inspection_gui" / "gui.py"
    if not f.is_file():
        return "找不到 gui.py"
    text = f.read_text(encoding="utf-8")
    if "remember the last used photo folder" in text:
        return "已打过补丁（跳过）"
    edits = [
        ("        self.last_dir = str(BASE / 'data' / 'incoming_photos')",
         "        # [local patch] remember the last used photo folder across restarts\n"
         "        _marker = BASE / 'last_photo_dir.txt'\n"
         "        try:\n"
         "            _saved = Path(_marker.read_text(encoding='utf-8').strip()) if _marker.is_file() else None\n"
         "        except OSError:\n"
         "            _saved = None\n"
         "        if _saved is not None and _saved.is_dir():\n"
         "            self.last_dir = str(_saved)\n"
         "        else:\n"
         "            _pictures = Path.home() / 'Pictures'\n"
         "            self.last_dir = str(_pictures) if _pictures.is_dir() else str(BASE)"),
        ("        self.last_dir = str(Path(self.paths[0]).parent) if self.paths else self.last_dir",
         "        self.last_dir = str(Path(self.paths[0]).parent) if self.paths else self.last_dir\n"
         "        try:   # [local patch] remember it for next launch\n"
         "            (BASE / 'last_photo_dir.txt').write_text(self.last_dir, encoding='utf-8')\n"
         "        except OSError:\n"
         "            pass"),
    ]
    applied = 0
    for old, new in edits:
        if new in text:
            continue
        if old in text:
            text = text.replace(old, new, 1)
            applied += 1
    if not applied:
        return "没找到目标代码行，请人工检查"
    shutil.copy2(f, f.with_suffix(".py.bak"))
    f.write_text(text, encoding="utf-8")
    return "Qt 界面已改为记住上次文件夹（原文件备份为 gui.py.bak）"


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
        for entry in pairs:
            old, new = entry[0], entry[1]
            marker = entry[2] if len(entry) > 2 else None
            if marker and marker in text:
                # 内容已经在文件里了：绝不再插一遍
                skipped.append(path.name)
                continue
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


def patch_dialog_layouts(engine: Path) -> str:
    """Three concrete layout complaints from real use:

    1. 实验记录: the 10 columns totalled ~2000 px inside a 1260 px dialog, the right
       columns were cut and the horizontal scrollbar was easy to miss. Make every
       column fit its content, stretch the last one, and size the dialog to the
       screen.
    2. 设备连接: the page content was squeezed (table rows cut, buttons drawn outside
       the group box). Give the dialog more height and tighten the card padding.
    3. main window: expanding 诊断信息 squeezed the left column so 「其他功能」
       disappeared. Put the left column in a scroll area.
    """
    edits = [
        (engine / "inspection_gui" / "records_view.py", [
            ("        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)\n"
             "        header.setStretchLastSection(False)\n",
             "        # [local patch] fit every column instead of clipping the right ones\n"
             "        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)\n"
             "        header.setStretchLastSection(True)\n"),
            ("        self.resize(1260, 720)\n        self.setMinimumSize(760, 450)",
             "        _screen = self.screen()\n"
             "        self.resize(min(1400, _screen.availableGeometry().width() - 60),\n"
             "                    min(780, _screen.availableGeometry().height() - 60))\n"
             "        self.setMinimumSize(760, 450)"),
        ]),
        (engine / "inspection_gui" / "devices_view.py", [
            ("        outer = QVBoxLayout(page)",
             "        outer = QVBoxLayout(page)\n"
             "        outer.setContentsMargins(12, 14, 12, 14)   # [local patch]\n"
             "        outer.setSpacing(12)                        # [local patch]"),
            ("                margin-top: 10px; padding: 12px 10px 8px; font-weight: 600;",
             "                margin-top: 18px; padding: 14px 12px 10px; font-weight: 600;"),
            ("        self.fields.setFixedHeight(230)   # [local patch] 6 rows + header",
             "        self.fields.setFixedHeight(246)   # [local patch] 6 rows + header\n"
             "        self.fields.verticalHeader().setDefaultSectionSize(33)   # [local patch]\n"
             "        self.fields.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)"),
            ("        self.fields.setFixedHeight(252)   # [local patch] 6 rows + header",
             "        self.fields.setFixedHeight(246)   # [local patch] 6 rows + header\n"
             "        self.fields.verticalHeader().setDefaultSectionSize(33)   # [local patch]\n"
             "        self.fields.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)"),
            ("        self.fields.setFixedHeight(246)   # [local patch] 6 rows + header\n"
             "        self.fields.verticalHeader().setDefaultSectionSize(33)   # [local patch]\n"
             "        self.fields.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)",
             "        self.fields.setFixedHeight(292)   # [local patch] 6 rows + header\n"
             "        self.fields.verticalHeader().setDefaultSectionSize(33)   # [local patch]\n"
             "        self.fields.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)"),
            ("    QComboBox,\n    QDialog,\n    QGroupBox,",
             "    QComboBox,\n    QDialog,\n    QFrame,\n    QGroupBox,"),
            ("        _height = min(820, _screen.availableGeometry().height() - 70) if _screen else 780\n"
             "        self.resize(720, _height)",
             "        _height = min(880, _screen.availableGeometry().height() - 30) if _screen else 820\n"
             "        self.resize(760, _height)"),
            ("        self.fields.setFixedHeight(214)   # [local patch] was 273 -> bottom row got clipped",
             "        self.fields.setFixedHeight(230)   # [local patch] 6 rows + header"),
            ("            QDialog#inspectionDevices QGroupBox {\n"
             "                background: white; border: 1px solid #d5deea; border-radius: 8px;\n"
             "                margin-top: 12px; padding: 15px 10px 10px; font-weight: 600;\n"
             "            }",
             "            QDialog#inspectionDevices QGroupBox {\n"
             "                background: white; border: 1px solid #d5deea; border-radius: 8px;\n"
             "                margin-top: 10px; padding: 12px 10px 8px; font-weight: 600;\n"
             "            }"),
            ("            scroll = QScrollArea()\n"
             "            scroll.setWidgetResizable(True)\n"
             "            scroll.setWidget(page)",
             "            scroll = QScrollArea()\n"
             "            scroll.setWidgetResizable(True)\n"
             "            scroll.setFrameShape(QFrame.Shape.NoFrame)\n"
             "            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)\n"
             "            scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)\n"
             "            page.setMinimumWidth(560)\n"
             "            scroll.setWidget(page)"),
        ]),
        (engine / "inspection_gui" / "gui.py", [
            ("        left = QWidget()\n"
             "        left.setFixedWidth(232)   # [local patch]\n"
             "        left_layout = QVBoxLayout(left)",
             "        left_inner = QWidget()\n"
             "        left_layout = QVBoxLayout(left_inner)"),
            ("        left_layout.addStretch(1)\n        body_layout.addWidget(left)",
             "        left_layout.addStretch(1)\n"
             "        # [local patch] keep the left column reachable when 诊断信息 expands\n"
             "        left = QScrollArea()\n"
             "        left.setWidgetResizable(True)\n"
             "        left.setWidget(left_inner)\n"
             "        left.setFrameShape(QFrame.Shape.NoFrame)\n"
             "        left.setFixedWidth(252)\n"
             "        left.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)\n"
             "        left.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)\n"
             "        body_layout.addWidget(left)"),
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
        out.append("已修: " + ", ".join(sorted(set(applied))))
    if skipped:
        out.append("已是最新: " + ", ".join(sorted(set(skipped))))
    if missing:
        out.append("未匹配: " + "; ".join(missing[:4]))
    return "；".join(out) or "无需修改"


def patch_light_frame(engine: Path) -> str:
    """The app is light but Windows is in dark mode, so every window kept a black
    title bar / frame - jarring against the light content. Force Qt's LIGHT colour
    scheme (Qt 6.8+ maps this to a light immersive title bar) and soften the few
    remaining dark borders."""
    edits = [
        (engine / "inspection_gui" / "main.py", [
            ("    application.setApplicationName('Engine Bore Inspection')\n",
             "    application.setApplicationName('Engine Bore Inspection')\n"
             "    # [local patch] force the LIGHT colour scheme so the Windows title bar\n"
             "    # and frame match the light UI instead of staying dark-mode black\n"
             "    try:\n"
             "        from PySide6.QtCore import Qt as _Qt\n"
             "        application.styleHints().setColorScheme(_Qt.ColorScheme.Light)\n"
             "    except Exception:\n"
             "        try:\n"
             "            application.setStyle('Fusion')\n"
             "        except Exception:\n"
             "            pass\n"),
        ]),
        (engine / "inspection_gui" / "records_view.py", [
            ("QTableWidget { background: white; color: #172b4d; gridline-color: #b8c2cf; "
             "alternate-background-color: #f3f6fa; }",
             "QTableWidget { background: white; color: #172b4d; gridline-color: #e2e8f0; "
             "alternate-background-color: #f5f8fc; }"),
            ("QHeaderView::section { padding: 6px; background: #e9eef5; \"\n"
             "            \"border: 1px solid #b8c2cf; font-weight: 600; }",
             "QHeaderView::section { padding: 7px; background: #eef3fa; \"\n"
             "            \"border: none; border-bottom: 1px solid #dbe4ee; font-weight: 600; }"),
        ]),
        (engine / "inspection_gui" / "devices_view.py", [
            ("                background: white; color: #234369; gridline-color: #d5deea; border: 1px solid #d5deea;",
             "                background: white; color: #234369; gridline-color: #e2e8f0; border: 1px solid #dbe4ee;"),
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
        out.append("已改: " + ", ".join(sorted(set(applied))))
    if skipped:
        out.append("已是最新: " + ", ".join(sorted(set(skipped))))
    if missing:
        out.append("未匹配: " + "; ".join(missing[:3]))
    return "；".join(out) or "无需修改"


def patch_fresh_start(engine: Path) -> str:
    """The app restored the previous batch at every startup, so a "new" run showed
    old photos, old ellipses and old numbers. Start clean instead and load the
    previous batch only when the user explicitly asks for it."""
    edits = [
        (engine / "inspection_gui" / "gui.py", [
            ("        self.log('系统就绪，检测使用当前正式模型，孔置信度保留阈值为 0.5。')\n"
             "        self.restore_last_batch()\n"
             "        self.set_controls()",
             "        # [local patch] start with a CLEAN workspace. The previous batch is\n"
             "        # only shown when the user clicks 「打开上次批次」 (or opens 实验记录).\n"
             "        self.log('系统就绪，检测使用当前正式模型，孔置信度保留阈值为 0.5。')\n"
             "        self.log('工作区为空。如需查看上一次的检测结果，请点「打开上次批次」。')\n"
             "        self.set_controls()"),
            ("        self.btn_results = QPushButton('打开结果文件夹')\n"
             "        for _button in (self.btn_devices, self.btn_records, self.btn_models,\n"
             "                        self.btn_simulation, self.btn_results):\n"
             "            others_layout.addWidget(_button)",
             "        self.btn_results = QPushButton('打开结果文件夹')\n"
             "        self.btn_last_batch = QPushButton('打开上次批次')   # [local patch]\n"
             "        self.btn_last_batch.setToolTip('只在你点击时才载入上一次的检测结果，启动时不会自动载入。')\n"
             "        for _button in (self.btn_devices, self.btn_records, self.btn_models,\n"
             "                        self.btn_simulation, self.btn_last_batch, self.btn_results):\n"
             "            others_layout.addWidget(_button)"),
             # [audit 2026-10-08] 这一行以前插入的是 open_last_batch，导致每次运行脚本
             # 都会再插一条连接（点一次「打开历史批次」弹出两个窗口）。直接插入最终形式。
             ("        self.btn_simulation.clicked.connect(self.show_simulation)\n",
              "        self.btn_simulation.clicked.connect(self.show_simulation)\n"
              "        self.btn_last_batch.clicked.connect(self.open_batch_history)   # [local patch]\n"),
            ("    def restore_last_batch(self):\n",
             "    @Slot()\n"
             "    def open_last_batch(self):\n"
             "        \"\"\"[local patch] explicit user action: load the previous batch.\"\"\"\n"
             "        if not LAST_BATCH.is_file():\n"
             "            QMessageBox.information(self, '没有历史批次',\n"
             "                                    '还没有可以打开的上一次检测结果。')\n"
             "            return\n"
             "        self.restore_last_batch()\n"
             "        if not self.paths:\n"
             "            QMessageBox.information(self, '没有历史批次',\n"
             "                                    '上一次的检测结果文件内容为空。')\n"
             "\n"
             "    def restore_last_batch(self):\n"),
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
        out.append("已改: " + ", ".join(sorted(set(applied))))
    if skipped:
        out.append("已是最新: " + ", ".join(sorted(set(skipped))))
    if missing:
        out.append("未匹配: " + "; ".join(missing[:3]))
    return "；".join(out) or "无需修改"


def patch_batch_history(engine: Path) -> str:
    """"打开上次批次" only ever reached the newest batch (last_batch.json is
    overwritten). Archive every batch and let the user pick which one to reopen."""
    target = engine / "inspection_gui" / "gui.py"
    if target.is_file() and "BATCH_DIR.mkdir(exist_ok=True)" in target.read_text(encoding="utf-8"):
        # [audit] 这一组改动是一次性的：已经在文件里就整体跳过，避免插入重复块
        return "已打过补丁（跳过）"
    edits = [
        (engine / "inspection_gui" / "gui.py", [
            ("LAST_BATCH = BASE / 'last_batch.json'",
             "LAST_BATCH = BASE / 'last_batch.json'\n"
             "BATCH_DIR = BASE / 'batches'                    # [local patch] 历史批次归档目录\n"
             "BATCH_INDEX = BATCH_DIR / 'index.jsonl'         # [local patch] 批次索引"),
            # 1) archive every batch next to last_batch.json
            ("        temporary = LAST_BATCH.with_suffix('.tmp')\n"
             "        temporary.write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding='utf-8')\n"
             "        temporary.replace(LAST_BATCH)",
             "        temporary = LAST_BATCH.with_suffix('.tmp')\n"
             "        temporary.write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding='utf-8')\n"
             "        temporary.replace(LAST_BATCH)\n"
             "        # [local patch] keep every batch so older ones stay reachable\n"
             "        try:\n"
             "            BATCH_DIR.mkdir(exist_ok=True)\n"
             "            stamp = datetime.now().strftime('%Y%m%d_%H%M%S')\n"
             "            snapshot = BATCH_DIR / (stamp + '.json')\n"
             "            snapshot.write_text(json.dumps(reports, ensure_ascii=False, indent=2),\n"
             "                                encoding='utf-8')\n"
             "            entry = {'stamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),\n"
             "                     'count': len(reports),\n"
             "                     'photos': [Path(r.get('image', '')).name for r in reports][:3],\n"
             "                     'dir': str(snapshot.parent),\n"
             "                     'file': str(snapshot)}\n"
             "            with BATCH_INDEX.open('a', encoding='utf-8') as handle:\n"
             "                handle.write(json.dumps(entry, ensure_ascii=False) + '\\n')\n"
             "        except OSError:\n"
             "            pass",
             "BATCH_DIR.mkdir(exist_ok=True)"),
            # 2) the button opens a chooser instead of blindly loading the newest
            ("        self.btn_last_batch = QPushButton('打开上次批次')   # [local patch]\n"
             "        self.btn_last_batch.setToolTip('只在你点击时才载入上一次的检测结果，启动时不会自动载入。')",
             "        self.btn_last_batch = QPushButton('打开历史批次')   # [local patch]\n"
             "        self.btn_last_batch.setToolTip('列出以前检测过的每一批，自己选一批重新载入；启动时不会自动载入。')"),
            # 3) replace the simple loader with a picker + a shared loader
            ("    @Slot()\n"
             "    def open_last_batch(self):\n"
             "        \"\"\"[local patch] explicit user action: load the previous batch.\"\"\"\n"
             "        if not LAST_BATCH.is_file():\n"
             "            QMessageBox.information(self, '没有历史批次',\n"
             "                                    '还没有可以打开的上一次检测结果。')\n"
             "            return\n"
             "        self.restore_last_batch()\n"
             "        if not self.paths:\n"
             "            QMessageBox.information(self, '没有历史批次',\n"
             "                                    '上一次的检测结果文件内容为空。')\n",
             "    def _batch_entries(self):\n"
             "        entries = []\n"
             "        if BATCH_INDEX.is_file():\n"
             "            try:\n"
             "                for line in BATCH_INDEX.read_text(encoding='utf-8').splitlines():\n"
             "                    if line.strip():\n"
             "                        entries.append(json.loads(line))\n"
             "            except (OSError, ValueError):\n"
             "                entries = []\n"
             "        entries = [entry for entry in entries\n"
             "                   if Path(entry.get('file', '')).is_file()]\n"
             "        if not entries and LAST_BATCH.is_file():\n"
             "            try:\n"
             "                reports = json.loads(LAST_BATCH.read_text(encoding='utf-8'))\n"
             "                entries = [{'stamp': '（较早，未归档）', 'count': len(reports),\n"
             "                            'photos': [Path(r.get('image', '')).name\n"
             "                                       for r in reports if isinstance(r, dict)][:3],\n"
             "                            'dir': str(BATCH_DIR), 'file': str(LAST_BATCH)}]\n"
             "            except (OSError, ValueError):\n"
             "                entries = []\n"
             "        return list(reversed(entries))\n"
             "\n"
             "    @Slot()\n"
             "    def open_batch_history(self):\n"
             "        \"\"\"[local patch] pick WHICH previous batch to reopen.\"\"\"\n"
             "        entries = self._batch_entries()\n"
             "        if not entries:\n"
             "            QMessageBox.information(self, '没有历史批次',\n"
             "                                    '还没有可以打开的历史检测批次。')\n"
             "            return\n"
             "        dialog = QDialog(self)\n"
             "        dialog.setWindowTitle('打开历史批次')\n"
             "        dialog.resize(820, 440)\n"
             "        layout = QVBoxLayout(dialog)\n"
             "        layout.addWidget(QLabel('选择要重新载入的检测批次（不会重新检测，也不会新增实验记录）：'))\n"
             "        table = QTableWidget(len(entries), 4)\n"
             "        table.setHorizontalHeaderLabels(['检测时间', '张数', '照片', '结果目录'])\n"
             "        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)\n"
             "        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)\n"
             "        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)\n"
             "        table.verticalHeader().setVisible(False)\n"
             "        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)\n"
             "        table.horizontalHeader().setStretchLastSection(True)\n"
             "        for row, entry in enumerate(entries):\n"
             "            photos = entry.get('photos') or []\n"
             "            table.setItem(row, 0, QTableWidgetItem(str(entry.get('stamp', ''))))\n"
             "            table.setItem(row, 1, QTableWidgetItem(str(entry.get('count', ''))))\n"
             "            table.setItem(row, 2, QTableWidgetItem('、'.join(photos)))\n"
             "            table.setItem(row, 3, QTableWidgetItem(str(entry.get('dir', ''))))\n"
             "        table.selectRow(0)\n"
             "        layout.addWidget(table, 1)\n"
             "        buttons = QHBoxLayout()\n"
             "        buttons.addStretch(1)\n"
             "        open_button = QPushButton('打开这一批')\n"
             "        open_button.setObjectName('primary')\n"
             "        cancel_button = QPushButton('取消')\n"
             "        buttons.addWidget(open_button)\n"
             "        buttons.addWidget(cancel_button)\n"
             "        layout.addLayout(buttons)\n"
             "        chosen = {'row': None}\n"
             "        def accept():\n"
             "            chosen['row'] = table.currentRow()\n"
             "            dialog.accept()\n"
             "        open_button.clicked.connect(accept)\n"
             "        cancel_button.clicked.connect(dialog.reject)\n"
             "        table.cellDoubleClicked.connect(lambda *_: accept())\n"
             "        if dialog.exec() != QDialog.DialogCode.Accepted or chosen['row'] is None:\n"
             "            return\n"
             "        self.load_batch(entries[chosen['row']].get('file'))\n"
             "\n"
             "    def load_batch(self, path):\n"
             "        \"\"\"[local patch] show a stored batch in the workspace (no detection).\"\"\"\n"
             "        try:\n"
             "            reports = json.loads(Path(path).read_text(encoding='utf-8'))\n"
             "        except (OSError, ValueError, TypeError):\n"
             "            reports = []\n"
             "        reports = [r for r in reports if isinstance(r, dict) and r.get('image')]\n"
             "        if not reports:\n"
             "            QMessageBox.information(self, '批次为空', '这个批次里没有可显示的结果。')\n"
             "            return\n"
             "        self.paths = [r['image'] for r in reports]\n"
             "        self.results = [_report_to_result(r) for r in reports]\n"
             "        self.selector.blockSignals(True)\n"
             "        self.selector.clear()\n"
             "        self.selector.addItems([f'{i + 1}. {Path(p).name}'\n"
             "                                for i, p in enumerate(self.paths)])\n"
             "        self.selector.blockSignals(False)\n"
             "        self.completed_count = len(reports)\n"
             "        self.batch_progress.setRange(0, len(reports))\n"
             "        self.batch_progress.setValue(len(reports))\n"
             "        self.show_index(0)\n"
             "        self.set_controls()\n"
             "        self.log(f'已载入历史批次：{len(reports)} 张（未重新检测、未新增实验记录）。')\n"),
            # restore_last_batch now goes through load_batch
            ("            self.paths = [report['image'] for report in reports]\n"
             "            self.results = [_report_to_result(report) for report in reports]\n"
             "            self.selector.blockSignals(True)\n"
             "            self.selector.addItems([f'{index + 1}. {Path(path).name}' for index, path in enumerate(self.paths)])\n"
             "            self.selector.blockSignals(False)\n"
             "            self.completed_count = len(reports)\n"
             "            self.batch_progress.setRange(0, len(reports))\n"
             "            self.batch_progress.setValue(len(reports))\n"
             "            self.show_index(0)\n"
             "            self.log(f'已恢复上次 {len(reports)} 张检测结果，未新增实验记录。')",
             "            self.load_batch(LAST_BATCH)   # [local patch] shared loader\n",
             "def _batch_entries"),
        ]),
    ]
    applied, skipped, missing = [], [], []
    for path, pairs in edits:
        if not path.is_file():
            missing.append(path.name)
            continue
        text = path.read_text(encoding="utf-8")
        original = text
        for entry in pairs:
            # 这批改动里有一条是 (old, new, 幂等标记)，不能只按两元组解包
            old, new = entry[0], entry[1]
            marker = entry[2] if len(entry) > 2 else None
            if marker and marker in text:
                skipped.append(path.name)
                continue
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
        out.append("已改: " + ", ".join(sorted(set(applied))))
    if skipped:
        out.append("已是最新: " + ", ".join(sorted(set(skipped))))
    if missing:
        out.append("未匹配: " + "; ".join(missing[:3]))
    return "；".join(out) or "无需修改"


def patch_diagnostics_style(engine: Path) -> str:
    """The diagnostics area used a dark navy log box inside the light UI. Give it the
    same light card style as the rest of the window."""
    f = engine / "inspection_gui" / "gui.py"
    if not f.is_file():
        return "找不到 gui.py"
    text = f.read_text(encoding="utf-8")
    if "#diagPanel" in text:
        return "已打过补丁（跳过）"
    edits = [
        ("QPlainTextEdit#log { background: #0f2438; color: #d7e6f7; border-radius: 8px;\n"
         "                     padding: 5px; font-size: 11px; }",
         "#diagPanel { background: #ffffff; border: 1px solid #dde5ee; border-radius: 10px; }\n"
         "QLabel#diagTitle { color: #17457f; font-weight: 600; }\n"
         "QPlainTextEdit#log { background: #f8fafd; color: #33415a;\n"
         "                     border: 1px solid #e4eaf2; border-radius: 8px;\n"
         "                     padding: 8px; font-size: 11px;\n"
         "                     font-family: 'Consolas', 'Microsoft YaHei UI'; }"),
        ("        self.diagnostics = QWidget()\n"
         "        diagnostics_layout = QVBoxLayout(self.diagnostics)\n"
         "        diagnostics_layout.setContentsMargins(0, 0, 0, 0)\n"
         "        details = QHBoxLayout()",
         "        self.diagnostics = QWidget()\n"
         "        self.diagnostics.setObjectName('diagPanel')   # [local patch] light card\n"
         "        diagnostics_layout = QVBoxLayout(self.diagnostics)\n"
         "        diagnostics_layout.setContentsMargins(12, 10, 12, 10)\n"
         "        diagnostics_layout.setSpacing(6)\n"
         "        diag_title = QLabel('运行日志与诊断')\n"
         "        diag_title.setObjectName('diagTitle')\n"
         "        diagnostics_layout.addWidget(diag_title)\n"
         "        details = QHBoxLayout()"),
    ]
    applied = 0
    for old, new in edits:
        if new in text:
            continue
        if old in text:
            text = text.replace(old, new, 1)
            applied += 1
        else:
            return "没找到目标代码段，请人工检查"
    if not applied:
        return "已是最新"
    shutil.copy2(f, f.with_suffix(".py.bak"))
    f.write_text(text, encoding="utf-8")
    return "诊断信息已改为浅色卡片（原文件备份为 gui.py.bak）"


def patch_left_column(engine: Path) -> str:
    """[audit 2026-10-08] Two real defects found while driving the GUI:

    1) expanding 诊断信息 squashed the left column, so 「其他功能」 collapsed into
       a single clipped strip (everything below it was cut off);
    2) 「打开历史批次」 was wired to two slots, so one click opened two dialogs.

    Make the left column compact (two-column 其他功能, slimmer navigation),
    give every card a real minimum height so the column scrolls instead of
    squashing, and drop the duplicated connection.
    """
    f = engine / "inspection_gui" / "gui.py"
    if not f.is_file():
        return "找不到 gui.py"
    text = f.read_text(encoding="utf-8")
    if "[compact-left]" in text:
        return "已打过补丁（跳过）"

    mark = "   # [compact-left]"
    edits = [
        # 1) 本组照片：导航按钮/下拉框/进度条都收紧
        ("        photos = QGroupBox('本组照片')\n"
         "        photos_layout = QVBoxLayout(photos)\n"
         "        photos_layout.setSpacing(6)\n",
         "        photos = QGroupBox('本组照片')\n"
         "        photos_layout = QVBoxLayout(photos)\n"
         "        photos_layout.setSpacing(5)\n"
         "        photos_layout.setContentsMargins(10, 6, 10, 8)" + mark + "\n"),
        ("        self.selector = QComboBox()\n"
         "        navigation = QHBoxLayout()\n"
         "        self.previous_button = QPushButton('上一张')\n"
         "        self.next_button = QPushButton('下一张')\n"
         "        navigation.addWidget(self.previous_button)\n",
         "        self.selector = QComboBox()\n"
         "        self.selector.setMinimumHeight(28)\n"
         "        navigation = QHBoxLayout()\n"
         "        navigation.setSpacing(5)\n"
         "        self.previous_button = QPushButton('上一张')\n"
         "        self.next_button = QPushButton('下一张')\n"
         "        for _nav_button in (self.previous_button, self.next_button):\n"
         "            _nav_button.setFixedHeight(30)\n"
         "        navigation.addWidget(self.previous_button)\n"),
        ("        self.batch_progress.setFormat('本组进度 %v/%m')\n",
         "        self.batch_progress.setFormat('本组进度 %v/%m')\n"
         "        self.batch_progress.setMaximumHeight(22)" + mark + "\n"),
        # 2) 其他功能：改成两列，省下约一半高度
        ("        others = QGroupBox('其他功能')\n"
         "        others_layout = QVBoxLayout(others)\n"
         "        others_layout.setSpacing(6)\n",
         "        others = QGroupBox('其他功能')\n"
         "        others_layout = QGridLayout(others)          # 两列" + mark + "\n"
         "        others_layout.setSpacing(6)\n"
         "        others_layout.setContentsMargins(10, 6, 10, 8)" + mark + "\n"),
        ("        for _button in (self.btn_devices, self.btn_records, self.btn_models,\n"
         "                        self.btn_simulation, self.btn_last_batch, self.btn_results):\n"
         "            others_layout.addWidget(_button)\n"
         "        left_layout.addWidget(others)\n"
         "        left_layout.addStretch(1)\n",
         "        for _index, _button in enumerate((self.btn_devices, self.btn_records,\n"
         "                                          self.btn_models, self.btn_simulation,\n"
         "                                          self.btn_last_batch, self.btn_results)):\n"
         "            _button.setMinimumHeight(32)\n"
         "            others_layout.addWidget(_button, _index // 2, _index % 2)\n"
         "        left_layout.addWidget(others)\n"
         "        # 每张卡片给一个真实最小高度：诊断信息展开时左栏改为滚动，\n"
         "        # 而不是把卡片压成一条看不清的细缝。" + mark + "\n"
         "        actions.setMinimumHeight(176)\n"
         "        photos.setMinimumHeight(158)\n"
         "        others.setMinimumHeight(146)\n"
         "        left_layout.addStretch(1)\n"),
        # 3) 左栏略加宽，容纳两列按钮
        ("        left.setFixedWidth(252)", "        left.setFixedWidth(266)" + mark),
        # 4) 去掉重复的信号连接（点一次「打开历史批次」会连开两个对话框）
        ("        self.btn_last_batch.clicked.connect(self.open_last_batch)   # [local patch]\n"
         "        self.btn_last_batch.clicked.connect(self.open_batch_history)   # [local patch]\n",
         "        # 以前这里连接了两次，点一下会连开两个对话框" + mark + "\n"
         "        self.btn_last_batch.clicked.connect(self.open_batch_history)\n"),
        # 5) 诊断日志框矮一点，展开时少挤占画面
        ("        self.logbox.setMaximumHeight(110)\n",
         "        self.logbox.setMaximumHeight(96)" + mark + "\n"),
    ]
    applied, skipped, missing = [], [], []
    for old, new in edits:
        if new in text:
            skipped.append(old.strip().splitlines()[0][:28])
            continue
        if old in text:
            text = text.replace(old, new, 1)
            applied.append(old.strip().splitlines()[0][:28])
        else:
            missing.append(old.strip().splitlines()[0][:28])
    if not applied:
        if not missing:
            return "已是最新（无需修改）"
        return "未匹配: " + "; ".join(missing[:4])
    shutil.copy2(f, f.with_suffix(".py.bak"))
    f.write_text(text, encoding="utf-8")
    out = ["已改 {} 处（左栏紧凑化 + 去重信号）".format(len(applied))]
    if skipped:
        out.append("已是最新: {}".format(len(skipped)))
    if missing:
        out.append("未匹配: " + "; ".join(missing[:4]))
    return "；".join(out)


def patch_diagnostics_compact(engine: Path) -> str:
    """[audit 2026-10-08] The 诊断信息 panel was a tall vertical stack (title +
    details + 110px log), so expanding it stole ~200px from the work area and
    pushed the left column out of view. Lay it out sideways instead: a narrow
    info block on the left, the log on the right, total height about half."""
    f = engine / "inspection_gui" / "gui.py"
    if not f.is_file():
        return "找不到 gui.py"
    text = f.read_text(encoding="utf-8")
    if "[compact-diag]" in text:
        return "已打过补丁（跳过）"

    old = (
        "        self.diagnostics = QWidget()\n"
        "        self.diagnostics.setObjectName('diagPanel')   # [local patch] light card\n"
        "        diagnostics_layout = QVBoxLayout(self.diagnostics)\n"
        "        diagnostics_layout.setContentsMargins(12, 10, 12, 10)\n"
        "        diagnostics_layout.setSpacing(6)\n"
        "        diag_title = QLabel('运行日志与诊断')\n"
        "        diag_title.setObjectName('diagTitle')\n"
        "        diagnostics_layout.addWidget(diag_title)\n"
        "        details = QHBoxLayout()\n"
        "        details.addWidget(self.lbl_part)\n"
        "        details.addWidget(self.lbl_engine, 1)\n"
        "        diagnostics_layout.addLayout(details)\n"
        "        self.logbox = QPlainTextEdit()\n"
        "        self.logbox.setObjectName('log')\n"
        "        self.logbox.setReadOnly(True)\n")
    new = (
        "        self.diagnostics = QWidget()\n"
        "        self.diagnostics.setObjectName('diagPanel')   # [local patch] light card\n"
        "        # 横向紧凑布局：左边是标题与运行信息，右边是日志。" + "   # [compact-diag]\n"
        "        diagnostics_layout = QHBoxLayout(self.diagnostics)\n"
        "        diagnostics_layout.setContentsMargins(12, 8, 12, 8)\n"
        "        diagnostics_layout.setSpacing(14)\n"
        "        diag_side = QWidget()\n"
        "        diag_side.setObjectName('diagSide')\n"
        "        diag_side.setFixedWidth(268)\n"
        "        side_layout = QVBoxLayout(diag_side)\n"
        "        side_layout.setContentsMargins(0, 0, 0, 0)\n"
        "        side_layout.setSpacing(4)\n"
        "        diag_title = QLabel('运行日志与诊断')\n"
        "        diag_title.setObjectName('diagTitle')\n"
        "        self.lbl_part.setWordWrap(True)\n"
        "        self.lbl_engine.setWordWrap(True)\n"
        "        side_layout.addWidget(diag_title)\n"
        "        side_layout.addWidget(self.lbl_part)\n"
        "        side_layout.addWidget(self.lbl_engine)\n"
        "        side_layout.addStretch(1)\n"
        "        diagnostics_layout.addWidget(diag_side)\n"
        "        self.logbox = QPlainTextEdit()\n"
        "        self.logbox.setObjectName('log')\n"
        "        self.logbox.setReadOnly(True)\n"
        "        self.logbox.setFixedHeight(92)" + "   # [compact-diag]\n")
    if old not in text:
        return "未匹配：诊断面板结构与预期不同（可能已改过）"
    text = text.replace(old, new, 1)
    text = text.replace("        diagnostics_layout.addWidget(self.logbox)\n",
                        "        diagnostics_layout.addWidget(self.logbox, 1)\n", 1)
    shutil.copy2(f, f.with_suffix(".py.bak"))
    f.write_text(text, encoding="utf-8")
    return "诊断面板已改为横向紧凑布局"


def patch_tidy_signals(engine: Path) -> str:
    """[audit 2026-10-08] Final tidy-up, safe to run on every pass:

    * keep exactly ONE ``btn_last_batch -> open_batch_history`` connection.
      Earlier revisions of the patch set could stack two, so a single click
      opened two dialogs on top of each other;
    * drop the leftover ``setMaximumHeight(96)`` on the log box, which the
      left-column patch left behind after the diagnostics panel was redesigned.
    """
    f = engine / "inspection_gui" / "gui.py"
    if not f.is_file():
        return "找不到 gui.py"
    original = f.read_text(encoding="utf-8")
    canonical = ("        self.btn_last_batch.clicked.connect("
                 "self.open_batch_history)   # [local patch]\n")
    kept, seen, dropped = [], False, 0
    for line in original.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith("self.btn_last_batch.clicked.connect("):
            if seen:
                dropped += 1
                continue
            kept.append(canonical)
            seen = True
            continue
        if "以前这里连接了两次" in line:
            dropped += 1
            continue
        if stripped.startswith("self.logbox.setMaximumHeight(96)"):
            dropped += 1
            continue
        kept.append(line)
    text = "".join(kept)
    if text == original:
        return "无需修改（已经是干净状态）"
    shutil.copy2(f, f.with_suffix(".py.bak"))
    f.write_text(text, encoding="utf-8")
    return "已清理 {} 行冗余（重复信号 / 多余设置）".format(dropped)


def patch_device_page_compact(engine: Path) -> str:
    """[audit 2026-10-08] On the 工业相机 tab the action buttons (连接设备 /
    断开连接) were half cut off at the bottom of the tab pane, so the user had to
    scroll inside the page to even see them. Tighten the page so the whole form
    plus its buttons fit in one screen."""
    f = engine / "inspection_gui" / "devices_view.py"
    if not f.is_file():
        return "找不到 devices_view.py"
    text = f.read_text(encoding="utf-8")
    if "[compact-device]" in text:
        return "已打过补丁（跳过）"
    mark = "   # [compact-device]"
    edits = [
        ("        outer.setContentsMargins(18, 20, 18, 18)\n"
         "        outer.setSpacing(16)",
         "        outer.setContentsMargins(16, 12, 16, 12)" + mark + "\n"
         "        outer.setSpacing(10)" + mark),
        ("        layout.setContentsMargins(20, 18, 20, 18)",
         "        layout.setContentsMargins(16, 12, 16, 12)" + mark),
        ('        heading.setStyleSheet("font-size: 22px; font-weight: 700; color: #183b65;")',
         '        heading.setStyleSheet("font-size: 20px; font-weight: 700; color: #183b65;")'),
        ("            self.fields.setRowHeight(row, 40)",
         "            self.fields.setRowHeight(row, 36)"),
        ("        self.fields.setFixedHeight(292)   # [local patch] 6 rows + header",
         "        self.fields.setFixedHeight(256)" + mark + " 6 行 x 36 + 表头"),
        ("        self.fields.verticalHeader().setDefaultSectionSize(33)   # [local patch]",
         "        self.fields.verticalHeader().setDefaultSectionSize(36)"),
    ]
    applied, skipped, missing = [], [], []
    for old, new in edits:
        if new in text:
            skipped.append(old.strip()[:26])
            continue
        if old in text:
            text = text.replace(old, new, 1)
            applied.append(old.strip()[:26])
        else:
            missing.append(old.strip()[:26])
    if not applied:
        return "未匹配: " + "; ".join(missing[:4])
    shutil.copy2(f, f.with_suffix(".py.bak"))
    f.write_text(text, encoding="utf-8")
    out = ["已改 {} 处（设备窗口一屏显示）".format(len(applied))]
    if skipped:
        out.append("已是最新: {}".format(len(skipped)))
    if missing:
        out.append("未匹配: " + "; ".join(missing[:4]))
    return "；".join(out)


def patch_batch_dialog_details(engine: Path) -> str:
    """[audit 2026-10-08] Two小问题 in the 打开历史批次 dialog: the last column was
    labelled 结果目录 but actually shows the archive folder, and only the first
    three photo names were stored/listed even for a four-photo batch."""
    f = engine / "inspection_gui" / "gui.py"
    if not f.is_file():
        return "找不到 gui.py"
    text = f.read_text(encoding="utf-8")
    if "[tidy-history]" in text:
        return "已打过补丁（跳过）"
    mk = "   # [tidy-history]"
    edits = [
        ("table.setHorizontalHeaderLabels(['检测时间', '张数', '照片', '结果目录'])",
         "table.setHorizontalHeaderLabels(['检测时间', '张数', '照片', '归档目录'])" + mk),
        ("'photos': [Path(r.get('image', '')).name for r in reports][:3],",
         "'photos': [Path(r.get('image', '')).name for r in reports]," + mk),
        ("'photos': [Path(r.get('image', '')).name\n"
         "                                       for r in reports if isinstance(r, dict)][:3],",
         "'photos': [Path(r.get('image', '')).name\n"
         "                                       for r in reports if isinstance(r, dict)]," + mk),
    ]
    applied, missing = [], []
    for old, new in edits:
        if new in text:
            continue
        if old in text:
            text = text.replace(old, new, 1)
            applied.append(old.strip()[:26])
        else:
            missing.append(old.strip()[:26])
    if not applied:
        return "未匹配: " + "; ".join(missing[:3])
    shutil.copy2(f, f.with_suffix(".py.bak"))
    f.write_text(text, encoding="utf-8")
    return "已改 {} 处（批次弹窗列名与照片列表）".format(len(applied))


def patch_fusion_sync(engine: Path) -> str:
    """[fusion-sync 2026-10-08] 把朋友分支 feature/fusion 新增的两个能力接进本软件：

    * 「测量就绪检查」（inspection_gui/measurement_readiness.py）——
      如实列出相机 / 两条机械臂 / 标定 / 测孔清单的完成情况，未完成的项不隐藏，
      用来决定「发送测量任务」能不能开放；
    * 「本次要测量的孔」——在孔位表里勾选孔号，只有圆心可靠的孔能进测量清单。

    另外三个新文件（camera_parameters.py / capture_archive.py / vision_workspace.py）
    已经原样复制进来，等接了真实工业相机（见 CAMERA_DRIVER_CONTRACT.md）再启用。
    """
    f = engine / "inspection_gui" / "gui.py"
    if not f.is_file():
        return "找不到 gui.py"
    text = f.read_text(encoding="utf-8")
    if "[fusion-sync]" in text:
        return "已打过补丁（跳过）"

    edits = [
        # 1) 其他功能：多一个「测量就绪检查」按钮
        ("        self.btn_last_batch.setToolTip('列出以前检测过的每一批，自己选一批重新载入；启动时不会自动载入。')\n"
         "        for _index, _button in enumerate((self.btn_devices, self.btn_records,\n"
         "                                          self.btn_models, self.btn_simulation,\n"
         "                                          self.btn_last_batch, self.btn_results)):\n",
         "        self.btn_last_batch.setToolTip('列出以前检测过的每一批，自己选一批重新载入；启动时不会自动载入。')\n"
         "        # [fusion-sync] 来自朋友分支的“测量就绪检查”\n"
         "        self.btn_readiness = QPushButton('测量就绪检查')\n"
         "        self.btn_readiness.setToolTip('列出相机 / 机械臂 / 标定 / 测孔清单的完成情况，未完成的项不会隐藏。')\n"
         "        for _index, _button in enumerate((self.btn_devices, self.btn_records,\n"
         "                                          self.btn_models, self.btn_simulation,\n"
         "                                          self.btn_last_batch, self.btn_results,\n"
         "                                          self.btn_readiness)):\n"),
        ("        others.setMinimumHeight(146)", "        others.setMinimumHeight(184)"),
        # 2) 孔位表：勾选＝本次要测的孔
        ("        self.task_note = QLabel('孔号按当前图像位置排序；尚未建立固定物理孔身份。')",
         "        self.task_note = QLabel('孔号按当前图像位置排序，不是永久物理孔号；勾选孔号表示“本次要测量这个孔”。')"),
        ("        self.table = QTableWidget(0, 5)\n"
         "        self.table.setHorizontalHeaderLabels(['孔号', '置信度', '图像圆心 px', '定位状态', '三维坐标'])",
         "        self.measure_targets = set()      # [fusion-sync] 本次要测量的孔\n"
         "        self._filling_table = False       # [fusion-sync] 防止程序填表误触发勾选回调\n"
         "        self.table = QTableWidget(0, 5)\n"
         "        self.table.setHorizontalHeaderLabels(['孔号 ☑', '置信度', '图像圆心 px', '定位状态', '三维坐标'])"),
        # 3) 填表时把勾选状态画出来，并记录可靠圆心
        ("        self.table.setRowCount(4)\n"
         "        for row in range(4):\n"
         "            hid = f'H{row + 1:02d}'\n"
         "            hole = by_id.get(hid)\n"
         "            if hole:\n"
         "                center = hole.get('center_px')\n"
         "                point = f'{center[0]:.2f}, {center[1]:.2f}' if center is not None else '—'\n"
         "                state = '图像已定位' if hole.get('reliable_center') else ('圆心待复核' if center else '未拟合出圆心')\n"
         "                values = [hid, f\"{hole['confidence']:.4f}\", point, state, '待标定']\n"
         "            else:\n"
         "                values = [hid, '—', '—', '未识别' if result else '待检测', '—']\n"
         "            for column, value in enumerate(values):\n"
         "                item = QTableWidgetItem(value)\n"
         "                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)\n"
         "                self.table.setItem(row, column, item)\n",
         "        self.table.setRowCount(4)\n"
         "        self._filling_table = True        # [fusion-sync]\n"
         "        try:\n"
         "            for row in range(4):\n"
         "                hid = f'H{row + 1:02d}'\n"
         "                hole = by_id.get(hid)\n"
         "                if hole:\n"
         "                    center = hole.get('center_px')\n"
         "                    point = f'{center[0]:.2f}, {center[1]:.2f}' if center is not None else '—'\n"
         "                    state = '图像已定位' if hole.get('reliable_center') else ('圆心待复核' if center else '未拟合出圆心')\n"
         "                    values = [hid, f\"{hole['confidence']:.4f}\", point, state, '待标定']\n"
         "                else:\n"
         "                    values = [hid, '—', '—', '未识别' if result else '待检测', '—']\n"
         "                for column, value in enumerate(values):\n"
         "                    item = QTableWidgetItem(value)\n"
         "                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)\n"
         "                    if column == 0:   # [fusion-sync] 勾选＝本次要测的孔\n"
         "                        item.setToolTip('勾选表示“本次要测量这个孔”；只有圆心可靠的孔才允许勾选。')\n"
         "                        if hole and hole.get('reliable_center'):\n"
         "                            item.setFlags(Qt.ItemFlag.ItemIsUserCheckable\n"
         "                                          | Qt.ItemFlag.ItemIsEnabled\n"
         "                                          | Qt.ItemFlag.ItemIsSelectable)\n"
         "                            item.setCheckState(Qt.CheckState.Checked if hid in self.measure_targets\n"
         "                                               else Qt.CheckState.Unchecked)\n"
         "                    self.table.setItem(row, column, item)\n"
         "        finally:\n"
         "            self._filling_table = False\n"),
        # 4) 信号
        ("        self.btn_last_batch.clicked.connect(self.open_batch_history)   # [local patch]\n",
         "        self.btn_last_batch.clicked.connect(self.open_batch_history)   # [local patch]\n"
         "        self.btn_readiness.clicked.connect(self.show_readiness)   # [fusion-sync]\n"),
        ("        self.table.cellDoubleClicked.connect(self.open_current_result)\n",
         "        self.table.cellDoubleClicked.connect(self.open_current_result)\n"
         "        self.table.itemChanged.connect(self.measure_target_changed)   # [fusion-sync]\n"),
        # 5) 未满足就绪条件前，发送测量任务保持禁用（说明去哪看）
        ("        self.btn_send.setToolTip('设备连接、三维坐标、孔轴方向和标定验证完成后才能下发测量任务。')",
         "        self.btn_send.setToolTip('先点「测量就绪检查」：标定、手眼坐标转换、测针 TCP 等未完成项全部满足后才会开放下发。')"),
        # 6) 新方法
        ("    def log(self, message):\n",
         "    def measure_target_changed(self, item):\n"
         "        \"\"\"[fusion-sync] 勾选孔号 = 本次要测量这个孔。\"\"\"\n"
         "        if self._filling_table or item.column() != 0:\n"
         "            return\n"
         "        hid = f'H{item.row() + 1:02d}'\n"
         "        if item.checkState() == Qt.CheckState.Checked:\n"
         "            self.measure_targets.add(hid)\n"
         "        else:\n"
         "            self.measure_targets.discard(hid)\n"
         "        chosen = '、'.join(sorted(self.measure_targets)) if self.measure_targets else '（空）'\n"
         "        self.log(f'本次测量清单：{chosen}')\n"
         "\n"
         "    def confirmed_targets(self):\n"
         "        \"\"\"[fusion-sync] 勾选且圆心可靠的孔（对齐朋友分支 selected_targets 的校验口径）。\"\"\"\n"
         "        result = self.current_result or {}\n"
         "        reliable = {hole['id'] for hole in result.get('fitted_holes', [])\n"
         "                    if hole.get('reliable_center')}\n"
         "        return sorted(self.measure_targets & reliable)\n"
         "\n"
         "    @Slot()\n"
         "    def show_readiness(self):\n"
         "        \"\"\"[fusion-sync] 测量就绪检查：如实列出未完成项，不因连接成功就放行。\"\"\"\n"
         "        try:\n"
         "            from .measurement_readiness import readiness_rows, ReadinessDialog\n"
         "            from .devices_view import _registered_backends\n"
         "        except ImportError as error:\n"
         "            QMessageBox.warning(self, '测量就绪检查不可用', str(error))\n"
         "            return\n"
         "        originals_kept = bool(self.paths) and all(Path(path).is_file() for path in self.paths)\n"
         "        group_done = bool(self.paths) and all(item is not None for item in self.results)\n"
         "        rows = readiness_rows(_registered_backends, originals_kept and group_done,\n"
         "                              bool(self.confirmed_targets()))\n"
         "        self.log('打开测量就绪检查：未完成的标定项不会被隐藏，发送测量任务保持禁用。')\n"
         "        ReadinessDialog(rows, self).exec()\n"
         "\n"
         "    def log(self, message):\n",
         "def show_readiness(self):"),
    ]
    applied, skipped, missing = [], [], []
    for entry in edits:
        old, new = entry[0], entry[1]
        marker = entry[2] if len(entry) > 2 else None
        if marker and marker in text:
            continue
        if new in text:
            skipped.append(old.strip().splitlines()[0][:26])
            continue
        if old in text:
            text = text.replace(old, new, 1)
            applied.append(old.strip().splitlines()[0][:26])
        else:
            missing.append(old.strip().splitlines()[0][:26])
    if not applied:
        return "未匹配: " + "; ".join(missing[:4])
    shutil.copy2(f, f.with_suffix(".py.bak"))
    f.write_text(text, encoding="utf-8")
    out = ["已改 {} 处（接入测量就绪检查 + 可勾选测量孔）".format(len(applied))]
    if skipped:
        out.append("已是最新: {}".format(len(skipped)))
    if missing:
        out.append("未匹配: " + "; ".join(missing[:4]))
    return "；".join(out)


def patch_camera_sync(engine: Path) -> str:
    """[camera-sync 2026-10-08] 接上 Orbbec Gemini 335Le 工业相机：

    * ``devices_view`` 注册真实相机驱动（没装 OrbbecSDK 时保持"未接入"，不假装）；
    * 主界面加「用工业相机拍照」按钮：取一帧 → 无损留样（capture_archive）→ 直接进工作区；
    * 「测量就绪检查」里的"本次原图留样"改为以真实留样为准。
    """
    devices = engine / "inspection_gui" / "devices_view.py"
    gui = engine / "inspection_gui" / "gui.py"
    if not devices.is_file() or not gui.is_file():
        return "找不到 devices_view.py 或 gui.py"
    applied, missing = [], []

    devices_text = devices.read_text(encoding="utf-8")
    old = "_registered_backends['robot_b'] = DobotFeedback()"
    new = ("_registered_backends['robot_b'] = DobotFeedback()\n"
           "# [camera-sync] 真实相机驱动：Orbbec Gemini 335Le（USB-Ethernet）。\n"
           "# 没有安装 OrbbecSDK 时保持“未接入”，绝不假装已连接。\n"
           "try:\n"
           "    from .orbbec_camera import OrbbecCamera\n"
           "    _registered_backends['camera'] = OrbbecCamera()\n"
           "except (ImportError, OSError):\n"
           "    pass")
    if new not in devices_text and old in devices_text:
        shutil.copy2(devices, devices.with_suffix(".py.bak"))
        devices.write_text(devices_text.replace(old, new, 1), encoding="utf-8")
        applied.append("devices_view: 注册相机驱动")
    elif new not in devices_text:
        missing.append("devices_view: _registered_backends['robot_b']")

    original = gui.read_text(encoding="utf-8")
    text = original
    edits = [
        ("        self.btn_select = QPushButton('① 选择照片')\n"
         "        self.btn_select.setObjectName('primary')\n",
         "        self.btn_select = QPushButton('① 选择照片')\n"
         "        self.btn_select.setObjectName('primary')\n"
         "        # [camera-sync] 直接从工业相机拍一张\n"
         "        self.btn_capture = QPushButton('用工业相机拍照')\n"
         "        self.btn_capture.setToolTip('从 Orbbec Gemini 335Le 取一帧彩色图，无损留样后直接放进工作区。')\n"),
        ("        actions.setMinimumHeight(176)", "        actions.setMinimumHeight(222)"),
        ("        for _button in (self.btn_select, self.btn_detect, self.btn_send):\n",
         "        # [camera-sync] 拍照按钮排在“选择照片”后面\n"
         "        for _button in (self.btn_select, self.btn_capture, self.btn_detect, self.btn_send):\n"),
        ("        self.btn_select.clicked.connect(self.select_images)\n",
         "        self.btn_select.clicked.connect(self.select_images)\n"
         "        self.btn_capture.clicked.connect(self.capture_from_camera)   # [camera-sync]\n"),
        ("        originals_kept = bool(self.paths) and all(Path(path).is_file() for path in self.paths)\n"
         "        group_done = bool(self.paths) and all(item is not None for item in self.results)\n"
         "        rows = readiness_rows(_registered_backends, originals_kept and group_done,\n"
         "                              bool(self.confirmed_targets()))",
         "        # [camera-sync] “本次原图留样”以真实留样为准（capture_archive 写的无损原图 + 同批 JSON）\n"
         "        has_capture = bool(getattr(self, 'last_capture', None))\n"
         "        rows = readiness_rows(_registered_backends, has_capture,\n"
         "                              bool(self.confirmed_targets()))"),
        ("    def log(self, message):\n",
         "    def camera_settings(self):\n"
         "        \"\"\"[camera-sync] 读「设备连接 → 工业相机」里保存的配置。\"\"\"\n"
         "        try:\n"
         "            from .devices_view import _load_settings, SETTINGS_PATH\n"
         "            settings, _warning = _load_settings(SETTINGS_PATH)\n"
         "            return settings.get('camera', {})\n"
         "        except (ImportError, OSError, ValueError):\n"
         "            return {}\n"
         "\n"
         "    @Slot()\n"
         "    def capture_from_camera(self):\n"
         "        \"\"\"[camera-sync] 用工业相机拍一张：无损留样后直接进入检测工作区。\"\"\"\n"
         "        try:\n"
         "            from .capture_archive import save_capture\n"
         "            from .devices_view import _registered_backends\n"
         "        except ImportError as error:\n"
         "            QMessageBox.warning(self, '相机拍照不可用', str(error))\n"
         "            return\n"
         "        camera = _registered_backends.get('camera')\n"
         "        if camera is None:\n"
         "            QMessageBox.information(self, '相机未接入',\n"
         "                                    '本机没有可用的 Orbbec 相机驱动。\\n'\n"
         "                                    '请确认已安装 OrbbecSDK，并且相机 USB 已插好。')\n"
         "            return\n"
         "        self.set_status('正在从工业相机拍照…', '#a86613')\n"
         "        QApplication.processEvents()\n"
         "        frame = None\n"
         "        try:\n"
         "            if not camera.is_connected() and not camera.connect(self.camera_settings()):\n"
         "                raise RuntimeError(camera.last_error or '相机连接失败。')\n"
         "            if not camera.start():\n"
         "                raise RuntimeError(camera.last_error or '相机取流失败。')\n"
         "            for _attempt in range(30):\n"
         "                frame = camera.get_frame()\n"
         "                if frame is not None:\n"
         "                    break\n"
         "            if frame is None:\n"
         "                raise RuntimeError('相机没有返回图像。')\n"
         "        except Exception as error:      # noqa: BLE001 - 相机异常一律如实报出\n"
         "            self.set_status('相机拍照失败', '#bf3e35')\n"
         "            self.log(f'相机拍照失败：{error}')\n"
         "            QMessageBox.warning(self, '相机拍照失败', str(error))\n"
         "            return\n"
         "        finally:\n"
         "            try:\n"
         "                camera.stop()\n"
         "            except Exception:\n"
         "                pass\n"
         "        try:\n"
         "            photo, info, data = save_capture(BASE / 'captures', frame, metadata={\n"
         "                'source': 'Orbbec Gemini 335Le（工业相机）',\n"
         "                'device_serial': getattr(camera, 'device_serial', '')\n"
         "                                 or getattr(camera, 'device_uid', ''),\n"
         "                'profile': getattr(camera, 'profile', ''),\n"
         "                'note': '软件内「用工业相机拍照」采集；原图无损保存，不覆盖。',\n"
         "            })\n"
         "        except OSError as error:\n"
         "            self.set_status('原图留样失败', '#bf3e35')\n"
         "            self.log(f'原图留样失败：{error}')\n"
         "            QMessageBox.warning(self, '原图留样失败', str(error))\n"
         "            return\n"
         "        self.last_capture = {'photo': str(photo), 'info': str(info)}\n"
         "        self.set_images([str(photo)])\n"
         "        self.set_status('相机拍照完成')\n"
         "        self.log(f'相机拍照完成：{photo.name}（{data[\"width_px\"]}×{data[\"height_px\"]}，'\n"
         "                 f'SHA256 {data[\"image_sha256\"][:12]}…）已放入工作区，可点「② 开始检测」。')\n"
         "\n"
         "    def log(self, message):\n",
         "def capture_from_camera(self):"),
    ]
    for entry in edits:
        old, new = entry[0], entry[1]
        marker = entry[2] if len(entry) > 2 else None
        if marker and marker in text:
            # 方法已经存在：绝不再插一遍（插重复会让软件行为不确定）
            continue
        if new in text:
            continue
        if old in text:
            text = text.replace(old, new, 1)
            applied.append(old.strip().splitlines()[0][:26])
        else:
            missing.append(old.strip().splitlines()[0][:26])
    if text != original:
        shutil.copy2(gui, gui.with_suffix(".py.bak"))
        gui.write_text(text, encoding="utf-8")
    if not applied:
        if not missing:
            return "已是最新（无需修改）"
        return "未匹配: " + "; ".join(missing[:4])
    out = ["已改 {} 处（接入工业相机拍照）".format(len(applied))]
    if missing:
        out.append("未匹配: " + "; ".join(missing[:4]))
    return "；".join(out)


def deploy_app_addons(engine: Path) -> str:
    """把 ``scripts/app_addons/`` 里的本机扩展模块同步进软件目录。

    这些模块（Orbbec 相机驱动、实时预览窗口）是**我们自己加的**，
    放在仓库里做版本管理，软件目录只是部署位置；按内容比较，幂等。
    """
    source = Path(__file__).resolve().parent / "app_addons"
    target = engine / "inspection_gui"
    if not source.is_dir():
        return "没有 scripts/app_addons 目录"
    if not target.is_dir():
        return "找不到 inspection_gui 目录"
    copied, kept = [], []
    for item in sorted(source.glob("*.py")):
        destination = target / item.name
        data = item.read_bytes()
        if destination.is_file() and destination.read_bytes() == data:
            kept.append(item.name)
            continue
        if destination.is_file():
            shutil.copy2(destination, destination.with_suffix(".py.bak"))
        destination.write_bytes(data)
        copied.append(item.name)
    out = []
    if copied:
        out.append("已更新: " + ", ".join(copied))
    if kept:
        out.append("已是最新: " + ", ".join(kept))
    return "；".join(out) or "无需修改"


def patch_camera_preview(engine: Path) -> str:
    """[camera-sync] 主界面加「相机实时预览」按钮，并接上预览窗口。"""
    f = engine / "inspection_gui" / "gui.py"
    if not f.is_file():
        return "找不到 gui.py"
    original = f.read_text(encoding="utf-8")
    text = original
    edits = [
        ("        self.btn_readiness.setToolTip('列出相机 / 机械臂 / 标定 / 测孔清单的完成情况，未完成的项不会隐藏。')\n"
         "        for _index, _button in enumerate((self.btn_devices, self.btn_records,\n"
         "                                          self.btn_models, self.btn_simulation,\n"
         "                                          self.btn_last_batch, self.btn_results,\n"
         "                                          self.btn_readiness)):\n",
         "        self.btn_readiness.setToolTip('列出相机 / 机械臂 / 标定 / 测孔清单的完成情况，未完成的项不会隐藏。')\n"
         "        self.btn_preview = QPushButton('相机实时预览')      # [camera-sync]\n"
         "        self.btn_preview.setToolTip('打开工业相机实时画面；预览本身不写文件，抓拍才做无损留样。')\n"
         "        for _index, _button in enumerate((self.btn_devices, self.btn_records,\n"
         "                                          self.btn_models, self.btn_simulation,\n"
         "                                          self.btn_last_batch, self.btn_results,\n"
         "                                          self.btn_readiness, self.btn_preview)):\n"),
        ("        self.btn_readiness.clicked.connect(self.show_readiness)   # [fusion-sync]\n",
         "        self.btn_readiness.clicked.connect(self.show_readiness)   # [fusion-sync]\n"
         "        self.btn_preview.clicked.connect(self.show_camera_preview)   # [camera-sync]\n"),
        # 实时预览正在取流时，主界面的「用工业相机拍照」不要再动相机，
        # 直接交给预览窗口抓拍，避免两条取流互相打断。
        ("        camera = _registered_backends.get('camera')\n"
         "        if camera is None:\n"
         "            QMessageBox.information(self, '相机未接入',\n"
         "                                    '本机没有可用的 Orbbec 相机驱动。\\n'\n"
         "                                    '请确认已安装 OrbbecSDK，并且相机 USB 已插好。')\n"
         "            return\n",
         "        camera = _registered_backends.get('camera')\n"
         "        if camera is None:\n"
         "            QMessageBox.information(self, '相机未接入',\n"
         "                                    '本机没有可用的 Orbbec 相机驱动。\\n'\n"
         "                                    '请确认已安装 OrbbecSDK，并且相机 USB 已插好。')\n"
         "            return\n"
         "        preview = getattr(self, 'preview_dialog', None)   # [camera-sync] 实时预览正在占用相机\n"
         "        if preview is not None and getattr(preview, 'worker', None) is not None:\n"
         "            preview.grab(False)\n"
         "            return\n",
         "实时预览正在占用相机"),
        ("        self.bridge.detach()\n",
         "        preview = getattr(self, 'preview_dialog', None)\n"
         "        if preview is not None:      # [camera-sync] 先停取流线程，避免退出时线程还在跑\n"
         "            try:\n"
         "                preview.stop_preview()\n"
         "            except RuntimeError:\n"
         "                pass\n"
         "        self.bridge.detach()\n"),
        ("    def log(self, message):\n",
         "    @Slot()\n"
         "    def show_camera_preview(self):\n"
         "        \"\"\"[camera-sync] 工业相机实时预览（取流线程复用朋友分支的 vision_workspace）。\"\"\"\n"
         "        try:\n"
         "            from .camera_preview import CameraPreviewDialog\n"
         "        except ImportError as error:\n"
         "            QMessageBox.warning(self, '实时预览不可用', str(error))\n"
         "            return\n"
         "        dialog = getattr(self, 'preview_dialog', None)\n"
         "        try:\n"
         "            if dialog is None:\n"
         "                raise RuntimeError('create')\n"
         "            dialog.show()\n"
         "            dialog.raise_()\n"
         "            dialog.activateWindow()\n"
         "        except RuntimeError:\n"
         "            self.preview_dialog = CameraPreviewDialog(self)\n"
         "            self.preview_dialog.show()\n"
         "\n"
         "    def log(self, message):\n",
         "def show_camera_preview(self):"),
    ]
    applied, missing = [], []
    for entry in edits:
        old, new = entry[0], entry[1]
        marker = entry[2] if len(entry) > 2 else None
        if marker and marker in text:
            continue
        if new in text:
            continue
        if old in text:
            text = text.replace(old, new, 1)
            applied.append(old.strip().splitlines()[0][:26])
        else:
            missing.append(old.strip().splitlines()[0][:26])
    if text != original:
        shutil.copy2(f, f.with_suffix(".py.bak"))
        f.write_text(text, encoding="utf-8")
    if not applied:
        if not missing:
            return "已是最新（无需修改）"
        return "未匹配: " + "; ".join(missing[:4])
    out = ["已改 {} 处（实时预览窗口）".format(len(applied))]
    if missing:
        out.append("未匹配: " + "; ".join(missing[:4]))
    return "；".join(out)


def patch_device_state_sync(engine: Path) -> str:
    """[device-state] 让状态栏显示**真实**连接状态。

    以前只有「设备连接」窗口里点按钮才会刷新状态栏；实时预览 / 拍照是直接调用
    驱动连接的，状态栏不知道，于是明明相机在出图，底部还写着"未连接"。
    这里加一个定时器，按驱动的 ``is_connected()`` 真值刷新状态栏，
    并同步设备窗口里那一页的状态，避免两处显示互相矛盾。
    """
    f = engine / "inspection_gui" / "gui.py"
    if not f.is_file():
        return "找不到 gui.py"
    original = f.read_text(encoding="utf-8")
    text = original
    edits = [
        # 1) 把「状态栏文字」抽成独立方法，并带上真实型号
        ("    def device_status_changed(self, device, connected, note):\n"
         "        self.device_states[device] = connected\n"
         "        names = {'camera':'工业相机', 'robot_a':'拍照机械臂 A', 'robot_b':'测量机械臂 B'}\n"
         "        self.connection_line.setText('　｜　'.join(\n"
         "            names[key]+('：只读反馈已连接' if key == 'robot_b' and self.device_states.get(key)\n"
         "                        else '：已连接' if self.device_states.get(key) else '：未连接')\n"
         "            for key in names))\n"
         "        self.log(names[device]+'：'+note)\n",
         "    def device_status_changed(self, device, connected, note):\n"
         "        self.device_states[device] = connected\n"
         "        self.update_connection_line()\n"
         "        names = {'camera':'工业相机', 'robot_a':'拍照机械臂 A', 'robot_b':'测量机械臂 B'}\n"
         "        self.log(names[device]+'：'+note)\n"
         "\n"
         "    def _device_backends(self):\n"
         "        \"\"\"[device-state] 当前注册的设备驱动。\"\"\"\n"
         "        try:\n"
         "            from .devices_view import _registered_backends\n"
         "        except ImportError:\n"
         "            return {}\n"
         "        return _registered_backends\n"
         "\n"
         "    def update_connection_line(self):\n"
         "        \"\"\"[device-state] 状态栏只反映实际连接状态，显示真实型号。\"\"\"\n"
         "        names = {'camera': '工业相机', 'robot_a': '拍照机械臂 A', 'robot_b': '测量机械臂 B'}\n"
         "        backends = self._device_backends()\n"
         "        parts = []\n"
         "        for key, title in names.items():\n"
         "            connected = bool(self.device_states.get(key))\n"
         "            suffix = ''\n"
         "            if connected:\n"
         "                backend = backends.get(key)\n"
         "                model = (getattr(backend, 'device_name', '') or\n"
         "                         getattr(backend, 'device_serial', '')) if backend is not None else ''\n"
         "                if model:\n"
         "                    suffix = f'（{model}）'\n"
         "            state = '只读反馈已连接' if (key == 'robot_b' and connected) else ('已连接' if connected else '未连接')\n"
         "            parts.append(f'{title}：{state}{suffix}')\n"
         "        self.connection_line.setText('　｜　'.join(parts))\n"
         "\n"
         "    def refresh_device_states(self):\n"
         "        \"\"\"[device-state] 按驱动真实状态刷新状态栏与设备窗口（谁连上就显示谁）。\"\"\"\n"
         "        backends = self._device_backends()\n"
         "        if not backends:\n"
         "            return\n"
         "        changed = False\n"
         "        for key in ('camera', 'robot_a', 'robot_b'):\n"
         "            backend = backends.get(key)\n"
         "            try:\n"
         "                connected = bool(backend is not None and backend.is_connected())\n"
         "            except Exception:      # noqa: BLE001 - 驱动异常不能把界面弄崩\n"
         "                connected = False\n"
         "            if bool(self.device_states.get(key, False)) != connected:\n"
         "                self.device_states[key] = connected\n"
         "                changed = True\n"
         "                self.sync_device_dialog(key, connected)\n"
         "        if changed:\n"
         "            self.update_connection_line()\n"
         "\n"
         "    def sync_device_dialog(self, device, connected):\n"
         "        \"\"\"[device-state] 设备窗口那一页的状态跟着变，避免两处显示矛盾。\"\"\"\n"
         "        dialog = getattr(self, '_inspection_devices_dialog', None)\n"
         "        if dialog is None:\n"
         "            return\n"
         "        try:\n"
         "            page = dialog.pages.get(device)\n"
         "            if page is None:\n"
         "                return\n"
         "            page._set_status(bool(connected),\n"
         "                             '连接已建立。' if connected else '连接已断开。')\n"
         "        except (RuntimeError, AttributeError):\n"
         "            pass\n",
         "def update_connection_line"),
        # 2) 启动定时刷新
        ("        QShortcut(QKeySequence('Ctrl+O'), self, activated=self.select_images)\n",
         "        # [device-state] 定时用驱动真值刷新状态栏，不再依赖“上一次点击”\n"
         "        self.device_timer = QTimer(self)\n"
         "        self.device_timer.setInterval(1500)\n"
         "        self.device_timer.timeout.connect(self.refresh_device_states)\n"
         "        self.device_timer.start()\n"
         "        self.refresh_device_states()\n"
         "        QShortcut(QKeySequence('Ctrl+O'), self, activated=self.select_images)\n",
         "self.device_timer.setInterval(1500)"),
        # 3) 设备窗口那一页：只有和真实状态不一致时才改写，避免把"尚未接入"说成"已断开"
        ("            page = dialog.pages.get(device)\n"
         "            if page is None:\n"
         "                return\n"
         "            page._set_status(bool(connected),\n"
         "                             '连接已建立。' if connected else '连接已断开。')\n",
         "            page = dialog.pages.get(device)\n"
         "            if page is None:\n"
         "                return\n"
         "            if ('已连接' in page.status.text()) == bool(connected):\n"
         "                return\n"
         "            page._set_status(bool(connected),\n"
         "                             '连接已建立。' if connected else '连接已断开。')\n",
         "if ('已连接' in page.status.text()) == bool(connected):"),
        # 4) 打开设备窗口时先对齐一次真实状态（否则后打开的窗口永远停在"未连接"）
        ("    def show_device_panel(self):\n"
         "        dialog = show_devices(self)\n"
         "        if not getattr(dialog, '_main_status_bound', False):\n"
         "            dialog.connection_status_changed.connect(self.device_status_changed)\n"
         "            dialog._main_status_bound = True\n",
         "    def show_device_panel(self):\n"
         "        dialog = show_devices(self)\n"
         "        if not getattr(dialog, '_main_status_bound', False):\n"
         "            dialog.connection_status_changed.connect(self.device_status_changed)\n"
         "            dialog._main_status_bound = True\n"
         "        # [device-state] 打开时按驱动真值对齐，避免窗口里和状态栏说法不一致\n"
         "        self.refresh_device_states()\n"
         "        for _key in ('camera', 'robot_a', 'robot_b'):\n"
         "            self.sync_device_dialog(_key, bool(self.device_states.get(_key)))\n",
         "self.sync_device_dialog(_key, bool(self.device_states.get(_key)))"),
    ]
    applied, missing = [], []
    for entry in edits:
        old, new = entry[0], entry[1]
        marker = entry[2] if len(entry) > 2 else None
        if marker and marker in text:
            continue
        if new in text:
            continue
        if old in text:
            text = text.replace(old, new, 1)
            applied.append(old.strip().splitlines()[0][:26])
        else:
            missing.append(old.strip().splitlines()[0][:26])
    if text != original:
        shutil.copy2(f, f.with_suffix(".py.bak"))
        f.write_text(text, encoding="utf-8")
    if not applied:
        if not missing:
            return "已是最新（无需修改）"
        return "未匹配: " + "; ".join(missing[:4])
    out = ["已改 {} 处（设备状态自动刷新）".format(len(applied))]
    if missing:
        out.append("未匹配: " + "; ".join(missing[:4]))
    return "；".join(out)


def patch_auto_connect(engine: Path) -> str:
    """[camera-sync] 软件启动后在**后台**自动连一次相机。

    原则不变：连上就显示已连接（含型号），连不上就照实显示未连接并写清原因，
    绝不假装连接成功；连接过程不阻塞界面（放到后台线程里做）。
    """
    f = engine / "inspection_gui" / "gui.py"
    if not f.is_file():
        return "找不到 gui.py"
    original = f.read_text(encoding="utf-8")
    text = original
    edits = [
        ("import json\nfrom pathlib import Path\n",
         "import json\nimport threading\nfrom pathlib import Path\n",
         "import threading"),
        ("        QShortcut(QKeySequence('Ctrl+O'), self, activated=self.select_images)\n",
         "        # [camera-sync] 启动后延迟一点在后台自动连一次相机（不阻塞界面）\n"
         "        self._auto_connect_state = {'done': False, 'ok': False, 'error': ''}\n"
         "        self._auto_connect_checks = 0\n"
         "        QTimer.singleShot(1200, self.auto_connect_camera)\n"
         "        QShortcut(QKeySequence('Ctrl+O'), self, activated=self.select_images)\n",
         "self._auto_connect_state"),
        ("    def log(self, message):\n",
         "    def auto_connect_camera(self):\n"
         "        \"\"\"[camera-sync] 后台连一次相机；连不上只记录原因，不改任何显示状态。\"\"\"\n"
         "        backend = self._device_backends().get('camera')\n"
         "        if backend is None:\n"
         "            self.log('未发现 Orbbec 相机驱动（未安装 OrbbecSDK），相机保持未连接。')\n"
         "            return\n"
         "        try:\n"
         "            if backend.is_connected():\n"
         "                self.refresh_device_states()\n"
         "                return\n"
         "        except Exception:      # noqa: BLE001 - 驱动异常不能影响启动\n"
         "            pass\n"
         "        state = self._auto_connect_state\n"
         "        settings = self.camera_settings()\n"
         "\n"
         "        def worker():\n"
         "            try:\n"
         "                state['ok'] = bool(backend.connect(settings)) and bool(backend.is_connected())\n"
         "                state['error'] = '' if state['ok'] else (getattr(backend, 'last_error', '') or '未知原因')\n"
         "            except Exception as error:      # noqa: BLE001\n"
         "                state['ok'], state['error'] = False, str(error)\n"
         "            state['done'] = True\n"
         "\n"
         "        threading.Thread(target=worker, daemon=True, name='camera-auto-connect').start()\n"
         "        QTimer.singleShot(3000, self.report_auto_connect)\n"
         "\n"
         "    def report_auto_connect(self):\n"
         "        \"\"\"[camera-sync] 把自动连接的结果如实写进运行日志。\"\"\"\n"
         "        state = getattr(self, '_auto_connect_state', None)\n"
         "        if state is None:\n"
         "            return\n"
         "        if not state.get('done'):\n"
         "            self._auto_connect_checks = getattr(self, '_auto_connect_checks', 0) + 1\n"
         "            if self._auto_connect_checks <= 5:\n"
         "                QTimer.singleShot(3000, self.report_auto_connect)\n"
         "            else:\n"
         "                self.log('相机自动连接仍在等待设备响应，可点「相机实时预览」重试。')\n"
         "            return\n"
         "        backend = self._device_backends().get('camera')\n"
         "        if state['ok']:\n"
         "            name = (getattr(backend, 'device_name', '') or '相机') if backend is not None else '相机'\n"
         "            serial = getattr(backend, 'device_serial', '') if backend is not None else ''\n"
         "            self.log('相机已自动连接：' + name + (f'（序列号 {serial}）' if serial else ''))\n"
         "        else:\n"
         "            self.log('相机自动连接未成功：' + (state['error'] or '未知原因')\n"
         "                     + '；可点「相机实时预览」或「设备连接 → 连接设备」重试。')\n"
         "        self.refresh_device_states()\n"
         "\n"
         "    def log(self, message):\n",
         "def report_auto_connect(self):"),
    ]
    applied, missing = [], []
    for entry in edits:
        old, new = entry[0], entry[1]
        marker = entry[2] if len(entry) > 2 else None
        if marker and marker in text:
            continue
        if new in text:
            continue
        if old in text:
            text = text.replace(old, new, 1)
            applied.append(old.strip().splitlines()[0][:26])
        else:
            missing.append(old.strip().splitlines()[0][:26])
    if text != original:
        shutil.copy2(f, f.with_suffix(".py.bak"))
        f.write_text(text, encoding="utf-8")
    if not applied:
        if not missing:
            return "已是最新（无需修改）"
        return "未匹配: " + "; ".join(missing[:4])
    out = ["已改 {} 处（启动自动连相机）".format(len(applied))]
    if missing:
        out.append("未匹配: " + "; ".join(missing[:4]))
    return "；".join(out)


def patch_records_data(engine: Path) -> str:
    """[records-tools] 实验记录数据层：补上"组 id / 组号 / 报告路径"，并支持删除整组。

    界面要能做「载入到工作区」「打开检测报告」「删除这一组」，就必须知道每条记录
    属于哪一组、报告文件在哪。这里只**增加字段和方法**，不动原有语义。
    """
    f = engine / "experiment_records.py"
    if not f.is_file():
        return "找不到 experiment_records.py"
    original = f.read_text(encoding="utf-8")
    text = original
    edits = [
        ("                       'model': report.get('model', group['model']), 'image': report['image'],\n"
         "                       'result_image': report.get('result_image', ''),\n"
         "                       'part_model': report.get('part_model') or ''}\n",
         "                       'model': report.get('model', group['model']), 'image': report['image'],\n"
         "                       'result_image': report.get('result_image', ''),\n"
         "                       'result_csv': report.get('result_csv', ''),\n"
         "                       'group_id': group.get('id', ''),\n"
         "                       'group_number': group.get('number', ''),\n"
         "                       'part_model': report.get('part_model') or ''}\n",
         "'group_id': group.get('id', '')"),
        ("    def export(self, destination):\n",
         "    def reports_of(self, group_id):\n"
         "        \"\"\"[records-tools] 取某一组的原始 reports（用于载入到工作区）。\"\"\"\n"
         "        for group in self.groups:\n"
         "            if group.get('id') == group_id:\n"
         "                return list(group.get('reports', []))\n"
         "        return []\n"
         "\n"
         "    def delete_group(self, group_id):\n"
         "        \"\"\"[records-tools] 删除一整组实验记录；返回 (是否删除, 说明)。\n"
         "\n"
         "        只删记录本身，不动磁盘上的原图 / 结果图 / 报告文件。\n"
         "        \"\"\"\n"
         "        for index, group in enumerate(self.groups):\n"
         "            if group.get('id') == group_id:\n"
         "                number = group.get('number', '?')\n"
         "                count = len(group.get('reports', []))\n"
         "                del self.groups[index]\n"
         "                self.save()\n"
         "                return True, f'第{number}组（{count} 张）已从实验记录中删除；原图与结果文件未删除。'\n"
         "        return False, '没有找到这一组，可能已经被删除。'\n"
         "\n"
         "    def export(self, destination):\n",
         "def delete_group(self, group_id):"),
    ]
    applied, missing = [], []
    for entry in edits:
        old, new = entry[0], entry[1]
        marker = entry[2] if len(entry) > 2 else None
        if marker and marker in text:
            continue
        if new in text:
            continue
        if old in text:
            text = text.replace(old, new, 1)
            applied.append(old.strip().splitlines()[0][:26])
        else:
            missing.append(old.strip().splitlines()[0][:26])
    if text != original:
        shutil.copy2(f, f.with_suffix(".py.bak"))
        f.write_text(text, encoding="utf-8")
    if not applied:
        if not missing:
            return "已是最新（无需修改）"
        return "未匹配: " + "; ".join(missing[:4])
    return "已改 {} 处（记录数据层）".format(len(applied))


def patch_records_tools(engine: Path) -> str:
    """[records-tools] 实验记录窗口：合并"打开历史批次"的能力，并支持删除与看图。

    新增按钮：载入到工作区 / 打开原图 / 打开结果图 / 打开检测报告 / 删除这一组。
    这样「打开历史批次」就多余了，主界面那个按钮会一并去掉。
    """
    f = engine / "inspection_gui" / "records_view.py"
    if not f.is_file():
        return "找不到 records_view.py"
    original = f.read_text(encoding="utf-8")
    text = original
    edits = [
        ("        folder_button = QPushButton('打开结果文件夹')\n"
         "        folder_button.clicked.connect(self.open_results_folder)\n"
         "        tools.addWidget(folder_button)\n"
         "        layout.addLayout(tools)\n",
         "        folder_button = QPushButton('打开结果文件夹')\n"
         "        folder_button.clicked.connect(self.open_results_folder)\n"
         "        tools.addWidget(folder_button)\n"
         "        # [records-tools] 载入 / 看图 / 报告 / 删除（合并了原来的「打开历史批次」）\n"
         "        load_button = QPushButton('载入到工作区')\n"
         "        load_button.setToolTip('把选中的这一组照片和检测结果载入主界面（不会重新检测、不会新增记录）')\n"
         "        load_button.clicked.connect(self.load_group)\n"
         "        tools.addWidget(load_button)\n"
         "        original_button = QPushButton('打开原图')\n"
         "        original_button.clicked.connect(lambda: self.open_field('image', '原图'))\n"
         "        tools.addWidget(original_button)\n"
         "        result_button = QPushButton('打开结果图')\n"
         "        result_button.clicked.connect(lambda: self.open_field('result_image', '结果图'))\n"
         "        tools.addWidget(result_button)\n"
         "        report_button = QPushButton('打开检测报告')\n"
         "        report_button.setToolTip('打开这一张图对应的检测报告（CSV，可用 Excel / WPS 打开）')\n"
         "        report_button.clicked.connect(lambda: self.open_field('result_csv', '检测报告'))\n"
         "        tools.addWidget(report_button)\n"
         "        delete_button = QPushButton('删除这一组')\n"
         "        delete_button.setToolTip('从实验记录里删除选中的整组（含该组所有照片的行），删除后无法撤销')\n"
         "        delete_button.clicked.connect(self.delete_group)\n"
         "        tools.addWidget(delete_button)\n"
         "        layout.addLayout(tools)\n",
         "delete_button = QPushButton('删除这一组')"),
        ('            "每批照片为一组，新实验追加保存。空白表示没有保留该孔。"\n'
         '            "孔号按图像位置排序；双击一行打开检测结果图片。"\n',
         '            "每批照片为一组，新实验追加保存。空白表示没有保留该孔。"\n'
         '            "孔号按图像位置排序。选中一行后可以：载入到工作区 / 打开原图 / 打开结果图 / 打开检测报告 / 删除这一组。"\n',
         "选中一行后可以：载入到工作区"),
        ("    @Slot(int, int)\n"
         "    def open_result(self, row_index: int, _column: int = 0) -> None:\n",
         "    def current_row(self):\n"
         "        \"\"\"[records-tools] 当前选中的那一行记录。\"\"\"\n"
         "        row = self.table.currentRow()\n"
         "        return self.rows[row] if 0 <= row < len(self.rows) else None\n"
         "\n"
         "    @Slot()\n"
         "    def open_field(self, key, label):\n"
         "        \"\"\"[records-tools] 打开这一行的原图 / 结果图 / 检测报告。\"\"\"\n"
         "        row = self.current_row()\n"
         "        if row is None:\n"
         "            QMessageBox.information(self, '请先选一行', '请先在表格里选中一张图片。')\n"
         "            return\n"
         "        path_text = row.get(key, '') or ''\n"
         "        if not path_text or not Path(path_text).is_file():\n"
         "            QMessageBox.information(self, label + '无法打开',\n"
         "                                    f'这条记录没有可用的{label}文件。\\n'\n"
         "                                    f'路径：{path_text or \"（记录里没有记录路径）\"}')\n"
         "            return\n"
         "        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path_text).resolve()))):\n"
         "            QMessageBox.warning(self, label + '无法打开', f'未能打开：\\n{path_text}')\n"
         "\n"
         "    @Slot()\n"
         "    def load_group(self):\n"
         "        \"\"\"[records-tools] 把选中的这一组载入主界面工作区（不重新检测）。\"\"\"\n"
         "        row = self.current_row()\n"
         "        if row is None:\n"
         "            QMessageBox.information(self, '请先选一行', '请先选中要载入的那一组里的任意一行。')\n"
         "            return\n"
         "        reports = self.records.reports_of(row.get('group_id', ''))\n"
         "        if not reports:\n"
         "            QMessageBox.information(self, '无法载入', '这一组里没有可显示的照片记录。')\n"
         "            return\n"
         "        main = self.parent()\n"
         "        if main is None or not hasattr(main, 'load_reports'):\n"
         "            QMessageBox.information(self, '无法载入', '当前主界面不支持载入，请用主界面的「选择照片」。')\n"
         "            return\n"
         "        main.load_reports(reports)\n"
         "        if hasattr(main, 'log'):\n"
         "            main.log(f'已从实验记录载入第{row.get(\"group_number\", \"?\")}组：{len(reports)} 张'\n"
         "                     '（未重新检测、未新增记录）。')\n"
         "\n"
         "    @Slot()\n"
         "    def delete_group(self):\n"
         "        \"\"\"[records-tools] 删除选中的整组记录（二次确认）。\"\"\"\n"
         "        row = self.current_row()\n"
         "        if row is None:\n"
         "            QMessageBox.information(self, '请先选一行', '请先选中要删除的那一组里的任意一行。')\n"
         "            return\n"
         "        number = row.get('group_number', '?')\n"
         "        confirm = QMessageBox.question(\n"
         "            self, '确认删除',\n"
         "            f'确定要从实验记录中删除「第{number}组」吗？\\n\\n'\n"
         "            '该组的全部照片记录都会被删除，删除后无法撤销。\\n'\n"
         "            '（磁盘上的原图、结果图、检测报告文件不会被删除）',\n"
         "            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,\n"
         "            QMessageBox.StandardButton.No)\n"
         "        if confirm != QMessageBox.StandardButton.Yes:\n"
         "            return\n"
         "        ok, message = self.records.delete_group(row.get('group_id', ''))\n"
         "        self.refresh()\n"
         "        QMessageBox.information(self, '删除完成' if ok else '未删除', message)\n"
         "\n"
         "    @Slot(int, int)\n"
         "    def open_result(self, row_index: int, _column: int = 0) -> None:\n",
         "def delete_group(self):"),
    ]
    applied, missing = [], []
    for entry in edits:
        old, new = entry[0], entry[1]
        marker = entry[2] if len(entry) > 2 else None
        if marker and marker in text:
            continue
        if new in text:
            continue
        if old in text:
            text = text.replace(old, new, 1)
            applied.append(old.strip().splitlines()[0][:26])
        else:
            missing.append(old.strip().splitlines()[0][:26])
    if text != original:
        shutil.copy2(f, f.with_suffix(".py.bak"))
        f.write_text(text, encoding="utf-8")
    if not applied:
        if not missing:
            return "已是最新（无需修改）"
        return "未匹配: " + "; ".join(missing[:4])
    out = ["已改 {} 处（实验记录工具）".format(len(applied))]
    if missing:
        out.append("未匹配: " + "; ".join(missing[:4]))
    return "；".join(out)


def patch_canvas_live(engine: Path) -> str:
    """[canvas-live] 视觉检测区做成"能实时看、能抓拍、能点孔"的主工作区。

    * 「相机实时画面」开关 + 「抓拍」按钮直接放在检测区工具栏；
    * 直接点图片上的孔 = 勾选/取消"本次要测量的孔"（用朋友的 pick_hole 命中判断）；
    * 「打开历史批次」按钮去掉——它的能力已经并进「实验记录 → 载入到工作区」。
    """
    f = engine / "inspection_gui" / "gui.py"
    if not f.is_file():
        return "找不到 gui.py"
    original = f.read_text(encoding="utf-8")
    text = original
    methods = (
        "    @Slot(bool)\n"
        "    def toggle_live_preview(self, on):\n"
        "        \"\"\"[canvas-live] 视觉检测区显示/关闭工业相机实时画面。\"\"\"\n"
        "        if on:\n"
        "            if self.batch_running or self.bridge.busy:\n"
        "                self.chk_live.setChecked(False)\n"
        "                QMessageBox.information(self, '正在忙', '检测或训练正在进行，先等它结束再开实时画面。')\n"
        "                return\n"
        "            backend = self._device_backends().get('camera')\n"
        "            if backend is None:\n"
        "                self.chk_live.setChecked(False)\n"
        "                QMessageBox.information(self, '相机未接入',\n"
        "                                        '本机没有可用的 Orbbec 相机驱动。\\n'\n"
        "                                        '请确认已安装 OrbbecSDK，并且相机 USB 已插好。')\n"
        "                return\n"
        "            self.set_status('正在连接相机…', '#a86613')\n"
        "            QApplication.processEvents()\n"
        "            try:\n"
        "                if not backend.is_connected() and not backend.connect(self.camera_settings()):\n"
        "                    raise RuntimeError(backend.last_error or '相机连接失败。')\n"
        "            except Exception as error:      # noqa: BLE001 - 如实报出\n"
        "                self.chk_live.setChecked(False)\n"
        "                self.set_status('相机连接失败', '#bf3e35')\n"
        "                self.log('实时画面启动失败：' + str(error))\n"
        "                QMessageBox.warning(self, '实时画面启动失败', str(error))\n"
        "                return\n"
        "            from .vision_workspace import CameraPreviewWorker\n"
        "            self.live_worker = CameraPreviewWorker(backend, self)\n"
        "            self.live_worker.failed.connect(self.live_preview_failed)\n"
        "            self.live_worker.start()\n"
        "            self.live_timer.start()\n"
        "            self.log('视觉检测区已切到相机实时画面（预览不写文件，点「抓拍」才留样）。')\n"
        "        else:\n"
        "            self.live_timer.stop()\n"
        "            worker, self.live_worker = getattr(self, 'live_worker', None), None\n"
        "            if worker is not None:\n"
        "                worker.stop()\n"
        "                worker.wait(5000)\n"
        "            self.live_frame = None\n"
        "            self.log('实时画面已关闭。')\n"
        "            self.render_view()\n"
        "        self.chk_fit.setEnabled(not on)\n"
        "        self.sld_zoom.setEnabled(not on)\n"
        "\n"
        "    def update_live_frame(self):\n"
        "        \"\"\"[canvas-live] 把最新一帧画到视觉检测区。\"\"\"\n"
        "        worker = getattr(self, 'live_worker', None)\n"
        "        if worker is None:\n"
        "            return\n"
        "        packet = worker.snapshot_packet() if hasattr(worker, 'snapshot_packet') else None\n"
        "        if not packet:\n"
        "            self.image_info.setText('等待相机图像…（若一直没有画面，检查相机网段是否为 192.168.1.100）')\n"
        "            return\n"
        "        frame = packet.get('frame')\n"
        "        if frame is None:\n"
        "            return\n"
        "        self.live_frame = frame\n"
        "        height, width = frame.shape[:2]\n"
        "        size = self.image_label.size()\n"
        "        scale = min(size.width() / width, size.height() / height, 1.0)\n"
        "        canvas = frame\n"
        "        if scale < 0.999:\n"
        "            canvas = cv2.resize(frame, (max(1, int(width * scale)), max(1, int(height * scale))),\n"
        "                                interpolation=cv2.INTER_AREA)\n"
        "        self.image_label.setPixmap(bgr_to_pixmap(canvas))\n"
        "        self.image_info.setText(f'相机实时画面 · {width}×{height}（未写文件）')\n"
        "\n"
        "    def live_preview_failed(self, message):\n"
        "        self.log('实时画面中断：' + message)\n"
        "        if getattr(self, 'chk_live', None) is not None and self.chk_live.isChecked():\n"
        "            self.chk_live.setChecked(False)\n"
        "\n"
        "    @Slot()\n"
        "    def snap_from_camera(self):\n"
        "        \"\"\"[canvas-live] 抓拍：无损留样后放进工作区（实时画面会被冻结成照片）。\"\"\"\n"
        "        live_on = getattr(self, 'chk_live', None) is not None and self.chk_live.isChecked()\n"
        "        frame = getattr(self, 'live_frame', None)\n"
        "        frame = frame.copy() if (live_on and frame is not None) else None\n"
        "        backend = self._device_backends().get('camera')\n"
        "        if frame is None:\n"
        "            if backend is None:\n"
        "                QMessageBox.information(self, '相机未接入', '本机没有可用的 Orbbec 相机驱动。')\n"
        "                return\n"
        "            self.set_status('正在从相机拍照…', '#a86613')\n"
        "            QApplication.processEvents()\n"
        "            try:\n"
        "                if not backend.is_connected() and not backend.connect(self.camera_settings()):\n"
        "                    raise RuntimeError(backend.last_error or '相机连接失败。')\n"
        "                if not backend.start():\n"
        "                    raise RuntimeError(backend.last_error or '相机取流失败。')\n"
        "                for _attempt in range(30):\n"
        "                    frame = backend.get_frame()\n"
        "                    if frame is not None:\n"
        "                        break\n"
        "                if frame is None:\n"
        "                    raise RuntimeError('相机没有返回图像。')\n"
        "            except Exception as error:      # noqa: BLE001\n"
        "                self.set_status('相机拍照失败', '#bf3e35')\n"
        "                self.log('相机拍照失败：' + str(error))\n"
        "                QMessageBox.warning(self, '相机拍照失败', str(error))\n"
        "                return\n"
        "            finally:\n"
        "                try:\n"
        "                    backend.stop()\n"
        "                except Exception:\n"
        "                    pass\n"
        "        if live_on:\n"
        "            self.chk_live.setChecked(False)      # 冻结成照片，避免立刻被实时画面覆盖\n"
        "        try:\n"
        "            photo, info, data = save_capture(BASE / 'captures', frame, metadata={\n"
        "                'source': 'Orbbec Gemini 335Le（工业相机 · 视觉检测区抓拍）',\n"
        "                'device_serial': getattr(backend, 'device_serial', '')\n"
        "                                 or getattr(backend, 'device_uid', ''),\n"
        "                'profile': getattr(backend, 'profile', ''),\n"
        "                'note': '视觉检测区抓拍；原图无损保存，不覆盖。',\n"
        "            })\n"
        "        except OSError as error:\n"
        "            self.set_status('原图留样失败', '#bf3e35')\n"
        "            self.log('原图留样失败：' + str(error))\n"
        "            QMessageBox.warning(self, '原图留样失败', str(error))\n"
        "            return\n"
        "        self.last_capture = {'photo': str(photo), 'info': str(info)}\n"
        "        self.set_images([str(photo)])\n"
        "        self.set_status('相机拍照完成')\n"
        "        self.log(f'相机抓拍：{photo.name}（{data[\"width_px\"]}×{data[\"height_px\"]}，'\n"
        "                 f'SHA256 {data[\"image_sha256\"][:12]}…）已放入工作区，可点「② 开始检测」。')\n"
        "\n"
        "    def canvas_clicked(self, x, y):\n"
        "        \"\"\"[canvas-live] 在图片上点一下 = 选中/取消这个孔（本次要测量的孔）。\"\"\"\n"
        "        if getattr(self, 'chk_live', None) is not None and self.chk_live.isChecked():\n"
        "            return\n"
        "        if self.display_photo is None:\n"
        "            return\n"
        "        holes = (self.current_result or {}).get('fitted_holes', [])\n"
        "        if not holes:\n"
        "            self.log('这张图还没有检测结果，先点「② 开始检测」，再点孔来选。')\n"
        "            return\n"
        "        from .vision_workspace import pick_hole\n"
        "        hole_id = pick_hole(x, y, getattr(self, 'display_mapping', None), holes)\n"
        "        if not hole_id:\n"
        "            return\n"
        "        if hole_id in self.measure_targets:\n"
        "            self.measure_targets.discard(hole_id)\n"
        "        else:\n"
        "            self.measure_targets.add(hole_id)\n"
        "        \"\"\"点孔后立刻把表格里的勾选状态同步过来\"\"\"\n"
        "        self.refresh_current_summary()\n"
        "        chosen = '、'.join(sorted(self.measure_targets)) if self.measure_targets else '（空）'\n"
        "        self.log(f'点选 {hole_id} → 本次测量清单：{chosen}')\n"
        "\n"
        "    def log(self, message):\n"
    )
    edits = [
        ("from .view_render import compose, holes_bbox, zoom_rect, _map_pts\n",
         "from .view_render import compose, holes_bbox, zoom_rect, _map_pts\n"
         "from .vision_workspace import CameraPreviewWorker, ClickablePhoto   # [canvas-live]\n",
         "from .vision_workspace import CameraPreviewWorker, ClickablePhoto"),
        ("        image_tools = QHBoxLayout()\n"
         "        self.image_info = QLabel('尚未选择照片')\n"
         "        self.chk_fit = QCheckBox('适应孔区域')\n",
         "        image_tools = QHBoxLayout()\n"
         "        self.image_info = QLabel('尚未选择照片')\n"
         "        # [canvas-live] 视觉检测区里直接看实时、直接抓拍\n"
         "        self.chk_live = QCheckBox('相机实时画面')\n"
         "        self.chk_live.setToolTip('勾选后中间这块直接显示工业相机实时画面；预览本身不写文件。')\n"
         "        self.chk_live.toggled.connect(self.toggle_live_preview)\n"
         "        self.btn_snap = QPushButton('抓拍')\n"
         "        self.btn_snap.setToolTip('把当前画面（实时画面，或临时取一帧）无损留样并放进工作区。')\n"
         "        self.btn_snap.clicked.connect(self.snap_from_camera)\n"
         "        self.chk_fit = QCheckBox('适应孔区域')\n",
         "self.chk_live = QCheckBox"),
        ("        image_tools.addWidget(self.image_info, 1)\n"
         "        image_tools.addWidget(self.chk_fit)\n",
         "        image_tools.addWidget(self.image_info, 1)\n"
         "        image_tools.addWidget(self.chk_live)\n"
         "        image_tools.addWidget(self.btn_snap)\n"
         "        image_tools.addWidget(self.chk_fit)\n",
         "image_tools.addWidget(self.chk_live)"),
        ("        legend = QLabel('青色：孔轮廓　黄色：拟合椭圆　红色十字：图像圆心')\n",
         "        legend = QLabel('青色：孔轮廓　黄色：拟合椭圆　红色十字：图像圆心　｜　直接点图上的孔即可选中/取消（要测量的孔）')\n",
         "直接点图上的孔即可选中"),
        ("        self.image_label = QLabel('请选择一组测试照片')\n"
         "        self.image_label.setObjectName('canvas')\n"
         "        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)\n",
         "        self.image_label = ClickablePhoto('请选择一组测试照片')\n"
         "        self.image_label.setObjectName('canvas')\n"
         "        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)\n"
         "        self.image_label.clicked.connect(self.canvas_clicked)     # [canvas-live]\n",
         "self.image_label = ClickablePhoto("),
        ("                                          self.btn_last_batch, self.btn_results,\n"
         "                                          self.btn_readiness, self.btn_preview)):\n",
         "                                          self.btn_results,   # 「打开历史批次」已并入「实验记录」\n"
         "                                          self.btn_readiness, self.btn_preview)):\n",
         "「打开历史批次」已并入「实验记录」"),
        ("    def render_view(self, *_):\n"
         "        self.lbl_zoom.setText(f'{self.sld_zoom.value()}%')\n",
         "    def render_view(self, *_):\n"
         "        if getattr(self, 'chk_live', None) is not None and self.chk_live.isChecked():\n"
         "            return      # [canvas-live] 实时画面由定时器刷新，别被静态渲染覆盖\n"
         "        self.lbl_zoom.setText(f'{self.sld_zoom.value()}%')\n",
         "别被静态渲染覆盖"),
        ("        canvas, mapping = compose(self.display_photo, (size.width(), size.height()), crop_rect=crop)\n",
         "        canvas, mapping = compose(self.display_photo, (size.width(), size.height()), crop_rect=crop)\n"
         "        # [canvas-live] compose 已经把裁剪框/缩放算好放在 mapping 里，点击换算直接用它，\n"
         "        # 千万不要再覆盖 crop——裁剪被裁边时会让点击位置偏移。\n"
         "        self.display_mapping = dict(mapping) if mapping else None\n",
         "self.display_mapping = dict(mapping)"),
        # 已经打过旧版本的：把那次多余的 crop 覆盖去掉
        ("        self.display_mapping = dict(mapping) if mapping else None      # [canvas-live] 供点击选孔\n"
         "        if self.display_mapping is not None:\n"
         "            self.display_mapping['crop'] = (int(crop[0]), int(crop[1]))\n",
         "        # [canvas-live] compose 已算好裁剪框/缩放，点击换算直接用它，不要覆盖 crop。\n"
         "        self.display_mapping = dict(mapping) if mapping else None\n",
         "不要覆盖 crop"),
        ("        self._auto_connect_state = {'done': False, 'ok': False, 'error': ''}\n"
         "        self._auto_connect_checks = 0\n"
         "        QTimer.singleShot(1200, self.auto_connect_camera)\n"
         "        QShortcut(QKeySequence('Ctrl+O'), self, activated=self.select_images)\n",
         "        self._auto_connect_state = {'done': False, 'ok': False, 'error': ''}\n"
         "        self._auto_connect_checks = 0\n"
         "        QTimer.singleShot(1200, self.auto_connect_camera)\n"
         "        # [canvas-live] 视觉检测区实时画面的刷新定时器\n"
         "        self.live_worker = None\n"
         "        self.live_frame = None\n"
         "        self.live_timer = QTimer(self)\n"
         "        self.live_timer.setInterval(40)\n"
         "        self.live_timer.timeout.connect(self.update_live_frame)\n"
         "        QShortcut(QKeySequence('Ctrl+O'), self, activated=self.select_images)\n",
         "self.live_timer.setInterval(40)"),
        ("        preview = getattr(self, 'preview_dialog', None)\n",
         "        worker = getattr(self, 'live_worker', None)      # [canvas-live] 先停实时画面\n"
         "        if worker is not None:\n"
         "            try:\n"
         "                self.live_timer.stop()\n"
         "                worker.stop()\n"
         "                worker.wait(5000)\n"
         "            except RuntimeError:\n"
         "                pass\n"
         "        preview = getattr(self, 'preview_dialog', None)\n",
         "worker = getattr(self, 'live_worker', None)"),
        ("    def log(self, message):\n", methods, "def canvas_clicked(self, x, y):"),
        # 点空的时候也要如实写日志，便于排查"点了没反应"
        ("        hole_id = pick_hole(x, y, getattr(self, 'display_mapping', None), holes)\n"
         "        if not hole_id:\n"
         "            self.log(f'点击位置（画布 {int(x)},{int(y)}）没有落在孔上；直接点孔中心即可选中。')\n"
         "            return\n",
         "        hole_id = pick_hole(x, y, getattr(self, 'display_mapping', None), holes)\n"
         "        if not hole_id:\n"
         "            mapping = getattr(self, 'display_mapping', None)\n"
         "            if mapping:\n"
         "                px = (x - mapping['ox']) / mapping['scale'] + mapping['crop'][0]\n"
         "                py = (y - mapping['oy']) / mapping['scale'] + mapping['crop'][1]\n"
         "                self.log(f'点击（画布 {int(x)},{int(y)} → 图像 {int(px)},{int(py)}）没有落在孔上；'\n"
         "                         '直接点孔中心即可选中。')\n"
         "            else:\n"
         "                self.log('点击位置没有落在孔上（当前画面没有映射信息）。')\n"
         "            return\n",
         "→ 图像"),
        # 实时画面打开后，AI 检测状态不要停在"正在连接相机…"
        ("            self.live_worker.start()\n"
         "            self.live_timer.start()\n"
         "            self.log('视觉检测区已切到相机实时画面（预览不写文件，点「抓拍」才留样）。')\n",
         "            self.live_worker.start()\n"
         "            self.live_timer.start()\n"
         "            self.set_status('相机实时画面中', '#a86613')      # [canvas-live]\n"
         "            self.log('视觉检测区已切到相机实时画面（预览不写文件，点「抓拍」才留样）。')\n",
         "self.set_status('相机实时画面中'"),
        # 抓拍方法里漏了 save_capture 的导入（会 NameError）
        ('    def snap_from_camera(self):\n'
         '        """[canvas-live] 抓拍：无损留样后放进工作区（实时画面会被冻结成照片）。"""\n'
         '        live_on = getattr(self, \'chk_live\', None) is not None and self.chk_live.isChecked()\n',
         '    def snap_from_camera(self):\n'
         '        """[canvas-live] 抓拍：无损留样后放进工作区（实时画面会被冻结成照片）。"""\n'
         '        from .capture_archive import save_capture      # [canvas-live]\n'
         '        live_on = getattr(self, \'chk_live\', None) is not None and self.chk_live.isChecked()\n',
         "from .capture_archive import save_capture      # [canvas-live]"),
        # 「实验记录 → 载入到工作区」需要主窗口提供 load_reports
        ("    def log(self, message):\n",
         "    def load_reports(self, reports):\n"
         "        \"\"\"[canvas-live] 把一组已保存的检测结果载入工作区（不重新检测、不新增记录）。\"\"\"\n"
         "        reports = [report for report in reports\n"
         "                   if isinstance(report, dict) and report.get('image')]\n"
         "        if not reports:\n"
         "            QMessageBox.information(self, '没有可载入的记录', '这一组里没有可显示的照片记录。')\n"
         "            return\n"
         "        if getattr(self, 'chk_live', None) is not None and self.chk_live.isChecked():\n"
         "            self.chk_live.setChecked(False)      # 先关掉实时画面，才能显示载入的照片\n"
         "        self.paths = [report['image'] for report in reports]\n"
         "        self.results = [_report_to_result(report) for report in reports]\n"
         "        self.selector.blockSignals(True)\n"
         "        self.selector.clear()\n"
         "        self.selector.addItems([f'{index + 1}. {Path(path).name}'\n"
         "                                for index, path in enumerate(self.paths)])\n"
         "        self.selector.blockSignals(False)\n"
         "        self.completed_count = len(reports)\n"
         "        self.batch_progress.setRange(0, len(reports))\n"
         "        self.batch_progress.setValue(len(reports))\n"
         "        self.show_index(0)\n"
         "        self.set_controls()\n"
         "\n"
         "    def log(self, message):\n",
         "def load_reports(self, reports):"),
    ]
    applied, missing = [], []
    for entry in edits:
        old, new = entry[0], entry[1]
        marker = entry[2] if len(entry) > 2 else None
        if marker and marker in text:
            continue
        if new in text:
            continue
        if old in text:
            text = text.replace(old, new, 1)
            applied.append(old.strip().splitlines()[0][:26])
        else:
            missing.append(old.strip().splitlines()[0][:26])
    if text != original:
        shutil.copy2(f, f.with_suffix(".py.bak"))
        f.write_text(text, encoding="utf-8")
    if not applied:
        if not missing:
            return "已是最新（无需修改）"
        return "未匹配: " + "; ".join(missing[:4])
    out = ["已改 {} 处（检测区实时画面/抓拍/点孔选孔）".format(len(applied))]
    if missing:
        out.append("未匹配: " + "; ".join(missing[:4]))
    return "；".join(out)


def patch_device_autofill(engine: Path) -> str:
    """[device-autofill] 换电脑也能用：不依赖保存下来的本地设备参数。

    * 相机页的提示语按"是否真的接了驱动"来写，不再一律说"没有连接功能"；
    * 连上以后，把驱动**探测到**的厂家/型号/序列号填进界面（用户填过的不覆盖）；
    * 自动连接失败时给出可操作的提示（网段），且不写死任何本机路径。
    """
    devices = engine / "inspection_gui" / "devices_view.py"
    gui = engine / "inspection_gui" / "gui.py"
    if not devices.is_file() or not gui.is_file():
        return "找不到 devices_view.py 或 gui.py"
    applied, missing = [], []

    original = devices.read_text(encoding="utf-8")
    text = original
    edits_devices = [
        ('        self.connection_note = QLabel("尚未接入此设备的连接功能，填写配置后也不会自动连接。")\n',
         '        self.connection_note = QLabel(\n'
         '            "已接入连接功能：点「连接设备」即可连接，连不上会如实提示原因。"\n'
         '            if device_id in _registered_backends else\n'
         '            "尚未接入此设备的连接功能，填写配置后也不会自动连接。")\n',
         "已接入连接功能"),
        ("    def validate(self) -> str:\n",
         "    def adopt_runtime_identity(self, backend) -> None:\n"
         "        \"\"\"[device-autofill] 把驱动探测到的真实身份填进界面。\n"
         "\n"
         "        别人电脑上相机地址/序列号可能不同，所以不依赖保存的参数：\n"
         "        探测到什么就显示什么；用户自己填过的内容不会被覆盖。\n"
         "        \"\"\"\n"
         "        name = str(getattr(backend, 'device_name', '') or '')\n"
         "        serial = str(getattr(backend, 'device_serial', '')\n"
         "                     or getattr(backend, 'device_uid', ''))\n"
         "        if not self.manufacturer.text() and name:\n"
         "            self.manufacturer.setText(name.split(' ')[0])\n"
         "        if not self.model.text() and name:\n"
         "            self.model.setText(name.replace('Orbbec', '').strip() or name)\n"
         "        if not self.serial_number.text() and serial:\n"
         "            self.serial_number.setText(serial)\n"
         "\n"
         "    def validate(self) -> str:\n",
         "def adopt_runtime_identity(self, backend)"),
    ]
    for entry in edits_devices:
        old, new = entry[0], entry[1]
        marker = entry[2] if len(entry) > 2 else None
        if marker and marker in text:
            continue
        if new in text:
            continue
        if old in text:
            text = text.replace(old, new, 1)
            applied.append("devices_view: " + old.strip().splitlines()[0][:22])
        else:
            missing.append("devices_view: " + old.strip().splitlines()[0][:22])
    if text != original:
        shutil.copy2(devices, devices.with_suffix(".py.bak"))
        devices.write_text(text, encoding="utf-8")

    original = gui.read_text(encoding="utf-8")
    text = original
    edits_gui = [
        ("            if ('已连接' in page.status.text()) == bool(connected):\n",
         "            if connected and hasattr(page, 'adopt_runtime_identity'):\n"
         "                # 换电脑也能用：把探测到的真实型号/序列号填进界面\n"
         "                page.adopt_runtime_identity(self._device_backends().get(device))\n"
         "            if ('已连接' in page.status.text()) == bool(connected):\n",
         "page.adopt_runtime_identity("),
        ("            self.log('相机自动连接未成功：' + (state['error'] or '未知原因')\n"
         "                     + '；可点「相机实时预览」或「设备连接 → 连接设备」重试。')\n",
         "            self.log('相机自动连接未成功：' + (state['error'] or '未知原因')\n"
         "                     + '；可点检测区的「相机实时画面」或「设备连接 → 连接设备」重试。'\n"
         "                     + '若提示连接超时，请先确认电脑与相机在同一网段（相机默认 192.168.1.10）。')\n",
         "若提示连接超时，请先确认电脑与相机在同一网段"),
    ]
    for entry in edits_gui:
        old, new = entry[0], entry[1]
        marker = entry[2] if len(entry) > 2 else None
        if marker and marker in text:
            continue
        if new in text:
            continue
        if old in text:
            text = text.replace(old, new, 1)
            applied.append("gui: " + old.strip().splitlines()[0][:22])
        else:
            missing.append("gui: " + old.strip().splitlines()[0][:22])
    if text != original:
        shutil.copy2(gui, gui.with_suffix(".py.bak"))
        gui.write_text(text, encoding="utf-8")

    if not applied:
        if not missing:
            return "已是最新（无需修改）"
        return "未匹配: " + "; ".join(missing[:4])
    out = ["已改 {} 处（设备信息自适应）".format(len(applied))]
    if missing:
        out.append("未匹配: " + "; ".join(missing[:4]))
    return "；".join(out)


def _op_state(text: str, op: str):
    """单条改动的状态：apply（该改）/ done（已经是目标状态）/ missing（对不上）。"""
    if op[0] == "replace":
        old, new = op[1], op[2]
        if old and new and old in new and new in text:
            # 插入型改动（新文本里包含锚点）：锚点还在不代表没插过，别重复插
            return "done"
        if old in text:
            return "apply"
        return "done" if (not new or new in text) else "missing"
    start, end, new = op[1], op[2], op[3]        # ("cut", 起点, 终点, 替换内容)
    begin, finish = text.find(start), text.find(end)
    if begin >= 0 and finish >= begin:
        return "apply"
    return "done" if (not new or new in text) else "missing"


def _apply_ops(text: str, ops):
    """套用一组改动：只要有任意一处对不上就整组不改（避免半套用）。

    返回 ``(新文本, 状态)``；状态 applied / done / missing。
    已经处于目标状态的条目会跳过，所以重复运行是安全的。
    """
    states = [_op_state(text, op) for op in ops]
    if "missing" in states:
        return text, "missing"
    if "apply" not in states:
        return text, "done"
    for op in ops:
        if op[0] == "replace":
            if op[1] in text:
                text = text.replace(op[1], op[2], 1)
        else:
            begin, finish = text.find(op[1]), text.find(op[2])
            if begin >= 0 and finish >= begin:
                text = text[:begin] + op[3] + text[finish:]
    return text, "applied"


def patch_merge_history(engine: Path) -> str:
    """9w) 合并「打开历史批次」进「实验记录」，抓拍只留一套取流代码。

    用户在 2026-10-08 提的要求：历史批次和实验记录内容重复，没必要两个入口；
    视觉检测区已经有「相机实时画面 / 抓拍」，单独的「相机实时预览」也重复。

    * gui.py 去掉按钮、批次归档读写和死代码，历史只留实验记录这一份；
    * 「用工业相机拍照」复用视觉检测区的抓拍，实时画面开着时不再两边抢相机；
    * 实验记录窗口和主界面共用同一个 ExperimentRecords：删掉一组之后，
      下一次检测不会把删掉的组又写回来（原来的数据只在内存里删）。
    """
    gui = engine / "inspection_gui" / "gui.py"
    records = engine / "inspection_gui" / "records_view.py"
    data = engine / "experiment_records.py"
    if not gui.is_file():
        return "找不到 gui.py"
    applied, skipped, missing = [], [], []

    text = gui.read_text(encoding="utf-8")
    original = text
    groups = [
        # 1) 常量：不再维护批次归档目录
        [("replace",
          "BASE = Path(__file__).resolve().parents[1]\n"
          "LAST_BATCH = BASE / 'last_batch.json'\n"
          "BATCH_DIR = BASE / 'batches'                    # [local patch] 历史批次归档目录\n"
          "BATCH_INDEX = BATCH_DIR / 'index.jsonl'         # [local patch] 批次索引\n",
          "BASE = Path(__file__).resolve().parents[1]\n"
          "# [merge-history] 历史批次原来单独归档在 last_batch.json / batches/index.jsonl，\n"
          "# 内容和「实验记录」重复。现在只保留实验记录这一份历史：不再写这些归档文件，\n"
          "# 磁盘上已有的旧文件也不会删除。\n")],
        # 2) 启动提示改成指向实验记录
        [("replace",
          "        # [local patch] start with a CLEAN workspace. The previous batch is\n"
          "        # only shown when the user clicks 「打开上次批次」 (or opens 实验记录).\n",
          "        # [local patch] start with a CLEAN workspace. History is only shown\n"
          "        # when the user opens 实验记录 and loads a group back into the workspace.\n"),
         ("replace",
          "        self.log('工作区为空。如需查看上一次的检测结果，请点「打开上次批次」。')\n",
          "        self.log('工作区为空。如需查看以前的检测结果，请点「实验记录」，'\n"
          "                 '选中一组后「载入到工作区」。')\n"
          "        self.log('设备信息不再保存到本机：相机插上即自动识别，机械臂按当前电脑实际 IP 填写。')\n")],
        # 3) 去掉两个重复入口按钮
        [("replace",
          "        self.btn_results = QPushButton('打开结果文件夹')\n"
          "        self.btn_last_batch = QPushButton('打开历史批次')   # [local patch]\n"
          "        self.btn_last_batch.setToolTip('列出以前检测过的每一批，自己选一批重新载入；启动时不会自动载入。')\n",
          "        self.btn_results = QPushButton('打开结果文件夹')\n"),
         ("replace",
          "        self.btn_preview = QPushButton('相机实时预览')      # [camera-sync]\n"
          "        self.btn_preview.setToolTip('打开工业相机实时画面；预览本身不写文件，抓拍才做无损留样。')\n",
          "        # [merge-history] 「打开历史批次」已并入「实验记录」；\n"
          "        # 「相机实时预览」已并入视觉检测区的「相机实时画面 / 抓拍」。\n"),
         ("replace",
          "                                          self.btn_results,   # 「打开历史批次」已并入「实验记录」\n"
          "                                          self.btn_readiness, self.btn_preview)):\n",
          "                                          self.btn_results,\n"
          "                                          self.btn_readiness)):\n"),
         ("replace",
          "        self.btn_last_batch.clicked.connect(self.open_batch_history)   # [local patch]\n",
          ""),
         ("replace",
          "        self.btn_preview.clicked.connect(self.show_camera_preview)   # [camera-sync]\n",
          "")],
        # 4) 抓拍统一入口 + 相机拍照改为复用抓拍（顺带去掉单独预览窗口的收尾代码）
        [("cut",
          "    @Slot()\n    def capture_from_camera(self):\n",
          "    def auto_connect_camera(self):\n",
          "    @Slot()\n"
          "    def capture_from_camera(self):\n"
          "        \"\"\"[camera-sync] 用工业相机拍一张：交给视觉检测区同一套「抓拍」逻辑。\n"
          "\n"
          "        [merge-capture] 以前这里和「抓拍」各写了一份取流代码，实时画面开着\n"
          "        的时候两边抢同一台相机。现在统一走 snap_from_camera：实时画面开着\n"
          "        就直接冻结当前帧，没开才临时取流。\n"
          "        \"\"\"\n"
          "        self.snap_from_camera(source='用工业相机拍照')\n"
          "\n"),
         ("replace",
          "        preview = getattr(self, 'preview_dialog', None)\n"
          "        if preview is not None:      # [camera-sync] 先停取流线程，避免退出时线程还在跑\n"
          "            try:\n"
          "                preview.stop_preview()\n"
          "            except RuntimeError:\n"
          "                pass\n"
          "        self.bridge.detach()\n",
          "        self.bridge.detach()\n")],
        # 5) 抓拍函数支持来源说明
        [("replace",
          "    def snap_from_camera(self):\n"
          "        \"\"\"[canvas-live] 抓拍：无损留样后放进工作区（实时画面会被冻结成照片）。\"\"\"\n",
          "    def snap_from_camera(self, *_args, source='视觉检测区抓拍'):\n"
          "        \"\"\"[canvas-live] 抓拍：无损留样后放进工作区（实时画面会被冻结成照片）。\n"
          "\n"
          "        ``*_args`` 用来吸收按钮 clicked 信号带过来的布尔值；``source``\n"
          "        只影响留样说明，不影响保存内容。\n"
          "        \"\"\"\n"),
         ("replace",
          "                'source': 'Orbbec Gemini 335Le（工业相机 · 视觉检测区抓拍）',\n",
          "                'source': f'Orbbec Gemini 335Le（工业相机 · {source}）',\n"),
         ("replace",
          "                'note': '视觉检测区抓拍；原图无损保存，不覆盖。',\n",
          "                'note': f'{source}；原图无损保存，不覆盖。',\n")],
        # 6) 检测结果不再另存批次归档；这一组被删掉时如实说明
        [("replace",
          "            self.records.update(self.active_group, report=report)\n"
          "            self.save_batch()\n",
          "            # [merge-history] 实验记录就是唯一的历史来源，不再另存批次归档。\n"
          "            if not self.records.update(self.active_group, report=report):\n"
          "                self.record_error = True\n"
          "                self.log('这一组已经在「实验记录」里被删除，本次结果不再写回实验记录'\n"
          "                         '（结果图与检测报告仍在结果文件夹里）。')\n"),
         ("replace",
          "            self.records.update(self.active_group, status=status)\n",
          "            if not self.records.update(self.active_group, status=status):\n"
          "                self.record_error = True\n"
          "                self.log('这一组已在「实验记录」里被删除，本组状态不再写回记录。')\n")],
        # 7) 相机配置只取本次运行填写的内容
        [("replace",
          "    def camera_settings(self):\n"
          "        \"\"\"[camera-sync] 读「设备连接 → 工业相机」里保存的配置。\"\"\"\n"
          "        try:\n"
          "            from .devices_view import _load_settings, SETTINGS_PATH\n"
          "            settings, _warning = _load_settings(SETTINGS_PATH)\n"
          "            return settings.get('camera', {})\n"
          "        except (ImportError, OSError, ValueError):\n"
          "            return {}\n",
          "    def camera_settings(self):\n"
          "        \"\"\"[camera-sync] 取「设备连接 → 工业相机」本次运行填写的配置。\n"
          "\n"
          "        [no-local-config] 配置不再从本机文件读取，只取本次运行内存里的内容；\n"
          "        没有填写时返回空字典，相机按实际接入的设备自动识别。\n"
          "        \"\"\"\n"
          "        try:\n"
          "            from .devices_view import current_settings\n"
          "            return current_settings().get('camera', {})\n"
          "        except (ImportError, OSError, ValueError, KeyError):\n"
          "            return {}\n"),
         ("replace",
          "                self.log('相机自动连接仍在等待设备响应，可点「相机实时预览」重试。')\n",
          "                self.log('相机自动连接仍在等待设备响应，可勾选检测区的「相机实时画面」重试。')\n")],
    ]
    cut_ops = [
        # 存档方法 / 历史批次弹窗与载入方法整体删除
        [("cut", "    def save_batch(self):\n",
          "    @Slot()\n    def finish_batch(self):\n", "")],
        [("cut", "    def _batch_entries(self):\n",
          "    @Slot()\n    def show_records(self):\n", "")],
    ]
    for group in groups + cut_ops:
        label = group[0][1].strip().splitlines()[0][:26]
        result, state = _apply_ops(text, group)
        if state == "missing":
            missing.append(label)
        elif state == "done":
            skipped.append(label)
        else:
            text = result
            applied.append(label)
    if text == original:
        if missing:
            return "未匹配（可能已改过或上游补丁变了）: " + "; ".join(missing[:4])
        return "已是最新（无需修改）"
    shutil.copy2(gui, gui.with_suffix(".py.bak"))
    gui.write_text(text, encoding="utf-8")

    # ---- 记录窗口与主界面共用同一份数据 ----
    if records.is_file():
        original = records.read_text(encoding="utf-8")
        text = original
        edits = [
            ("        self.records = ExperimentRecords.__new__(ExperimentRecords)\n"
             "        self.records.path = self.path\n"
             "        self.records.groups = []\n",
             "        # [records-tools] 有主界面传进来的 records 就直接共用同一个对象，\n"
             "        # 这样在这里删除/刷新之后主界面内存里的记录不会滞后。\n"
             "        if records is not None:\n"
             "            self.records = records\n"
             "        else:\n"
             "            self.records = ExperimentRecords.__new__(ExperimentRecords)\n"
             "            self.records.path = self.path\n"
             "            self.records.groups = []\n",
             "有主界面传进来的 records 就直接共用同一个对象"),
            ("        try:\n"
             "            groups = json.loads(self.path.read_text(encoding=\"utf-8\")) if self.path.exists() else []\n"
             "            if not isinstance(groups, list):\n"
             "                raise ValueError(\"记录文件的内容不是实验组列表\")\n"
             "            snapshot = ExperimentRecords.__new__(ExperimentRecords)\n"
             "            snapshot.path, snapshot.groups = self.path, groups\n"
             "            rows = snapshot.rows()\n",
             "        try:\n"
             "            # 重新读盘，成功后 self.records 就是磁盘上的真实内容（读失败时原有内容不变）。\n"
             "            groups = self.records.refresh_from_disk()\n"
             "            rows = self.records.rows()\n",
             "self.records.refresh_from_disk()"),
            ("        self.records, self.rows = snapshot, rows\n",
             "        self.rows = rows\n",
             "        self.rows = rows\n"),
        ]
        touched = False
        for old, new, marker in edits:
            if marker in text:
                continue
            if old in text:
                text = text.replace(old, new, 1)
                touched = True
            else:
                missing.append("records_view: " + old.strip().splitlines()[0][:22])
        if touched:
            shutil.copy2(records, records.with_suffix(".py.bak"))
            records.write_text(text, encoding="utf-8")
    else:
        missing.append("records_view.py")

    # ---- 记录数据层：删除之后不会再“复活” ----
    if data.is_file():
        original = data.read_text(encoding="utf-8")
        text = original
        edits = [
            ("    def begin(self, paths, model):\n",
             "    def refresh_from_disk(self):\n"
             "        \"\"\"[records-tools] 重新从磁盘读记录，但不动任何组的状态。\n"
             "\n"
             "        实验记录窗口和主界面共用同一个对象：删除/载入之后重新读一次文件，\n"
             "        两边就不会出现“界面上删了、内存里还在”的分歧。\n"
             "        \"\"\"\n"
             "        groups = json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else []\n"
             "        if not isinstance(groups, list):\n"
             "            raise ValueError('记录文件的内容不是实验组列表')\n"
             "        self.groups = groups\n"
             "        return self.groups\n"
             "\n"
             "    def begin(self, paths, model):\n",
             "def refresh_from_disk(self):"),
            ("    def update(self, group_id, report=None, status=None):\n"
             "        group = next(g for g in self.groups if g['id'] == group_id)\n"
             "        if report is not None:\n"
             "            group['reports'].append(report)\n"
             "        if status is not None:\n"
             "            group['status'] = status\n"
             "        self.save()\n",
             "    def update(self, group_id, report=None, status=None):\n"
             "        group = next((g for g in self.groups if g.get('id') == group_id), None)\n"
             "        if group is None:\n"
             "            # 这一组可能已经在「实验记录」里被删除，不能再凭空写回去。\n"
             "            return False\n"
             "        if report is not None:\n"
             "            group['reports'].append(report)\n"
             "        if status is not None:\n"
             "            group['status'] = status\n"
             "        self.save()\n"
             "        return True\n",
             "这一组可能已经在「实验记录」里被删除"),
        ]
        touched = False
        for old, new, marker in edits:
            if marker in text:
                continue
            if old in text:
                text = text.replace(old, new, 1)
                touched = True
            else:
                missing.append("experiment_records: " + old.strip().splitlines()[0][:22])
        if touched:
            shutil.copy2(data, data.with_suffix(".py.bak"))
            data.write_text(text, encoding="utf-8")
    else:
        missing.append("experiment_records.py")

    out = ["已改 {} 组（合并历史批次/抓拍入口）".format(len(applied))]
    if missing:
        out.append("未匹配: " + "; ".join(missing[:4]))
    return "；".join(out)


def patch_no_local_config(engine: Path) -> str:
    """9x) 设备参数不落盘：换电脑直接按实际设备用，不带上一台机器的参数。

    * devices_view：不再读写 device_settings.json，设备信息只留在本次运行内存里；
      相机不强制填地址（插上自动识别），机械臂按当前电脑实际 IP 填写；
    * camera_parameters：期望曝光/增益/触发模式同样只对本次运行有效。
    """
    devices = engine / "inspection_gui" / "devices_view.py"
    params = engine / "inspection_gui" / "camera_parameters.py"
    applied, missing = [], []

    if devices.is_file():
        text = devices.read_text(encoding="utf-8")
        if "[no-local-config]" in text:
            pass
        else:
            groups = [
                [("replace",
                  "No motion or image acquisition is initiated from this window.\n\"\"\"\n",
                  "No motion or image acquisition is initiated from this window.\n"
                  "\n"
                  "[no-local-config] 设备参数（型号、地址、序列号等）只对本次运行有效：软件\n"
                  "不再把它们写到这台电脑上。换一台电脑时，打开软件就按那台电脑实际连接的\n"
                  "设备填写或由驱动自动读取，避免把上一台机器的参数带过去。\n"
                  "\"\"\"\n"),
                 ("replace",
                  "import ipaddress\nimport json\nimport os\nimport re\nimport uuid\n"
                  "import weakref\nimport threading\n",
                  "import ipaddress\nimport re\nimport weakref\nimport threading\n"),
                 ("replace",
                  "SETTINGS_PATH = Path(__file__).with_name(\"device_settings.json\")\n",
                  "# [no-local-config] 这个路径只用来兼容旧调用，程序不会再读写它。\n"
                  "SETTINGS_PATH = Path(__file__).with_name(\"device_settings.json\")\n"),
                 ("cut",
                  "def _load_settings(path: Path) -> tuple[dict, str]:\n",
                  "def _validate_address(address: str) -> bool:\n",
                  "# [no-local-config] 设备参数不再从磁盘读取、也不再写入磁盘。\n"
                  "# 只保留一份“本次运行”的副本：用户在设备连接窗口里填写/应用的内容，\n"
                  "# 或者驱动探测到的真实信息，都放进这个内存字典里。\n"
                  "_runtime_settings = _default_settings()\n"
                  "\n"
                  "\n"
                  "def current_settings() -> dict:\n"
                  "    \"\"\"[no-local-config] 本次运行中填写或自动读取到的设备信息（不落盘）。\"\"\"\n"
                  "    return deepcopy(_runtime_settings)\n"
                  "\n"
                  "\n"
                  "def remember_settings(settings: dict) -> None:\n"
                  "    \"\"\"[no-local-config] 把设备窗口里确认过的内容留在本次运行的内存中。\"\"\"\n"
                  "    for device_id, values in (settings or {}).items():\n"
                  "        if device_id in _runtime_settings and isinstance(values, dict):\n"
                  "            _runtime_settings[device_id] = dict(values)\n"
                  "\n"
                  "\n"
                  "def _load_settings(path: Path | None = None) -> tuple[dict, str]:\n"
                  "    \"\"\"[no-local-config] 兼容旧调用：直接返回本次运行的设备信息。\n"
                  "\n"
                  "    参数 ``path`` 只是为了让旧代码可以照原样调用，已经不再读写。\n"
                  "    \"\"\"\n"
                  "    return current_settings(), \"\"\n"
                  "\n"
                  "\n"),
                 ("cut",
                  "def _write_settings(path: Path, settings: dict) -> None:\n",
                  "class DevicePage(QWidget):\n", ""),
                 ("replace",
                  "        explanation = QLabel(\"地址和端口按设备说明填写；未知内容可以暂时留空。\")\n",
                  "        explanation = QLabel(\n"
                  "            \"相机可以不填地址：插好相机后软件按实际连接的设备自动识别；\"\n"
                  "            \"机械臂如需连接，请填写这台电脑上实际使用的 IP。\"\n"
                  "            \"内容只在本次运行中使用，不会保存到这台电脑。\")\n"),
                 ("replace",
                  "            settings = self.settings()\n"
                  "            if not settings['address']:\n"
                  "                self.connection_note.setText('请先填写机械臂或设备的 IP 地址。')\n",
                  "            settings = self.settings()\n"
                  "            # [no-local-config] 相机由驱动自动识别，不强制填写地址；\n"
                  "            # 机械臂是网络设备，必须填写这台电脑实际连到的 IP。\n"
                  "            if not settings['address'] and self.device_id != 'camera':\n"
                  "                self.connection_note.setText('请先填写机械臂的 IP 地址（相机可以不填，插好会自动识别）。')\n"),
                 ("replace",
                  "        self.save_note = QLabel(warning or \"配置只保存在本机，不会自动连接设备。\")\n",
                  "        self.save_note = QLabel(warning or \"设备信息只在本次运行中使用，不会保存到这台电脑；\"\n"
                  "                                          \"换电脑后按实际设备重新填写或由软件自动读取。\")\n"),
                 ("replace",
                  "        save = QPushButton(\"保存设备配置\")\n",
                  "        save = QPushButton(\"应用到本次运行\")\n"),
                 ("replace",
                  "        settings = self.settings()\n"
                  "        try:\n"
                  "            _write_settings(self.settings_path, settings)\n"
                  "        except OSError as exc:\n"
                  "            QMessageBox.warning(self, \"配置未保存\", f\"请检查本机文件夹是否可以写入。\\n{exc}\")\n"
                  "            return False\n"
                  "        self.save_note.setText(\"设备配置已保存到本机。连接状态保持当前状态。\")\n",
                  "        settings = self.settings()\n"
                  "        # [no-local-config] 只记在内存里：换电脑后不会带着上一台机器的参数。\n"
                  "        remember_settings(settings)\n"
                  "        self.save_note.setText(\"设备信息已用于本次运行，不会保存到这台电脑；连接状态保持当前状态。\")\n")],
            ]
            touched, blocked = False, False
            for group in groups:
                result, state = _apply_ops(text, group)
                if state == "missing":
                    blocked = True
                    break
                if state == "done":
                    continue
                text = result
                touched = True
            if touched and not blocked:
                shutil.copy2(devices, devices.with_suffix(".py.bak"))
                devices.write_text(text, encoding="utf-8")
                applied.append("devices_view: 设备参数不落盘")
            elif blocked:
                missing.append("devices_view: 设备参数不落盘（上游文本变了）")
    else:
        missing.append("devices_view.py")

    if params.is_file():
        original = params.read_text(encoding="utf-8")
        text = original
        edits = [
            ("\"\"\"Desired camera settings are distinct from verified device readback.\"\"\"\n"
             "from pathlib import Path\n",
             "\"\"\"Desired camera settings are distinct from verified device readback.\n"
             "\n"
             "[no-local-config] 期望参数只保留在本次运行的内存里，不写到这台电脑上：\n"
             "换一台电脑或换一台相机时，直接按实际设备重新设置并以设备读回为准。\n"
             "\"\"\"\n",
             "[no-local-config]"),
            ("from PySide6.QtWidgets import QDialog,QVBoxLayout,QFormLayout,QLabel,QDoubleSpinBox,QComboBox,QPushButton,QMessageBox\n",
             "from PySide6.QtWidgets import QDialog,QVBoxLayout,QFormLayout,QLabel,QDoubleSpinBox,QComboBox,QPushButton,QMessageBox\n"
             "\n"
             "# [no-local-config] 本次运行中填写的期望参数（不落盘）。\n"
             "_session_desired = {}\n",
             "_session_desired = {}"),
            ("        self.config_path=Path(__file__).resolve().parents[1]/'data/camera_parameters.json'\n"
             "        try:\n"
             "            data=json.loads(self.config_path.read_text(encoding='utf-8')).get('desired',{});self.exposure.setValue(data.get('exposure_us',self.exposure.value()));self.gain.setValue(data.get('gain_db',0));index=self.trigger.findData(data.get('trigger_mode'));self.trigger.setCurrentIndex(max(0,index))\n"
             "        except (OSError,ValueError):pass\n",
             "        # [no-local-config] 只回填本次运行填过的值，不读本机保存的旧参数。\n"
             "        self.exposure.setValue(_session_desired.get('exposure_us',self.exposure.value()))\n"
             "        self.gain.setValue(_session_desired.get('gain_db',0))\n"
             "        index=self.trigger.findData(_session_desired.get('trigger_mode'))\n"
             "        self.trigger.setCurrentIndex(max(0,index))\n",
             "只回填本次运行填过的值"),
            ("    def save_desired(self):\n"
             "        try:\n"
             "            self.config_path.parent.mkdir(parents=True,exist_ok=True)\n"
             "            data={'saved_at':datetime.now().astimezone().isoformat(),'desired':self.desired(),'actual_readback':self.actual,'applied':False}\n"
             "            self.config_path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');self.status.setText('期望配置已保存，不代表相机实际参数。')\n"
             "        except OSError as error:QMessageBox.warning(self,'配置未保存',str(error))\n",
             "    def save_desired(self):\n"
             "        # [no-local-config] 相机参数不保存到这台电脑，只在本次运行里生效。\n"
             "        _session_desired.clear();_session_desired.update(self.desired())\n"
             "        self.status.setText('期望配置已用于本次运行，不会保存到这台电脑；实际参数以「读取实际参数」为准。')\n",
             "相机参数不保存到这台电脑"),
        ]
        touched = False
        for old, new, marker in edits:
            if marker in text:
                continue
            if old in text:
                text = text.replace(old, new, 1)
                touched = True
            else:
                missing.append("camera_parameters: " + old.strip().splitlines()[0][:22])
        if touched:
            shutil.copy2(params, params.with_suffix(".py.bak"))
            params.write_text(text, encoding="utf-8")
        if touched:
            applied.append("camera_parameters: 期望参数不落盘")
    else:
        missing.append("camera_parameters.py")

    if not applied:
        if not missing:
            return "已是最新（无需修改）"
        return "未匹配: " + "; ".join(missing[:4])
    out = ["已改： " + "、".join(applied)]
    if missing:
        out.append("未匹配: " + "; ".join(missing[:4]))
    return "；".join(out)


def patch_split_view(engine: Path) -> str:
    """9y) 视觉检测区拆成左右两格：左=相机实时画面（只看），右=检测结果（点孔选测量目标）。

    用户 2026-10-08 反馈：实时画面和标定好的孔图要同时看，一块画布来回切很别扭。
    左边只负责对准，右边负责"标定/识别后的孔 + 点选本次要测的孔"；关掉实时时
    左格隐藏，结果图占满整格。
    """
    gui = engine / "inspection_gui" / "gui.py"
    if not gui.is_file():
        return "找不到 gui.py"
    text = gui.read_text(encoding="utf-8")
    original = text
    applied, skipped, missing = [], [], []

    groups = [
        # -1) 分屏要用的 QSize
        [("replace",
          "from PySide6.QtCore import QObject, QThread, Qt, QTimer, Signal, Slot, QUrl\n",
          "from PySide6.QtCore import QObject, QSize, QThread, Qt, QTimer, Signal, Slot, QUrl\n")],
        # 0) 尺寸变化会重画的分屏画布类（结果格专用）
        [("replace",
          "class BatchWorker(QObject):\n",
          "class PanePhoto(ClickablePhoto):\n"
          "    \"\"\"[split-view] 画布尺寸一变就通知重画。\n"
          "\n"
          "    拖动分隔条、隐藏实时格、缩放窗口都会改变这一格的尺寸；如果不重画，\n"
          "    点击时用的坐标映射还是旧的，点孔就会点偏。\n"
          "\n"
          "    \"\"\"\n"
          "\n"
          "    resized = Signal()\n"
          "\n"
          "    def sizeHint(self):\n"
          "        # 交给分隔条决定大小；否则 QLabel 会拿 pixmap 尺寸当期望值，拖起来又卡又跳。\n"
          "        return QSize(160, 160)\n"
          "\n"
          "    def minimumSizeHint(self):\n"
          "        return QSize(120, 120)\n"
          "\n"
          "    def resizeEvent(self, event):\n"
          "        super().resizeEvent(event)\n"
          "        self.resized.emit()\n"
          "\n"
          "\n"
          "class PaneLabel(QLabel):\n"
          "    \"\"\"[split-view] 只显示画面的格子（实时那一格），尺寸完全由分隔条决定。\"\"\"\n"
          "\n"
          "    def sizeHint(self):\n"
          "        return QSize(160, 160)\n"
          "\n"
          "    def minimumSizeHint(self):\n"
          "        return QSize(120, 120)\n"
          "\n"
          "\n"
          "class BatchWorker(QObject):\n")],
        # 1) 两个格子的角标样式 + 分隔条颜色
        [("replace",
          "QLabel#canvas { background: #f7f9fc; border: 1px solid #dde5ee; border-radius: 8px; color: #8a97a8; }\n",
          "QLabel#canvas { background: #f7f9fc; border: 1px solid #dde5ee; border-radius: 8px; color: #8a97a8; }\n"
          "QLabel#paneCaption { color: #5a6b82; font-size: 11px; font-weight: 600; }\n"
          "QSplitter#visualSplit::handle { background: #cfdae8; }\n"
          "QSplitter#visualSplit::handle:hover { background: #9fb6d1; }\n")],
        # 2) 单画布 -> 左右分屏
        [("replace",
          "        self.image_label = ClickablePhoto('请选择一组测试照片')\n"
          "        self.image_label.setObjectName('canvas')\n"
          "        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)\n"
          "        self.image_label.clicked.connect(self.canvas_clicked)     # [canvas-live]\n"
          "        self.image_label.setMinimumSize(420, 260)\n"
          "        self.image_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)\n"
          "        visual_layout.addWidget(self.image_label, 1)\n",
          "        # [split-view] 视觉检测区拆成左右两格：左边相机实时画面（只看），右边检测结果\n"
          "        # （标定/识别后的孔图，点孔选本次要测的孔）。中间分隔条可拖，关掉实时时结果图占满。\n"
          "        self.visual_split = QSplitter(Qt.Orientation.Horizontal)\n"
          "        self.visual_split.setObjectName('visualSplit')\n"
          "        # [split-view] 不允许把某一格拖成 0（拖没了就找不回来），分隔条加宽一点好抓\n"
          "        self.visual_split.setChildrenCollapsible(False)\n"
          "        self.visual_split.setHandleWidth(8)\n"
          "\n"
          "        self.live_column = QWidget()\n"
          "        live_layout = QVBoxLayout(self.live_column)\n"
          "        live_layout.setContentsMargins(0, 0, 0, 0)\n"
          "        live_layout.setSpacing(4)\n"
          "        self.live_caption = QLabel('实时画面（未开启）')\n"
          "        self.live_caption.setObjectName('paneCaption')\n"
          "        self.live_view = PaneLabel('勾选下方「相机实时画面」\\n在这里看相机实时画面（只看，不点选）')\n"
          "        self.live_view.setObjectName('canvas')\n"
          "        self.live_view.setAlignment(Qt.AlignmentFlag.AlignCenter)\n"
          "        self.live_view.setMinimumSize(150, 200)\n"
          "        self.live_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)\n"
          "        live_layout.addWidget(self.live_caption)\n"
          "        live_layout.addWidget(self.live_view, 1)\n"
          "        self.live_column.setMinimumWidth(160)\n"
          "\n"
          "        self.result_column = QWidget()\n"
          "        result_layout = QVBoxLayout(self.result_column)\n"
          "        result_layout.setContentsMargins(0, 0, 0, 0)\n"
          "        result_layout.setSpacing(4)\n"
          "        self.result_caption = QLabel('检测结果（标定好的孔）')\n"
          "        self.result_caption.setObjectName('paneCaption')\n"
          "        self._result_caption_base = '检测结果（标定好的孔）'\n"
          "        self.result_view = PanePhoto('请选择一组测试照片')\n"
          "        self.result_view.setObjectName('canvas')\n"
          "        self.result_view.setAlignment(Qt.AlignmentFlag.AlignCenter)\n"
          "        self.result_view.clicked.connect(self.canvas_clicked)     # [split-view]\n"
          "        self.result_view.resized.connect(self.render_view)        # [split-view] 尺寸变了就重算坐标映射\n"
          "        self.result_view.setMinimumSize(150, 200)\n"
          "        self.result_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)\n"
          "        result_layout.addWidget(self.result_caption)\n"
          "        result_layout.addWidget(self.result_view, 1)\n"
          "        self.result_column.setMinimumWidth(220)\n"
          "\n"
          "        self.visual_split.addWidget(self.live_column)\n"
          "        self.visual_split.addWidget(self.result_column)\n"
          "        self.visual_split.setStretchFactor(0, 4)\n"
          "        self.visual_split.setStretchFactor(1, 6)\n"
          "        self.visual_split.splitterMoved.connect(self.render_view)  # [split-view] 拖动分隔条也跟着重画\n"
          "        self.live_column.hide()          # [split-view] 默认不显示实时，结果图先占满整格\n"
          "        visual_layout.addWidget(self.visual_split, 1)\n"
          "        self.image_label = self.result_view      # [split-view] 兼容旧调用，指向结果格\n")],
        # 3) 提示文字改成"左格实时 / 右格结果"
        [("replace",
          "        self.chk_live.setToolTip('勾选后中间这块直接显示工业相机实时画面；预览本身不写文件。')\n",
          "        self.chk_live.setToolTip('勾选后左边这一格显示工业相机实时画面；预览本身不写文件。')\n"),
         ("replace",
          "        self.btn_snap.setToolTip('把当前画面（实时画面，或临时取一帧）无损留样并放进工作区。')\n",
          "        self.btn_snap.setToolTip('把当前实时画面无损留样，放进工作区并在右格显示（不自动检测）。')\n"),
         ("replace",
          "        legend = QLabel('青色：孔轮廓　黄色：拟合椭圆　红色十字：图像圆心　｜　直接点图上的孔即可选中/取消（要测量的孔）')\n",
          "        legend = QLabel('左格：相机实时画面（只看）　｜　右格：检测结果——青色孔轮廓、黄色拟合椭圆、'\n"
          "                        '红色十字圆心；直接点右格的孔即可选中/取消（要测量的孔）')\n")],
        # 4) 开关实时：加实时格 / 关掉实时隐藏左格；并补上三个小工具方法
        [("replace",
          "        \"\"\"[canvas-live] 视觉检测区显示/关闭工业相机实时画面。\"\"\"\n",
          "        \"\"\"[split-view] 左侧那一格显示/关闭工业相机实时画面（右格结果图不受影响）。\"\"\"\n"),
         ("replace",
          "            self.live_worker.failed.connect(self.live_preview_failed)\n"
          "            self.live_worker.start()\n"
          "            self.live_timer.start()\n"
          "            self.set_status('相机实时画面中', '#a86613')      # [canvas-live]\n"
          "            self.log('视觉检测区已切到相机实时画面（预览不写文件，点「抓拍」才留样）。')\n"
          "        else:\n"
          "            self.live_timer.stop()\n"
          "            worker, self.live_worker = getattr(self, 'live_worker', None), None\n"
          "            if worker is not None:\n"
          "                worker.stop()\n"
          "                worker.wait(5000)\n"
          "            self.live_frame = None\n"
          "            self.log('实时画面已关闭。')\n"
          "            self.render_view()\n"
          "        self.chk_fit.setEnabled(not on)\n"
          "        self.sld_zoom.setEnabled(not on)\n",
          "            self.live_worker.failed.connect(self.live_preview_failed)\n"
          "            self.live_worker.start()\n"
          "            self.live_timer.start()\n"
          "            self._show_live_column()\n"
          "            self.set_status('相机实时画面中', '#a86613')      # [canvas-live]\n"
          "            self.log('左侧已切到相机实时画面（只看、不点选；预览不写文件，点「抓拍」才留样）。')\n"
          "        else:\n"
          "            self.live_timer.stop()\n"
          "            worker, self.live_worker = getattr(self, 'live_worker', None), None\n"
          "            if worker is not None:\n"
          "                worker.stop()\n"
          "                worker.wait(5000)\n"
          "            self.live_frame = None\n"
          "            self._live_placeholder()\n"
          "            if getattr(self, 'live_column', None) is not None:\n"
          "                self.live_column.hide()      # [split-view] 关掉实时后，结果图占满整格\n"
          "            self.log('实时画面已关闭。')\n"
          "            self.refresh_current_summary()\n"
          "\n"
          "    def _live_placeholder(self):\n"
          "        \"\"\"[split-view] 实时那一格的占位提示（不写文件，也不冒充已经有画面）。\"\"\"\n"
          "        label = getattr(self, 'live_view', None)\n"
          "        if label is None:\n"
          "            return\n"
          "        label.clear()\n"
          "        label.setText('勾选下方「相机实时画面」\\n在这里看相机实时画面（只看，不点选）')\n"
          "        self.live_caption.setText('实时画面（未开启）')\n"
          "\n"
          "    def _show_live_column(self):\n"
          "        \"\"\"[split-view] 打开实时格，按 45:55 摆分隔条（两边都留够最小宽度，之后可以自己拖）。\"\"\"\n"
          "        if getattr(self, 'live_column', None) is None:\n"
          "            return\n"
          "        self.live_column.show()\n"
          "        total = max(self.visual_split.width(), 420)\n"
          "        live_width = max(160, min(int(total * 0.45), total - 220))\n"
          "        self.visual_split.setSizes([live_width, max(220, total - live_width)])\n"
          "\n"
          "    def _paint_live_frame(self):\n"
          "        \"\"\"[split-view] 把最近一帧按实时格当前大小重画（保持长宽比）。\"\"\"\n"
          "        frame = getattr(self, 'live_frame', None)\n"
          "        label = getattr(self, 'live_view', None)\n"
          "        if frame is None or label is None:\n"
          "            return\n"
          "        height, width = frame.shape[:2]\n"
          "        size = label.size()\n"
          "        scale = min(size.width() / max(width, 1), size.height() / max(height, 1), 1.0)\n"
          "        canvas = frame\n"
          "        if scale < 0.999:\n"
          "            canvas = cv2.resize(frame, (max(1, int(width * scale)), max(1, int(height * scale))),\n"
          "                                interpolation=cv2.INTER_AREA)\n"
          "        label.setPixmap(bgr_to_pixmap(canvas))\n")],
        # 5) 实时帧只画到左格
        [("replace",
          "        \"\"\"[canvas-live] 把最新一帧画到视觉检测区。\"\"\"\n",
          "        \"\"\"[canvas-live] 把最新一帧画到左侧实时格。\"\"\"\n"),
         ("replace",
          "            self.image_info.setText('等待相机图像…（若一直没有画面，检查相机网段是否为 192.168.1.100）')\n",
          "            self.live_caption.setText('实时画面（相机）· 等待图像…'\n"
          "                                      '（若一直没有画面，检查相机网段是否为 192.168.1.100）')\n"),
         ("replace",
          "        self.live_frame = frame\n"
          "        height, width = frame.shape[:2]\n"
          "        size = self.image_label.size()\n"
          "        scale = min(size.width() / width, size.height() / height, 1.0)\n"
          "        canvas = frame\n"
          "        if scale < 0.999:\n"
          "            canvas = cv2.resize(frame, (max(1, int(width * scale)), max(1, int(height * scale))),\n"
          "                                interpolation=cv2.INTER_AREA)\n"
          "        self.image_label.setPixmap(bgr_to_pixmap(canvas))\n"
          "        self.image_info.setText(f'相机实时画面 · {width}×{height}（未写文件）')\n",
          "        self.live_frame = frame\n"
          "        self._paint_live_frame()\n"
          "        size_text = f'{frame.shape[1]}×{frame.shape[0]}（未写文件）'\n"
          "        # [split-view] 格子窄的时候只留短标题，别把字挤到隔壁那格去\n"
          "        self.live_caption.setText('实时画面（相机）· ' + size_text\n"
          "                                  if self.live_column.width() >= 330 else '实时画面（相机）')\n"
          "        self.live_caption.setToolTip('实时画面（相机）· ' + size_text)\n")],
        # 6) 抓拍不再冻结实时（左格继续实时，右格换成抓拍的照片）
        [("replace",
          "        if live_on:\n"
          "            self.chk_live.setChecked(False)      # 冻结成照片，避免立刻被实时画面覆盖\n",
          "")],
        # 7) 点选孔只发生在右格
        [("replace",
          "        \"\"\"[canvas-live] 在图片上点一下 = 选中/取消这个孔（本次要测量的孔）。\"\"\"\n"
          "        if getattr(self, 'chk_live', None) is not None and self.chk_live.isChecked():\n"
          "            return\n",
          "        \"\"\"[split-view] 在右格结果图上点一下 = 选中/取消这个孔（本次要测量的孔）。\"\"\"\n")],
        # 8) 载入实验记录不再需要先关实时
        [("replace",
          "        if getattr(self, 'chk_live', None) is not None and self.chk_live.isChecked():\n"
          "            self.chk_live.setChecked(False)      # 先关掉实时画面，才能显示载入的照片\n"
          "        self.paths = [report['image'] for report in reports]\n",
          "        self.paths = [report['image'] for report in reports]\n")],
        # 9) 右格渲染：不再被实时挡住（拆成小步，只改各版本都有的那几行）
        [("replace",
          "        if getattr(self, 'chk_live', None) is not None and self.chk_live.isChecked():\n"
          "            return      # [canvas-live] 实时画面由定时器刷新，别被静态渲染覆盖\n",
          "        \"\"\"[split-view] 只画右格（检测结果）；左格实时画面由定时器单独刷新。\"\"\"\n")],
        [("replace",
          "            self.image_label.clear()\n"
          "            self.image_label.setText('照片未能读取，请重新选择本机照片。' if self.paths else '请选择一组测试照片')\n",
          "            self.result_caption.setText('检测结果（标定好的孔）')\n"
          "            self.result_view.clear()\n"
          "            self.result_view.setText('照片未能读取，请重新选择本机照片。' if self.paths else '请选择一组测试照片')\n")],
        [("replace",
          "        size = self.image_label.size()\n",
          "        size = self.result_view.size()\n")],
        [("replace",
          "        self.image_label.setPixmap(bgr_to_pixmap(canvas))\n",
          "        self.result_view.setPixmap(bgr_to_pixmap(canvas))\n")],
        [("replace",
          "        if hasattr(self, 'image_label'):\n"
          "            self.render_view()\n",
          "        if hasattr(self, 'result_view'):\n"
          "            self.render_view()\n"
          "        self._paint_live_frame()\n")],
    ]
    for group in groups:
        label = group[0][1].strip().splitlines()[0][:26]
        result, state = _apply_ops(text, group)
        if state == "missing":
            missing.append(label)
        elif state == "done":
            skipped.append(label)
        else:
            text = result
            applied.append(label)

    # 右格角标：show_index 在不同版本里写法不一样，用 page_label 那一行做锚点。
    caption_mark = "self._result_caption_base = f'检测结果（标定好的孔）· {Path(path).name}'"
    caption_new = ("        " + caption_mark + "\n"
                   "        self.result_caption.setText(self._result_caption_base)\n")
    page_label_line = "        self.page_label.setText(f'{self.current_index + 1}/{len(self.paths)}')\n"
    if caption_mark in text:
        skipped.append("右格角标")
    elif page_label_line in text:
        text = text.replace(page_label_line, page_label_line + caption_new, 1)
        applied.append("右格角标")
    else:
        missing.append("右格角标")

    # 实时画面开着时，状态栏不要被"当前照片…"覆盖（点选孔之后最容易看到）
    live_note_mark = "        # [split-view] 实时画面开着时不要把状态栏改回\"当前照片…\"\n"
    old_live_note = ("        if not self.batch_running and not self.bridge.busy:\n"
                     "            if result.get('errors'):\n")
    if live_note_mark in text:
        skipped.append("实时状态不被覆盖")
    elif old_live_note in text:
        text = text.replace(
            old_live_note,
            "        live_on = getattr(self, 'chk_live', None) is not None and self.chk_live.isChecked()\n"
            "        if not self.batch_running and not self.bridge.busy and not live_on:\n"
            + live_note_mark
            + "            if result.get('errors'):\n", 1)
        applied.append("实时状态不被覆盖")
    else:
        missing.append("实时状态不被覆盖")

    if text == original:
        if missing:
            return "未匹配: " + "; ".join(missing[:4])
        return "已是最新（无需修改）"
    shutil.copy2(gui, gui.with_suffix(".py.bak"))
    gui.write_text(text, encoding="utf-8")
    out = ["已改 {} 组（视觉检测区左右分屏）".format(len(applied))]
    if missing:
        out.append("未匹配: " + "; ".join(missing[:4]))
    return "；".join(out)


def patch_selection_feedback(engine: Path) -> str:
    """9z) 点孔要有看得见的反馈；「删除这一组」改成「删除整批记录」。

    用户 2026-10-08 反馈：
    * 在结果图上点孔只是表格勾了一下，图上没变化，别人不知道选没选上；
      现在选中的孔会套绿环 + 圆心打白勾，角标也写清"本次要测：H01、H03"。
    * 记录窗口的「删除这一组」说法别扭，改成「删除整批记录」，确认框里写明这批几张。
    """
    gui = engine / "inspection_gui" / "gui.py"
    records = engine / "inspection_gui" / "records_view.py"
    data = engine / "experiment_records.py"
    applied, skipped, missing = [], [], []

    if gui.is_file():
        text = gui.read_text(encoding="utf-8")
        original = text
        groups = [
            # 1) 没有照片时角标也用同一个基名
            [("replace",
              "            self.result_caption.setText('检测结果（标定好的孔）')\n",
              "            self.result_caption.setText(getattr(self, '_result_caption_base', '检测结果（标定好的孔）'))\n")],
            # 2) 画完之后把"本次要测哪几个孔"写进角标
            [("replace",
              "        self.display_mapping = dict(mapping) if mapping else None\n"
              "        if mapping:\n"
              "            for hole in display_result.get('fitted_holes', []):\n",
              "        self.display_mapping = dict(mapping) if mapping else None\n"
              "        chosen = sorted(self.measure_targets)\n"
              "        # [select-mark] 角标写清\"本次要测哪几个孔\"，配合图上绿色圈 + 白勾\n"
              "        caption_base = getattr(self, '_result_caption_base', '检测结果（标定好的孔）')\n"
              "        caption_note = '本次要测：' + ('、'.join(chosen) if chosen else '（未选中，点图上的孔即可选中）')\n"
              "        # [split-view] 格子窄的时候优先留\"本次要测\"，完整信息进提示\n"
              "        self.result_caption.setText(caption_note if self.result_column.width() < 430\n"
              "                                    else caption_base + '　｜　' + caption_note)\n"
              "        self.result_caption.setToolTip(caption_base + '　｜　' + caption_note)\n"
              "        if mapping:\n"
              "            for hole in display_result.get('fitted_holes', []):\n")],
            # 3) 选中的孔：绿环 + 绿点白勾（单独一个方法，哪一版源码都能套上）
            [("replace",
              "        self.result_view.setPixmap(bgr_to_pixmap(canvas))\n"
              "\n"
              "    def resizeEvent(self, event):\n",
              "        self._draw_selection_marks(canvas, mapping, display_result)\n"
              "        self.result_view.setPixmap(bgr_to_pixmap(canvas))\n"
              "\n"
              "    def _draw_selection_marks(self, canvas, mapping, display_result):\n"
              "        \"\"\"[select-mark] 给\"本次要测的孔\"套绿环 + 圆心打白勾，让别人一眼看出选没选上。\n"
              "\n"
              "        单独一个方法：不同版本的标注循环写法不一样，这里只依赖圆心和椭圆参数。\n"
              "        \"\"\"\n"
              "        if canvas is None or not mapping or not display_result:\n"
              "            return canvas\n"
              "        for hole in display_result.get('fitted_holes', []):\n"
              "            if hole.get('id') not in self.measure_targets:\n"
              "                continue\n"
              "            centre_px = hole.get('center_px')\n"
              "            if not centre_px:\n"
              "                continue\n"
              "            cx, cy = _map_pts([centre_px], mapping)[0]\n"
              "            if not (mapping['ox'] - 40 <= cx <= mapping['ox'] + mapping['tw'] + 40\n"
              "                    and mapping['oy'] - 40 <= cy <= mapping['oy'] + mapping['th'] + 40):\n"
              "                continue\n"
              "            ellipse = hole.get('ellipse')\n"
              "            if ellipse:\n"
              "                ec = _map_pts([ellipse['center']], mapping)[0]\n"
              "                # cv2.ellipse 的 axes 是\"半径\"，这里用拟合椭圆的半轴——圈就正好贴着孔口，\n"
              "                # 再往里收 10%，画成细环：不往外扩、也不盖住黄色的拟合椭圆。\n"
              "                axes = (max(3, int(ellipse['width'] * mapping['scale'] * 0.45)),\n"
              "                        max(3, int(ellipse['height'] * mapping['scale'] * 0.45)))\n"
              "                cv2.ellipse(canvas, tuple(np.round(ec).astype(int)), axes,\n"
              "                            ellipse['angle'], 0, 360, (80, 215, 95), 2, cv2.LINE_AA)\n"
              "            centre = (int(round(cx)), int(round(cy)))\n"
              "            cv2.circle(canvas, centre, 8, (80, 215, 95), -1)\n"
              "            cv2.circle(canvas, centre, 8, (255, 255, 255), 2, cv2.LINE_AA)\n"
              "            cv2.polylines(canvas, [np.array([[centre[0] - 4, centre[1] - 1],\n"
              "                                             [centre[0] - 1, centre[1] + 3],\n"
              "                                             [centre[0] + 5, centre[1] - 5]], np.int32)],\n"
              "                          False, (255, 255, 255), 2, cv2.LINE_AA)\n"
              "        return canvas\n"
              "\n"
              "    def resizeEvent(self, event):\n")],
            # 3b) 我们这一版的标签也跟着变绿（别人的版本对不上就跳过，不影响绿圈白勾）
            [("replace",
              "                text = f\"{hole['id']}  {hole['confidence']:.2f}\"\n",
              "                selected = hole['id'] in self.measure_targets\n"
              "                text = (f\">> {hole['id']}  {hole['confidence']:.2f}\" if selected\n"
              "                        else f\"{hole['id']}  {hole['confidence']:.2f}\")\n"),
             ("replace",
              "                tx = int(np.clip(cx + 10, mapping['ox'] + 3, max(mapping['ox'] + 3, mapping['ox'] + mapping['tw'] - width - 8)))\n",
              "                _dx = 26 if selected else 10     # [select-mark] 选中的孔留出绿点的位置\n"
              "                tx = int(np.clip(cx + _dx, mapping['ox'] + 3, max(mapping['ox'] + 3, mapping['ox'] + mapping['tw'] - width - 8)))\n"),
             ("replace",
              "                cv2.rectangle(canvas, (tx - 4, ty - height - 4), (tx + width + 4, ty + baseline + 4), (20, 35, 56), -1)\n"
              "                color = (170, 235, 255) if hole.get('reliable_center') else (50, 160, 255)\n",
              "                cv2.rectangle(canvas, (tx - 4, ty - height - 4), (tx + width + 4, ty + baseline + 4),\n"
              "                              (55, 170, 75) if selected else (20, 35, 56), -1)\n"
              "                color = ((255, 255, 255) if selected else\n"
              "                         ((170, 235, 255) if hole.get('reliable_center') else (50, 160, 255)))\n")],
            # 4) 点图和勾表格都要立刻重画
            [("replace",
              "        \"\"\"点孔后立刻把表格里的勾选状态同步过来\"\"\"\n"
              "        self.refresh_current_summary()\n",
              "        \"\"\"点孔后立刻把表格里的勾选状态同步过来\"\"\"\n"
              "        self.refresh_current_summary()\n"
              "        self.render_view()      # [select-mark] 图上立刻出现/去掉绿色圈和白勾\n")],
            # 5) 图例说明选中的样子
            [("replace",
              "        legend = QLabel('左格：相机实时画面（只看）　｜　右格：检测结果——青色孔轮廓、黄色拟合椭圆、'\n"
              "                        '红色十字圆心；直接点右格的孔即可选中/取消（要测量的孔）')\n",
              "        legend = QLabel('左格：相机实时画面（只看）　｜　右格：检测结果——青色孔轮廓、黄色拟合椭圆、'\n"
              "                        '红色十字圆心；点右格的孔即可选中/取消，选中的孔会套上绿色圈并打勾（要测量的孔）')\n")],
            # 5b) 绿圈别画大：贴着孔口 + 图例同步说清楚
            [("replace",
              "                        '红色十字圆心；点右格的孔即可选中/取消，选中的孔会套上绿色圈并打勾（要测量的孔）')\n",
              "                        '红色十字圆心；点右格的孔即可选中/取消，选中的孔椭圆变绿、圆心打勾（要测量的孔）')\n")],
        ]
        for group in groups:
            label = group[0][1].strip().splitlines()[0][:26]
            result, state = _apply_ops(text, group)
            if state == "missing":
                missing.append("gui: " + label)
            elif state == "done":
                skipped.append("gui: " + label)
            else:
                text = result
                applied.append("gui: " + label)
        if text != original:
            shutil.copy2(gui, gui.with_suffix(".py.bak"))
            gui.write_text(text, encoding="utf-8")

        # 勾表格也要在图上显示（只有带 measure_target_changed 的版本才有这一步）
        table_mark = "self.render_view()      # [select-mark] 勾表格也要在图上显示出来"
        table_line = "        self.log(f'本次测量清单：{chosen}')\n"
        if table_mark in text:
            skipped.append("勾表格重画")
        elif "def measure_target_changed(self)" not in text:
            skipped.append("勾表格重画（该版本没有这个方法）")
        elif table_line in text:
            gui.write_text(text.replace(table_line, table_line + "        " + table_mark + "\n", 1),
                           encoding="utf-8")
            applied.append("勾表格重画")
        else:
            missing.append("勾表格重画")
    else:
        missing.append("gui.py")

    if records.is_file():
        text = records.read_text(encoding="utf-8")
        original = text
        groups = [
            [("replace",
              "        delete_button = QPushButton('删除这一组')\n"
              "        delete_button.setToolTip('从实验记录里删除选中的整组（含该组所有照片的行），删除后无法撤销')\n",
              "        delete_button = QPushButton('删除整批记录')\n"
              "        delete_button.setToolTip('删除选中的这一批记录（这批的全部照片行）；删除后无法撤销，磁盘上的原图/结果图/报告不受影响')\n")],
            [("replace",
              "            \"孔号按图像位置排序。选中一行后可以：载入到工作区 / 打开原图 / 打开结果图 / 打开检测报告 / 删除这一组。\"\n",
              "            \"孔号按图像位置排序。选中一行后可以：载入到工作区 / 打开原图 / 打开结果图 / \"\n"
              "            \"打开检测报告 / 删除整批记录（把这一批的记录一起去掉）。\"\n")],
            [("replace",
              "        \"\"\"[records-tools] 删除选中的整组记录（二次确认）。\"\"\"\n",
              "        \"\"\"[records-tools] 删除选中的这一批记录（二次确认）。\"\"\"\n"),
             ("replace",
              "            QMessageBox.information(self, '请先选一行', '请先选中要删除的那一组里的任意一行。')\n",
              "            QMessageBox.information(self, '请先选一行', '请先选中要删除的那一批里的任意一行。')\n"),
             ("replace",
              "        number = row.get('group_number', '?')\n"
              "        confirm = QMessageBox.question(\n"
              "            self, '确认删除',\n"
              "            f'确定要从实验记录中删除「第{number}组」吗？\\n\\n'\n"
              "            '该组的全部照片记录都会被删除，删除后无法撤销。\\n'\n"
              "            '（磁盘上的原图、结果图、检测报告文件不会被删除）',\n",
              "        group_id = row.get('group_id', '')\n"
              "        number = row.get('group_number', '?')\n"
              "        batch = len(self.records.reports_of(group_id)) if group_id else 0\n"
              "        confirm = QMessageBox.question(\n"
              "            self, '确认删除',\n"
              "            f'要删除实验记录里的「第{number}组」吗？\\n\\n'\n"
              "            f'这批共 {batch} 张照片，整批记录都会从实验记录里去掉，删除后无法撤销。\\n'\n"
              "            '磁盘上的原图、结果图、检测报告文件都会保留（需要的话可以重新检测一遍）。',\n"),
             ("replace",
              "        ok, message = self.records.delete_group(row.get('group_id', ''))\n",
              "        ok, message = self.records.delete_group(group_id)\n")],
        ]
        for group in groups:
            label = group[0][1].strip().splitlines()[0][:26]
            result, state = _apply_ops(text, group)
            if state == "missing":
                missing.append("records_view: " + label)
            elif state == "done":
                skipped.append("records_view: " + label)
            else:
                text = result
                applied.append("records_view: " + label)
        if text != original:
            shutil.copy2(records, records.with_suffix(".py.bak"))
            records.write_text(text, encoding="utf-8")
    else:
        missing.append("records_view.py")

    if data.is_file():
        text = data.read_text(encoding="utf-8")
        original = text
        old = "                return True, f'第{number}组（{count} 张）已从实验记录中删除；原图与结果文件未删除。'\n"
        new = "                return True, f'这批记录（第{number}组，{count} 张）已删除；原图与结果文件都还在。'\n"
        if new in text:
            skipped.append("experiment_records: 删除说明")
        elif old in text:
            data.write_text(text.replace(old, new, 1), encoding="utf-8")
            applied.append("experiment_records: 删除说明")
        else:
            missing.append("experiment_records: 删除说明")
    else:
        missing.append("experiment_records.py")

    if not applied:
        if not missing:
            return "已是最新（无需修改）"
        return "未匹配: " + "; ".join(missing[:4])
    out = ["已改 {} 处（点孔反馈 + 删除措辞）".format(len(applied))]
    if missing:
        out.append("未匹配: " + "; ".join(missing[:4]))
    return "；".join(out)


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
    print("5b) Qt目录  :", patch_qt_photo_dir(engine))
    print("6) Tk 配色  :", patch_tk_dark_mode(engine))
    print("7) 界面布局 :", patch_ui_layout(engine))
    print("8) 3D 场景  :", patch_3d_scene(engine))
    print("9) 界面重排 :", patch_ui_redesign(engine))
    print("9b) 画布配色:", patch_canvas_theme(engine))
    print("9c) 弹窗布局:", patch_dialog_layouts(engine))
    print("9d) 浅色外框:", patch_light_frame(engine))
    print("9e) 空白启动:", patch_fresh_start(engine))
    print("9f) 批次历史:", patch_batch_history(engine))
    print("9g) 诊断样式:", patch_diagnostics_style(engine))
    print("9h) 左栏紧凑:", patch_left_column(engine))
    print("9i) 诊断紧凑:", patch_diagnostics_compact(engine))
    print("9j) 收尾清理:", patch_tidy_signals(engine))
    print("9k) 设备页紧凑:", patch_device_page_compact(engine))
    print("9l) 批次弹窗:", patch_batch_dialog_details(engine))
    print("9m) 融合同步:", patch_fusion_sync(engine))
    print("9n) 相机接入:", patch_camera_sync(engine))
    print("9o) 扩展模块:", deploy_app_addons(engine))
    print("9p) 实时预览:", patch_camera_preview(engine))
    print("9q) 设备状态:", patch_device_state_sync(engine))
    print("9r) 自动连相机:", patch_auto_connect(engine))
    print("9s) 记录数据层:", patch_records_data(engine))
    print("9t) 记录窗口:", patch_records_tools(engine))
    print("9u) 检测区实时:", patch_canvas_live(engine))
    print("9v) 设备自适应:", patch_device_autofill(engine))
    print("9w) 合并入口  :", patch_merge_history(engine))
    print("9x) 参数不落盘:", patch_no_local_config(engine))
    print("9y) 视觉分屏  :", patch_split_view(engine))
    print("9z) 点孔反馈  :", patch_selection_feedback(engine))
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
