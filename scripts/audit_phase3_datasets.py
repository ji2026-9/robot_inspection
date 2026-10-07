# -*- coding: utf-8 -*-
"""
Phase 3 真图审计：T-LESS 测试场景 01 + Workpieces
================================================
对真实下载并校验过的数据做程序化统计，并生成 contact sheet：

  T-LESS：
    - rgb/ 图像数量、尺寸、解码成功率、亮度、对比度、强高光比例
    - 霍夫圆检测（圆形/椭圆开口）、是否存在成排（近似共线）多圆
    - 解析 gt.yml 得到每帧的目标数、类别（obj_id）、bbox 尺寸与长宽比（判断斜视/透视程度）
    - 明确记录：原始格式是否提供 mask
  Workpieces：
    - 图像数量、格式、尺寸、解码成功率、亮度、对比度、强高光比例
    - Defects / Ok 分布

输出：
  external_datasets\\metadata\\phase3_tless_stats.json
  external_datasets\\metadata\\phase3_workpieces_stats.json
  external_datasets\\phase3_tless_audit\\previews\\*.jpg
  external_datasets\\phase3_workpieces_audit\\previews\\*.jpg

用法：
    python scripts\\audit_phase3_datasets.py
"""

import json
import random
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

DL = Path(r"E:\robot_inspection\external_datasets\phase3_downloads")
META = Path(r"E:\robot_inspection\external_datasets\metadata")
TA = Path(r"E:\robot_inspection\external_datasets\phase3_tless_audit")
WA = Path(r"E:\robot_inspection\external_datasets\phase3_workpieces_audit")
SEED = 0
N_SAMPLE = 120


