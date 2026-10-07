# -*- coding: utf-8 -*-
"""
训练结果可视化报告生成脚本
--------------------------
读取最近一次 YOLO 训练目录，生成一个 HTML 报告。

【只读脚本】不会训练、不会修改模型、不会修改任何 run 产物，只新增一个 HTML 文件。

用法：
    python scripts\\make_training_report.py
    python scripts\\make_training_report.py --run E:\\robot_inspection\\runs\\box_yolo_yolo11n_seg
    python scripts\\make_training_report.py --out E:\\robot_inspection\\results\\training_report.html
"""

import argparse
import csv
import hashlib
import html
import os
import sys
from datetime import datetime
from pathlib import Path

PROJ = Path(r"E:\robot_inspection")
RUNS_DIR = PROJ / "runs"
RESULTS_DIR = PROJ / "results"
DATASET_DIR = PROJ / "dataset" / "box_yolo"
DATASET_YAML = DATASET_DIR / "data.yaml"
WEIGHTS_DIR = PROJ / "weights"
IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}


# --------------------------------------------------------------------------
# 工具
# --------------------------------------------------------------------------
def find_latest_run(runs_dir: Path):
    """找出最近一次有 results.csv 的训练目录（优先非 smoke 实验）。"""
    cands = []
    if runs_dir.is_dir():
        for d in runs_dir.iterdir():
            csv_path = d / "results.csv"
            if d.is_dir() and csv_path.is_file():
                cands.append((csv_path.stat().st_mtime, d))
    if not cands:
        return None
    real = [c for c in cands if "smoke" not in c[1].name.lower()]
    return max(real or cands, key=lambda x: x[0])[1]


def read_yaml(p: Path):
    try:
        import yaml
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def count_images(d: Path) -> int:
    if not d.is_dir():
        return 0
    return len([p for p in d.iterdir() if p.suffix.lower() in IMG_EXTS])


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def rel_src(p: Path, base: Path) -> str:
    """生成 HTML 用的相对路径（正斜杠，可含中文）。"""
    try:
        return os.path.relpath(str(p), str(base)).replace("\\", "/")
    except Exception:
        return str(p).replace("\\", "/")


def fmt(v, nd=4):
    try:
        return "{:.{}f}".format(float(v), nd)
    except Exception:
        return str(v)


def img_block(path: Path, base: Path, title: str, note: str = "") -> str:
    """生成一张图片卡片；文件不存在时给出提示而不是报错。"""
    if not path.is_file():
        return ('<div class="card"><div class="card-title">{}</div>'
                '<div class="missing">（未找到该图片：{}）</div></div>').format(
            html.escape(title), html.escape(path.name))
    note_html = '<div class="card-note">{}</div>'.format(html.escape(note)) if note else ""
    return ('<div class="card"><div class="card-title">{}</div>'
            '<a href="{src}" target="_blank"><img src="{src}" alt="{alt}"></a>'
            '{note}</div>').format(
        html.escape(title), src=rel_src(path, base), alt=html.escape(title), note=note_html)


