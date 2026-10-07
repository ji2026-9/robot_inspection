# -*- coding: utf-8 -*-
"""
正式训练对照实验：统一测试 + 统计 + 报告
========================================
对 experiments\\formal_seed{0,42,123} 里的 best.pt 与 last.pt，
在 4 张测试图片上各跑一遍，输出：

  experiments\\formal_comparison.json          逐条记录 (seed / weight / image / hole / confidence)
  experiments\\formal_comparison.csv           每个 (seed, weight) 一行，16 列 confidence + 统计
  experiments\\formal_comparison_report.html   最终对比报告
  experiments\\formal_seedN\\results\\<图片>_<best|last>_result.jpg   预测可视化

编号约定（本对照实验采用）：
  Hole1 ~ Hole4 = 按图像 y 坐标从小到大，即“从上到下”。
  注意：这与 predict_holes.py 沿 PCA 主轴排序得到的 H01~H04 方向可能相反。
  测试3 的反光孔 = 从上往下第 3 个孔（中心 y ≈ 2559）。

用法：
    python scripts\\make_formal_comparison.py
"""

import argparse
import csv
import html
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

PROJ = Path(r"E:\robot_inspection")
EXP_DIR = PROJ / "experiments"
TEST_DIR = PROJ / "test_images"
SEEDS = [0, 42, 123]
WEIGHT_TYPES = [("best", "best.pt"), ("last", "last.pt")]
IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}

CONF_FLOOR = 0.05
CONF_MAIN = 0.50
REFLECTIVE_XY = (1434.8, 2559.2)


def ellipse_from_mask(mask_bool):
    m = (mask_bool.astype(np.uint8)) * 255
    contours, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return None, None
    cnt = max(contours, key=cv2.contourArea)
    if len(cnt) < 5:
        return None, cnt
    return cv2.fitEllipse(cnt), cnt


def list_test_images():
    if not TEST_DIR.is_dir():
        return []
    return sorted([p for p in TEST_DIR.iterdir()
                   if p.suffix.lower() in IMG_EXTS and p.stem.startswith("测试")])


def draw_result(img, holes, out_path, title):
    if img is None:
        return
    overlay = img.copy()
    for h in holes:
        overlay[h["mask_bool"]] = h["color"]
    vis = cv2.addWeighted(overlay, 0.35, img, 0.65, 0)

    for h in holes:
        if h["contour"] is not None:
            cv2.drawContours(vis, [h["contour"]], -1, (255, 255, 255), 2)
        (cx, cy), (MA, ma), ang = h["ellipse"]
        col = (0, 255, 0) if h["conf"] >= CONF_MAIN else (0, 200, 255)
        cv2.ellipse(vis, ((cx, cy), (MA, ma), ang), col, 3)
        cv2.circle(vis, (int(round(cx)), int(round(cy))), 6, (0, 0, 255), -1)
        cv2.circle(vis, (int(round(cx)), int(round(cy))), 9, (255, 255, 255), 2)
        label = "{}  conf={:.3f}{}".format(h["hole_id"], h["conf"],
                                           "  LOW" if h["conf"] < CONF_MAIN else "")
        tx, ty = int(round(cx)) + 12, int(round(cy)) - 12
        cv2.putText(vis, label, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 4, cv2.LINE_AA)
        cv2.putText(vis, label, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA)

    cv2.putText(vis, title, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 5, cv2.LINE_AA)
    cv2.putText(vis, title, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 255), 2, cv2.LINE_AA)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_path), vis)


def read_train_metrics(run_dir):
    csv_path = run_dir / "results.csv"
    if not csv_path.is_file():
        return None
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))
    if not rows:
        return None

    def g(r, k):
        try:
            return float(r[k])
        except Exception:
            return 0.0

    kb, km = "metrics/mAP50-95(B)", "metrics/mAP50-95(M)"
    best = max(rows, key=lambda r: 0.1 * g(r, kb) + 0.9 * g(r, km))
    return {
        "epochs_run": len(rows),
        "best_epoch": int(float(best.get("epoch", 0))),
        "seconds": g(rows[-1], "time"),
        "precision": g(best, "metrics/precision(M)"),
        "recall": g(best, "metrics/recall(M)"),
        "map50": g(best, "metrics/mAP50(M)"),
        "map5095": g(best, "metrics/mAP50-95(M)"),
    }


