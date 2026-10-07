# -*- coding: utf-8 -*-
"""
Diagnostic: how good is the ellipse fit on the real masks?
=========================================================
For every detected hole it saves a zoomed crop with
  * mask outline (white)
  * cv2.fitEllipse result (green)
  * convex-hull based fit (orange)
and computes objective metrics:
  * area ratio = contour_area / ellipse_area   (1.0 = perfect)
  * RMS / p95 distance from contour points to the fitted ellipse, as a % of
    the ellipse minor radius (smaller = better)

Read-only: it only loads the model and the test images.
"""

import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import MODEL_PATH, TEST_IMAGE_DIR  # noqa: E402
from vision import HoleDetector, ellipse_from_mask, imread_unicode  # noqa: E402

OUT = Path(__file__).resolve().parent / "diag"


def ellipse_points(ell, n=180):
    (cx, cy), (MA, ma), ang = ell
    t = np.linspace(0, 2 * np.pi, n)
    a, b = MA / 2.0, ma / 2.0
    th = np.deg2rad(ang)
    x = a * np.cos(t)
    y = b * np.sin(t)
    xr = cx + x * np.cos(th) - y * np.sin(th)
    yr = cy + x * np.sin(th) + y * np.cos(th)
    return np.stack([xr, yr], axis=1)


def fit_metrics(contour, ell):
    """Area ratio + radial deviation (% of ellipse minor radius)."""
    ca = cv2.contourArea(contour)
    (_, _), (MA, ma), _ = ell
    ea = np.pi * (MA / 2.0) * (ma / 2.0)
    pts = contour.reshape(-1, 2).astype(np.float64)
    poly = ellipse_points(ell, 720)
    d = np.array([np.min(np.linalg.norm(poly - p, axis=1)) for p in pts])
    r_min = max(1.0, min(MA, ma) / 2.0)
    return {"area_ratio": round(float(ca / max(ea, 1e-6)), 4),
            "rms_pct": round(float(np.sqrt((d ** 2).mean()) / r_min * 100), 2),
            "p95_pct": round(float(np.percentile(d, 95) / r_min * 100), 2)}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    det = HoleDetector(MODEL_PATH)
    report = []
    for img_path in sorted(Path(TEST_IMAGE_DIR).glob("*.jpg")):
        img = imread_unicode(img_path)
        if img is None:
            continue
        res = det.detect(img_path)
        tiles = []
        for h in res["holes"]:
            # re-extract contour/mask from the stored internals
            mask = h["_mask"]
            ell, cnt = ellipse_from_mask(mask)
            hull = cv2.convexHull(cnt)
            ell_hull = cv2.fitEllipse(hull) if len(hull) >= 5 else ell
            m_orig = fit_metrics(cnt, ell)
            m_hull = fit_metrics(cnt, ell_hull)
            m_saved = fit_metrics(cnt, ((h["ellipse"]["center"]),
                                        (h["ellipse"]["width"], h["ellipse"]["height"]),
                                        h["ellipse"]["angle"]))
            report.append({"image": img_path.name, "hole": h["id"],
                           "contour_pts": int(len(cnt)),
                           "fitEllipse": m_orig, "fitEllipse_on_hull": m_hull,
                           "saved": m_saved,
                           "angle_deg": h["ellipse"]["angle"],
                           "w": h["ellipse"]["width"], "h": h["ellipse"]["height"]})

            # zoomed crop tile
            cx, cy = h["ellipse"]["center"]
            R = int(max(h["ellipse"]["width"], h["ellipse"]["height"]) * 0.85) + 40
            x0, y0 = max(0, int(cx - R)), max(0, int(cy - R))
            x1, y1 = min(img.shape[1], int(cx + R)), min(img.shape[0], int(cy + R))
            crop = img[y0:y1, x0:x1].copy()
            if crop.size == 0:
                continue
            c_local = cnt - np.array([x0, y0])
            cv2.drawContours(crop, [c_local], -1, (255, 255, 255), 3)
            cv2.polylines(crop, [np.round(ellipse_points(ell) - [x0, y0]).astype(np.int32)],
                          True, (0, 255, 0), 4)
            cv2.polylines(crop, [np.round(ellipse_points(ell_hull) - [x0, y0]).astype(np.int32)],
                          True, (0, 165, 255), 3)
            crop = cv2.resize(crop, (420, 420))
            cv2.putText(crop, "{} {}".format(h["id"], img_path.stem), (10, 34),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 6, cv2.LINE_AA)
            cv2.putText(crop, "{} {}".format(h["id"], img_path.stem), (10, 34),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 255), 2, cv2.LINE_AA)
            cv2.putText(crop, "green=fitEllipse rms {:.1f}%".format(m_orig["rms_pct"]),
                        (10, 390), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (0, 0, 0), 4, cv2.LINE_AA)
            cv2.putText(crop, "green=fitEllipse rms {:.1f}%".format(m_orig["rms_pct"]),
                        (10, 390), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (0, 255, 0), 1, cv2.LINE_AA)
            cv2.putText(crop, "orange=hull-fit rms {:.1f}%".format(m_hull["rms_pct"]),
                        (10, 412), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (0, 0, 0), 4, cv2.LINE_AA)
            cv2.putText(crop, "orange=hull-fit rms {:.1f}%".format(m_hull["rms_pct"]),
                        (10, 412), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (0, 165, 255), 1, cv2.LINE_AA)
            tiles.append(crop)
        if tiles:
            cols = min(4, len(tiles))
            rows = (len(tiles) + cols - 1) // cols
            sheet = np.full((rows * 430, cols * 430, 3), 245, np.uint8)
            for i, t in enumerate(tiles):
                r, c = divmod(i, cols)
                sheet[r * 430:r * 430 + t.shape[0], c * 430:c * 430 + t.shape[1]] = t
            cv2.imwrite(str(OUT / "fit_{}.jpg".format(img_path.stem)), sheet,
                        [cv2.IMWRITE_JPEG_QUALITY, 92])
        print("{}: {} holes".format(img_path.name, len(res["holes"])))

    (OUT / "fit_metrics.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
    print("\n--- metrics (rms% = 轮廓点到椭圆的 RMS 偏差，占短半轴百分比) ---")
    print("{:<12}{:<6}{:>12}{:>12}{:>12}{:>12}".format(
        "image", "hole", "fitEllipse", "hull-fit", "area_ratio", "saved_rms"))
    for r in report:
        print("{:<12}{:<6}{:>11.1f}%{:>11.1f}%{:>12.3f}{:>11.1f}%".format(
            r["image"].replace(".jpg", ""), r["hole"], r["fitEllipse"]["rms_pct"],
            r["fitEllipse_on_hull"]["rms_pct"], r["fitEllipse"]["area_ratio"],
            r["saved"]["rms_pct"]))
    print("\n已保存:", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
