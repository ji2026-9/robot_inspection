# -*- coding: utf-8 -*-
"""
Phase 4A：T-LESS 三场景完整审计 + 无标签预训练候选子集
=====================================================
输入（已校验，不重新下载）：
  external_datasets\\phase3_downloads\\tless_test_primesense_{01,02,03}\\<scene>\\rgb\\*.png
  external_datasets\\phase3_downloads\\tless_test_primesense_{01,02,03}\\<scene>\\gt.yml

做四件事：
  1) 完整审计：数量 / 可读性 / 分辨率 / 文件大小 / 精确重复 / 感知重复 / 连续帧重复 / 质量
  2) object ID 分布 + priority objects
  3) 生成两个**只含清单、不复制数据**的候选子集：
       TLESS-ALL   （三场景均匀覆盖，去重）
       TLESS-HOLE  （优先含多孔/成排孔/内壁物体的帧，去重）
  4) 全部视为 UNLABELED RGB —— 不生成任何 hole 标签

输出目录：
  external_datasets\\phase4_tless_audit\\
  external_datasets\\phase4_tless_pretrain\\

用法：
    python scripts\\audit_phase4_tless.py
"""

import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import yaml

EXT = Path(r"E:\robot_project\robot_inspection\external_datasets")
DL = EXT / "phase3_downloads"
AU = EXT / "phase4_tless_audit"
PR = EXT / "phase4_tless_pretrain"
SCENES = ["01", "02", "03"]

# Phase 3 人工确认过的优先物体（附理由）
PRIORITY = {
    7:  (1, "场景02 真实图人工确认：三个孔排成一排"),
    8:  (1, "场景03 真实图人工确认：多孔成组（四孔块）"),
    6:  (1, "场景02 真实图人工确认：两个并排孔"),
    18: (1, "场景03 真实图人工确认：带金属螺纹的中央孔与内壁"),
    5:  (2, "灯座类，标准视图显示明显圆孔（Phase2 物体图）"),
    11: (2, "灯座类，标准视图显示圆孔与内壁"),
    12: (2, "灯座类，标准视图显示圆孔与内壁"),
    13: (2, "圆筒带金属螺纹内壁（Phase2 物体图）"),
    14: (2, "圆筒带金属螺纹内壁"),
    15: (2, "圆筒带金属螺纹内壁"),
    16: (2, "圆筒带螺纹内壁"),
    17: (2, "法兰圆座带中央孔"),
    23: (2, "双联插座，含圆形开口"),
    24: (2, "圆柱件带螺纹"),
    2:  (3, "灯座，含圆孔（但场景01 视角未露出孔）"),
    3:  (3, "灯座，含圆孔"),
    4:  (3, "顶面大圆开口"),
    9:  (3, "三孔排（标准视图）"),
    10: (3, "方形件带圆孔"),
    19: (3, "端子排，正面多个圆凹"),
    20: (3, "端子排，正面多个圆凹"),
    25: (3, "接线盒（方形外壳，无可见孔）"),
    26: (3, "接线盒（方形外壳）"),
    27: (3, "方形盒体"),
    28: (3, "盒体带两个圆孔"),
    29: (3, "方形外壳"),
    30: (3, "圆筒外壳带侧开口"),
}


def dhash(img, size=8):
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    g = cv2.resize(g, (size + 1, size), interpolation=cv2.INTER_AREA)
    diff = g[:, 1:] > g[:, :-1]
    bits = 0
    for i, v in enumerate(diff.flatten()):
        if v:
            bits |= (1 << i)
    return bits


def hamming(a, b):
    return bin(a ^ b).count("1")


