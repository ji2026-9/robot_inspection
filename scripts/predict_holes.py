# -*- coding: utf-8 -*-
"""
孔位检测 + 椭圆拟合 + PCA 主轴编号（H01~H04）
--------------------------------------------
流程：
    图片 -> YOLO11n-Seg 推理（cylinder_bore）
         -> 每个实例的 mask 轮廓 -> cv2.fitEllipse 得到更准确的孔中心
         -> 4 个孔中心做 PCA 求工件长轴
         -> 沿长轴排序，编号 H01 / H02 / H03 / H04
         -> 可视化保存到 E:\\robot_project\\robot_inspection\\results\\

用法：
    E:\\robot_project\\robot_inspection\\.venv\\Scripts\\python.exe scripts\\predict_holes.py
    E:\\robot_project\\robot_inspection\\.venv\\Scripts\\python.exe scripts\\predict_holes.py --source "E:\\some\\dir"
    E:\\robot_project\\robot_inspection\\.venv\\Scripts\\python.exe scripts\\predict_holes.py --source 测试1.jpg
"""

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

PROJ = Path(r"E:\robot_project\robot_inspection")
DEFAULT_WEIGHTS = PROJ / "weights" / "best.pt"
DEFAULT_OUT = PROJ / "results"
CONF_THRESHOLD = 0.50      # 高置信度阈值（与之前验证一致）
CONF_FLOOR = 0.10          # 补检下限：不足 4 个孔时，用低阈值补足，并标注为低置信度
IOU_THRESHOLD = 0.70
IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}

# 测试图片的候选查找位置（按顺序）
CANDIDATE_DIRS = [
    PROJ / "test_images",
    Path(r"E:\vm_share\训练照片（箱体）"),
    PROJ / "dataset" / "box_yolo" / "images" / "test",
    Path(r"E:\vm_share\训练照片"),
]

COLORS = [(0, 200, 0), (0, 140, 255), (255, 120, 0), (200, 0, 200), (0, 220, 220), (255, 0, 0)]


def find_images(source):
    """定位待测试图片。"""
    if source:
        p = Path(source)
        if p.is_dir():
            return sorted([q for q in p.iterdir() if q.suffix.lower() in IMG_EXTS])
        if p.is_file():
            return [p]
        for d in CANDIDATE_DIRS:
            cand = d / source
            if cand.is_file():
                return [cand]
        return []

    for d in CANDIDATE_DIRS:
        if not d.is_dir():
            continue
        tests = sorted([q for q in d.iterdir()
                        if q.suffix.lower() in IMG_EXTS and q.stem.startswith("测试")])
        if tests:
            return tests
    return []


def ellipse_from_mask(mask_bool):
    """用 mask 的最大外轮廓做 cv2.fitEllipse。"""
    m = (mask_bool.astype(np.uint8)) * 255
    contours, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return None, None
    cnt = max(contours, key=cv2.contourArea)
    if len(cnt) < 5:
        return None, cnt
    return cv2.fitEllipse(cnt), cnt


def pca_long_axis(centers):
    """对孔中心做 PCA，返回 (单位主轴向量, 质心)。主轴方向固定指向图像右侧，保证编号可复现。"""
    pts = np.asarray(centers, dtype=float)
    mean = pts.mean(axis=0)
    x = pts - mean
    _, _, vt = np.linalg.svd(x, full_matrices=False)
    axis = vt[0]
    if axis[0] < 0:
        axis = -axis
    return axis, mean


