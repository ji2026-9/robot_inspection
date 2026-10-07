# -*- coding: utf-8 -*-
"""Empirical test: which reader works for which kind of path?"""

import os
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from vision import imread_unicode  # noqa: E402

from config import TEST_IMAGE_DIR  # noqa: E402

TEST_DIR = Path(TEST_IMAGE_DIR)
TMP = Path(__file__).resolve().parent / "diag"


def try_read(tag, p):
    a = cv2.imread(str(p))
    b = imread_unicode(p)
    print("{:<38} cv2.imread={:<18} unicode_safe={:<18} exists={} size={}".format(
        tag, "OK" + str(a.shape) if a is not None else "None",
        "OK" + str(b.shape) if b is not None else "None",
        p.is_file(), p.stat().st_size if p.is_file() else "-"))
    return a is not None, b is not None


def main() -> int:
    TMP.mkdir(parents=True, exist_ok=True)
    print("cwd =", os.getcwd())
    print("opencv =", cv2.__version__, "python =", sys.version.split()[0])
    print()
    ok_cv, ok_un = [], []

    print("--- 1) 原始测试图（中文文件名，中文父目录）---")
    for p in sorted(TEST_DIR.glob("*.jpg")):
        a, b = try_read(p.name, p)
        ok_cv.append(a)
        ok_un.append(b)

    print("\n--- 2) 复制到 ASCII 目录后（英文文件名）---")
    ascii_dir = TMP / "ascii_dir"
    ascii_dir.mkdir(parents=True, exist_ok=True)
    for p in sorted(TEST_DIR.glob("*.jpg")):
        q = ascii_dir / "img_ascii.jpg"
        shutil.copy2(p, q)
        a, b = try_read("ascii_dir/img_ascii.jpg", q)
        ok_cv.append(a)
        ok_un.append(b)
        break

    print("\n--- 3) 中文目录 + 中文文件名（另存副本）---")
    cn_dir = TMP / "中文目录"
    cn_dir.mkdir(parents=True, exist_ok=True)
    q = cn_dir / "照片副本.jpg"
    shutil.copy2(sorted(TEST_DIR.glob("*.jpg"))[0], q)
    a, b = try_read("中文目录/照片副本.jpg", q)
    ok_cv.append(a)
    ok_un.append(b)

    print("\n--- 4) PNG 格式（中文名）---")
    png = cn_dir / "截图.png"
    img = cv2.imdecode(np.fromfile(str(sorted(TEST_DIR.glob('*.jpg'))[0]), np.uint8), 1)
    cv2.imencode(".png", img)[1].tofile(str(png))
    a, b = try_read("中文目录/截图.png", png)
    ok_cv.append(a)
    ok_un.append(b)

    print("\n--- 5) 微信临时目录里的 PNG（用户实际可能的来源）---")
    wx = Path(r"C:\Users\Administrator\xwechat_files\wxid_3acshvd2c2ta22_73f0\temp\RWTemp\2026-10\71f40f01f15be54110ec0e86a5559811\f825c6323361aad54f5df047660b717a.png")
    if wx.is_file():
        a, b = try_read("wechat temp png", wx)
        ok_cv.append(a)
        ok_un.append(b)
    else:
        print("wechat temp png: 不存在（跳过）")

    print()
    print("汇总: cv2.imread 成功 {}/{}, unicode_safe 成功 {}/{}".format(
        sum(ok_cv), len(ok_cv), sum(ok_un), len(ok_un)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
