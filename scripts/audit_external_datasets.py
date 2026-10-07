# -*- coding: utf-8 -*-
"""
外部数据集审计脚本
==================
扫描 external_datasets 下的候选数据集目录，统计：
  图片数量/格式/宽/高/宽高比、label 数、bbox 数、segmentation 数、
  类别数量/名称、空标注数、损坏图片数
并生成：
  external_datasets\audit\<dataset>_preview.jpg     最多 20 张 contact sheet（画 mask/bbox）
  external_datasets\reports\<dataset>_audit.html    单数据集 HTML 报告
  external_datasets\metadata\audit_summary.json     机器可读汇总

支持 YOLO(labels/*.txt) / COCO(*.json) 类别名 / VOC(*.xml) / 纯图片目录。

用法：
    python scripts\audit_external_datasets.py
"""

import argparse
import json
import random
import sys
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

PROJ = Path(r"E:\robot_inspection")
EXT = PROJ / "external_datasets"
AUDIT = EXT / "audit"
REPORTS = EXT / "reports"
META = EXT / "metadata"
IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
MAX_PREVIEW = 20
THUMB = 320
SEED = 0


def collect_images(root):
    return sorted([p for p in root.rglob("*") if p.suffix.lower() in IMG_EXTS])


def load_class_names(root):
    for name in ("data.yaml", "data.yml"):
        for p in root.rglob(name):
            try:
                import yaml
                d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
                if isinstance(d, dict) and "names" in d:
                    n = d["names"]
                    return list(n.values()) if isinstance(n, dict) else list(n)
            except Exception:
                pass
    for name in ("obj.names", "classes.txt", "categories.txt"):
        for p in root.rglob(name):
            try:
                return [l.strip() for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
            except Exception:
                pass
    for js in root.rglob("*.json"):
        try:
            d = json.loads(js.read_text(encoding="utf-8"))
            if isinstance(d, dict) and "categories" in d:
                return [c.get("name") for c in d["categories"]]
        except Exception:
            pass
    return []


def parse_yolo_label(txt):
    nb = ns = 0
    ids = []
    try:
        lines = [l.strip() for l in txt.read_text(encoding="utf-8", errors="ignore").splitlines() if l.strip()]
    except Exception:
        return 0, 0, [], True
    for l in lines:
        parts = l.split()
        if len(parts) < 5:
            continue
        try:
            ids.append(int(float(parts[0])))
        except Exception:
            continue
        n = len(parts) - 5
        if n >= 6 and n % 2 == 0:
            ns += 1
        else:
            nb += 1
    return nb, ns, ids, (len(lines) == 0)


def find_label_for(img):
    cands = [img.with_suffix(".txt")]
    s = str(img)
    for a, b in (("\\images\\", "\\labels\\"), ("/images/", "/labels/")):
        if a in s:
            cands.append(Path(s.replace(a, b)).with_suffix(".txt"))
    for c in cands:
        if c.is_file():
            return c
    return None


def audit_dataset(name, root):
    images = collect_images(root)
    classes = load_class_names(root)
    info = {"name": name, "path": str(root), "image_count": len(images),
            "formats": {}, "widths": [], "heights": [], "aspect": [],
            "label_files": 0, "bbox_count": 0, "seg_count": 0, "empty_labels": 0,
            "corrupt": [], "class_ids": [], "class_names": classes,
            "segmentation_format": "none", "has_bbox": False, "has_segmentation": False,
            "class_count": len(classes)}
    if not images:
        return info

    for img in images:
        info["formats"][img.suffix.lower()] = info["formats"].get(img.suffix.lower(), 0) + 1
        im = cv2.imread(str(img))
        if im is None:
            info["corrupt"].append(str(img))
        else:
            h, w = im.shape[:2]
            info["widths"].append(w)
            info["heights"].append(h)
            info["aspect"].append(w / h if h else 0)
        lbl = find_label_for(img)
        if lbl:
            info["label_files"] += 1
            nb, ns, ids, empty = parse_yolo_label(lbl)
            info["bbox_count"] += nb
            info["seg_count"] += ns
            info["class_ids"] += ids
            if empty:
                info["empty_labels"] += 1

    info["has_bbox"] = info["bbox_count"] > 0
    info["has_segmentation"] = info["seg_count"] > 0
    if info["seg_count"] and not info["bbox_count"]:
        info["segmentation_format"] = "yolo-seg (polygon)"
    elif info["seg_count"]:
        info["segmentation_format"] = "yolo-seg (polygon) + partial boxes"
    if info["class_ids"]:
        info["class_count"] = len(set(info["class_ids"]))

    def stat(a):
        if not a:
            return None
        if isinstance(a[0], int):
            return {"min": int(min(a)), "max": int(max(a)), "mean": round(float(np.mean(a)), 1)}
        return {"min": round(min(a), 3), "max": round(max(a), 3), "mean": round(float(np.mean(a)), 3)}

    info["width_stat"] = stat(info["widths"])
    info["height_stat"] = stat(info["heights"])
    info["aspect_stat"] = stat(info["aspect"])
    info["images"] = [str(p) for p in images]
    return info


def make_preview(name, info, out_dir, max_n=MAX_PREVIEW):
    random.seed(SEED)
    imgs = info["images"]
    if not imgs:
        return None
    sel = random.sample(imgs, min(max_n, len(imgs)))
    tiles = []
    for s in sel:
        img = cv2.imread(s)
        if img is None:
            continue
        h0, w0 = img.shape[:2]
        tile = cv2.resize(img, (THUMB, THUMB))
        lbl = find_label_for(Path(s))
        if lbl and lbl.is_file():
            polys, boxes = [], []
            try:
                lines = [l.split() for l in lbl.read_text(encoding="utf-8", errors="ignore").splitlines() if l.strip()]
            except Exception:
                lines = []
            for parts in lines:
                if len(parts) < 5:
                    continue
                try:
                    nums = [float(v) for v in parts[1:]]
                except Exception:
                    continue
                if len(nums) >= 6 and len(nums) % 2 == 0:
                    polys.append(nums)
                elif len(nums) == 4:
                    boxes.append(nums)
            for cx, cy, bw, bh in boxes:
                x1, y1 = int((cx - bw / 2) * THUMB), int((cy - bh / 2) * THUMB)
                x2, y2 = int((cx + bw / 2) * THUMB), int((cy + bh / 2) * THUMB)
                cv2.rectangle(tile, (x1, y1), (x2, y2), (0, 255, 0), 2)
            if polys:
                ov = tile.copy()
                for poly in polys:
                    pts = np.array([[int(poly[i] * THUMB), int(poly[i + 1] * THUMB)]
                                    for i in range(0, len(poly), 2)], np.int32)
                    cv2.fillPoly(ov, [pts], (0, 255, 0))
                    cv2.polylines(tile, [pts], True, (0, 255, 0), 2)
                tile = cv2.addWeighted(ov, 0.35, tile, 0.65, 0)
        tiles.append(tile)
    if not tiles:
        return None
    cols = 5
    rows = (len(tiles) + cols - 1) // cols
    sheet = np.full((rows * THUMB, cols * THUMB, 3), 245, np.uint8)
    for i, t in enumerate(tiles):
        r, c = divmod(i, cols)
        sheet[r * THUMB:(r + 1) * THUMB, c * THUMB:(c + 1) * THUMB] = t
    out = out_dir / "{}_preview.jpg".format(name)
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), sheet, [cv2.IMWRITE_JPEG_QUALITY, 88])
    return out


