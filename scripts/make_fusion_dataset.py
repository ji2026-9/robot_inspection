# -*- coding: utf-8 -*-
"""
Build the "fusion v1" training set: our 25 annotated photos + the 3 extra photos
the friend shipped in his Release (database_seed), converted to YOLO-seg labels.

Why 28: the audit (docs/FRIEND_PIPELINE_AUDIT.md) showed his model wins on the 4
held-out test images, and the only visible difference is training-data size
(20 vs 28). This script reproduces the "more data" arm of that comparison.

Output (OUTSIDE the git repo on purpose - data must not enter Git):
    E:/fusion_train/dataset_v28/
        images/train, images/val
        labels/train, labels/val
        data.yaml
        split_manifest.csv

READ ONLY with respect to every input. Never touches best.pt / the datasets.

Usage:
    E:/robot_inspection/.venv/Scripts/python.exe E:/robot_inspection/scripts/make_fusion_dataset.py
    ... --val-count 3 --seed 42
"""

import argparse
import csv
import json
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np

try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

PROJ = Path("E:/robot_inspection")
OUR_DATASET = PROJ / "dataset" / "box_yolo"
HIS_SEED = Path("E:/friend_engine_test/engine_bore_local/data/database_seed")
OUT = Path("E:/fusion_train/dataset_v28")
CLASS_NAME = "cylinder_bore"
CLASS_ID = 0
BORE_LABELS = {"bore", "cylinder_bore"}
EXTS = (".jpg", ".jpeg", ".png", ".bmp")


def our_pairs():
    """(image, label) pairs from our own dataset."""
    for split in ("train", "val", "test"):
        idir = OUR_DATASET / "images" / split
        ldir = OUR_DATASET / "labels" / split
        if not idir.is_dir():
            continue
        for img in sorted(p for p in idir.iterdir() if p.suffix.lower() in EXTS):
            lab = ldir / (img.stem + ".txt")
            if lab.is_file():
                yield img, lab, "ours", split


def labelme_to_yolo_seg(json_path, img_w, img_h):
    """Labelme polygons -> YOLO-seg lines (only the bore class)."""
    data = json.loads(Path(json_path).read_text(encoding="utf-8"))
    w = float(data.get("imageWidth") or img_w)
    h = float(data.get("imageHeight") or img_h)
    lines = []
    for sh in data.get("shapes", []):
        if str(sh.get("label", "")).strip().lower() not in BORE_LABELS:
            continue
        pts = sh.get("points") or []
        if len(pts) < 3:
            continue
        coords = []
        for x, y in pts:
            coords.append(min(max(float(x) / w, 0.0), 1.0))
            coords.append(min(max(float(y) / h, 0.0), 1.0))
        lines.append("{} {}".format(CLASS_ID, " ".join("{:.6f}".format(c) for c in coords)))
    return lines


def his_pairs():
    """His extra photos (jpg + labelme json) -> YOLO-seg lines."""
    if not HIS_SEED.is_dir():
        return
    for img in sorted(p for p in HIS_SEED.iterdir() if p.suffix.lower() in EXTS):
        js = img.with_suffix(".json")
        if not js.is_file():
            continue
        im = cv2.imdecode(np.fromfile(str(img), dtype=np.uint8), cv2.IMREAD_COLOR)
        if im is None:
            print("  [warn] cannot read", img.name)
            continue
        lines = labelme_to_yolo_seg(js, im.shape[1], im.shape[0])
        if not lines:
            print("  [warn] no bore polygon in", js.name)
            continue
        yield img, lines, "friend", "database_seed"


def fingerprint(img_path):
    """64x64 normalised grey fingerprint, used to detect the photos both sides have."""
    im = cv2.imdecode(np.fromfile(str(img_path), dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if im is None:
        return None
    g = cv2.resize(im, (64, 64), interpolation=cv2.INTER_AREA).astype(np.float32)
    return (g - g.mean()) / (g.std() + 1e-6)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--val-count", type=int, default=3)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--force", action="store_true", help="allow overwriting the output dir")
    ap.add_argument("--dup-threshold", type=float, default=0.95,
                    help="指纹相关高于这个值就认为两边是同一张照片，只保留我们那一份")
    args = ap.parse_args()

    out = Path(args.out)
    if out.exists() and any(out.iterdir()):
        if not args.force:
            print("output already exists (use --force):", out)
            return 2
        shutil.rmtree(out)
    for sub in ("images/train", "images/val", "labels/train", "labels/val"):
        (out / sub).mkdir(parents=True, exist_ok=True)

    items = []
    ours = list(our_pairs())
    for img, lab, src, split in ours:
        items.append({"img": img, "label_file": lab, "source": src, "origin": split,
                      "name": "{}_{}".format(split, img.name)})

    # his set repeats our 25 photos; keep only the ones we do not have (fingerprint)
    our_fp = [f for f in (fingerprint(p) for p, _, _, _ in ours) if f is not None]
    dup, extra = 0, 0
    for img, lines, src, origin in his_pairs():
        f = fingerprint(img)
        if f is not None and our_fp:
            best = max(float((a * f).mean()) for a in our_fp)
            if best >= args.dup_threshold:
                dup += 1
                continue
        items.append({"img": img, "label_lines": lines, "source": src, "origin": origin,
                      "name": "friend_{}{}".format(img.stem[:12], img.suffix)})
        extra += 1

    print("collected: {} images  (ours {} + his new {};  his duplicates skipped: {})".format(
        len(items), len(ours), extra, dup))

    rng = np.random.default_rng(args.seed)
    order = rng.permutation(len(items))
    val_idx = set()
    for _ in range(50):
        val_idx = set(order[:args.val_count].tolist())
        if sum(1 for i in val_idx if items[i]["source"] == "friend") <= 1:
            break
        order = rng.permutation(len(items))

    rows = []
    for idx, it in enumerate(items):
        split = "val" if idx in val_idx else "train"
        dst_img = out / "images" / split / it["name"]
        dst_lab = out / "labels" / split / (Path(it["name"]).stem + ".txt")
        shutil.copy2(it["img"], dst_img)
        if "label_lines" in it:
            dst_lab.write_text("\n".join(it["label_lines"]) + "\n", encoding="utf-8")
            n_poly = len(it["label_lines"])
        else:
            shutil.copy2(it["label_file"], dst_lab)
            n_poly = len([ln for ln in dst_lab.read_text(encoding="utf-8").splitlines() if ln.strip()])
        rows.append([split, it["name"], it["source"], it["origin"], n_poly])

    (out / "data.yaml").write_text(
        "path: {}\ntrain: images/train\nval: images/val\n\nnames:\n  0: {}\n".format(
            out.as_posix(), CLASS_NAME), encoding="utf-8")

    with (out / "split_manifest.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["split", "image", "source", "origin", "polygons"])
        w.writerows(rows)

    n_train = sum(1 for r in rows if r[0] == "train")
    n_val = sum(1 for r in rows if r[0] == "val")
    print("train = {}  val = {}   (val = {})".format(
        n_train, n_val, ", ".join(r[1] for r in rows if r[0] == "val")))
    print("data.yaml :", out / "data.yaml")
    print("manifest  :", out / "split_manifest.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
