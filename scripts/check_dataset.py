# -*- coding: utf-8 -*-
"""
数据集检查脚本
--------------
用途：
    1. 检查 dataset/box_yolo 的目录结构是否完整；
    2. 统计 train / val / test 的图片数与标签数；
    3. 校验每张图片是否都有同名 label 文件（.txt）；
    4. 读取并打印 data.yaml。

用法：
    E:\\robot_inspection\\.venv\\Scripts\\python.exe scripts\\check_dataset.py
"""

import argparse
import sys
from pathlib import Path

IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
EXPECT = {"train": 20, "val": 2, "test": 3}


def read_yaml_text(p: Path) -> str:
    try:
        import yaml
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
        return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    except Exception:
        return p.read_text(encoding="utf-8", errors="replace")


def check_split(root: Path, split: str) -> dict:
    img_dir = root / "images" / split
    lbl_dir = root / "labels" / split
    images = sorted([p for p in img_dir.iterdir() if p.suffix.lower() in IMG_EXTS]) if img_dir.is_dir() else []
    labels = sorted([p for p in lbl_dir.iterdir() if p.suffix.lower() == ".txt"]) if lbl_dir.is_dir() else []

    img_stems = {p.stem for p in images}
    lbl_stems = {p.stem for p in labels}

    return {
        "split": split,
        "images": len(images),
        "labels": len(labels),
        "expected": EXPECT.get(split),
        "missing_label": sorted(img_stems - lbl_stems),
        "missing_image": sorted(lbl_stems - img_stems),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=r"E:\robot_inspection\dataset\box_yolo")
    args = ap.parse_args()

    root = Path(args.root)
    print("=" * 68)
    print("数据集检查：", root)
    print("=" * 68)

    ok = True

    if not root.is_dir():
        print("[错误] 数据集目录不存在：", root)
        print("[提示] 请把 box_yolo_dataset.zip 解压到 E:\\robot_inspection\\dataset\\ 下，")
        print("       解压后应为 E:\\robot_inspection\\dataset\\box_yolo\\")
        return 2

    data_yaml = root / "data.yaml"
    if data_yaml.is_file():
        print("")
        print("--- data.yaml ---")
        print(read_yaml_text(data_yaml))
    else:
        print("[错误] 找不到 data.yaml：", data_yaml)
        ok = False

    print("--- 各子集统计 ---")
    print("{:<8}{:>8}{:>8}{:>10}  {}".format("split", "images", "labels", "expected", "status"))
    for split in ("train", "val", "test"):
        r = check_split(root, split)
        problems = []
        if r["expected"] is not None and r["images"] != r["expected"]:
            problems.append("图片数应为 {}".format(r["expected"]))
        if r["images"] != r["labels"]:
            problems.append("图片/标签数量不一致")
        if r["missing_label"]:
            problems.append("{} 张图片缺少标签".format(len(r["missing_label"])))
        if r["missing_image"]:
            problems.append("{} 个标签缺少图片".format(len(r["missing_image"])))
        status = "OK" if not problems else "问题: " + "; ".join(problems)
        if problems:
            ok = False
        print("{:<8}{:>8}{:>8}{:>10}  {}".format(r["split"], r["images"], r["labels"], str(r["expected"]), status))
        if r["missing_label"]:
            print("        缺少标签的图片:", ", ".join(r["missing_label"][:10]))
        if r["missing_image"]:
            print("        缺少图片的标签:", ", ".join(r["missing_image"][:10]))

    print("")
    print("=" * 68)
    print("结论：数据集检查通过" if ok else "结论：数据集存在问题（见上）")
    print("=" * 68)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
