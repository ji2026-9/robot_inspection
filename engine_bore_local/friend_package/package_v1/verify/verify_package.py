#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
交付包完整性 + 模型可加载性验证脚本
==================================
用法（在交付包根目录下）：
    python verify\verify_package.py
或：
    python verify/verify_package.py

检查项：
  1. weights/best.pt 是否存在
  2. dataset 是否存在
  3. data.yaml 是否存在
  4. train/val/test 是否存在（images 与 labels）
  5. images 与 labels 数量是否匹配
  6. test_images 是否存在
  7. inference/predict_holes.py 是否存在
  8. docs/SHA256.txt 是否存在，且关键文件 SHA256 是否一致
  9. best.pt 是否可以被读取（用 ultralytics 加载模型）

【安全声明】本脚本**只加载模型**，绝不调用 model.train() / trainer.train()，
不写任何文件（除非显式加 --write-report）。
"""

import argparse
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent   # package_v1/
IMG_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest().upper()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write-report", action="store_true", help="把结果写到 verify\\verify_report.json")
    args = ap.parse_args()

    ok_all = True
    results = []

    def check(name, cond, detail=""):
        nonlocal ok_all
        ok_all = ok_all and bool(cond)
        results.append({"check": name, "pass": bool(cond), "detail": detail})
        print("[{}] {}{}".format("PASS" if cond else "FAIL", name, ("  -> " + detail) if detail else ""))
        return bool(cond)

    print("=" * 70)
    print("交付包验证  根目录:", ROOT)
    print("=" * 70)

    # 1
    best = ROOT / "weights" / "best.pt"
    check("1. weights/best.pt 存在", best.is_file(),
          "{} 字节".format(best.stat().st_size) if best.is_file() else "缺失")
    # 2
    ds = ROOT / "dataset"
    check("2. dataset 目录存在", ds.is_dir(), str(ds))
    # 3
    box = ds / "box_yolo"
    yml = box / "data.yaml"
    check("3. dataset/box_yolo/data.yaml 存在", yml.is_file(), str(yml))
    # 4 / 5
    for split in ("train", "val", "test"):
        di, dl = box / "images" / split, box / "labels" / split
        imgs = sorted([p for p in di.iterdir() if p.suffix.lower() in IMG_EXT]) if di.is_dir() else []
        lbls = sorted([p for p in dl.iterdir() if p.suffix.lower() == ".txt"]) if dl.is_dir() else []
        check("4. {} 目录存在".format(split), di.is_dir() and dl.is_dir(),
              "images={} labels={}".format(len(imgs), len(lbls)))
        same = len(imgs) == len(lbls) and {p.stem for p in imgs} == {p.stem for p in lbls}
        check("5. {} images/labels 匹配".format(split), same,
              "{} vs {}".format(len(imgs), len(lbls)))
    # 6
    ti = ROOT / "test_images"
    n_test = len([p for p in ti.iterdir() if p.suffix.lower() in IMG_EXT]) if ti.is_dir() else 0
    check("6. test_images 存在且有图片", n_test > 0, "{} 张".format(n_test))
    # 7
    inf = ROOT / "inference" / "predict_holes.py"
    check("7. inference/predict_holes.py 存在", inf.is_file(), str(inf))
    # 8
    shafile = ROOT / "docs" / "SHA256.txt"
    has_sha = shafile.is_file()
    check("8. docs/SHA256.txt 存在", has_sha, str(shafile))
    if has_sha:
        bad = []
        checked = 0
        for line in shafile.read_text(encoding="utf-8", errors="ignore").splitlines():
            parts = line.split()
            if len(parts) < 3:
                continue
            rel, digest = parts[0], parts[1]
            if len(digest) != 64:
                continue
            f = ROOT / rel
            checked += 1
            if not f.is_file() or sha256(f) != digest:
                bad.append(rel)
        check("8b. SHA256 校验（关键文件）", not bad,
              "已校验 {} 个文件，{} 个不一致{}".format(
                  checked, len(bad), ("：" + ", ".join(bad[:5])) if bad else ""))

    # 9 模型加载（只加载，绝不训练）
    load_ok, detail = False, ""
    if best.is_file():
        try:
            from ultralytics import YOLO
            m = YOLO(str(best))          # 只加载
            detail = "任务={} 类别={}".format(getattr(m, "task", "?"), getattr(m, "names", "?"))
            load_ok = True
        except ImportError as e:
            detail = "未安装 ultralytics（{}）。请先 pip install ultralytics".format(e)
        except Exception as e:
            detail = "{}: {}".format(type(e).__name__, e)
    else:
        detail = "weights/best.pt 不存在"
    check("9. best.pt 可被读取", load_ok, detail)
    print()
    print("MODEL LOAD: {}".format("PASS" if load_ok else "FAIL"))
    if not load_ok:
        print("  原因:", detail)

    print()
    print("=" * 70)
    print("总体结果:", "全部通过 ✔" if ok_all else "存在失败项 ✘")
    print("=" * 70)
    print("说明：本脚本只验证，不训练、不修改任何文件。")

    if args.write_report:
        import json
        out = ROOT / "verify" / "verify_report.json"
        out.write_text(json.dumps({"root": str(ROOT), "all_pass": ok_all,
                                   "model_load": load_ok, "checks": results},
                                  ensure_ascii=False, indent=2), encoding="utf-8")
        print("已写出:", out)
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
