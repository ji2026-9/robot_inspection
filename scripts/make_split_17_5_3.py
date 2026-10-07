# -*- coding: utf-8 -*-
"""
重新划分数据集：17 train / 5 val / 3 test
-----------------------------------------
规则（严格遵守）：
  1. 原来的 3 张 test 图片原样继续作为 test；
  2. 原来的 2 张 val 图片保留在 val；
  3. 只从原来的 20 张 train 中拿 3 张补进 val，使 val 达到 5 张；
  4. 剩下的 17 张作为 train；
  5. 图片与 YOLO-Seg label 成对复制；
  6. 只复制，绝不修改/删除原始 dataset\\box_yolo 目录。

输出目录：
  E:\\robot_project\\robot_inspection\\experiments\\dataset_17_5_3\\

用法：
  python scripts\\make_split_17_5_3.py
"""

import shutil
import sys
from pathlib import Path

SRC = Path(r"E:\robot_project\robot_inspection\dataset\box_yolo")
DST = Path(r"E:\robot_project\robot_inspection\experiments\dataset_17_5_3")
IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}

# 从原 train 里挑 3 张补进 val：按文件名排序后取第 1、9、17 张（分布较均匀，可复现）
PICK_POSITIONS = [0, 8, 16]


def list_images(d: Path):
    if not d.is_dir():
        return []
    return sorted([p for p in d.iterdir() if p.suffix.lower() in IMG_EXTS])


def copy_pair(img: Path, split: str) -> bool:
    """把图片和同名 label 复制到目标 split，返回是否找到 label。"""
    (DST / "images" / split).mkdir(parents=True, exist_ok=True)
    (DST / "labels" / split).mkdir(parents=True, exist_ok=True)
    shutil.copy2(img, DST / "images" / split / img.name)
    lbl_src = SRC / "labels" / img.parent.name / (img.stem + ".txt")
    if lbl_src.is_file():
        shutil.copy2(lbl_src, DST / "labels" / split / (img.stem + ".txt"))
        return True
    return False


def main() -> int:
    print("=" * 70)
    print("重新划分数据集 17 / 5 / 3")
    print("源目录（只读，不会被修改）:", SRC)
    print("目标目录                    :", DST)
    print("=" * 70)

    if not SRC.is_dir():
        print("[错误] 找不到原始数据集：", SRC)
        return 2

    if DST.exists() and any(DST.rglob("*")):
        print("[错误] 目标目录已存在且非空：", DST)
        print("       为避免覆盖已有实验数据，本脚本不会自动删除它。")
        print("       如确认要重建，请先手动改名或删除该目录后重跑。")
        return 2

    src_train = list_images(SRC / "images" / "train")
    src_val = list_images(SRC / "images" / "val")
    src_test = list_images(SRC / "images" / "test")
    print("\n原始数据: train={}  val={}  test={}".format(len(src_train), len(src_val), len(src_test)))

    if len(src_train) < 3:
        print("[错误] 原 train 不足 3 张，无法凑够 5 张 val")
        return 2

    move_to_val = [src_train[i] for i in PICK_POSITIONS if i < len(src_train)]
    new_train = [p for p in src_train if p not in move_to_val]
    new_val = list(src_val) + move_to_val

    print("\n从原 train 划入 val 的 3 张（按文件名排序取第 1/9/17 张）:")
    for p in move_to_val:
        print("   -", p.name)

    print("\n开始复制……")
    missing = []
    for p in new_train:
        if not copy_pair(p, "train"):
            missing.append(("train", p.name))
    for p in new_val:
        if not copy_pair(p, "val"):
            missing.append(("val", p.name))
    for p in src_test:
        if not copy_pair(p, "test"):
            missing.append(("test", p.name))

    yaml_text = (
        "path: E:/robot_project/robot_inspection/experiments/dataset_17_5_3\n"
        "train: images/train\n"
        "val: images/val\n"
        "test: images/test\n"
        "\n"
        "names:\n"
        "  0: cylinder_bore\n"
    )
    (DST / "data.yaml").write_text(yaml_text, encoding="utf-8")

    print("\n" + "=" * 70)
    print("校验结果")
    print("=" * 70)
    ok = True
    for split, expect in (("train", 17), ("val", 5), ("test", 3)):
        imgs = list_images(DST / "images" / split)
        lbls = sorted((DST / "labels" / split).glob("*.txt"))
        stems_i = {p.stem for p in imgs}
        stems_l = {p.stem for p in lbls}
        good = (len(imgs) == expect and len(lbls) == expect and stems_i == stems_l)
        if not good:
            ok = False
        print("{:<6} images = {:<3} labels = {:<3} (期望 {})  {}".format(
            split, len(imgs), len(lbls), expect, "OK" if good else "问题"))
        if stems_i != stems_l:
            print("       缺标签:", sorted(stems_i - stems_l), " 缺图片:", sorted(stems_l - stems_i))

    if missing:
        ok = False
        print("[警告] 以下图片没有找到对应 label：", missing)

    new_test_stems = {p.stem for p in list_images(DST / "images" / "test")}
    old_test_stems = {p.stem for p in src_test}
    same_test = new_test_stems == old_test_stems
    print("\n原 test 图片完全保留在 test：{}  {}".format(same_test, sorted(new_test_stems)))
    if not same_test:
        ok = False

    print("原始目录未被改动检查: train={} val={} test={}".format(
        len(list_images(SRC / "images" / "train")),
        len(list_images(SRC / "images" / "val")),
        len(list_images(SRC / "images" / "test"))))
    print("data.yaml: {}".format(DST / "data.yaml"))
    print("\n[{}] 数据划分完成".format("成功" if ok else "存在问题"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