def pick(run_dir: Path, *names):
    """按顺序返回第一个存在的文件。"""
    for n in names:
        p = run_dir / n
        if p.is_file():
            return p
    return run_dir / names[0]


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default=None, help="指定训练目录；默认自动选最近一次")
    ap.add_argument("--out", default=str(RESULTS_DIR / "training_report.html"))
    args = ap.parse_args()

    run_dir = Path(args.run) if args.run else find_latest_run(RUNS_DIR)
    if run_dir is None or not run_dir.is_dir():
        print("[错误] 找不到任何包含 results.csv 的训练目录（{}）".format(RUNS_DIR))
        return 2

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    cfg = read_yaml(run_dir / "args.yaml")
    csv_path = run_dir / "results.csv"
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8"))) if csv_path.is_file() else []

    # ---- 指标计算 --------------------------------------------------------
    KB, KM = "metrics/mAP50-95(B)", "metrics/mAP50-95(M)"

    def fitness(r):
        try:
            return 0.1 * float(r[KB]) + 0.9 * float(r[KM])   # Ultralytics 对 segment 任务的适应度
        except Exception:
            return -1.0

    best_row = max(rows, key=fitness) if rows else {}
    last_row = rows[-1] if rows else {}
    best_epoch = int(float(best_row.get("epoch", 0))) if best_row else 0
    n_epochs = len(rows)

    # ---- 数据集 ----------------------------------------------------------
    n_train = count_images(DATASET_DIR / "images" / "train")
    n_val = count_images(DATASET_DIR / "images" / "val")
    n_test = count_images(DATASET_DIR / "images" / "test")

    # ---- 设备 ------------------------------------------------------------
    device_txt = str(cfg.get("device", "0"))
    try:
        import torch
        if torch.cuda.is_available():
            device_txt = "{}  (device={}, VRAM {:.2f} GB)".format(
                torch.cuda.get_device_name(0), cfg.get("device", "0"),
                torch.cuda.get_device_properties(0).total_memory / 1024 ** 3)
    except Exception:
        pass

    # ---- 模型文件 --------------------------------------------------------
    run_best = run_dir / "weights" / "best.pt"
    perm_best = WEIGHTS_DIR / "best.pt"
    model_rows = []
    for label, p in [("本次 run 的 best.pt", run_best), ("永久保存的 best.pt", perm_best)]:
        if p.is_file():
            st = p.stat()
            model_rows.append(
                "<tr><td>{}</td><td>{}</td><td>{}</td><td class='path'>{}</td>"
                "<td class='mono small'>{}</td></tr>".format(
                    html.escape(label),
                    "{:,} 字节 ({:.2f} MB)".format(st.st_size, st.st_size / 1024 ** 2),
                    datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                    html.escape(str(p)),
                    sha256_file(p)[:16] + "…"))
        else:
            model_rows.append("<tr><td>{}</td><td colspan='4'>未找到：{}</td></tr>".format(
                html.escape(label), html.escape(str(p))))

    # ---- 图片清单 --------------------------------------------------------
    curves = [
        img_block(pick(run_dir, "results.png"), out_path.parent, "训练总曲线 results.png",
                  "loss / precision / recall / mAP 随 epoch 变化"),
        img_block(pick(run_dir, "MaskPR_curve.png"), out_path.parent, "分割 PR 曲线 MaskPR_curve.png"),
        img_block(pick(run_dir, "MaskF1_curve.png"), out_path.parent, "分割 F1 曲线 MaskF1_curve.png"),
        img_block(pick(run_dir, "BoxPR_curve.png"), out_path.parent, "检测框 PR 曲线 BoxPR_curve.png"),
        img_block(pick(run_dir, "BoxF1_curve.png"), out_path.parent, "检测框 F1 曲线 BoxF1_curve.png"),
    ]
    matrix = [
        img_block(pick(run_dir, "confusion_matrix.png"), out_path.parent, "混淆矩阵 confusion_matrix.png"),
        img_block(pick(run_dir, "confusion_matrix_normalized.png"), out_path.parent,
                  "归一化混淆矩阵 confusion_matrix_normalized.png"),
        img_block(pick(run_dir, "labels.jpg"), out_path.parent, "标签分布 labels.jpg"),
    ]
    batches = [img_block(p, out_path.parent, p.name) for p in sorted(run_dir.glob("train_batch*.jpg"))]
    valcards = [img_block(p, out_path.parent, p.name) for p in sorted(run_dir.glob("val_batch*.jpg"))]

    # ---- HTML ------------------------------------------------------------
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    css = """
    :root{--bg:#f5f7fa;--card:#fff;--line:#e2e8f0;--txt:#1f2937;--muted:#6b7280;
          --blue:#2563eb;--green:#16a34a;--amber:#d97706;--red:#dc2626;}
    *{box-sizing:border-box}
    body{margin:0;padding:28px;background:var(--bg);color:var(--txt);
         font-family:"Segoe UI","Microsoft YaHei",system-ui,sans-serif;line-height:1.6}
    h1{font-size:26px;margin:0 0 6px}
    h2{font-size:19px;margin:34px 0 14px;padding-left:10px;border-left:5px solid var(--blue)}
    .sub{color:var(--muted);font-size:13px;margin-bottom:20px}
    .panel{background:var(--card);border:1px solid var(--line);border-radius:12px;
           padding:18px 20px;margin-bottom:18px;box-shadow:0 1px 2px rgba(0,0,0,.04)}
    table{border-collapse:collapse;width:100%;font-size:14px}
    th,td{border:1px solid var(--line);padding:8px 10px;text-align:left;vertical-align:top}
    th{background:#eef2f7;font-weight:600;white-space:nowrap}
    td.num{font-variant-numeric:tabular-nums;font-weight:600}
    td.path{word-break:break-all;font-size:12px;color:var(--muted)}
    .mono{font-family:Consolas,monospace}
    .small{font-size:12px}
    .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:16px}
    .card{background:var(--card);border:1px solid var(--line);border-radius:12px;
          padding:12px;box-shadow:0 1px 2px rgba(0,0,0,.04)}
    .card-title{font-size:13px;font-weight:600;margin-bottom:8px;color:#374151}
    .card-note{font-size:12px;color:var(--muted);margin-top:6px}
    .card img{width:100%;height:auto;border-radius:8px;border:1px solid var(--line);display:block}
    .missing{font-size:12px;color:var(--amber);padding:10px;background:#fffbeb;border-radius:8px}
    .kpi{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
    .kpi div{background:#eef6ff;border:1px solid #dbeafe;border-radius:10px;padding:12px 14px}
    .kpi b{display:block;font-size:22px;color:var(--blue);font-variant-numeric:tabular-nums}
    .kpi span{font-size:12px;color:var(--muted)}
    .tag{display:inline-block;padding:2px 8px;border-radius:999px;font-size:12px;font-weight:600}
    .tag-ok{background:#dcfce7;color:#166534}
    """
    parts = []
    A = parts.append
    A("<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>")
    A("<title>训练结果报告 - {}</title>".format(html.escape(run_dir.name)))
    A("<style>{}</style></head><body>".format(css))
    A("<h1>YOLO-Seg 训练结果报告</h1>")
    A("<div class='sub'>实验目录：<span class='mono'>{}</span><br>报告生成时间：{}</div>".format(
        html.escape(str(run_dir)), now))

    # 训练基本信息
    A("<h2>训练基本信息</h2><div class='panel'><table>")
    info = [
        ("模型", str(cfg.get("model", "yolo11n-seg.pt"))),
        ("任务", str(cfg.get("task", "segment"))),
        ("数据集", "box_yolo"),
        ("训练图像", "{} 张".format(n_train)),
        ("验证图像", "{} 张".format(n_val)),
        ("测试图像", "{} 张".format(n_test)),
        ("设备", device_txt),
        ("输入尺寸 imgsz", str(cfg.get("imgsz", "-"))),
        ("batch", str(cfg.get("batch", "-"))),
        ("epochs（设定 / 实际）", "{} / {}".format(cfg.get("epochs", "-"), n_epochs)),
        ("patience", str(cfg.get("patience", "-"))),
        ("workers", str(cfg.get("workers", "-"))),
        ("随机种子 seed", str(cfg.get("seed", "-"))),
        ("deterministic", str(cfg.get("deterministic", "-"))),
        ("AMP 混合精度", str(cfg.get("amp", "-"))),
        ("数据配置 data", str(cfg.get("data", "-"))),
    ]
    for k, v in info:
        A("<tr><th style='width:230px'>{}</th><td>{}</td></tr>".format(
            html.escape(k), html.escape(v)))
    A("</table></div>")

    # 训练指标
    A("<h2>训练指标</h2><div class='panel'>")
    A("<div class='kpi'>")
    for label, key in [("Precision (Mask)", "metrics/precision(M)"),
                       ("Recall (Mask)", "metrics/recall(M)"),
                       ("mAP50 (Mask)", "metrics/mAP50(M)"),
                       ("mAP50-95 (Mask)", "metrics/mAP50-95(M)")]:
        A("<div><b>{}</b><span>{}</span></div>".format(
            fmt(best_row.get(key)) if best_row else "-", html.escape(label)))
    A("<div><b>{}</b><span>最好 epoch</span></div>".format(best_epoch))
    A("<div><b>{}</b><span>训练 epoch 数</span></div>".format(n_epochs))
    A("</div>")
    A("<p class='small' style='color:#6b7280;margin:14px 0 8px'>"
      "'最好 epoch' 按 Ultralytics 对分割任务的适应度计算："
      "fitness = 0.1 × mAP50-95(Box) + 0.9 × mAP50-95(Mask)，即 best.pt 对应的轮次。</p>")
    A("<table><tr><th>指标</th><th>最好 epoch（第 {} 轮）</th>"
      "<th>最后一轮（第 {} 轮）</th></tr>".format(best_epoch, n_epochs))
    for label, key in [("Precision (Mask)", "metrics/precision(M)"),
                       ("Recall (Mask)", "metrics/recall(M)"),
                       ("mAP50 (Mask)", "metrics/mAP50(M)"),
                       ("mAP50-95 (Mask)", "metrics/mAP50-95(M)"),
                       ("Precision (Box)", "metrics/precision(B)"),
                       ("Recall (Box)", "metrics/recall(B)"),
                       ("mAP50 (Box)", "metrics/mAP50(B)"),
                       ("mAP50-95 (Box)", "metrics/mAP50-95(B)")]:
        A("<tr><th>{}</th><td class='num'>{}</td><td class='num'>{}</td></tr>".format(
            html.escape(label), fmt(best_row.get(key)) if best_row else "-",
            fmt(last_row.get(key)) if last_row else "-"))
    A("</table></div>")

    A("<h2>训练曲线</h2><div class='grid'>{}</div>".format("".join(curves)))
    A("<h2>混淆矩阵与标签分布</h2><div class='grid'>{}</div>".format("".join(matrix)))
    if batches:
        A("<h2>训练样例（train_batch）</h2><div class='grid'>{}</div>".format("".join(batches)))
    if valcards:
        A("<h2>验证集样例（val_batch）</h2><div class='grid'>{}</div>".format("".join(valcards)))

    A("<h2>模型文件</h2><div class='panel'><table>")
    A("<tr><th>说明</th><th>文件大小</th><th>修改时间</th><th>路径</th><th>SHA256(前缀)</th></tr>")
    A("".join(model_rows))
    A("</table><p class='small' style='color:#6b7280;margin-top:10px'>"
      "本报告为只读展示：不训练、不修改 best.pt、不修改任何训练产物。</p></div>")

    A("<p class='sub'>原始训练目录：<span class='mono'>{}</span></p>".format(html.escape(str(run_dir))))
    A("</body></html>")

    out_path.write_text("\n".join(parts), encoding="utf-8")
    print("[OK] 训练报告已生成：{}".format(out_path))
    print("     数据来源 run：{}".format(run_dir))
    print("     共 {} 轮，最好 epoch = {}，Mask mAP50-95 = {}".format(
        n_epochs, best_epoch, fmt(best_row.get(KM)) if best_row else "-"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
