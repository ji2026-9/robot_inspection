# -*- coding: utf-8 -*-
"""
180° 旋转稳定性测试（客观验证，无任何针对测试图的硬编码）
========================================================
方法：
  对每张测试图，
    1) 用 stable_hole_id 的编号规则在原图上编号 → 记录每个孔的 id 与中心
    2) 把图像旋转 180°，再编号 → 把中心坐标映射回原图坐标系
    3) 用最近邻把两轮的孔配对，检查**同一物理孔在两轮中是否得到相同 id**
  若同一物理孔在两轮中 id 不同（通常表现为 H01<->H04 整体对调），
  说明当前编号规则不满足"180° 旋转不变性"。

输出：results\\rotation_stability.json

用法：
    python experiments\\stable_hole_id\\scripts\\rotation_stability_test.py
"""

import json
import sys
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

PROJ = Path(r"E:\robot_inspection")
ROOT = PROJ / "experiments" / "stable_hole_id"
sys.path.insert(0, str(ROOT))

from stable_hole_id import process  # noqa: E402

RESULTS = ROOT / "results"


def main() -> int:
    RESULTS.mkdir(parents=True, exist_ok=True)
    from ultralytics import YOLO
    model = YOLO(str(PROJ / "weights" / "best.pt"))

    out = []
    for p in sorted((PROJ / "test_images").glob("*.jpg")):
        img = cv2.imread(str(p))
        h, w = img.shape[:2]

        r1 = process(model, p, reference_axis=None, write_vis=False)
        rot = cv2.rotate(img, cv2.ROTATE_180)
        tmp = RESULTS / "_rot_tmp.jpg"
        cv2.imwrite(str(tmp), rot)
        r2 = process(model, tmp, reference_axis=None, write_vis=False)
        tmp.unlink(missing_ok=True)

        # 把旋转图的中心映射回原图坐标
        def mapped(holes):
            ms = []
            for hh in holes:
                x, y = hh["center_x"], hh["center_y"]
                ms.append({"id": hh["id"], "orig_xy": (w - 1 - x, h - 1 - y)})
            return ms

        a = [{"id": hh["id"], "xy": (hh["center_x"], hh["center_y"])} for hh in r1["holes"]]
        b = mapped(r2["holes"])

        pairs, used = [], set()
        for ha in a:
            best, bd = None, 1e18
            for j, hb in enumerate(b):
                if j in used:
                    continue
                d = float(np.hypot(ha["xy"][0] - hb["orig_xy"][0],
                                   ha["xy"][1] - hb["orig_xy"][1]))
                if d < bd:
                    best, bd = j, d
            if best is not None and bd < 300:
                used.add(best)
                pairs.append({"id_original": ha["id"], "id_after_180": b[best]["id"],
                              "match_dist_px": round(bd, 1)})

        same = sum(1 for x in pairs if x["id_original"] == x["id_after_180"])
        swapped = [x for x in pairs if x["id_original"] != x["id_after_180"]]
        rec = {"image": p.name,
               "detections_original": r1["detections"], "detections_rotated": r2["detections"],
               "pairs": pairs, "n_matched": len(pairs), "n_same_id": same,
               "n_swapped": len(swapped),
               "rotation_invariant": bool(len(pairs) >= 3 and same == len(pairs))}
        out.append(rec)
        print("{:<12} 原图 {} 孔 / 旋转后 {} 孔 | 配对 {} | id 一致 {} | 对调 {}".format(
            p.name, r1["detections"], r2["detections"], len(pairs), same, len(swapped)))
        for x in pairs:
            flag = "OK " if x["id_original"] == x["id_after_180"] else "对调"
            print("      {} -> {}   {}".format(x["id_original"], x["id_after_180"], flag))

    (RESULTS / "rotation_stability.json").write_text(
        json.dumps({"generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "method": "原图编号 vs 180°旋转后编号（中心映射回原图，最近邻配对）",
                    "results": out}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n已保存:", RESULTS / "rotation_stability.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