def draw_result(img, dets, axis, mean, out_path, title):
    overlay = img.copy()
    for d in dets:
        c = COLORS[(d["index"] - 1) % len(COLORS)]
        overlay[d["mask_bool"]] = c
    vis = cv2.addWeighted(overlay, 0.35, img, 0.65, 0)

    for d in dets:
        cnt = d["contour"]
        if cnt is not None:
            cv2.drawContours(vis, [cnt], -1, (255, 255, 255), 2)

        (cx, cy), (MA, ma), ang = d["ellipse"]
        ell_color = (0, 255, 0) if d["conf"] >= CONF_THRESHOLD else (0, 200, 255)
        cv2.ellipse(vis, ((cx, cy), (MA, ma), ang), ell_color, 3)
        cv2.circle(vis, (int(round(cx)), int(round(cy))), 6, (0, 0, 255), -1)
        cv2.circle(vis, (int(round(cx)), int(round(cy))), 9, (255, 255, 255), 2)

        label = "H{:02d}  conf={:.2f}".format(d["index"], d["conf"])
        if d["conf"] < CONF_THRESHOLD:
            label += "  LOW"
        tx, ty = int(round(cx)) + 12, int(round(cy)) - 12
        cv2.putText(vis, label, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 0, 0), 4, cv2.LINE_AA)
        cv2.putText(vis, label, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255, 255, 255), 2, cv2.LINE_AA)

    if axis is not None and len(dets) >= 2:
        pts = np.array([d["center"] for d in dets], dtype=float)
        proj = (pts - mean) @ axis
        p0 = mean + axis * (proj.min() - 60)
        p1 = mean + axis * (proj.max() + 60)
        cv2.line(vis, tuple(np.round(p0).astype(int)), tuple(np.round(p1).astype(int)), (255, 0, 0), 3)
        cv2.putText(vis, "PCA long axis", tuple(np.round(p1).astype(int) + np.array([10, 0])),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 0, 0), 2, cv2.LINE_AA)

    n_low = sum(1 for d in dets if d["conf"] < CONF_THRESHOLD)
    hdr = "{}  |  detections={}  |  conf>={} : {} , low-conf: {}".format(
        title, len(dets), CONF_THRESHOLD, len(dets) - n_low, n_low)
    cv2.putText(vis, hdr, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 5, cv2.LINE_AA)
    cv2.putText(vis, hdr, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 255), 2, cv2.LINE_AA)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_path), vis)
    return vis


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", default=str(DEFAULT_WEIGHTS))
    ap.add_argument("--source", default=None, help="图片文件或目录；默认自动查找 测试1~4.jpg")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--conf", type=float, default=CONF_THRESHOLD)
    ap.add_argument("--conf-floor", type=float, default=CONF_FLOOR,
                    help="补检下限；不足 4 个孔时用该阈值补足并标注为低置信度")
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--device", default="0")
    args = ap.parse_args()

    weights = Path(args.weights)
    if not weights.is_file():
        print("[错误] 找不到模型权重：{}".format(weights))
        print("       请先运行训练脚本 scripts\\train_seg.py")
        return 2

    images = find_images(args.source)
    if not images:
        print("[错误] 没有找到任何测试图片。")
        print("       请把测试图片放到 E:\\robot_project\\robot_inspection\\test_images\\ 下，")
        print("       或用 --source 指定图片路径/目录。")
        return 2

    print("=" * 70)
    print("模型权重 : {}".format(weights))
    print("测试图片 : {} 张".format(len(images)))
    for p in images:
        print("           ", p)
    print("=" * 70)

    from ultralytics import YOLO
    model = YOLO(str(weights))

    out_dir = Path(args.out)
    report = {"weights": str(weights), "conf_threshold": args.conf, "images": []}

    for img_path in images:
        img = cv2.imread(str(img_path))
        if img is None:
            print("[警告] 无法读取图片：{}".format(img_path))
            continue

        # 先用较低阈值推理，再按需要取前 4 个；高/低置信度在结果中分别标注
        results = model.predict(
            source=str(img_path), conf=min(args.conf, args.conf_floor), iou=IOU_THRESHOLD,
            imgsz=args.imgsz, device=args.device, retina_masks=True, verbose=False,
        )
        r = results[0]
        n = 0 if r.masks is None else len(r.masks)

        dets = []
        for i in range(n):
            mask = r.masks.data[i].cpu().numpy() > 0.5
            conf = float(r.boxes.conf[i].cpu().numpy())
            cls = int(r.boxes.cls[i].cpu().numpy())
            name = r.names.get(cls, str(cls))
            ell, cnt = ellipse_from_mask(mask)
            if ell is None:
                continue
            (cx, cy), (MA, ma), ang = ell
            dets.append({
                "conf": round(conf, 4), "cls": cls, "name": name,
                "mask_bool": mask, "contour": cnt, "ellipse": ell,
                "mask_center": [round(cx, 2), round(cy, 2)],
                "center": (float(cx), float(cy)),
                "angle_deg": round(float(ang), 2),
                "width": round(float(MA), 2),
                "height": round(float(ma), 2),
                "low_conf": conf < args.conf,
            })

        # 本项目工件固定 4 个大型圆孔：按置信度取前 4 个
        dets.sort(key=lambda d: d["conf"], reverse=True)
        dets = dets[:4]

        axis = mean = None
        if len(dets) >= 2:
            axis, mean = pca_long_axis([d["center"] for d in dets])

        if axis is not None:
            pts = np.array([d["center"] for d in dets])
            proj = (pts - mean) @ axis
            order = np.argsort(proj)
            for new_idx, det_i in enumerate(order, start=1):
                dets[det_i]["index"] = new_idx
        else:
            for i, d in enumerate(dets, start=1):
                d["index"] = i

        dets_sorted = sorted(dets, key=lambda d: d["index"])

        stem = img_path.stem
        vis_path = out_dir / "{}_result.jpg".format(stem)
        draw_result(img, dets_sorted, axis, mean, vis_path, stem)

        entry = {"image": str(img_path), "detections": len(dets_sorted), "holes": []}
        n_low = sum(1 for d in dets_sorted if d["low_conf"])
        print("")
        print("-" * 70)
        print("图片：{}    检测到 cylinder_bore：{} 个（其中低置信度补检 {} 个）".format(
            img_path.name, len(dets_sorted), n_low))
        print("{:<6}{:>8}{:>22}{:>12}{:>10}{:>10}".format("编号", "conf", "center(x,y)", "angle(deg)", "width", "height"))
        for d in dets_sorted:
            flag = " *低置信度" if d["low_conf"] else ""
            print("H{:02d}   {:>8.3f}{:>22}{:>12.2f}{:>10.2f}{:>10.2f}{}".format(
                d["index"], d["conf"],
                "({:.1f}, {:.1f})".format(d["center"][0], d["center"][1]),
                d["angle_deg"], d["width"], d["height"], flag))
            entry["holes"].append({
                "id": "H{:02d}".format(d["index"]),
                "confidence": d["conf"],
                "low_confidence": d["low_conf"],
                "class": d["name"],
                "ellipse_center": d["mask_center"],
                "ellipse_angle_deg": d["angle_deg"],
                "ellipse_width": d["width"],
                "ellipse_height": d["height"],
            })
        print("可视化已保存：{}".format(vis_path))
        report["images"].append(entry)

    report_path = out_dir / "detection_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("")
    print("=" * 70)
    print("检测报告已保存：{}".format(report_path))
    total_ok = sum(1 for e in report["images"] if e["detections"] == 4)
    print("汇总：{}/{} 张图片检测到 4 个目标大孔".format(total_ok, len(report["images"])))
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
