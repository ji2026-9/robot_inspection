# -*- coding: utf-8 -*-
"""
Step 1　可行性分析（只读，不训练、不改任何现有文件）
==================================================
对 test_images 的 4 张图运行 best.pt，得到 4 个孔的椭圆中心，然后测量：
  1) PCA 主轴与投影排序（现有方案）
  2) 孔间距（投影后）序列 —— 是否单调？是否可作为方向线索？
  3) 孔径（椭圆主轴长度）序列 —— 是否单调？
  4) 箱体外轮廓（经典分割）—— 长轴方向的宽度剖面、两端留白距离、非对称度
  5) 组合信号：能否给出一个与 PCA 符号无关的“参考端”

输出：
  results\\feasibility_analysis.json
  visualizations\\feas_<图片名>.jpg

用法：
    python experiments\\stable_hole_id\\scripts\\feasibility_analysis.py
"""

import json
import sys
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

PROJ = Path(r"E:\robot_inspection")
ROOT = PROJ / "experiments" / "stable_hole_id"
WEIGHTS = PROJ / "weights" / "best.pt"
TEST_DIR = PROJ / "test_images"
RESULTS = ROOT / "results"
VIS = ROOT / "visualizations"
CONF = 0.50


def ellipse_from_mask(m):
    mm = (m.astype(np.uint8)) * 255
    cnts, _ = cv2.findContours(mm, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not cnts:
        return None, None
    c = max(cnts, key=cv2.contourArea)
    if len(c) < 5:
        return None, c
    return cv2.fitEllipse(c), c


def box_silhouette(img):
    """经典分割：Otsu + 形态学 + 取包含孔区域的较大连通域。"""
    h, w = img.shape[:2]
    small = cv2.resize(img, (w // 4, h // 4), interpolation=cv2.INTER_AREA)
    g = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    g = cv2.GaussianBlur(g, (5, 5), 0)
    _, th = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    th = cv2.morphologyEx(th, cv2.MORPH_OPEN, np.ones((7, 7), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(th, 8)
    if n <= 1:
        return None
    # 选面积最大且不是整幅背景的连通域
    order = sorted(range(1, n), key=lambda i: -stats[i, cv2.CC_STAT_AREA])
    for i in order:
        if stats[i, cv2.CC_STAT_AREA] < 0.05 * th.size:
            continue
        comp = (lab == i).astype(np.uint8) * 255
        cnts, _ = cv2.findContours(comp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        if not cnts:
            continue
        c = max(cnts, key=cv2.contourArea)
        return (c * 4.0).astype(np.float32)   # 还原到原尺寸（float32 供 minAreaRect 使用）
    return None


def analyze(img_path, model):
    img = cv2.imread(str(img_path))
    h, w = img.shape[:2]
    r = model.predict(source=str(img_path), conf=CONF, iou=0.7, imgsz=640,
                      device=0, retina_masks=True, verbose=False)[0]
    n = 0 if r.masks is None else len(r.masks)
    holes = []
    for i in range(n):
        m = r.masks.data[i].cpu().numpy() > 0.5
        ell, cnt = ellipse_from_mask(m)
        if ell is None:
            continue
        (cx, cy), (MA, ma), ang = ell
        holes.append({"conf": round(float(r.boxes.conf[i].cpu().numpy()), 4),
                      "center": [round(float(cx), 2), round(float(cy), 2)],
                      "major": round(float(max(MA, ma)), 2),
                      "minor": round(float(min(MA, ma)), 2),
                      "angle": round(float(ang), 2),
                      "area": float(cv2.contourArea(cnt)),
                      "contour": cnt, "mask": m, "ellipse": ell})
    out = {"image": img_path.name, "size": [w, h], "detections": len(holes)}
    if len(holes) < 2:
        out["note"] = "检测不足 2 个孔，无法做 PCA"
        return out, None

    pts = np.array([dd["center"] for dd in holes], float)
    mean = pts.mean(axis=0)
    _, _, vt = np.linalg.svd(pts - mean, full_matrices=False)
    axis = vt[0]
    # 投影（不强制符号，保留原始 PCA 方向以展示歧义）
    proj = (pts - mean) @ axis
    order = np.argsort(proj)
    holes_sorted = [holes[i] for i in order]
    p_sorted = proj[order]

    spacings = np.diff(p_sorted)
    majors = np.array([dd["major"] for dd in holes_sorted])
    minors = np.array([dd["minor"] for dd in holes_sorted])

    # 间距/孔径单调性（只关心是否单调，方向由此决定）
    def mono(a):
        d = np.diff(a)
        if np.all(d > 0):
            return "increasing"
        if np.all(d < 0):
            return "decreasing"
        return "non-monotonic"

    out["pca"] = {"mean": [round(float(v), 2) for v in mean],
                  "axis": [round(float(v), 6) for v in axis],
                  "projections": [round(float(v), 2) for v in p_sorted],
                  "spacings": [round(float(v), 2) for v in spacings],
                  "spacing_monotonic": mono(spacings),
                  "major_axes": [round(float(v), 1) for v in majors],
                  "major_monotonic": mono(majors),
                  "minor_axes": [round(float(v), 1) for v in minors],
                  "major_over_minor": [round(float(a / b), 3) for a, b in zip(majors, minors)]}

    # ---- 箱体外轮廓 ----
    bc = box_silhouette(img)
    box = {"found": bc is not None}
    if bc is not None and len(bc) >= 5:
        rect = cv2.minAreaRect(bc)
        (rcx, rcy), (rw, rh), rang = rect
        box["min_area_rect"] = {"center": [round(rcx, 1), round(rcy, 1)],
                                "wh": [round(rw, 1), round(rh, 1)], "angle": round(rang, 2)}
        # 两端留白：把 4 个孔中心投影到轴上，量到轮廓在轴方向上的极值
        d = bc.reshape(-1, 2).astype(float) - mean
        box_proj = d @ axis
        h_min, h_max = float(p_sorted[0]), float(p_sorted[-1])
        gap_low = h_min - float(np.percentile(box_proj, 0.5))
        gap_high = float(np.percentile(box_proj, 99.5)) - h_max
        box["axis_extent"] = [round(float(np.percentile(box_proj, 0.5)), 1),
                              round(float(np.percentile(box_proj, 99.5)), 1)]
        box["hole_end_gap"] = {"low_side": round(gap_low, 1), "high_side": round(gap_high, 1),
                               "ratio": round(max(gap_low, gap_high) / max(min(gap_low, gap_high), 1e-6), 2)}
        box["area_ratio_vs_image"] = round(float(cv2.contourArea(bc)) / (w * h), 3)
        # 宽度剖面：沿轴分 10 段，量每段在垂直轴方向的跨度
        perp = np.array([-axis[1], axis[0]])
        dp = d @ perp
        nb = 10
        edges = np.linspace(box_proj.min(), box_proj.max(), nb + 1)
        widths = []
        for k in range(nb):
            sel = (box_proj >= edges[k]) & (box_proj < edges[k + 1])
            widths.append(round(float(dp[sel].max() - dp[sel].min()), 1) if sel.sum() > 5 else None)
        box["width_profile"] = widths
        wv = [x for x in widths if x]
        box["width_monotonic"] = mono(np.array(wv)) if len(wv) >= 3 else "n/a"
    out["box"] = box

    # 可视化
    vis = img.copy()
    overlay = img.copy()
    for dd in holes:
        overlay[dd["mask"]] = (0, 200, 0)
    vis = cv2.addWeighted(overlay, 0.3, vis, 0.7, 0)
    for k, dd in enumerate(holes_sorted, 1):
        cv2.drawContours(vis, [dd["contour"]], -1, (255, 255, 255), 2)
        (cx, cy), (MA, ma), ang = dd["ellipse"]
        cv2.ellipse(vis, ((cx, cy), (MA, ma), ang), (0, 255, 0), 3)
        cv2.circle(vis, (int(cx), int(cy)), 7, (0, 0, 255), -1)
        cv2.putText(vis, "P{}".format(k), (int(cx) + 14, int(cy) - 14),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 0, 0), 6, cv2.LINE_AA)
        cv2.putText(vis, "P{}".format(k), (int(cx) + 14, int(cy) - 14),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 255, 255), 2, cv2.LINE_AA)
    p0 = mean + axis * (p_sorted[0] - 80)
    p1 = mean + axis * (p_sorted[-1] + 80)
    cv2.line(vis, tuple(np.round(p0).astype(int)), tuple(np.round(p1).astype(int)), (255, 0, 0), 4)
    if bc is not None:
        cv2.drawContours(vis, [bc.astype(int)], -1, (0, 255, 255), 3)
    cv2.putText(vis, "spacing {}".format(out["pca"]["spacings"]), (20, 50),
                cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 0), 6, cv2.LINE_AA)
    cv2.putText(vis, "spacing {}".format(out["pca"]["spacings"]), (20, 50),
                cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 255, 255), 2, cv2.LINE_AA)
    vis_path = VIS / "feas_{}.jpg".format(img_path.stem)
    cv2.imwrite(str(vis_path), vis, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return out, vis_path


def main() -> int:
    RESULTS.mkdir(parents=True, exist_ok=True)
    VIS.mkdir(parents=True, exist_ok=True)
    from ultralytics import YOLO
    model = YOLO(str(WEIGHTS))
    imgs = sorted([p for p in TEST_DIR.iterdir() if p.suffix.lower() == ".jpg"])
    all_out = []
    for p in imgs:
        o, v = analyze(p, model)
        all_out.append(o)
        print("=" * 70)
        print(p.name, "-> 检出", o["detections"], "个孔")
        if "pca" in o:
            print("  spacing      :", o["pca"]["spacings"], o["pca"]["spacing_monotonic"])
            print("  major axes   :", o["pca"]["major_axes"], o["pca"]["major_monotonic"])
            print("  PCA axis     :", o["pca"]["axis"])
            b = o["box"]
            print("  box found    :", b["found"], b.get("hole_end_gap"), b.get("width_monotonic"))
        if v:
            print("  vis ->", v)
    (RESULTS / "feasibility_analysis.json").write_text(
        json.dumps({"generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "weights": str(WEIGHTS), "conf": CONF, "images": all_out},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n已保存:", RESULTS / "feasibility_analysis.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
