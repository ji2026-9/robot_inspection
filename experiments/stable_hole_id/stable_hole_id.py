# -*- coding: utf-8 -*-
"""
稳定 H01–H04 编号模块（独立脚本，不修改任何现有文件）
====================================================
设计原则：
  1. PCA 只给出「轴」，不给出方向 —— 模块**不默认** PCA 正方向就是 H01 方向。
  2. 方向消歧必须来自**可验证的对象内在参考**（外部参考轴 / 通过严格校验的外轮廓非对称）。
  3. 若找不到可靠参考 → orientation_status = "uncertain"，仍输出排序，
     但明确声明 H01/H04 可能对调，不谎称稳定。

方向参考方法链（按优先级）：
  M1 external_reference_axis : 调用方给定图像坐标系中的参考方向（来自标定/夹具/工作台）
  M2 silhouette_asymmetry    : GrabCut 分割工件轮廓，且必须通过严格校验才采信
  M3 none                    : 无可靠参考 → uncertain

用法：
  python stable_hole_id.py --source E:\\robot_inspection\\test_images
  python stable_hole_id.py --source xxx.jpg --reference-axis 0,1
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

PROJ = Path(r"E:\robot_inspection")
DEFAULT_WEIGHTS = PROJ / "weights" / "best.pt"
OUT_DIR = PROJ / "experiments" / "stable_hole_id" / "results"
VIS_DIR = PROJ / "experiments" / "stable_hole_id" / "visualizations"
CONF_DEFAULT = 0.50


def ellipse_from_mask(m):
    mm = (m.astype(np.uint8)) * 255
    cnts, _ = cv2.findContours(mm, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not cnts:
        return None, None
    c = max(cnts, key=cv2.contourArea)
    if len(c) < 5:
        return None, c
    return cv2.fitEllipse(c), c


def pca_axis(pts):
    mean = pts.mean(axis=0)
    _, _, vt = np.linalg.svd(pts - mean, full_matrices=False)
    return vt[0], mean


def try_silhouette(img, centers):
    """GrabCut 分割 + 严格校验。返回 (axis, info)；axis 为 None 表示不可信。"""
    h, w = img.shape[:2]
    xs = [c[0] for c in centers]
    ys = [c[1] for c in centers]
    spanx, spany = max(xs) - min(xs), max(ys) - min(ys)
    mx, my = 0.75 * spanx, 0.75 * spany
    rect = (max(0, int(min(xs) - mx)), max(0, int(min(ys) - my)),
            min(w - 1, int(spanx + 2 * mx)), min(h - 1, int(spany + 2 * my)))
    small = cv2.resize(img, (w // 4, h // 4), interpolation=cv2.INTER_AREA)
    r4 = (rect[0] // 4, rect[1] // 4, max(2, rect[2] // 4), max(2, rect[3] // 4))
    mask = np.zeros(small.shape[:2], np.uint8)
    bgd, fgd = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
    try:
        cv2.grabCut(small, mask, r4, bgd, fgd, 5, cv2.GC_INIT_WITH_RECT)
    except Exception as e:
        return None, {"ok": False, "reason": "grabcut_failed: {}".format(e)}
    m2 = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
    m2 = cv2.morphologyEx(m2, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    m2 = cv2.morphologyEx(m2, cv2.MORPH_OPEN, np.ones((7, 7), np.uint8))
    cnts, _ = cv2.findContours(m2, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not cnts:
        return None, {"ok": False, "reason": "no_contour"}
    c = max(cnts, key=cv2.contourArea).astype(np.float32) * 4.0

    area_ratio = cv2.contourArea(c) / (w * h)
    inside = sum(1 for (x, y) in centers
                 if cv2.pointPolygonTest(c, (float(x), float(y)), False) >= 0)
    ok_area = 0.02 <= area_ratio <= 0.45
    ok_holes = inside >= max(1, len(centers) - 1)
    info = {"ok": bool(ok_area and ok_holes), "area_ratio": round(area_ratio, 4),
            "holes_inside": inside, "n_holes": len(centers),
            "check_area": ok_area, "check_holes": ok_holes}
    if not info["ok"]:
        info["reason"] = "validation_failed"
        return None, info

    (_, _), (rw, rh), rang = cv2.minAreaRect(c)
    ang = np.deg2rad(rang)
    axis = np.array([np.cos(ang), np.sin(ang)])
    if rw < rh:
        axis = np.array([-axis[1], axis[0]])
    info["min_area_rect_wh"] = [round(rw, 1), round(rh, 1)]
    return axis, info


def id_holes(holes, axis_ref=None):
    pts = np.array([h["center"] for h in holes], float)
    if len(pts) < 2:
        for i, h in enumerate(holes, 1):
            h["id"] = "H{:02d}".format(i)
        return holes, None, None
    axis, mean = pca_axis(pts)
    if axis_ref is not None:
        a = np.asarray(axis_ref, float)
        a = a / (np.linalg.norm(a) + 1e-9)
        if np.dot(a, axis) < 0:
            a = -a
        order_axis = a
    else:
        order_axis = axis
        if order_axis[0] < 0:      # 仅用于可复现，不是物理方向
            order_axis = -order_axis
    proj = (pts - mean) @ order_axis
    order = np.argsort(proj)
    for i, idx in enumerate(order, 1):
        holes[idx]["id"] = "H{:02d}".format(i)
        holes[idx]["proj"] = round(float(proj[idx]), 2)
    return holes, order_axis, mean


def draw(img, holes, axis, mean, status, method, out_path):
    vis = img.copy()
    overlay = img.copy()
    for h in holes:
        overlay[h["mask"]] = (0, 200, 0)
    vis = cv2.addWeighted(overlay, 0.3, vis, 0.7, 0)
    for h in holes:
        cv2.drawContours(vis, [h["contour"]], -1, (255, 255, 255), 2)
        (cx, cy), (MA, ma), ang = h["ellipse"]
        cv2.ellipse(vis, ((cx, cy), (MA, ma), ang), (0, 255, 0), 3)
        cv2.circle(vis, (int(cx), int(cy)), 7, (0, 0, 255), -1)
        txt = "{} conf={:.2f}".format(h["id"], h["conf"])
        cv2.putText(vis, txt, (int(cx) + 14, int(cy) - 14), cv2.FONT_HERSHEY_SIMPLEX,
                    1.0, (0, 0, 0), 6, cv2.LINE_AA)
        cv2.putText(vis, txt, (int(cx) + 14, int(cy) - 14), cv2.FONT_HERSHEY_SIMPLEX,
                    1.0, (0, 255, 255), 2, cv2.LINE_AA)
    if axis is not None and mean is not None:
        p0 = mean - axis * 220
        p1 = mean + axis * 220
        cv2.arrowedLine(vis, tuple(np.round(p0).astype(int)), tuple(np.round(p1).astype(int)),
                        (255, 0, 0), 4, tipLength=0.06)
    col = (0, 200, 0) if status == "stable" else (0, 165, 255)
    hdr = "orientation_status = {}   method = {}".format(status, method)
    cv2.putText(vis, hdr, (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.3, (0, 0, 0), 7, cv2.LINE_AA)
    cv2.putText(vis, hdr, (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.3, col, 3, cv2.LINE_AA)
    if status != "stable":
        note = "H01/H04 may be swapped (180-deg ambiguity)"
        cv2.putText(vis, note, (20, 120), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 0, 0), 6, cv2.LINE_AA)
        cv2.putText(vis, note, (20, 120), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 0, 255), 2, cv2.LINE_AA)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_path), vis, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return out_path


def process(model, img_path, reference_axis=None, write_vis=True):
    img = cv2.imread(str(img_path))
    r = model.predict(source=str(img_path), conf=CONF_DEFAULT, iou=0.7, imgsz=640,
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
                      "center": (float(cx), float(cy)),
                      "center_x": round(float(cx), 2), "center_y": round(float(cy), 2),
                      "ellipse_major": round(float(max(MA, ma)), 2),
                      "ellipse_minor": round(float(min(MA, ma)), 2),
                      "ellipse_angle": round(float(ang), 2),
                      "ellipse": ell, "contour": cnt, "mask": m})

    centers = [h["center"] for h in holes]
    status, method, oconf, detail = "uncertain", "none", 0.0, {}

    if reference_axis is not None and len(holes) >= 2:
        holes, axis, mean = id_holes(holes, axis_ref=np.asarray(reference_axis, float))
        A, _ = pca_axis(np.array(centers))
        rv = np.asarray(reference_axis, float)
        rv = rv / (np.linalg.norm(rv) + 1e-9)
        oconf = round(abs(float(np.dot(rv, A))), 3)
        status, method = "stable", "external_reference_axis"
    else:
        sax, sinfo = (None, {})
        if len(holes) >= 3:
            sax, sinfo = try_silhouette(img, centers)
        detail["silhouette"] = sinfo
        if sax is not None:
            holes, axis, mean = id_holes(holes, axis_ref=sax)
            status, method = "stable", "silhouette_asymmetry"
            oconf = round(float(sinfo.get("area_ratio", 0.0)), 3)
        else:
            holes, axis, mean = id_holes(holes, axis_ref=None)

    holes_sorted = sorted(holes, key=lambda h: h["id"])
    out = {
        "image": str(img_path),
        "detections": len(holes_sorted),
        "holes": [{"id": h["id"], "center_x": h["center_x"], "center_y": h["center_y"],
                   "confidence": h["conf"], "ellipse_major": h["ellipse_major"],
                   "ellipse_minor": h["ellipse_minor"], "ellipse_angle": h["ellipse_angle"]}
                  for h in holes_sorted],
        "orientation_confidence": oconf,
        "orientation_method": method,
        "orientation_status": status,
        "flip_ambiguity": bool(status != "stable"),
        "notes": (["未找到可验证的对象内在方向参考；H01-H04 仅按 PCA 主轴投影排序，"
                   "H01/H04 在 180 度翻转下会对调。"] if status != "stable" else
                  ["方向来自 {}。".format(method)]),
        "detail": detail,
    }
    if write_vis:
        vp = VIS_DIR / "stable_{}.jpg".format(img_path.stem)
        draw(img, holes_sorted, axis, mean, status, method, vp)
        out["visualization"] = str(vp)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", default=str(DEFAULT_WEIGHTS))
    ap.add_argument("--source", default=str(PROJ / "test_images"))
    ap.add_argument("--reference-axis", default=None,
                    help="图像坐标系参考方向 'x,y'，指向物理 H01 端（来自标定/夹具）")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    src = Path(args.source)
    imgs = sorted([p for p in src.iterdir() if p.suffix.lower() in (".jpg", ".png")]) \
        if src.is_dir() else [src]
    ref = [float(v) for v in args.reference_axis.split(",")] if args.reference_axis else None

    from ultralytics import YOLO
    model = YOLO(str(args.weights))
    outs = [process(model, p, reference_axis=ref) for p in imgs]
    res = {"generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
           "weights": str(args.weights), "conf_threshold": CONF_DEFAULT,
           "reference_axis": ref, "results": outs}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    op = Path(args.out) if args.out else OUT_DIR / "stable_hole_id_output.json"
    op.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    for o in outs:
        print("{:<12} det={} status={} method={}".format(
            Path(o["image"]).name, o["detections"], o["orientation_status"], o["orientation_method"]))
        for h in o["holes"]:
            print("    {}  ({:.0f}, {:.0f})  conf={:.3f}".format(
                h["id"], h["center_x"], h["center_y"], h["confidence"]))
    print("\n已保存:", op)
    return 0


if __name__ == "__main__":
    sys.exit(main())
