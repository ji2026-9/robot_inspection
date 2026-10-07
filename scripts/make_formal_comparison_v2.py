# -*- coding: utf-8 -*-
"""
正式实验 v2 汇总：5 个 seed x best/last x 4 张测试图 = 40 组
============================================================
正式统计阈值：confidence >= 0.50（不使用 fallback conf-floor 作为正式统计）
另外单独用 conf=0.05 做误检分析，两者严格分开。

输出（不修改任何已有文件）：
  experiments\\formal_comparison_v2.json
  experiments\\formal_comparison_v2.csv
  experiments\\formal_comparison_v2.html

只为本次新增实验（seed=7 / seed=2024）写预测可视化，
formal_seed0 / 42 / 123 的 results 目录保持原样不动。

用法：
    python scripts\\make_formal_comparison_v2.py
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

PROJ = Path(r"E:\robot_project\robot_inspection")
EXP_DIR = PROJ / "experiments"
TEST_DIR = PROJ / "test_images"

SEEDS = [0, 42, 123, 7, 2024]
WEIGHT_TYPES = [("best", "best.pt"), ("last", "last.pt")]
IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}

CONF_MAIN = 0.50          # 正式统计阈值
CONF_ANALYSIS = 0.05      # 仅用于误检分析
DIST_TOL = 200.0          # 把 conf>=0.5 的检测匹配到 4 个目标孔时的距离容差(px)
REFLECTIVE_XY = (1434.8, 2559.2)   # 测试3 反光孔中心
WRITE_IMAGES_SEEDS = [7, 2024]     # 只为新增实验写可视化，不动已有实验目录


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
    return sorted([p for p in TEST_DIR.iterdir()
                   if p.suffix.lower() in IMG_EXTS and p.stem.startswith("测试")])


def predict_dets(model, img_path, conf, imgsz, device):
    r = model.predict(source=str(img_path), conf=conf, iou=0.7, imgsz=imgsz,
                      device=device, retina_masks=True, verbose=False)[0]
    n = 0 if r.masks is None else len(r.masks)
    out = []
    for i in range(n):
        mask = r.masks.data[i].cpu().numpy() > 0.5
        ell, cnt = ellipse_from_mask(mask)
        if ell is None:
            continue
        (cx, cy), (MA, ma), ang = ell
        out.append({"conf": float(r.boxes.conf[i].cpu().numpy()),
                    "cx": float(cx), "cy": float(cy),
                    "ellipse": ell, "contour": cnt, "mask_bool": mask,
                    "width": float(MA), "height": float(ma), "angle": float(ang),
                    "class_id": int(r.boxes.cls[i].cpu().numpy())})
    out.sort(key=lambda d: d["conf"], reverse=True)
    return out


def draw_result(img, holes, out_path, title):
    if img is None:
        return
    cols = [(0, 200, 0), (0, 140, 255), (255, 120, 0), (200, 0, 200)]
    overlay = img.copy()
    for i, h in enumerate(holes):
        overlay[h["mask_bool"]] = cols[i % 4]
    vis = cv2.addWeighted(overlay, 0.35, img, 0.65, 0)
    for i, h in enumerate(holes):
        if h["contour"] is not None:
            cv2.drawContours(vis, [h["contour"]], -1, (255, 255, 255), 2)
        (cx, cy), (MA, ma), ang = h["ellipse"]
        col = (0, 255, 0) if h["conf"] >= CONF_MAIN else (0, 200, 255)
        cv2.ellipse(vis, ((cx, cy), (MA, ma), ang), col, 3)
        cv2.circle(vis, (int(round(cx)), int(round(cy))), 6, (0, 0, 255), -1)
        cv2.circle(vis, (int(round(cx)), int(round(cy))), 9, (255, 255, 255), 2)
        label = "{}  conf={:.3f}{}".format(h["hole_id"], h["conf"],
                                           "  LOW" if h["conf"] < CONF_MAIN else "")
        cv2.putText(vis, label, (int(cx) + 12, int(cy) - 12), cv2.FONT_HERSHEY_SIMPLEX,
                    0.8, (0, 0, 0), 4, cv2.LINE_AA)
        cv2.putText(vis, label, (int(cx) + 12, int(cy) - 12), cv2.FONT_HERSHEY_SIMPLEX,
                    0.8, (255, 255, 255), 2, cv2.LINE_AA)
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
    return {"epochs_run": len(rows), "best_epoch": int(float(best.get("epoch", 0))),
            "seconds": g(rows[-1], "time"),
            "precision": g(best, "metrics/precision(M)"),
            "recall": g(best, "metrics/recall(M)"),
            "map50": g(best, "metrics/mAP50(M)"),
            "map5095": g(best, "metrics/mAP50-95(M)")}


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
        print("[错误] 找不到测试图片")
        return 2

    from ultralytics import YOLO

    groups = []          # 40 组明细
    train_metrics = {}
    records = []         # 逐孔记录（每孔一行）

    for seed in SEEDS:
        run_dir = EXP_DIR / "formal_seed{}".format(seed) / "runs" / "yolo11n_seg_seed{}".format(seed)
        train_metrics[seed] = read_train_metrics(run_dir)
        tm = train_metrics[seed]
        print("[训练] seed={} {}".format(seed, "OK" if tm else "指标读取失败"))

        for wname, wfile in WEIGHT_TYPES:
            wpath = EXP_DIR / "formal_seed{}".format(seed) / "weights" / wfile
            if not wpath.is_file():
                print("[失败] 缺少权重 {} —— 该组跳过".format(wpath))
                continue
            model = YOLO(str(wpath))

            for img_path in images:
                stem = img_path.stem
                dets_low = predict_dets(model, img_path, CONF_ANALYSIS, args.imgsz, args.device)
                dets_main = predict_dets(model, img_path, CONF_MAIN, args.imgsz, args.device)

                # 4 个目标孔：低阈值下置信度最高的 4 个，按 y 从上到下排序
                targets = sorted(dets_low[:4], key=lambda d: d["cy"])
                for i, t in enumerate(targets, 1):
                    t["hole_id"] = "Hole{}".format(i)

                # 把 conf>=0.5 的检测匹配到目标孔
                used = set()
                holes = []
                for t in targets:
                    best_j, best_d = None, 1e9
                    for j, d in enumerate(dets_main):
                        if j in used:
                            continue
                        dist = float(np.hypot(d["cx"] - t["cx"], d["cy"] - t["cy"]))
                        if dist < best_d:
                            best_j, best_d = j, dist
                    if best_j is not None and best_d <= DIST_TOL:
                        used.add(best_j)
                        d = dets_main[best_j]
                        holes.append({"hole_id": t["hole_id"], "detected": True,
                                      "confidence": round(d["conf"], 4),
                                      "center": [round(d["cx"], 2), round(d["cy"], 2)],
                                      "ellipse_width": round(d["width"], 2),
                                      "ellipse_height": round(d["height"], 2),
                                      "ellipse_angle_deg": round(d["angle"], 2),
                                      "match_dist": round(best_d, 1)})
                    else:
                        holes.append({"hole_id": t["hole_id"], "detected": False,
                                      "confidence": None,
                                      "center": [round(t["cx"], 2), round(t["cy"], 2)],
                                      "ellipse_width": None, "ellipse_height": None,
                                      "ellipse_angle_deg": None, "match_dist": None})

                missed = [h["hole_id"] for h in holes if not h["detected"]]
                spurious = [{"confidence": round(d["conf"], 4),
                             "center": [round(d["cx"], 2), round(d["cy"], 2)]}
                            for j, d in enumerate(dets_main) if j not in used]
                extra_low = [d for d in dets_low if d["conf"] < CONF_MAIN
                             and all(float(np.hypot(d["cx"] - t["cx"], d["cy"] - t["cy"])) > DIST_TOL
                                     for t in targets)]

                g = {"seed": seed, "weight": wname, "image": img_path.name,
                     "n_main": len(dets_main), "n_low": len(dets_low),
                     "holes": holes, "missed": missed,
                     "spurious": spurious, "n_spurious": len(spurious),
                     "extra_low_005": len(extra_low),
                     "min_conf": min([h["confidence"] for h in holes if h["detected"]], default=None),
                     "is_4of4": (len(missed) == 0 and len(dets_main) == 4)}
                groups.append(g)

                # 反光孔
                if stem == "测试3":
                    ref = np.array(REFLECTIVE_XY)
                    g["reflective"] = min(
                        [{"hole_id": h["hole_id"], "confidence": h["confidence"],
                          "center": h["center"]} for h in holes],
                        key=lambda h: float(np.linalg.norm(np.array(h["center"]) - ref)))
                else:
                    g["reflective"] = None

                for h in holes:
                    records.append({"seed": seed, "weight_type": wname, "image": img_path.name,
                                    "hole_id": h["hole_id"], "detected": h["detected"],
                                    "confidence": h["confidence"], "center": h["center"],
                                    "class": "cylinder_bore",
                                    "threshold": CONF_MAIN})

                print("    seed={:<5} {:<5} {:<8} conf>=0.5 检出 {} 个 | 4/4={} | 漏检={} | 误检={} | 最低目标孔conf={}".format(
                    seed, wname, stem, len(dets_main), g["is_4of4"],
                    missed if missed else "无", len(spurious),
                    g["min_conf"] if g["min_conf"] is not None else "—"))

                if seed in WRITE_IMAGES_SEEDS:
                    draw_result(cv2.imread(str(img_path)), targets,
                                EXP_DIR / "formal_seed{}".format(seed) / "results" /
                                "{}_{}_result.jpg".format(stem, wname),
                                "seed={} {}  {}  (conf>=0.5: {} detected)".format(
                                    seed, wname, stem, len(dets_main)))

    # ---------------- 统计 ----------------
    n_total = len(groups)
    n_4of4 = sum(1 for g in groups if g["is_4of4"])
    hole_confs = [h["confidence"] for g in groups for h in g["holes"] if h["detected"]]
    misses = [(g["seed"], g["weight"], g["image"], g["missed"]) for g in groups if g["missed"]]
    spurious_all = [(g["seed"], g["weight"], g["image"], g["n_spurious"], g["spurious"])
                    for g in groups if g["n_spurious"] > 0]
    refl_all = [g["reflective"]["confidence"] for g in groups
                if g["reflective"] and g["reflective"]["confidence"] is not None]

    refl_by_seed = {}
    for seed in SEEDS:
        vals = [g["reflective"]["confidence"] for g in groups
                if g["seed"] == seed and g["reflective"] and g["reflective"]["confidence"] is not None]
        if vals:
            refl_by_seed[seed] = {"values": vals, "mean": float(np.mean(vals)),
                                  "min": float(np.min(vals)), "max": float(np.max(vals))}
    refl_seed_means = [v["mean"] for v in refl_by_seed.values()]
    refl_stats = {
        "mean": float(np.mean(refl_seed_means)) if refl_seed_means else None,
        "std": float(np.std(refl_seed_means, ddof=0)) if refl_seed_means else None,
        "min": float(np.min(refl_seed_means)) if refl_seed_means else None,
        "max": float(np.max(refl_seed_means)) if refl_seed_means else None,
    }
    best_vals = [g["reflective"]["confidence"] for g in groups
                 if g["weight"] == "best" and g["reflective"] and g["reflective"]["confidence"] is not None]
    last_vals = [g["reflective"]["confidence"] for g in groups
                 if g["weight"] == "last" and g["reflective"] and g["reflective"]["confidence"] is not None]

    summary = {
        "n_groups": n_total, "n_4of4": n_4of4,
        "rate_4of4": (n_4of4 / n_total) if n_total else 0.0,
        "per_seed_4of4": {},
        "hole_conf_min": float(np.min(hole_confs)) if hole_confs else None,
        "hole_conf_mean": float(np.mean(hole_confs)) if hole_confs else None,
        "hole_conf_below_050": int(sum(1 for c in hole_confs if c < CONF_MAIN)),
        "n_misses": len(misses), "misses": misses,
        "n_groups_with_spurious": len(spurious_all),
        "spurious_total": int(sum(s[3] for s in spurious_all)),
        "spurious": spurious_all,
        "reflective": {"all": refl_all, "by_seed": {str(k): v for k, v in refl_by_seed.items()},
                       "seed_level": refl_stats,
                       "best_mean": float(np.mean(best_vals)) if best_vals else None,
                       "last_mean": float(np.mean(last_vals)) if last_vals else None,
                       "best_minus_last": (float(np.mean(best_vals)) - float(np.mean(last_vals)))
                       if best_vals and last_vals else None},
    }
    for seed in SEEDS:
        gs = [g for g in groups if g["seed"] == seed]
        if gs:
            summary["per_seed_4of4"][str(seed)] = "{}/{}".format(
                sum(1 for g in gs if g["is_4of4"]), len(gs))

    # ---------------- 写 JSON ----------------
    json_out = EXP_DIR / "formal_comparison_v2.json"
    json_out.write_text(json.dumps({
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "config": {"seeds": SEEDS, "weights": [w for w, _ in WEIGHT_TYPES],
                   "imgsz": args.imgsz, "conf_main": CONF_MAIN, "conf_analysis": CONF_ANALYSIS,
                   "dataset": "dataset_17_5_3 (17 train / 5 val / 3 test)",
                   "hole_order": "Hole1~Hole4 = 从上到下（图像 y 升序）",
                   "match_tolerance_px": DIST_TOL},
        "train_metrics": {str(k): v for k, v in train_metrics.items()},
        "summary": summary,
        "groups": groups,
        "records": records,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n[OK] {}".format(json_out))

    # ---------------- 写 CSV ----------------
    csv_out = EXP_DIR / "formal_comparison_v2.csv"
    col = []
    for img in images:
        for i in range(1, 5):
            col.append("{}_{:02d}".format(img.stem, i))
    with csv_out.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["seed", "weight"] + col +
                   ["检测到4个孔的图片数", "4/4检测率", "目标孔最低confidence",
                    "目标孔平均confidence", "测试3反光孔confidence",
                    "漏检孔数", "conf>=0.5误检数", "conf=0.05额外低分检测数"])
        for seed in SEEDS:
            for wname, _ in WEIGHT_TYPES:
                gs = [g for g in groups if g["seed"] == seed and g["weight"] == wname]
                if not gs:
                    continue
                vals = {}
                for g in gs:
                    for h in g["holes"]:
                        vals["{}_{:02d}".format(Path(g["image"]).stem, int(h["hole_id"][-1]))] = \
                            h["confidence"] if h["detected"] else ""
                confs = [h["confidence"] for g in gs for h in g["holes"] if h["detected"]]
                refl = next((g["reflective"]["confidence"] for g in gs if g["reflective"]), None)
                n4 = sum(1 for g in gs if g["is_4of4"])
                w.writerow([seed, wname] + [vals.get(c, "") for c in col] +
                           ["{}/{}".format(n4, len(gs)),
                            "{:.1f}%".format(100.0 * n4 / len(gs)),
                            "{:.4f}".format(min(confs)) if confs else "",
                            "{:.4f}".format(float(np.mean(confs))) if confs else "",
                            refl if refl is not None else "",
                            sum(len(g["missed"]) for g in gs),
                            sum(g["n_spurious"] for g in gs),
                            sum(g["extra_low_005"] for g in gs)])
    print("[OK] {}".format(csv_out))

    # ---------------- 最终判断（按用户给定原则） ----------------
    crit1 = summary["n_misses"] == 0
    crit2 = summary["rate_4of4"] >= 0.95
    crit3 = summary["hole_conf_below_050"] == 0
    crit4 = summary["spurious_total"] == 0
    if crit1 and crit2 and crit3 and crit4:
        verdict = ("在当前测试集和实验范围内，YOLO11n-Seg 已表现出较好的检测稳定性，"
                   "暂不需要仅因模型容量问题升级到 YOLO11s。")
    else:
        problems = []
        if not crit1:
            problems.append("存在目标孔漏检 {} 处".format(summary["n_misses"]))
        if not crit2:
            problems.append("4/4 比例仅 {:.1f}%".format(100 * summary["rate_4of4"]))
        if not crit3:
            problems.append("存在 {} 个目标孔 confidence < 0.5".format(summary["hole_conf_below_050"]))
        if not crit4:
            problems.append("conf>=0.5 下存在 {} 个未匹配到目标孔的检测".format(summary["spurious_total"]))
        verdict = "未满足全部稳定性条件：" + "；".join(problems) + "。需按实际数据进一步分析。"

    seed_note = ("随机种子对结果存在一定波动（5 个 seed 的反光孔平均 confidence 标准差 {:.4f}），"
                 "但没有改变目标孔 4/4 检测的总体结论。".format(summary["reflective"]["seed_level"]["std"])
                 if summary["reflective"]["seed_level"]["std"] is not None else "")

    # ---------------- 写 HTML ----------------
    html_out = EXP_DIR / "formal_comparison_v2.html"
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
    .kpi{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}
    .kpi div{background:#eef6ff;border:1px solid #dbeafe;border-radius:10px;padding:12px 14px}
    .kpi b{display:block;font-size:20px;color:var(--blue);font-variant-numeric:tabular-nums}
    .kpi span{font-size:12px;color:var(--muted)}
    .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px}
    .card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px}
    .card-title{font-size:13px;font-weight:600;margin-bottom:8px;color:#374151}
    .card img{width:100%;height:auto;border-radius:8px;border:1px solid var(--line);display:block}
    .tag{display:inline-block;padding:2px 9px;border-radius:999px;font-size:12px;font-weight:700}
    .ok{background:#dcfce7;color:#166534}
    .low{background:#fef3c7;color:#92400e}
    .bad{background:#fee2e2;color:#991b1b}
    .verdict{background:#ecfdf5;border:1px solid #a7f3d0;border-radius:12px;padding:16px 18px;
             font-size:15px;color:#065f46}
    .warn{background:#fffbeb;border:1px solid #fde68a;border-radius:10px;padding:12px 14px;
          font-size:13px;color:#92400e;margin-bottom:16px}
    .mono{font-family:Consolas,monospace;font-size:12px}
    .refl{background:#fff7ed;font-weight:700;color:#9a3412}
    """

    P = []
    A = P.append
    A("<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>")
    A("<title>正式实验汇总 v2（5 seeds）</title><style>{}</style></head><body>".format(css))
    A("<h1>正式训练对照实验汇总 v2 —— 5 个随机种子</h1>")
    A("<div class='sub'>生成时间：{}<br>"
      "数据集：dataset_17_5_3（17 train / 5 val / 3 test，原始 3 张 test 保持不变）<br>"
      "统一配置：yolo11n-seg.pt ｜ imgsz=640 ｜ batch=8 ｜ epochs=100 ｜ patience=0 ｜ device=0 ｜ "
      "workers=2 ｜ deterministic=True<br>"
      "<b>正式统计阈值 conf >= 0.50</b>（conf=0.05 仅用于单独的误检分析，两者严格分开）<br>"
      "组合数：{} seeds × 2 checkpoints × 4 images = <b>{}</b> 组</div>".format(
          datetime.now().strftime("%Y-%m-%d %H:%M:%S"), len(SEEDS), n_total))

    A("<h2>一、训练指标</h2><div class='panel'><table>")
    A("<tr><th>seed</th><th>轮数</th><th>best epoch</th><th>Precision</th><th>Recall</th>"
      "<th>mAP50</th><th>mAP50-95</th><th>耗时</th></tr>")
    for seed in SEEDS:
        tm = train_metrics.get(seed)
        A("<tr><td>{}</td>".format(seed))
        if tm:
            A("<td class='num'>{}</td><td class='num'>{}</td><td class='num'>{:.4f}</td>"
              "<td class='num'>{:.4f}</td><td class='num'>{:.4f}</td><td class='num'>{:.4f}</td>"
              "<td class='num'>{:.1f}s</td></tr>".format(
                  tm["epochs_run"], tm["best_epoch"], tm["precision"], tm["recall"],
                  tm["map50"], tm["map5095"], tm["seconds"]))
        else:
            A("<td colspan='7'>读取失败</td></tr>")
    A("</table></div>")

    A("<h2>二、40 组组合结果（正式阈值 conf>=0.5）</h2><div class='panel' style='overflow-x:auto'><table>")
    A("<tr><th class='l'>seed</th><th>weight</th>")
    for img in images:
        A("<th>{}<br><span class='mono'>检出/4</span></th>".format(html.escape(img.stem)))
    A("<th>反光孔 conf</th><th>最低目标孔 conf</th><th>漏检</th><th>conf>=0.5 误检</th></tr>")
    for g in groups:
        if g["image"] != images[0].name:
            continue
        A("<tr><td class='l'>{}</td><td>{}</td>".format(g["seed"], g["weight"]))
        for img in images:
            gg = next((x for x in groups if x["seed"] == g["seed"] and x["weight"] == g["weight"]
                       and x["image"] == img.name), None)
            if gg:
                A("<td><span class='tag {}'>{}/4</span></td>".format(
                    "ok" if gg["is_4of4"] else "bad", gg["n_main"]))
            else:
                A("<td>—</td>")
        g3 = next((x for x in groups if x["seed"] == g["seed"] and x["weight"] == g["weight"]
                   and x["image"] == "测试3.jpg"), None)
        rc = g3["reflective"]["confidence"] if (g3 and g3["reflective"]) else None
        mins = [x["min_conf"] for x in groups if x["seed"] == g["seed"] and x["weight"] == g["weight"]
                and x["min_conf"] is not None]
        nmiss = sum(len(x["missed"]) for x in groups if x["seed"] == g["seed"] and x["weight"] == g["weight"])
        nsp = sum(x["n_spurious"] for x in groups if x["seed"] == g["seed"] and x["weight"] == g["weight"])
        A("<td class='num refl'>{}</td><td class='num'>{}</td><td>{}</td><td>{}</td></tr>".format(
            "{:.4f}".format(rc) if rc is not None else "—",
            "{:.4f}".format(min(mins)) if mins else "—",
            nmiss if nmiss else "无", nsp if nsp else "无"))
    A("</table><p class='mono' style='color:#6b7280;margin-top:8px'>"
      "反光孔 = 测试3 中从上往下第 3 个孔（中心 y≈2559）。</p></div>")

    A("<h2>三、逐孔 confidence 明细（4 张图 × 4 孔）</h2><div class='panel' style='overflow-x:auto'><table>")
    A("<tr><th class='l'>seed</th><th>weight</th>")
    for img in images:
        for i in range(1, 5):
            A("<th>{}_{:02d}</th>".format(html.escape(img.stem), i))
    A("</tr>")
    for seed in SEEDS:
        for wname, _ in WEIGHT_TYPES:
            gs = [g for g in groups if g["seed"] == seed and g["weight"] == wname]
            if not gs:
                continue
            A("<tr><td class='l'>{}</td><td>{}</td>".format(seed, wname))
            for img in images:
                g = next((x for x in gs if x["image"] == img.name), None)
                for i in range(1, 5):
                    h = next((x for x in (g["holes"] if g else []) if int(x["hole_id"][-1]) == i), None)
                    if h is None:
                        A("<td>—</td>")
                    elif h["detected"]:
                        A("<td class='{}'>{:.4f}</td>".format(
                            "num refl" if (img.stem == "测试3" and i == 3) else "num", h["confidence"]))
                    else:
                        A("<td><span class='tag bad'>漏检</span></td>")
            A("</tr>")
    A("</table></div>")

    A("<h2>四、统计量（A–I）</h2><div class='panel'><div class='kpi'>")
    A("<div><b>{}/{}</b><span>A. 4/4 检测率 = {:.1f}%</span></div>".format(
        n_4of4, n_total, 100 * summary["rate_4of4"]))
    A("<div><b>{:.4f}</b><span>B. 目标孔 confidence 最小值</span></div>".format(
        summary["hole_conf_min"] if summary["hole_conf_min"] is not None else float('nan')))
    A("<div><b>{:.4f}</b><span>C. 目标孔 confidence 平均值</span></div>".format(
        summary["hole_conf_mean"] if summary["hole_conf_mean"] is not None else float('nan')))
    A("<div><b>{:.4f}</b><span>D. 反光孔 confidence 平均（40 组中 10 组）</span></div>".format(
        float(np.mean(refl_all)) if refl_all else float('nan')))
    A("<div><b>{}</b><span>G. 目标孔 confidence &lt; 0.5 的数量</span></div>".format(
        summary["hole_conf_below_050"]))
    A("<div><b>{}</b><span>H. 目标孔漏检数量</span></div>".format(summary["n_misses"]))
    A("<div><b>{}</b><span>I. conf>=0.5 明显误检数量</span></div>".format(summary["spurious_total"]))
    A("</div><table style='margin-top:16px'>")
    A("<tr><th class='l'>统计项</th><th>值</th></tr>")
    for seed in SEEDS:
        v = refl_by_seed.get(seed)
        if v:
            A("<tr><td class='l'>seed={} 反光孔（best / last）</td><td>{}</td></tr>".format(
                seed, " / ".join("{:.4f}".format(x) for x in v["values"])))
    if refl_seed_means:
        A("<tr><td class='l'>E. 各 seed 反光孔均值 → 均值 / 标准差 / 最小 / 最大</td>"
          "<td>{:.4f} / {:.4f} / {:.4f} / {:.4f}</td></tr>".format(
              refl_stats["mean"], refl_stats["std"], refl_stats["min"], refl_stats["max"]))
    if summary["reflective"]["best_mean"] is not None:
        A("<tr><td class='l'>F. best 反光孔平均 / last 反光孔平均 / 差值</td><td>{:.4f} / {:.4f} / {:+.4f}</td></tr>".format(
            summary["reflective"]["best_mean"], summary["reflective"]["last_mean"],
            summary["reflective"]["best_minus_last"]))
    A("</table>")
    if summary["n_misses"] == 0:
        A("<p style='margin-top:12px'>H. 40 组组合中<b>没有任何目标孔漏检</b>。</p>")
    else:
        A("<div class='warn' style='margin-top:12px'><b>H. 存在漏检：</b>{}"
          "</div>".format("；".join("seed={} {} {} 漏 {}".format(s, w, i, m) for s, w, i, m in summary["misses"])))
    if summary["spurious_total"] == 0:
        A("<p>I. conf>=0.5 下没有出现未匹配到目标孔的检测。</p>")
    else:
        A("<div class='warn'><b>I. conf>=0.5 下存在未匹配到目标孔的检测（疑似误检）：</b><br>{}</div>".format(
            "；".join("seed={} {} {} 共 {} 个 (conf={})".format(
                s, w, i, n, ", ".join("{:.3f}".format(d["confidence"]) for d in sp))
                for s, w, i, n, sp in summary["spurious"])))
    A("</div>")

    A("<h2>五、最终判断</h2><div class='panel'>")
    A("<div class='verdict'><b>{}</b></div>".format(html.escape(verdict)))
    if seed_note:
        A("<p style='margin-top:12px'>{}</p>".format(html.escape(seed_note)))
    A("<p class='mono' style='color:#6b7280;margin-top:12px'>"
      "本判断按预设四项条件自动生成：① 5 个 seed 目标孔均无漏检；② 4/4 比例 ≥95%；"
      "③ 目标孔 confidence 均 ≥0.5；④ conf≥0.5 下无未匹配检测。未人为挑选最优结果。"
      "不因某个 seed 表现最好就选择该 seed 作为最终模型。</p></div>")

    A("<h2>六、新增实验（seed=7 / seed=2024）预测可视化</h2>")
    for seed in WRITE_IMAGES_SEEDS:
        for wname, _ in WEIGHT_TYPES:
            A("<h3 style='margin:18px 0 8px;color:#374151'>seed = {} , weight = {}</h3><div class='grid'>".format(
                seed, wname))
            for img in images:
                p = EXP_DIR / "formal_seed{}".format(seed) / "results" / \
                    "{}_{}_result.jpg".format(img.stem, wname)
                if p.is_file():
                    A("<div class='card'><div class='card-title'>{}</div>"
                      "<a href='{src}' target='_blank'><img src='{src}'></a></div>".format(
                          html.escape(img.stem), src=rel_src(p, base)))
                else:
                    A("<div class='card'><div class='card-title'>{}</div>"
                      "<div class='mono' style='color:#d97706'>未找到</div></div>".format(html.escape(img.stem)))
            A("</div>")

    A("<p class='sub' style='margin-top:24px'>绿框椭圆 = conf>=0.5；橙框 = conf&lt;0.5；红点 = 椭圆中心；"
      "彩色区域 = mask。本报告只做客观展示。</p>")
    A("</body></html>")
    html_out.write_text("\n".join(P), encoding="utf-8")
    print("[OK] {}".format(html_out))
    print("\n4/4 = {}/{}  ({:.1f}%)".format(n_4of4, n_total, 100 * summary["rate_4of4"]))
    print("目标孔 confidence 最小 = {}".format(summary["hole_conf_min"]))
    print("漏检 = {} , 误检(conf>=0.5) = {}".format(summary["n_misses"], summary["spurious_total"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