def bore_cue(img, bbox):
    """次要信号：在物体 bbox 内找“被包围的暗区”（可能是孔）。不作为硬筛选。"""
    x, y, w, h = [int(v) for v in bbox]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(img.shape[1], x + w), min(img.shape[0], y + h)
    if x1 - x0 < 20 or y1 - y0 < 20:
        return 0
    roi = img[y0:y1, x0:x1]
    g = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    obj = (g > 45).astype(np.uint8) * 255
    obj = cv2.morphologyEx(obj, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    med = float(np.median(g[obj > 0])) if (obj > 0).any() else 128.0
    dark = ((g < med - 30).astype(np.uint8)) * 255
    dark = cv2.bitwise_and(dark, cv2.erode(obj, np.ones((7, 7), np.uint8)))
    cnts, _ = cv2.findContours(dark, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    n = 0
    area = float((obj > 0).sum())
    for c in cnts:
        a = cv2.contourArea(c)
        if area > 0 and 0.002 * area < a < 0.4 * area:
            n += 1
    return n


def main() -> int:
    AU.mkdir(parents=True, exist_ok=True)
    PR.mkdir(parents=True, exist_ok=True)

    per_image = []          # 每条记录
    obj_scene_count = defaultdict(set)
    obj_img_count = Counter()

    for s in SCENES:
        root = DL / ("tless_test_primesense_%s" % s) / s
        rgb = sorted((root / "rgb").glob("*.png"))
        gt = {}
        if (root / "gt.yml").is_file():
            gt = yaml.safe_load((root / "gt.yml").read_text(encoding="utf-8")) or {}
        print("scene %s: rgb=%d, gt frames=%d" % (s, len(rgb), len(gt)))
        for p in rgb:
            idx = int(p.stem)
            objs = gt.get(idx) or gt.get(str(idx)) or []
            ids = sorted({int(o["obj_id"]) for o in objs})
            bbs = [o.get("obj_bb") for o in objs if o.get("obj_bb")]
            for i in ids:
                obj_scene_count[i].add(s)
                obj_img_count[i] += 1
            im = cv2.imread(str(p))
            ok = im is not None
            rec = {"path": str(p), "scene": s, "frame": idx, "object_ids": ids,
                   "readable": ok, "size_bytes": p.stat().st_size}
            if ok:
                h, w = im.shape[:2]
                g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
                lap = float(cv2.Laplacian(g, cv2.CV_64F).var())
                bore = sum(bore_cue(im, bb) for bb in bbs) if bbs else 0
                rec.update({"width": w, "height": h, "resolution": "{}x{}".format(w, h),
                            "brightness": round(float(g.mean()), 1),
                            "contrast": round(float(g.std()), 1),
                            "blur_lapvar": round(lap, 1),
                            "specular": round(float((g > 240).mean()), 4),
                            "bore_cue": bore,
                            "dhash": dhash(im),
                            "sha1": hashlib.sha1(p.read_bytes()).hexdigest()})
            per_image.append(rec)

    n = len(per_image)
    readable = [r for r in per_image if r["readable"]]
    unreadable = [r for r in per_image if not r["readable"]]

    # ---- 精确重复 ----
    by_sha = defaultdict(list)
    for r in readable:
        by_sha[r["sha1"]].append(r["path"])
    exact_dups = {k: v for k, v in by_sha.items() if len(v) > 1}

    # ---- 感知重复（dHash 汉明距离 <=5，union-find）----
    parent = list(range(len(readable)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    def cluster(thr):
        par = list(range(len(readable)))

        def f(a):
            while par[a] != a:
                par[a] = par[par[a]]
                a = par[a]
            return a

        for i in range(len(readable)):
            hi = readable[i]["dhash"]
            for j in range(i + 1, len(readable)):
                if hamming(hi, readable[j]["dhash"]) <= thr:
                    ra, rb = f(i), f(j)
                    if ra != rb:
                        par[rb] = ra
        g = defaultdict(list)
        for i, r in enumerate(readable):
            g[f(i)].append(r["path"])
        return [v for v in g.values() if len(v) > 1]

    perc_groups = cluster(5)        # 高相似（统计口径）
    near_ident = cluster(2)         # 近同（去重口径）

    # ---- 连续帧重复 ----
    runs = []
    for s in SCENES:
        arr = sorted([r for r in readable if r["scene"] == s], key=lambda x: x["frame"])
        cur = 1
        for i in range(1, len(arr)):
            if hamming(arr[i]["dhash"], arr[i - 1]["dhash"]) <= 2 and arr[i]["frame"] == arr[i - 1]["frame"] + 1:
                cur += 1
            else:
                if cur >= 5:
                    runs.append({"scene": s, "start_frame": arr[i - cur]["frame"],
                                 "length": cur})
                cur = 1
        if cur >= 5:
            runs.append({"scene": s, "start_frame": arr[len(arr) - cur]["frame"], "length": cur})

    # ---- 统计输出 ----
    stats = {"generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
             "scenes": SCENES, "total_rgb": n, "readable": len(readable),
             "unreadable": len(unreadable),
             "per_scene": {s: sum(1 for r in readable if r["scene"] == s) for s in SCENES},
             "resolution": dict(Counter(r["resolution"] for r in readable).most_common()),
             "size_bytes_total": sum(r["size_bytes"] for r in readable),
             "size_bytes_min": min((r["size_bytes"] for r in readable), default=0),
             "size_bytes_max": max((r["size_bytes"] for r in readable), default=0),
             "exact_duplicate_groups": len(exact_dups),
             "exact_duplicate_extra_files": sum(len(v) - 1 for v in exact_dups.values()),
             "perceptual_duplicate_groups": len(perc_groups),
             "perceptual_duplicate_extra_files": sum(len(v) - 1 for v in perc_groups),
             "perceptual_threshold": "dHash 汉明距离 <=5（高相似，统计口径）",
             "near_identical_groups": len(near_ident),
             "near_identical_extra_files": sum(len(v) - 1 for v in near_ident),
             "near_identical_threshold": "dHash 汉明距离 <=2（近同，子集去重口径）",
             "long_consecutive_runs(>=5)": len(runs),
             "labels": "UNLABELED RGB（不生成任何 hole 标签）"}
    (AU / "dataset_stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2),
                                           encoding="utf-8")
    (AU / "duplicate_report.json").write_text(json.dumps({
        "exact_duplicate_groups": [{"sha1": k, "files": v} for k, v in exact_dups.items()][:200],
        "note": "perceptual = dHash<=5（高相似统计）；near_identical = dHash<=2（子集去重用）",
        "perceptual_duplicate_groups": perc_groups[:400],
        "near_identical_groups": near_ident[:400],
        "long_consecutive_high_similarity_runs": runs,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    (AU / "image_quality_report.json").write_text(json.dumps({
        "brightness_mean": round(float(np.mean([r["brightness"] for r in readable])), 1),
        "contrast_mean": round(float(np.mean([r["contrast"] for r in readable])), 1),
        "blur_lapvar_mean": round(float(np.mean([r["blur_lapvar"] for r in readable])), 1),
        "blur_lapvar_p05": round(float(np.percentile([r["blur_lapvar"] for r in readable], 5)), 1),
        "specular_mean": round(float(np.mean([r["specular"] for r in readable])), 4),
        "bore_cue_mean": round(float(np.mean([r["bore_cue"] for r in readable])), 2),
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---- object 分布 ----
    with (AU / "object_distribution.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["object_id", "scenes", "scene_count", "image_count", "priority_tier", "priority_reason"])
        for oid in sorted(obj_img_count):
            t, why = PRIORITY.get(oid, (9, "未在 Phase3 人工确认清单中"))
            w.writerow([oid, "|".join(sorted(obj_scene_count[oid])), len(obj_scene_count[oid]),
                        obj_img_count[oid], t, why])

    with (AU / "priority_objects.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["object_id", "scene_count", "scenes", "image_count", "priority_tier", "reason_for_priority"])
        for oid in sorted(obj_img_count):
            if oid in PRIORITY:
                t, why = PRIORITY[oid]
                w.writerow([oid, len(obj_scene_count[oid]), "|".join(sorted(obj_scene_count[oid])),
                            obj_img_count[oid], t, why])

    # ---- 子集构建（只用清单，不复制数据）----
    exact_dup_keep = set()
    for v in exact_dups.values():
        exact_dup_keep |= set(v[1:])
    perc_dup_drop = set()
    for grp in near_ident:
        g = sorted(grp)
        perc_dup_drop |= set(g[1:])

    def usable(r):
        return (r["readable"] and r["path"] not in exact_dup_keep
                and r["path"] not in perc_dup_drop
                and r["blur_lapvar"] >= 20.0)     # 去掉明显糊的

    # TLESS-ALL：三场景均匀覆盖
    all_sel = []
    per_scene_target = 250
    for s in SCENES:
        arr = sorted([r for r in readable if r["scene"] == s and usable(r)], key=lambda x: x["frame"])
        if not arr:
            continue
        k = min(per_scene_target, len(arr))
        idx = np.linspace(0, len(arr) - 1, k).astype(int)
        all_sel += [arr[i] for i in idx]

    # TLESS-HOLE：优先物体 tier1（6/7/8/18）与 tier2（5/11/12/13-17/23/24）
    def tier_of(r):
        ts = [PRIORITY.get(i, (9, ""))[0] for i in r["object_ids"]]
        return min(ts) if ts else 9

    hole_pool = [r for r in readable if usable(r) and tier_of(r) <= 2]
    hole_sel = []
    for s in SCENES:
        arr = sorted([r for r in hole_pool if r["scene"] == s], key=lambda x: x["frame"])
        if not arr:
            continue
        # 每个场景最多 350，保证覆盖三场景
        k = min(350, len(arr))
        idx = np.linspace(0, len(arr) - 1, k).astype(int)
        hole_sel += [arr[i] for i in idx]

    def write_manifest(sel, folder, name):
        d = PR / folder
        d.mkdir(parents=True, exist_ok=True)
        with (d / "manifest.csv").open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["image_path", "scene_id", "object_ids", "priority_reason",
                        "resolution", "file_size", "label_status"])
            for r in sel:
                reasons = []
                for i in r["object_ids"]:
                    if i in PRIORITY:
                        reasons.append("obj{}:{}".format(i, PRIORITY[i][1]))
                w.writerow([r["path"], r["scene"], "|".join(str(i) for i in r["object_ids"]),
                            " ; ".join(reasons) if reasons else "通用工业物体（无优先孔证据）",
                            r["resolution"], r["size_bytes"], "UNLABELED_RGB"])
        (d / "README.md").write_text("\n".join([
            "# {}".format(name),
            "",
            "- 图像数量：**{}**".format(len(sel)),
            "- 数据来源：T-LESS v2 测试场景 01/02/03 的 RGB（CC BY 4.0）",
            "- **本子集只包含清单（manifest.csv），未复制原始图像**",
            "- **标签状态：UNLABELED_RGB —— 不生成、也不允许生成任何 hole 标签**",
            "- 去除了精确重复、感知重复（dHash≤5）与明显模糊帧（Laplacian方差<20）",
            "",
            "重新读取时按 manifest.csv 的 image_path 列加载即可。",
            "",
        ]), encoding="utf-8")
        return d / "manifest.csv"

    m_all = write_manifest(all_sel, "TLESS-ALL", "T-LESS-ALL（三场景均匀覆盖）")
    m_hole = write_manifest(hole_sel, "TLESS-HOLE", "T-LESS-HOLE（含多孔/成排孔/内壁物体）")

    summary = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_rgb": n, "readable": len(readable),
        "exact_duplicate_extra": stats["exact_duplicate_extra_files"],
        "perceptual_duplicate_extra": stats["perceptual_duplicate_extra_files"],
        "TLESS_ALL": len(all_sel), "TLESS_HOLE": len(hole_sel),
        "manifests": {"TLESS-ALL": str(m_all), "TLESS-HOLE": str(m_hole)},
        "objects": {str(k): {"scenes": sorted(obj_scene_count[k]), "images": obj_img_count[k],
                             "tier": PRIORITY.get(k, (9, ""))[0]} for k in sorted(obj_img_count)},
        "labels": "UNLABELED_RGB",
    }
    (EXT / "phase4_tless_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    with (EXT / "phase4_tless_summary.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["item", "value"])
        for k, v in [("三场景 RGB 总数", n), ("可正常读取", len(readable)),
                     ("精确重复(多余文件)", stats["exact_duplicate_extra_files"]),
                     ("感知重复(多余文件)", stats["perceptual_duplicate_extra_files"]),
                     ("TLESS-ALL", len(all_sel)), ("TLESS-HOLE", len(hole_sel))]:
            w.writerow([k, v])

    print()
    print("总数 {} / 可读 {} / 精确重复多余 {} / 感知重复多余 {}".format(
        n, len(readable), stats["exact_duplicate_extra_files"],
        stats["perceptual_duplicate_extra_files"]))
    print("TLESS-ALL = {} 张   TLESS-HOLE = {} 张".format(len(all_sel), len(hole_sel)))
    print("最长连续高相似段数(>=5帧):", len(runs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
