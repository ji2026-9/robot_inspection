# -*- coding: utf-8 -*-
"""
Same holes, two fitting POLICIES - which one lands on the real aperture rim?

  policy_his  : robust fit; refine with image edges ONLY if the mask support < 0.85
                (this is exactly what the friend's detect_core.py does)
  policy_ours : robust fit; ALWAYS try the image-edge refinement, keep it only if
                the refinement's own stability/coverage gates pass
                (this is what app/vision.py now does, ELLIPSE_FIT_MODE="robust_edge")

Metric: median / 25th-percentile gradient magnitude along the ellipse. The physical
hole rim IS a strong intensity edge, so a better ellipse sits on a higher, more
continuous gradient band. Also reports how far the two policies disagree.

READ ONLY. Outputs to results/fit_policy_comparison/ .
"""

import json
import sys
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

PROJ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJ / "app"))

from imageio_util import imread_unicode                      # noqa: E402
from vision import HoleDetector                              # noqa: E402
from robust_bore_ellipse import robust_bore_ellipse          # noqa: E402
from edge_bore_refinement import refine_multi_edge           # noqa: E402

OUT = PROJ / "results" / "fit_policy_comparison"


def edge_score(image, ellipse, n=360):
    gray = cv2.GaussianBlur(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), (0, 0), 2).astype(np.float32)
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3) / 8
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3) / 8
    (cx, cy), (a, b), ang = ellipse
    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    c, s = np.cos(np.deg2rad(ang)), np.sin(np.deg2rad(ang))
    u, v = a / 2 * np.cos(t), b / 2 * np.sin(t)
    x = (cx + c * u - s * v).astype(np.float32)
    y = (cy + s * u + c * v).astype(np.float32)
    mag = np.hypot(cv2.remap(gx, x, y, cv2.INTER_LINEAR), cv2.remap(gy, x, y, cv2.INTER_LINEAR))
    return float(np.median(mag)), float(np.percentile(mag, 25))


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    det = HoleDetector()
    if not det.load():
        print("model load failed:", det.load_error)
        return 2

    rows = []
    for img_path in sorted((PROJ / "test_images").glob("*.jpg")):
        res = det.detect(str(img_path), conf=0.15)
        img = imread_unicode(img_path)
        for h in res["holes"]:
            cnt = h["_contour"]
            ell_r, _s, _i, _med, support = robust_bore_ellipse(cnt)

            ell_his, info_his = (ell_r, {"used": False, "reason": "support>=0.85"})
            if support < 0.85:
                ell_his, info_his = refine_multi_edge(img, ell_r)
                if not info_his.get("used"):
                    ell_his = ell_r

            ell_ours, info_ours = refine_multi_edge(img, ell_r)
            if not info_ours.get("used"):
                ell_ours = ell_r

            e_his = edge_score(img, ell_his)
            e_our = edge_score(img, ell_ours)
            dist = float(np.hypot(ell_his[0][0] - ell_ours[0][0],
                                  ell_his[0][1] - ell_ours[0][1]))
            rows.append({
                "image": img_path.name, "hole": h["id"], "confidence": round(h["confidence"], 4),
                "mask_support": round(float(support), 3),
                "his_used_edge": bool(info_his.get("used")),
                "ours_used_edge": bool(info_ours.get("used")),
                "edge_p50_his": round(e_his[0], 2), "edge_p25_his": round(e_his[1], 2),
                "edge_p50_ours": round(e_our[0], 2), "edge_p25_ours": round(e_our[1], 2),
                "center_gap_px": round(dist, 2),
            })

    def avg(key):
        return float(np.mean([r[key] for r in rows]))

    his_better = sum(1 for r in rows if r["edge_p25_his"] > r["edge_p25_ours"] + 0.5)
    ours_better = sum(1 for r in rows if r["edge_p25_ours"] > r["edge_p25_his"] + 0.5)

    summary = {
        "holes": len(rows),
        "edge_p50_mean_his": round(avg("edge_p50_his"), 2),
        "edge_p50_mean_ours": round(avg("edge_p50_ours"), 2),
        "edge_p25_mean_his": round(avg("edge_p25_his"), 2),
        "edge_p25_mean_ours": round(avg("edge_p25_ours"), 2),
        "mean_center_gap_px": round(avg("center_gap_px"), 2),
        "max_center_gap_px": round(max(r["center_gap_px"] for r in rows), 2),
        "holes_his_better": his_better, "holes_ours_better": ours_better,
        "his_edge_used": sum(1 for r in rows if r["his_used_edge"]),
        "ours_edge_used": sum(1 for r in rows if r["ours_used_edge"]),
    }
    (OUT / "comparison.json").write_text(json.dumps(
        {"generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
         "summary": summary, "per_hole": rows}, ensure_ascii=False, indent=2), encoding="utf-8")

    print("{:<12}{:<5}{:>10}{:>12}{:>12}{:>10}{:>10}{:>9}".format(
        "image", "hole", "support", "edge25_his", "edge25_our", "gap_px", "his_edge", "our_edge"))
    for r in rows:
        print("{:<12}{:<5}{:>10.3f}{:>12.2f}{:>12.2f}{:>10.2f}{:>10}{:>9}".format(
            r["image"], r["hole"], r["mask_support"], r["edge_p25_his"], r["edge_p25_ours"],
            r["center_gap_px"], r["his_used_edge"], r["ours_used_edge"]))
    print()
    for k, v in summary.items():
        print("  {:<20} {}".format(k, v))
    print("\nsaved:", OUT / "comparison.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
