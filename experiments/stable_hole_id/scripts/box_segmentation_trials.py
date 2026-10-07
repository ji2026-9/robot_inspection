# -*- coding: utf-8 -*-
"""
Step 2　箱体外轮廓分割方案对比（只读）
=====================================
Phase 1 的可行性分析发现：Otsu+连通域 抓到的是背景工作台，而不是箱体。
本脚本对比三种分割策略，并输出并排可视化，用于判断“箱体外轮廓”是否能可靠获得。

策略：
  S1: Otsu + 最大连通域（上一步已证明不可靠，这里保留作对照）
  S2: GrabCut，ROI = 由 4 个孔位外扩得到
  S3: GrabCut + 颜色先验（金属灰：低饱和 + 中高亮度）

输出：visualizations\\seg_<图片>_<策略>.jpg 与 results\\box_segmentation_trials.json

用法：
    python experiments\\stable_hole_id\\scripts\\box_segmentation_trials.py
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


def hole_centers(model, img_path):
    r = model.predict(source=str(img_path), conf=CONF, iou=0.7, imgsz=640,
                      device=0, retina_masks=True, verbose=False)[0]
    cs = []
    n = 0 if r.masks is None else len(r.masks)
    for i in range(n):
        m = r.masks.data[i].cpu().numpy() > 0.5
        mm = (m.astype(np.uint8)) * 255
        cnts, _ = cv2.findContours(mm, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        if not cnts:
            continue
        c = max(cnts, key=cv2.contourArea)
        if len(c) < 5:
            continue
        (cx, cy), _, _ = cv2.fitEllipse(c)
        cs.append((float(cx), float(cy), float(cv2.contourArea(c))))
    return cs


def s1_otsu(img):
    h, w = img.shape[:2]
    small = cv2.resize(img, (w // 4, h // 4), interpolation=cv2.INTER_AREA)
    g = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), (5, 5), 0)
    _, th = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    th = cv2.morphologyEx(th, cv2.MORPH_OPEN, np.ones((7, 7), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(th, 8)
    if n <= 1:
        return None
    i = max(range(1, n), key=lambda k: stats[k, cv2.CC_STAT_AREA])
    comp = (lab == i).astype(np.uint8) * 255
    cnts, _ = cv2.findContours(comp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    return (max(cnts, key=cv2.contourArea) * 4.0).astype(np.int32) if cnts else None


def grabcut(img, rect, iters=6):
    mask = np.zeros(img.shape[:2], np.uint8)
    bgd = np.zeros((1, 65), np.float64)
    fgd = np.zeros((1, 65), np.float64)
    try:
        cv2.grabCut(img, mask, rect, bgd, fgd, iters, cv2.GC_INIT_WITH_RECT)
    except Exception:
        return None
    m2 = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 1, 0).astype(np.uint8)
    m2 = cv2.morphologyEx(m2 * 255, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    m2 = cv2.morphologyEx(m2, cv2.MORPH_OPEN, np.ones((15, 15), np.uint8))
    cnts, _ = cv2.findContours(m2, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    return max(cnts, key=cv2.contourArea) if cnts else None


def contour_metrics(c, centers, shape):
    if c is None or len(c) < 5:
        return {"ok": False}
    area = cv2.contourArea(c)
    rect = cv2.minAreaRect(c.astype(np.float32))
    (rcx, rcy), (rw, rh), rang = rect
    inside = sum(1 for (x, y, _) in centers if cv2.pointPolygonTest(c.astype(np.float32), (x, y), False) >= 0)
    return {"ok": True, "area_ratio": round(float(area) / (shape[0] * shape[1]), 3),
            "min_area_rect_wh": [round(rw, 1), round(rh, 1)], "rect_angle": round(rang, 2),
            "holes_inside": inside, "n_holes": len(centers)}


def main() -> int:
    RESULTS.mkdir(parents=True, exist_ok=True)
    VIS.mkdir(parents=True, exist_ok=True)
    from ultralytics import YOLO
    model = YOLO(str(WEIGHTS))
    out = []
    for p in sorted(TEST_DIR.glob("*.jpg")):
        img = cv2.imread(str(p))
        h, w = img.shape[:2]
        centers = hole_centers(model, p)
        print("=" * 70)
        print(p.name, "孔数", len(centers))
        if not centers:
            continue
        xs = [c[0] for c in centers]
        ys = [c[1] for c in centers]
        x0, x1 = min(xs), max(xs)
        y0, y1 = min(ys), max(ys)
        spanx, spany = x1 - x0, y1 - y0
        mx, my = 0.75 * spanx, 0.75 * spany
        rect = (max(0, int(x0 - mx)), max(0, int(y0 - my)),
                min(w - 1, int(spanx + 2 * mx)), min(h - 1, int(spany + 2 * my)))
        s1 = s1_otsu(img)
        s2 = grabcut(img, rect, 6)
        rec = {"image": p.name, "n_holes": len(centers),
               "roi_rect": list(rect),
               "s1_otsu": contour_metrics(s1, centers, (h, w)),
               "s2_grabcut": contour_metrics(s2, centers, (h, w))}
        # 可视化三宫格
        panel = img.copy()
        if s1 is not None:
            cv2.drawContours(panel, [s1], -1, (0, 255, 255), 4)
        if s2 is not None:
            cv2.drawContours(panel, [s2], -1, (0, 0, 255), 4)
        cv2.rectangle(panel, (rect[0], rect[1]), (rect[0] + rect[2], rect[1] + rect[3]), (255, 0, 0), 4)
        for (x, y, a) in centers:
            cv2.circle(panel, (int(x), int(y)), 10, (0, 255, 0), -1)
        cv2.putText(panel, "yellow=S1(Otsu) red=S2(GrabCut) blue=ROI", (20, 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 0, 0), 7, cv2.LINE_AA)
        cv2.putText(panel, "yellow=S1(Otsu) red=S2(GrabCut) blue=ROI", (20, 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.4, (255, 255, 255), 3, cv2.LINE_AA)
        vp = VIS / "seg_{}.jpg".format(p.stem)
        cv2.imwrite(str(vp), panel, [cv2.IMWRITE_JPEG_QUALITY, 88])
        rec["vis"] = str(vp)
        print("  S1:", rec["s1_otsu"])
        print("  S2:", rec["s2_grabcut"])
        out.append(rec)
    (RESULTS / "box_segmentation_trials.json").write_text(
        json.dumps({"generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "trials": out}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n已保存:", RESULTS / "box_segmentation_trials.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