HTML = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>数据集审计 - {name}</title><style>
body{{margin:0;padding:28px;background:#f5f7fa;color:#1f2937;
font-family:"Segoe UI","Microsoft YaHei",sans-serif}}
.wrap{{max-width:1000px;margin:0 auto;background:#fff;border:1px solid #e2e8f0;
border-radius:14px;padding:28px 32px}}
h1{{font-size:24px;margin:0 0 6px}}
h2{{font-size:18px;margin:26px 0 10px;border-left:5px solid #2563eb;padding-left:10px}}
table{{border-collapse:collapse;width:100%;font-size:14px;margin:10px 0}}
th,td{{border:1px solid #e2e8f0;padding:7px 10px;text-align:left}}
th{{background:#eef2f7}}
code{{background:#f1f5f9;padding:1px 5px;border-radius:4px;font-family:Consolas,monospace;font-size:13px}}
img{{max-width:100%;border:1px solid #e2e8f0;border-radius:10px}}
.muted{{color:#6b7280;font-size:13px}}
</style></head><body><div class="wrap">
<h1>外部数据集审计：{name}</h1>
<div class="muted">目录：<code>{path}</code><br>生成时间：{now}</div>
<h2>统计</h2><table>
<tr><th>项目</th><th>值</th></tr>
<tr><td>图片数量</td><td>{image_count}</td></tr>
<tr><td>图片格式</td><td>{formats}</td></tr>
<tr><td>宽度 (min/mean/max)</td><td>{w}</td></tr>
<tr><td>高度 (min/mean/max)</td><td>{h}</td></tr>
<tr><td>宽高比 (min/mean/max)</td><td>{a}</td></tr>
<tr><td>label 文件数</td><td>{label_files}</td></tr>
<tr><td>bbox 数量</td><td>{bbox}</td></tr>
<tr><td>segmentation 数量</td><td>{seg}</td></tr>
<tr><td>segmentation 形式</td><td>{segfmt}</td></tr>
<tr><td>类别数量</td><td>{nclass}</td></tr>
<tr><td>类别名称</td><td>{cnames}</td></tr>
<tr><td>空标注数量</td><td>{empty}</td></tr>
<tr><td>损坏图片数量</td><td>{ncorrupt}</td></tr>
</table>
<h2>抽样预览（最多 {maxp} 张，绿色 = mask / bbox）</h2>
{imgtag}
</div></body></html>"""


def write_html(name, info, preview, out, base):
    def rel(p):
        try:
            return str(Path(p).relative_to(base)).replace("\\", "/")
        except Exception:
            return str(p).replace("\\", "/")

    imgtag = '<img src="{}" alt="preview">'.format(rel(preview)) if preview \
        else '<p class="muted">（无可预览图片）</p>'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(HTML.format(
        name=name, path=info["path"], now=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        image_count=info["image_count"], formats=info["formats"],
        w=info.get("width_stat"), h=info.get("height_stat"), a=info.get("aspect_stat"),
        label_files=info["label_files"], bbox=info["bbox_count"], seg=info["seg_count"],
        segfmt=info["segmentation_format"], nclass=info["class_count"],
        cnames=info["class_names"] or "未确认", empty=info["empty_labels"],
        ncorrupt=len(info["corrupt"]), maxp=MAX_PREVIEW, imgtag=imgtag), encoding="utf-8")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default=None)
    args = ap.parse_args()
    for d in (AUDIT, REPORTS, META):
        d.mkdir(parents=True, exist_ok=True)

    if args.dataset:
        targets = [Path(args.dataset)]
    else:
        targets = sorted([d for d in EXT.iterdir() if d.is_dir() and d.name.startswith("dataset_")])
    if not targets:
        print("[提示] 没有找到 dataset_* 目录")
        return 0

    summary = []
    for t in targets:
        print("审计:", t.name)
        info = audit_dataset(t.name, t)
        preview = make_preview(t.name, info, AUDIT)
        rep = write_html(t.name, info, preview, REPORTS / "{}_audit.html".format(t.name), REPORTS)
        summary.append({k: v for k, v in info.items() if k != "images"})
        print("   图片 {}  标签 {}  bbox {}  seg {}  类别 {}  损坏 {}".format(
            info["image_count"], info["label_files"], info["bbox_count"],
            info["seg_count"], info["class_count"], len(info["corrupt"])))
        print("   预览: {}".format(preview))
        print("   报告: {}".format(rep))

    (META / "audit_summary.json").write_text(
        json.dumps({"generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "datasets": summary}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n汇总:", META / "audit_summary.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
