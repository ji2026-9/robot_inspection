# -*- coding: utf-8 -*-
"""
Compare three ellipse-fitting strategies on THIS project's own test images.

  A (current)  : cv2.fitEllipse(contour)                      <- what app/vision.py uses today
  B (friend)   : robust_bore_ellipse(contour)                 <- RANSAC + inlier refinement
  C (friend+)  : refine_multi_edge(image, B)                  <- + sub-pixel aperture edge search

Metrics per hole (all measured against the SAME resampled contour points):
  * median / p90 residual to the contour   (pixels, smaller = better)
  * support  = fraction of contour points within tolerance
  * stability = max centre drift (px) when the contour is randomly subsampled to 80%,
                which is what "the fit looks different every time" really measures

READ ONLY: never trains, never writes into the original dataset / images / weights.
Outputs go to results/ellipse_fit_comparison/ .

Usage:
    E:\\robot_inspection\\.venv\\Scripts\\python.exe scripts\\compare_ellipse_fit.py
    ... --conf 0.15 --imgsz 640
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

PROJ = Path(__file__).resolve().parents[1]
APP = PROJ / "app"
sys.path.insert(0, str(APP))

from imageio_util import imread_unicode, imwrite_unicode          # noqa: E402
from vision import HoleDetector                                    # noqa: E402
from robust_bore_ellipse import (ellipse_residual,                 # noqa: E402
                                 robust_bore_ellipse, sample_boundary)
from edge_bore_refinement import refine_multi_edge                 # noqa: E402

OUT_DIR = PROJ / "results" / "ellipse_fit_comparison"
IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp"}

COLOR_A = (60, 200, 60)      # green  - current
COLOR_B = (230, 190, 40)     # cyan   - robust
COLOR_C = (40, 120, 245)     # orange - robust + edge refinement


# ---------------------------------------------------------------- helpers
def fit_current(points):
    return cv2.fitEllipse(np.asarray(points, dtype=np.float32).reshape(-1, 1, 2))


def fit_robust(points):
    ellipse, _samples, _inliers, _med, _support = robust_bore_ellipse(points)
    return ellipse


def tolerance_for(points):
    low, high = points.min(axis=0), points.max(axis=0)
    return max(2.0, 0.02 * float(np.min(high - low)))


def residual_metrics(ellipse, points, tol):
    dist, _ang = ellipse_residual(points, ellipse)
    return {"median_px": float(np.median(dist)),
            "p90_px": float(np.percentile(dist, 90)),
            "max_px": float(dist.max()),
            "support": float(np.mean(dist <= tol))}


def axes(ellipse):
    (_cx, _cy), (a, b), ang = ellipse
    return float(max(a, b)), float(min(a, b)), float(ang) % 180.0


def stability(fitter, points, trials=5, keep=0.80, seed=7):
    """Max centre drift (px) when the contour is subsampled. Smaller = more stable.

    The subset must stay a *contiguous arc* of the contour: some fits (RANSAC on
    resampled boundary points) depend on point order, so a shuffled subset would
    measure nothing but our own scrambling.
    """
    try:
        base = fitter(points)[0]
    except Exception:
        return None
    rng = np.random.default_rng(seed)
    n = len(points)
    k = max(6, int(round(keep * n)))
    worst = 0.0
    for _ in range(trials):
        start = int(rng.integers(0, n))
        idx = (np.arange(k) + start) % n
        try:
            c = fitter(points[idx])[0]
        except Exception:
            return None
        worst = max(worst, float(np.hypot(c[0] - base[0], c[1] - base[1])))
    return worst


def edge_align_score(image, ellipse, n=360):
    """Median / 25th-percentile gradient magnitude along the fitted ellipse.

    This is the only metric here that is about the PHYSICAL aperture edge rather
    than about the mask boundary: the true hole rim is a strong intensity edge,
    so a good ellipse should sit on high-gradient pixels all the way round.
    """
    gray = cv2.GaussianBlur(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY),
                            (0, 0), 2).astype(np.float32)
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3) / 8
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3) / 8
    (cx, cy), (a, b), ang = ellipse
    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    c, s = np.cos(np.deg2rad(ang)), np.sin(np.deg2rad(ang))
    u, v = a / 2 * np.cos(t), b / 2 * np.sin(t)
    x = (cx + c * u - s * v).astype(np.float32)
    y = (cy + s * u + c * v).astype(np.float32)
    mag = np.hypot(cv2.remap(gx, x, y, cv2.INTER_LINEAR),
                   cv2.remap(gy, x, y, cv2.INTER_LINEAR))
    return {"edge_median": float(np.median(mag)),
            "edge_p25": float(np.percentile(mag, 25))}


def draw(vis, ellipse, color, thickness=4):
    cv2.ellipse(vis, ellipse, color, thickness)
    c = (int(round(ellipse[0][0])), int(round(ellipse[0][1])))
    cv2.circle(vis, c, 6, color, -1)


# ------------------------------------------------------------------ main
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", default=str(PROJ / "test_images"))
    ap.add_argument("--conf", type=float, default=0.15,
                    help="低阈值以便把反光孔也纳入拟合对比（默认 0.15）")
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--model", default=str(PROJ / "weights" / "best.pt"))
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    src = Path(args.images)
    imgs = sorted([p for p in src.iterdir() if p.suffix.lower() in IMG_EXTS]) \
        if src.is_dir() else [src]
    if not imgs:
        print("no images in", src)
        return 2

    print("model :", args.model)
    print("images:", len(imgs), " conf:", args.conf, " imgsz:", args.imgsz)
    detector = HoleDetector(args.model)
    if not detector.load():
        print("model load failed:", detector.load_error)
        return 2

    rows = []
    t0 = time.time()
    for image_path in imgs:
        res = detector.detect(str(image_path), conf=args.conf, imgsz=args.imgsz)
        if res["errors"]:
            print("  [warn]", image_path.name, res["errors"])
        img = imread_unicode(image_path)
        vis = img.copy()
        print("  {} -> {} holes".format(image_path.name, len(res["holes"])))

        for hole in res["holes"]:
            cnt = hole.get("_contour")
            if cnt is None or len(cnt) < 5:
                continue
            pts = sample_boundary(cnt, 360)
            tol = tolerance_for(pts)
            row = {"image": image_path.name, "hole": hole["id"],
                   "confidence": round(float(hole["confidence"]), 4),
                   "contour_points": int(len(cnt))}

            # ---- A: current -------------------------------------------------
            ell_a = None
            try:
                t_a = time.time()
                ell_a = fit_current(cnt)
                fit_ms_a = (time.time() - t_a) * 1000
                row["A_current"] = residual_metrics(ell_a, pts, tol)
                row["A_current"]["stability_px"] = stability(fit_current, pts)
                row["A_current"]["fit_ms"] = round(fit_ms_a, 1)
                row["A_current"].update(edge_align_score(img, ell_a))
                row["center_A"] = [round(float(ell_a[0][0]), 2), round(float(ell_a[0][1]), 2)]
            except Exception as exc:
                row["A_current"] = {"failed": "{}: {}".format(type(exc).__name__, exc)}

            # ---- B: friend robust -------------------------------------------
            ell_b = None
            try:
                t_b = time.time()
                ell_b = fit_robust(cnt)
                fit_ms_b = (time.time() - t_b) * 1000
                row["B_robust"] = residual_metrics(ell_b, pts, tol)
                row["B_robust"]["stability_px"] = stability(fit_robust, pts)
                row["B_robust"]["fit_ms"] = round(fit_ms_b, 1)
                row["B_robust"].update(edge_align_score(img, ell_b))
                row["center_B"] = [round(float(ell_b[0][0]), 2), round(float(ell_b[0][1]), 2)]
                if ell_a is not None:
                    row["B_robust"]["center_shift_vs_A_px"] = round(
                        float(np.hypot(ell_b[0][0] - ell_a[0][0],
                                       ell_b[0][1] - ell_a[0][1])), 3)
                    ma1, mi1, an1 = axes(ell_a)
                    ma2, mi2, an2 = axes(ell_b)
                    row["B_robust"]["major_delta_pct"] = round(100 * (ma2 - ma1) / ma1, 2)
                    row["B_robust"]["minor_delta_pct"] = round(100 * (mi2 - mi1) / mi1, 2)
                    row["B_robust"]["angle_delta_deg"] = round(abs(an2 - an1), 2)
            except Exception as exc:
                row["B_robust"] = {"failed": "{}: {}".format(type(exc).__name__, exc)}

            # ---- C: robust + sub-pixel edge refinement ----------------------
            if ell_b is not None:
                try:
                    t_c = time.time()
                    ell_c, info = refine_multi_edge(img, ell_b)
                    fit_ms_c = (time.time() - t_c) * 1000
                    row["C_edge"] = residual_metrics(ell_c, pts, tol)
                    row["C_edge"].update(edge_align_score(img, ell_c))
                    row["center_C"] = [round(float(ell_c[0][0]), 2), round(float(ell_c[0][1]), 2)]
                    row["C_edge"]["used"] = bool(info.get("used"))
                    row["C_edge"]["reason"] = info.get("reason")
                    row["C_edge"]["fit_ms"] = round(fit_ms_c, 1)
                    row["C_edge"]["center_spread_px"] = info.get("center_spread_px")
                    row["C_edge"]["axis_spread_px"] = info.get("axis_spread_px")
                    row["C_edge"]["center_shift_vs_B_px"] = round(
                        float(np.hypot(ell_c[0][0] - ell_b[0][0],
                                       ell_c[0][1] - ell_b[0][1])), 3)
                    draw(vis, ell_c, COLOR_C, 3)
                except Exception as exc:
                    row["C_edge"] = {"failed": "{}: {}".format(type(exc).__name__, exc)}

            if ell_a is not None:
                draw(vis, ell_a, COLOR_A, 5)
            if ell_b is not None:
                draw(vis, ell_b, COLOR_B, 3)
            rows.append(row)

        out_img = OUT_DIR / "{}_overlay.jpg".format(image_path.stem)
        imwrite_unicode(out_img, vis)

    # ------------------------------------------------------------ summary
    def agg(key, field):
        vals = [r[key][field] for r in rows
                if key in r and isinstance(r[key], dict)
                and isinstance(r[key].get(field), (int, float))]
        if not vals:
            return None, None, 0
        return float(np.median(vals)), float(np.mean(vals)), len(vals)

    def failed(key):
        return sum(1 for r in rows if key in r and "failed" in r[key])

    summary = {}
    for key in ("A_current", "B_robust", "C_edge"):
        med, mean, ok = agg(key, "median_px")
        _s1, sup_mean, _s2 = agg(key, "support")
        stab_med, _s3, _s4 = agg(key, "stability_px")
        _e1, edge_mean, _e2 = agg(key, "edge_median")
        _f1, edge_p25_mean, _f2 = agg(key, "edge_p25")
        spread_med, _g2, _g3 = agg(key, "center_spread_px")
        ms_med, _h2, _h3 = agg(key, "fit_ms")
        summary[key] = {"ok": ok, "failed": failed(key),
                        "median_residual_px": med if ok else None,
                        "mean_residual_px": mean if ok else None,
                        "mean_support": sup_mean if ok else None,
                        "median_stability_px": stab_med if ok else None,
                        "mean_edge_score": edge_mean if ok else None,
                        "mean_edge_p25": edge_p25_mean if ok else None,
                        "median_center_spread_px": spread_med,
                        "median_fit_ms": ms_med}

    payload = {"generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
               "model": str(args.model), "conf": args.conf, "imgsz": args.imgsz,
               "images": [p.name for p in imgs], "holes": len(rows),
               "elapsed_s": round(time.time() - t0, 1),
               "summary": summary, "per_hole": rows}
    (OUT_DIR / "comparison.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    labels = {"A_current": "A cv2.fitEllipse", "B_robust": "B robust(RANSAC)",
              "C_edge": "C robust+edge"}

    # ---------------------------------------------------------------- print
    print()
    print("{:<20}{:>5}{:>6}{:>13}{:>10}{:>10}{:>12}{:>11}".format(
        "method", "ok", "fail", "med_res(px)", "mean_sup", "stab(px)",
        "edge_p50", "edge_p25"))
    for key in ("A_current", "B_robust", "C_edge"):
        s = summary[key]
        print("{:<20}{:>5}{:>6}{:>13}{:>10}{:>10}{:>12}{:>11}".format(
            labels[key], s["ok"], s["failed"],
            "-" if s["median_residual_px"] is None else "{:.2f}".format(s["median_residual_px"]),
            "-" if s["mean_support"] is None else "{:.3f}".format(s["mean_support"]),
            "-" if s["median_stability_px"] is None else "{:.2f}".format(s["median_stability_px"]),
            "-" if s["mean_edge_score"] is None else "{:.2f}".format(s["mean_edge_score"]),
            "-" if s["mean_edge_p25"] is None else "{:.2f}".format(s["mean_edge_p25"])))

    md = OUT_DIR / "summary.md"
    with md.open("w", encoding="utf-8") as f:
        f.write("# 椭圆拟合方式对比\n\n")
        f.write("生成时间：{}\n\n".format(payload["generated"]))
        f.write("模型：`{}`　conf={}　imgsz={}　参与对比的孔数：{}\n\n".format(
            args.model, args.conf, args.imgsz, len(rows)))
        f.write("| 方法 | 成功 | 失败 | 中位残差(px) | 平均支持率 | 中位稳定性(px) | 边缘梯度中位 | 边缘梯度25% |\n")
        f.write("|---|---:|---:|---:|---:|---:|---:|---:|\n")
        for key in ("A_current", "B_robust", "C_edge"):
            s = summary[key]
            f.write("| {} | {} | {} | {} | {} | {} | {} | {} |\n".format(
                labels[key], s["ok"], s["failed"],
                "-" if s["median_residual_px"] is None else "{:.2f}".format(s["median_residual_px"]),
                "-" if s["mean_support"] is None else "{:.3f}".format(s["mean_support"]),
                "-" if s["median_stability_px"] is None else "{:.2f}".format(s["median_stability_px"]),
                "-" if s["mean_edge_score"] is None else "{:.2f}".format(s["mean_edge_score"]),
                "-" if s["mean_edge_p25"] is None else "{:.2f}".format(s["mean_edge_p25"])))
        f.write("\n说明：\n\n")
        f.write("- `中位残差 / 支持率` 是椭圆到 **mask 轮廓** 的距离 —— 对 A、B 有意义；\n")
        f.write("  对 C 无意义，因为 C 的设计目标就是离开 mask 边界、贴到真实强度边缘上。\n")
        f.write("- `边缘梯度中位 / 25%` 是椭圆落在**图像梯度**上的强度 —— 这是唯一与\n")
        f.write("  “物理孔口边缘”有关的指标，越高说明椭圆的整圈都压在真实边缘上。\n")
        f.write("- `稳定性` = 把轮廓随机截取 80% 连续弧段重拟合后，圆心的最大漂移（px）。\n\n")
        f.write("逐孔明细见 `comparison.json`；叠加图见 `*_overlay.jpg`"
                "（绿=现有 A，青=稳健 B，橙=稳健+边缘精修 C）。\n")

    print()
    print("json   :", OUT_DIR / "comparison.json")
    print("summary:", md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