def decode_stats(paths):
    ok = 0
    bad = []
    sizes = Counter()
    bright, contrast, spec = [], [], []
    for p in paths:
        im = cv2.imread(str(p), cv2.IMREAD_UNCHANGED)
        if im is None:
            bad.append(str(p))
            continue
        ok += 1
        if im.ndim == 3:
            g = cv2.cvtColor(im[:, :, :3].astype(np.uint8), cv2.COLOR_BGR2GRAY)
        else:
            g = cv2.normalize(im, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
        sizes["{}x{}".format(im.shape[1], im.shape[0])] += 1
        bright.append(float(g.mean()))
        contrast.append(float(g.std()))
        spec.append(float((g > 240).mean()))
    n = max(ok, 1)
    return {"count": len(paths), "decoded_ok": ok, "decode_failed": len(bad),
            "failed_examples": bad[:5],
            "sizes": dict(sizes.most_common(6)),
            "brightness_mean": round(float(np.mean(bright)), 1) if bright else None,
            "contrast_mean": round(float(np.mean(contrast)), 1) if contrast else None,
            "specular_ratio_mean": round(float(np.mean(spec)), 4) if spec else None}


def circle_analysis(paths, max_n=40):
    """在真实图上找圆/椭圆开口，并判断是否存在近似共线的成排圆。"""
    rows = []
    n_with_circle = n_with_row = 0
    for p in paths[:max_n]:
        im = cv2.imread(str(p))
        if im is None:
            continue
        g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
        g = cv2.medianBlur(g, 5)
        cs = cv2.HoughCircles(g, cv2.HOUGH_GRADIENT, dp=1.5, minDist=40,
                              param1=120, param2=45, minRadius=15, maxRadius=400)
        centers = []
        if cs is not None:
            centers = [(float(c[0]), float(c[1]), float(c[2])) for c in cs[0]]
        has_row = False
        if len(centers) >= 3:
            for axis in (0, 1):
                vals = sorted(c[axis] for c in centers)
                for k in range(len(vals) - 2):
                    if vals[k + 2] - vals[k] < 120:      # 三个圆心在 120px 内排成一行/一列
                        has_row = True
                        break
                if has_row:
                    break
        if centers:
            n_with_circle += 1
        if has_row:
            n_with_row += 1
        rows.append({"image": p.name, "n_circles": len(centers), "has_row": has_row})
    return {"images_analyzed": len(rows),
            "images_with_circle": n_with_circle,
            "images_with_collinear_circles": n_with_row,
            "detail": rows}


def contact_sheet(paths, cols, tile, out, labels=True):
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = (len(paths) + cols - 1) // cols
    canvas = np.full((rows * tile, cols * tile, 3), 235, np.uint8)
    for i, p in enumerate(paths):
        im = cv2.imread(str(p), cv2.IMREAD_UNCHANGED)
        if im is None:
            continue
        if im.ndim == 3:
            im = im[:, :, :3]
        if im.dtype != np.uint8:
            im = cv2.normalize(im, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
        h, w = im.shape[:2]
        s = min(tile / h, tile / w)
        im = cv2.resize(im, (max(1, int(w * s)), max(1, int(h * s))))
        r, c = divmod(i, cols)
        y = r * tile + (tile - im.shape[0]) // 2
        x = c * tile + (tile - im.shape[1]) // 2
        canvas[y:y + im.shape[0], x:x + im.shape[1]] = im
        if labels:
            cv2.putText(canvas, p.stem[:18], (c * tile + 6, r * tile + 22),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 4, cv2.LINE_AA)
            cv2.putText(canvas, p.stem[:18], (c * tile + 6, r * tile + 22),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 1, cv2.LINE_AA)
    cv2.imwrite(str(out), canvas, [cv2.IMWRITE_JPEG_QUALITY, 88])
    return out


def main() -> int:
    random.seed(SEED)
    META.mkdir(parents=True, exist_ok=True)

    # ---------------- T-LESS ----------------
    tless_root = DL / "tless_test_primesense_01"
    rgb = sorted((tless_root / "01" / "rgb").glob("*.png"))
    depth = sorted((tless_root / "01" / "depth").glob("*.png"))
    masks = sorted((tless_root / "01" / "mask").glob("*.png")) if (tless_root / "01" / "mask").is_dir() else []
    print("T-LESS: rgb={} depth={} mask={}".format(len(rgb), len(depth), len(masks)))

    # 抽样：在整段序列上均匀取，覆盖不同帧（不同视角）
    idx = np.linspace(0, len(rgb) - 1, min(N_SAMPLE, len(rgb))).astype(int)
    sample = [rgb[i] for i in idx]

    ts = decode_stats(rgb)
    ts.update({"rgb_count": len(rgb), "depth_count": len(depth), "mask_count": len(masks),
               "sampled": len(sample),
               "has_segmentation_mask_in_original": bool(masks),
               "note_mask": ("原始 T-LESS v2 格式未提供 mask 目录" if not masks
                             else "存在 mask 目录")})

    # 解析 gt.yml / info.yml
    gt_info = {}
    try:
        import yaml
        gt = yaml.safe_load((tless_root / "01" / "gt.yml").read_text(encoding="utf-8"))
        info = yaml.safe_load((tless_root / "01" / "info.yml").read_text(encoding="utf-8"))
        obj_ids = Counter()
        bb_aspect = []
        for k, v in gt.items():
            for o in (v or []):
                obj_ids[o.get("obj_id")] += 1
                bb = o.get("obj_bb")
                if bb and bb[2] > 0 and bb[3] > 0:
                    bb_aspect.append(bb[2] / bb[3])
        cam_K = None
        if info:
            first = info[sorted(info.keys())[0]]
            cam_K = first.get("cam_K")
        gt_info = {"frames": len(gt), "object_ids": dict(sorted(obj_ids.items())),
                   "n_objects_present": len(obj_ids),
                   "bbox_aspect_min": round(float(np.min(bb_aspect)), 2) if bb_aspect else None,
                   "bbox_aspect_max": round(float(np.max(bb_aspect)), 2) if bb_aspect else None,
                   "cam_K": cam_K}
    except Exception as e:
        gt_info = {"error": "{}: {}".format(type(e).__name__, e)}

    ts["gt"] = gt_info
    ts["circle_analysis"] = circle_analysis(sample, max_n=40)

    TA.mkdir(parents=True, exist_ok=True)
    sheet = contact_sheet(sample[:60], 6, 260, TA / "previews" / "tless_rgb_contact_sheet.jpg")
    (META / "phase3_tless_stats.json").write_text(
        json.dumps(ts, ensure_ascii=False, indent=2), encoding="utf-8")
    print("T-LESS 统计:", json.dumps({k: v for k, v in ts.items() if k != "circle_analysis"},
                                    ensure_ascii=False)[:400])
    print("T-LESS 圆检测:", {k: v for k, v in ts["circle_analysis"].items() if k != "detail"})
    print("contact sheet:", sheet)

    # ---------------- Workpieces ----------------
    wp_root = DL / "workpieces_surfaces" / "surfaces"
    all_wp = sorted([p for p in wp_root.rglob("*") if p.suffix.lower() in (".tif", ".tiff", ".jpg", ".png")])
    defects = sorted([p for p in all_wp if "Defects" in p.parts])
    ok_imgs = sorted([p for p in all_wp if p.parts and "Ok" in p.parts])
    overview = sorted([p for p in all_wp if p.suffix.lower() == ".jpg"])
    print("Workpieces: total={} defects={} ok={} overview={}".format(
        len(all_wp), len(defects), len(ok_imgs), len(overview)))

    sample_wp = []
    for grp in (defects, ok_imgs):
        if grp:
            k = min(len(grp), N_SAMPLE // 2)
            sample_wp += [grp[i] for i in np.linspace(0, len(grp) - 1, k).astype(int)]
    ws = decode_stats(sample_wp)
    ws.update({"total_images": len(all_wp), "defects_images": len(defects),
               "ok_images": len(ok_imgs), "overview_jpg": len(overview),
               "sampled": len(sample_wp),
               "pieces": sorted({p.parts[p.parts.index("surfaces") + 1] for p in all_wp
                                 if "surfaces" in p.parts and len(p.parts) > p.parts.index("surfaces") + 1}),
               "filename_hints": {
                   "interior": sum(1 for p in all_wp if "interior" in p.name.lower()),
                   "exterior": sum(1 for p in all_wp if "exterior" in p.name.lower()),
                   "foto": sum(1 for p in all_wp if p.stem.lower().startswith("foto"))}})

    WA.mkdir(parents=True, exist_ok=True)
    sheet_wp = contact_sheet(sample_wp[:60], 6, 260, WA / "previews" / "workpieces_contact_sheet.jpg")
    (META / "phase3_workpieces_stats.json").write_text(
        json.dumps(ws, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Workpieces 统计:", json.dumps(ws, ensure_ascii=False)[:500])
    print("contact sheet:", sheet_wp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