def rel_src(p, base):
    try:
        return os.path.relpath(str(p), str(base)).replace("\\", "/")
    except Exception:
        return str(p).replace("\\", "/")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--device", default="0")
    args = ap.parse_args()

    images = list_test_images()
    if not images:
        print("[错误] 在 {} 里找不到测试图片".format(TEST_DIR))
        return 2

    from ultralytics import YOLO

    records = []
    matrix = {}
    per_run = []
    train_metrics = {}

    for seed in SEEDS:
        run_dir = EXP_DIR / "formal_seed{}".format(seed) / "runs" / "yolo11n_seg_seed{}".format(seed)
        tm = read_train_metrics(run_dir)
        train_metrics[seed] = tm
        if tm:
            print("[训练指标] seed={}  轮数={}  best_epoch={}  P={:.4f} R={:.4f} mAP50={:.4f} mAP50-95={:.4f}  用时={:.0f}s".format(
                seed, tm["epochs_run"], tm["best_epoch"], tm["precision"], tm["recall"],
                tm["map50"], tm["map5095"], tm["seconds"]))
        else:
            print("[警告] seed={} 读不到训练指标（{}）".format(seed, run_dir))

        for wname, wfile in WEIGHT_TYPES:
            wpath = EXP_DIR / "formal_seed{}".format(seed) / "weights" / wfile
            if not wpath.is_file():
                print("[失败] 找不到权重：{}   —— 该组测试跳过".format(wpath))
                continue

            print("\n>>> 测试 seed={}  weight={}  ({})".format(seed, wname, wpath))
            model = YOLO(str(wpath))
            key = (seed, wname)
            matrix[key] = {}
            row = {"seed": seed, "weight": wname, "counts": {}, "reflective": None,
                   "all_conf": [], "n_low": 0}

            for img_path in images:
                stem = img_path.stem
                r = model.predict(source=str(img_path), conf=CONF_FLOOR, iou=0.7,
                                  imgsz=args.imgsz, device=args.device,
                                  retina_masks=True, verbose=False)[0]
                n = 0 if r.masks is None else len(r.masks)

                dets = []
                for i in range(n):
                    mask = r.masks.data[i].cpu().numpy() > 0.5
                    conf = float(r.boxes.conf[i].cpu().numpy())
                    ell, cnt = ellipse_from_mask(mask)
                    if ell is None:
                        continue
                    (cx, cy), (MA, ma), ang = ell
                    dets.append({"conf": conf, "ellipse": ell, "contour": cnt,
                                 "mask_bool": mask, "center": (float(cx), float(cy)),
                                 "cx": float(cx), "cy": float(cy),
                                 "width": float(MA), "height": float(ma), "angle": float(ang),
                                 "color": [(0, 200, 0), (0, 140, 255), (255, 120, 0), (200, 0, 200)][i % 4]})

                n_conf50 = sum(1 for d in dets if d["conf"] >= CONF_MAIN)
                row["counts"][stem] = n_conf50
                row["n_low"] += sum(1 for d in dets if d["conf"] < CONF_MAIN)
                row["all_conf"] += [d["conf"] for d in dets]

                dets.sort(key=lambda d: d["conf"], reverse=True)
                top = dets[:4]
                top.sort(key=lambda d: d["cy"])
                for idx, d in enumerate(top, start=1):
                    d["hole_id"] = "Hole{}".format(idx)
                    matrix[key]["{}_{:02d}".format(stem, idx)] = round(d["conf"], 4)

                if stem == "测试3" and top:
                    ref = np.array(REFLECTIVE_XY)
                    near = min(top, key=lambda d: float(np.linalg.norm(np.array(d["center"]) - ref)))
                    row["reflective"] = {"hole_id": near["hole_id"],
                                         "confidence": round(near["conf"], 4),
                                         "center": [round(near["cx"], 1), round(near["cy"], 1)]}

                out_img = EXP_DIR / "formal_seed{}".format(seed) / "results" / \
                    "{}_{}_result.jpg".format(stem, wname)
                draw_result(cv2.imread(str(img_path)), top, out_img,
                            "seed={} {}  {}  (conf>=0.5: {}/4)".format(seed, wname, stem, n_conf50))

                for d in top:
                    records.append({
                        "seed": seed, "weight_type": wname, "image": img_path.name,
                        "hole_id": d["hole_id"], "confidence": round(d["conf"], 4),
                        "class": "cylinder_bore",
                        "center": [round(d["cx"], 2), round(d["cy"], 2)],
                        "ellipse_width": round(d["width"], 2),
                        "ellipse_height": round(d["height"], 2),
                        "ellipse_angle_deg": round(d["angle"], 2),
                        "low_confidence": bool(d["conf"] < CONF_MAIN),
                    })

                print("    {}: conf>=0.5 检出 {}/4   全部 conf = {}".format(
                    stem, n_conf50,
                    [round(d["conf"], 4) for d in sorted(dets, key=lambda x: x["conf"], reverse=True)]))

            per_run.append(row)

    json_out = EXP_DIR / "formal_comparison.json"
    json_out.write_text(json.dumps({
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "config": {"seeds": SEEDS, "weights": [w for w, _ in WEIGHT_TYPES], "imgsz": args.imgsz,
                   "conf_floor": CONF_FLOOR, "conf_main": CONF_MAIN,
                   "dataset": "dataset_17_5_3 (17 train / 5 val / 3 test)",
                   "hole_order": "Hole1~Hole4 = 从上到下（图像 y 升序）"},
        "train_metrics": {str(k): v for k, v in train_metrics.items()},
        "records": records,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n[OK] {}".format(json_out))

    csv_out = EXP_DIR / "formal_comparison.csv"
    col_names = []
    for img in images:
        for i in range(1, 5):
            col_names.append("{}_{:02d}".format(img.stem, i))
    with csv_out.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["seed", "weight"] + col_names +
                   ["检测到4个孔的图片数", "4/4检测率",
                    "4孔平均confidence", "4孔最低confidence",
                    "测试3反光孔confidence", "额外低分检测数(非目标孔,<0.5)"])
        for row in per_run:
            key = (row["seed"], row["weight"])
            vals = [matrix.get(key, {}).get(c, "") for c in col_names]
            counts = [row["counts"].get(img.stem, 0) for img in images]
            n4 = sum(1 for c in counts if c == 4)
            confs = [v for v in vals if v != ""]          # 只统计被选中的 4 个目标孔
            extra_low = sum(1 for c in row["all_conf"] if c < CONF_MAIN) - \
                sum(1 for v in confs if float(v) < CONF_MAIN)
            w.writerow([row["seed"], row["weight"]] + vals +
                       ["{}/{}".format(n4, len(images)),
                        "{:.1f}%".format(100.0 * n4 / max(len(images), 1)),
                        "{:.4f}".format(float(np.mean(confs))) if confs else "",
                        "{:.4f}".format(float(np.min(confs))) if confs else "",
                        row["reflective"]["confidence"] if row["reflective"] else "",
                        extra_low])
    print("[OK] {}".format(csv_out))

    refl = [r["reflective"]["confidence"] for r in per_run if r["reflective"]]
    n4_total = sum(1 for r in per_run for c in r["counts"].values() if c == 4)
    n_groups = sum(len(r["counts"]) for r in per_run)

    html_out = EXP_DIR / "formal_comparison_report.html"
    base = html_out.parent
    css = """
    :root{--bg:#f5f7fa;--card:#fff;--line:#e2e8f0;--txt:#1f2937;--muted:#6b7280;
          --blue:#2563eb;--green:#16a34a;--amber:#d97706;--red:#dc2626;}
    *{box-sizing:border-box}
    body{margin:0;padding:28px;background:var(--bg);color:var(--txt);
         font-family:"Segoe UI","Microsoft YaHei",system-ui,sans-serif;line-height:1.6}
    h1{font-size:26px;margin:0 0 6px}
    h2{font-size:19px;margin:34px 0 14px;padding-left:10px;border-left:5px solid var(--blue)}
    h3{font-size:15px}
    .sub{color:var(--muted);font-size:13px;margin-bottom:20px;word-break:break-all}
    .panel{background:var(--card);border:1px solid var(--line);border-radius:12px;
           padding:18px 20px;margin-bottom:18px;box-shadow:0 1px 2px rgba(0,0,0,.04)}
    table{border-collapse:collapse;width:100%;font-size:13px}
    th,td{border:1px solid var(--line);padding:7px 9px;text-align:center;vertical-align:middle}
    th{background:#eef2f7;font-weight:600;white-space:nowrap}
    td.l,th.l{text-align:left}
    td.num{font-variant-numeric:tabular-nums}
    .kpi{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px}
    .kpi div{background:#eef6ff;border:1px solid #dbeafe;border-radius:10px;padding:12px 14px}
    .kpi b{display:block;font-size:21px;color:var(--blue);font-variant-numeric:tabular-nums}
    .kpi span{font-size:12px;color:var(--muted)}
    .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px}
    .card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px}
    .card-title{font-size:13px;font-weight:600;margin-bottom:8px;color:#374151}
    .card img{width:100%;height:auto;border-radius:8px;border:1px solid var(--line);display:block}
    .tag{display:inline-block;padding:2px 9px;border-radius:999px;font-size:12px;font-weight:700}
    .ok{background:#dcfce7;color:#166534}
    .low{background:#fef3c7;color:#92400e}
    .bad{background:#fee2e2;color:#991b1b}
    .warn{background:#fffbeb;border:1px solid #fde68a;border-radius:10px;padding:12px 14px;
          font-size:13px;color:#92400e;margin-bottom:16px}
    .mono{font-family:Consolas,monospace;font-size:12px}
    .refl{background:#fff7ed;font-weight:700;color:#9a3412}
    """

    P = []
    A = P.append
    A("<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>")
    A("<title>正式训练对照实验报告</title><style>{}</style></head><body>".format(css))
    A("<h1>正式训练对照实验报告（YOLO11n-Seg）</h1>")
    A("<div class='sub'>生成时间：{}<br>"
      "数据集：dataset_17_5_3（17 train / 5 val / 3 test，原 test 3 张完全保留）<br>"
      "统一配置：yolo11n-seg.pt ｜ imgsz=640 ｜ batch=8 ｜ epochs=100 ｜ patience=0（不早停）"
      " ｜ device=0 ｜ workers=2 ｜ deterministic=True<br>"
      "测试图片：{}（4 张）<br>"
      "孔编号约定：Hole1~Hole4 = <b>从上到下</b>（图像 y 升序）</div>".format(
          datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
          "、".join(p.name for p in images)))

    A("<h2>一、训练指标对比</h2><div class='panel'><table>")
    A("<tr><th>实验</th><th>seed</th><th>实际训练轮数</th><th>best epoch</th>"
      "<th>Precision</th><th>Recall</th><th>mAP50</th><th>mAP50-95</th><th>训练耗时</th></tr>")
    for seed in SEEDS:
        tm = train_metrics.get(seed)
        A("<tr><td class='l'>Experiment {}</td><td>{}</td>".format(
            {0: "A", 42: "B", 123: "C"}.get(seed, "?"), seed))
        if tm:
            A("<td class='num'>{}</td><td class='num'>{}</td><td class='num'>{:.4f}</td>"
              "<td class='num'>{:.4f}</td><td class='num'>{:.4f}</td><td class='num'>{:.4f}</td>"
              "<td class='num'>{:.1f} 秒</td></tr>".format(
                  tm["epochs_run"], tm["best_epoch"], tm["precision"], tm["recall"],
                  tm["map50"], tm["map5095"], tm["seconds"]))
        else:
            A("<td colspan='7'>（读取失败）</td></tr>")
    A("</table><p class='mono' style='color:#6b7280;margin-top:8px'>"
      "指标为 Mask（分割）指标；best epoch 按 fitness = 0.1×mAP50-95(Box) + 0.9×mAP50-95(Mask) 计算。</p></div>")

    A("<h2>二、测试结果对比（按主阈值 conf≥0.5 计孔数）</h2><div class='panel'><table>")
    A("<tr><th class='l'>seed</th><th>weight</th>")
    for img in images:
        A("<th>{}</th>".format(html.escape(img.stem)))
    A("<th>测试3反光孔 confidence</th></tr>")
    for row in per_run:
        A("<tr><td class='l'>{}</td><td>{}</td>".format(row["seed"], row["weight"]))
        for img in images:
            c = row["counts"].get(img.stem, 0)
            A("<td><span class='tag {}'>{}/4</span></td>".format("ok" if c == 4 else "bad", c))
        if row["reflective"]:
            rc = row["reflective"]["confidence"]
            A("<td class='num refl'>{} （{}） <span class='tag {}'>{}</span></td>".format(
                rc, row["reflective"]["hole_id"], "ok" if rc >= CONF_MAIN else "low",
                "正常" if rc >= CONF_MAIN else "LOW"))
        else:
            A("<td>—</td>")
        A("</tr>")
    A("</table><p class='mono' style='color:#6b7280;margin-top:8px'>"
      "测试3 反光孔 = 从上往下第 3 个孔（中心 y≈2559）。</p></div>")

    A("<h2>三、24 组 confidence 明细矩阵</h2><div class='panel' style='overflow-x:auto'><table>")
    A("<tr><th class='l'>seed</th><th>weight</th>")
    for img in images:
        for i in range(1, 5):
            A("<th>{}_{:02d}</th>".format(html.escape(img.stem), i))
    A("</tr>")
    for row in per_run:
        key = (row["seed"], row["weight"])
        A("<tr><td class='l'>{}</td><td>{}</td>".format(row["seed"], row["weight"]))
        for img in images:
            for i in range(1, 5):
                v = matrix.get(key, {}).get("{}_{:02d}".format(img.stem, i))
                if v is None:
                    A("<td>—</td>")
                else:
                    A("<td class='{}'>{:.4f}</td>".format(
                        "num refl" if (img.stem == "测试3" and i == 3) else "num", v))
        A("</tr>")
    A("</table><p class='mono' style='color:#6b7280;margin-top:8px'>"
      "橙色底 = 测试3 第 3 个孔（反光孔）。所有数值均为模型原始输出，未做任何修饰。</p></div>")

    A("<h2>四、客观统计（仅列出实际数据，不作好坏判断）</h2><div class='panel'>")
    A("<div class='kpi'>")
    A("<div><b>{}/{}</b><span>(seed,weight)×图片 组合中检出 4 个孔的比例</span></div>".format(n4_total, n_groups))
    if refl:
        A("<div><b>{:.4f}</b><span>测试3反光孔 平均 confidence（{} 组）</span></div>".format(
            float(np.mean(refl)), len(refl)))
        A("<div><b>{:.4f}</b><span>测试3反光孔 最高 confidence</span></div>".format(float(np.max(refl))))
        A("<div><b>{:.4f}</b><span>测试3反光孔 最低 confidence</span></div>".format(float(np.min(refl))))
        A("<div><b>{:.4f}</b><span>测试3反光孔 极差（最大−最小）</span></div>".format(
            float(np.max(refl) - np.min(refl))))
    A("</div>")

    A("<table style='margin-top:16px'>")
    A("<tr><th class='l'>统计项</th><th>值</th></tr>")
    for seed in SEEDS:
        vals = [r["reflective"]["confidence"] for r in per_run if r["seed"] == seed and r["reflective"]]
        if vals:
            A("<tr><td class='l'>seed={} 的测试3反光孔 confidence（best / last）</td><td>{}</td></tr>".format(
                seed, " / ".join("{:.4f}".format(v) for v in vals)))
    bests = [r["reflective"]["confidence"] for r in per_run if r["weight"] == "best" and r["reflective"]]
    lasts = [r["reflective"]["confidence"] for r in per_run if r["weight"] == "last" and r["reflective"]]
    if bests and lasts:
        A("<tr><td class='l'>best 权重 · 反光孔平均 / 最低</td><td>{:.4f} / {:.4f}</td></tr>".format(
            float(np.mean(bests)), float(np.min(bests))))
        A("<tr><td class='l'>last 权重 · 反光孔平均 / 最低</td><td>{:.4f} / {:.4f}</td></tr>".format(
            float(np.mean(lasts)), float(np.min(lasts))))
        A("<tr><td class='l'>best − last 反光孔平均差</td><td>{:+.4f}</td></tr>".format(
            float(np.mean(bests)) - float(np.mean(lasts))))

    all_confs = [c for r in per_run for c in r["all_conf"]]
    hole_confs = [v for r in per_run for c in matrix.get((r["seed"], r["weight"]), {}).values()
                  for v in [c] if v is not None]
    if hole_confs:
        A("<tr><td class='l'>被选中的 4 个目标孔 · confidence 平均</td><td>{:.4f}</td></tr>".format(
            float(np.mean(hole_confs))))
        A("<tr><td class='l'>被选中的 4 个目标孔 · confidence 最低</td><td>{:.4f}</td></tr>".format(
            float(np.min(hole_confs))))
        A("<tr><td class='l'>被选中的 4 个目标孔中低于 0.5 的数量</td><td>{} / {}</td></tr>".format(
            sum(1 for c in hole_confs if c < CONF_MAIN), len(hole_confs)))
    if all_confs:
        extra_low = sum(1 for c in all_confs if c < CONF_MAIN) - \
            sum(1 for c in hole_confs if c < CONF_MAIN)
        A("<tr><td class='l'>低阈值(0.05)推理下的<b>额外</b>低分检测（不属于4个目标孔）</td>"
          "<td>{} 个（全部 &lt; 0.5）</td></tr>".format(extra_low))
    A("</table>")

    low_rows = []
    for r in per_run:
        key = (r["seed"], r["weight"])
        for img in images:
            for i in range(1, 5):
                c = matrix.get(key, {}).get("{}_{:02d}".format(img.stem, i))
                if c is not None and c < CONF_MAIN:
                    low_rows.append((r["seed"], r["weight"], img.stem, i, c))
    if low_rows:
        A("<div class='warn' style='margin-top:14px'><b>出现低于 0.5 的 confidence：{} 处</b><br>{}</div>".format(
            len(low_rows),
            "；".join("seed={} {} {} Hole{} = {:.4f}".format(s, w, im, i, c) for s, w, im, i, c in low_rows)))
    else:
        A("<p style='margin-top:14px'>本次 24 组结果中，没有出现低于 0.5 的 confidence。</p>")
    A("</div>")

    A("<h2>五、各实验训练曲线与混淆矩阵</h2>")
    for seed in SEEDS:
        run_dir = EXP_DIR / "formal_seed{}".format(seed) / "runs" / "yolo11n_seg_seed{}".format(seed)
        A("<h3 style='margin:18px 0 8px;color:#374151'>seed = {}</h3><div class='grid'>".format(seed))
        for n, t in [("results.png", "训练总曲线 results.png"),
                     ("MaskPR_curve.png", "MaskPR_curve.png"),
                     ("MaskF1_curve.png", "MaskF1_curve.png"),
                     ("confusion_matrix.png", "confusion_matrix.png")]:
            p = run_dir / n
            if p.is_file():
                A("<div class='card'><div class='card-title'>{}</div>"
                  "<a href='{src}' target='_blank'><img src='{src}'></a></div>".format(
                      html.escape(t), src=rel_src(p, base)))
            else:
                A("<div class='card'><div class='card-title'>{}</div>"
                  "<div class='mono' style='color:#d97706'>未找到</div></div>".format(html.escape(t)))
        A("</div>")

    A("<h2>六、4 张测试图片的预测结果（best / last）</h2>")
    for seed in SEEDS:
        for wname, _ in WEIGHT_TYPES:
            A("<h3 style='margin:18px 0 8px;color:#374151'>seed = {} , weight = {}</h3>"
              "<div class='grid'>".format(seed, wname))
            for img in images:
                p = EXP_DIR / "formal_seed{}".format(seed) / "results" / \
                    "{}_{}_result.jpg".format(img.stem, wname)
                if p.is_file():
                    A("<div class='card'><div class='card-title'>{}</div>"
                      "<a href='{src}' target='_blank'><img src='{src}'></a></div>".format(
                          html.escape(img.stem), src=rel_src(p, base)))
                else:
                    A("<div class='card'><div class='card-title'>{}</div>"
                      "<div class='mono' style='color:#d97706'>未找到结果图</div></div>".format(
                          html.escape(img.stem)))
            A("</div>")

    A("<p class='sub' style='margin-top:24px'>橙框椭圆 = confidence &lt; 0.5（低置信度），绿框 = 正常；"
      "红点 = 椭圆中心；彩色区域 = mask。本报告只做客观展示，不对模型优劣下结论。</p>")
    A("</body></html>")

    html_out.write_text("\n".join(P), encoding="utf-8")
    print("[OK] {}".format(html_out))
    print("\n全部完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
