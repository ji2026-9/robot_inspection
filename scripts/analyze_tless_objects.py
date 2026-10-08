# -*- coding: utf-8 -*-
"""
T-LESS 物体孔洞/反光程序化分析
==============================
对 T-LESS 官方 30 个物体预览图，逐张统计：
  - 物体轮廓面积
  - 被轮廓包围的暗区（孔洞/开口）数量、圆度、椭圆长短轴比
  - 圆形孔数量
  - 镜面高光像素比例（反光）
输出：tless_sample\\metadata\\tless_object_analysis.json

用法：
    python scripts\analyze_tless_objects.py
"""

import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(r"E:\robot_project\robot_inspection\external_datasets\tless_sample")


def main() -> int:
    imgs = sorted((ROOT / "images" / "objects").glob("*.jpg"))
    if not imgs:
        print("[错误] 找不到物体预览图：", ROOT / "images" / "objects")
        return 2

    res = []
    for p in imgs:
        img = cv2.imread(str(p))
        if img is None:
            continue
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # 1) 物体轮廓（黑幕背景 -> 亮度阈值）
        _, th = cv2.threshold(gray, 28, 255, cv2.THRESH_BINARY)
        th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
        cnts, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not cnts:
            continue
        main_c = max(cnts, key=cv2.contourArea)
        obj_area = int(cv2.contourArea(main_c))
        if obj_area < 500:
            continue
        obj_mask = np.zeros_like(gray)
        cv2.drawContours(obj_mask, [main_c], -1, 255, -1)

        # 2) 物体内部的暗区 = 孔洞/开口候选（腐蚀掉外缘，避免把阴影算进来）
        dark = ((gray < 60).astype(np.uint8)) * 255
        dark = cv2.bitwise_and(dark, obj_mask)
        dark = cv2.morphologyEx(dark, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
        dark = cv2.bitwise_and(dark, cv2.erode(obj_mask, np.ones((15, 15), np.uint8)))

        holes = []
        hc, _ = cv2.findContours(dark, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in hc:
            a = cv2.contourArea(c)
            if a < obj_area * 0.004 or a > obj_area * 0.55:
                continue
            per = cv2.arcLength(c, True)
            circ = 4 * np.pi * a / (per * per) if per > 0 else 0.0
            aspect = 1.0
            if len(c) >= 5:
                (_, _), (ma, mi), _ = cv2.fitEllipse(c)
                if max(ma, mi) > 0:
                    aspect = min(ma, mi) / max(ma, mi)
            cx, cy = np.mean(c.reshape(-1, 2), axis=0)
            holes.append({"area_ratio": round(a / obj_area, 4),
                          "circularity": round(float(circ), 3),
                          "ellipse_aspect": round(float(aspect), 3),
                          "center": [round(float(cx), 1), round(float(cy), 1)]})

        # 3) 镜面高光比例
        spec = float(((gray > 235) & (obj_mask > 0)).sum()) / max(obj_area, 1)

        # 4) 放宽版检测：相对亮度阈值（孔内壁常是中灰，不是纯黑）
        obj_px = gray[obj_mask > 0]
        med = float(np.median(obj_px)) if obj_px.size else 128.0
        dark2 = ((gray < med - 35).astype(np.uint8)) * 255
        dark2 = cv2.bitwise_and(dark2, obj_mask)
        dark2 = cv2.morphologyEx(dark2, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
        dark2 = cv2.bitwise_and(dark2, cv2.erode(obj_mask, np.ones((11, 11), np.uint8)))
        hc2, _ = cv2.findContours(dark2, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        holes2 = []
        for c in hc2:
            a = cv2.contourArea(c)
            if a < obj_area * 0.002 or a > obj_area * 0.55:
                continue
            per = cv2.arcLength(c, True)
            circ = 4 * np.pi * a / (per * per) if per > 0 else 0.0
            aspect = 1.0
            if len(c) >= 5:
                (_, _), (ma, mi), _ = cv2.fitEllipse(c)
                if max(ma, mi) > 0:
                    aspect = min(ma, mi) / max(ma, mi)
            holes2.append({"area_ratio": round(a / obj_area, 4),
                           "circularity": round(float(circ), 3),
                           "ellipse_aspect": round(float(aspect), 3)})

        # 5) 霍夫圆（补充：找圆形开口边缘）
        blur = cv2.medianBlur(gray, 5)
        circles = cv2.HoughCircles(blur, cv2.HOUGH_GRADIENT, dp=1.5, minDist=60,
                                   param1=120, param2=45, minRadius=28, maxRadius=220)
        n_circ = 0
        if circles is not None:
            for c in circles[0]:
                cx, cy, rr = float(c[0]), float(c[1]), float(c[2])
                # 圆心必须落在物体内部（含一定容差）
                if 0 <= int(cy) < gray.shape[0] and 0 <= int(cx) < gray.shape[1]:
                    if obj_mask[int(cy), int(cx)] > 0 or \
                       cv2.pointPolygonTest(main_c, (cx, cy), False) >= -rr * 0.5:
                        n_circ += 1

        res.append({"object": p.stem.replace("obj_", ""),
                    "object_area_px": obj_area,
                    "n_holes": len(holes),
                    "round_holes": sum(1 for x in holes
                                       if x["circularity"] > 0.55 and x["ellipse_aspect"] > 0.6),
                    "holes": holes,
                    "n_holes_relaxed": len(holes2),
                    "round_holes_relaxed": sum(1 for x in holes2
                                               if x["circularity"] > 0.45 and x["ellipse_aspect"] > 0.5),
                    "hough_circles": n_circ,
                    "object_median_brightness": round(med, 1),
                    "specular_ratio": round(spec, 4),
                    "mean_brightness": round(float(gray[obj_mask > 0].mean()), 1)})

    out = ROOT / "metadata" / "tless_object_analysis.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")

    print("{:<6}{:>7}{:>9}{:>8}{:>8}{:>10}{:>9}".format(
        "obj", "holes", "relaxed", "rnd_rel", "hough", "specular", "bright"))
    for r in res:
        print("{:<6}{:>7}{:>9}{:>8}{:>8}{:>10.3f}{:>9.1f}".format(
            r["object"], r["n_holes"], r["n_holes_relaxed"], r["round_holes_relaxed"],
            r["hough_circles"], r["specular_ratio"], r["mean_brightness"]))

    n = len(res)
    h1 = sum(1 for r in res if r["n_holes"] >= 1)
    r1 = sum(1 for r in res if r["round_holes"] >= 1)
    h3 = sum(1 for r in res if r["n_holes"] >= 3)
    sp = sum(1 for r in res if r["specular_ratio"] > 0.005)
    print("\n对象总数                               : {}".format(n))
    print("检出 >=1 个孔的对象                    : {} ({:.0f}%)".format(h1, 100 * h1 / n))
    print("检出 >=1 个【圆形】孔的对象            : {} ({:.0f}%)".format(r1, 100 * r1 / n))
    print("检出 >=3 个孔（成排多孔特征）的对象    : {}".format(h3))
    print("有明显镜面高光的对象 (specular>0.5%)   : {}".format(sp))
    h1r = sum(1 for r in res if r["n_holes_relaxed"] >= 1)
    r1r = sum(1 for r in res if r["round_holes_relaxed"] >= 1)
    h3r = sum(1 for r in res if r["n_holes_relaxed"] >= 3)
    hg = sum(1 for r in res if r["hough_circles"] >= 1)
    hg3 = sum(1 for r in res if r["hough_circles"] >= 3)
    print("放宽阈值：检出 >=1 个孔/开口的对象      : {} ({:.0f}%)".format(h1r, 100 * h1r / n))
    print("放宽阈值：检出 >=1 个近圆孔的对象       : {} ({:.0f}%)".format(r1r, 100 * r1r / n))
    print("放宽阈值：检出 >=3 个孔（成排多孔）     : {}".format(h3r))
    print("霍夫圆：检出 >=1 个圆的对象             : {} ({:.0f}%)".format(hg, 100 * hg / n))
    print("霍夫圆：检出 >=3 个圆的对象（多孔排列） : {}".format(hg3))
    print("保存:", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
