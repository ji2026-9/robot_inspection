# -*- coding: utf-8 -*-
"""
Build the GitHub Release assets for the robot_inspection project.

分类原则（和 docs/PROJECT_FILES.md 一致）：
  A. Git 仓库   : 代码 / 脚本 / 配置 / 文档 / 轻量实验记录    -> git push
  B. Release 附件: 模型 / 数据集 / 图片 / 训练输出 / 大压缩包  -> 本脚本生成
  C. 不上传      : .venv / __pycache__ / _installers          -> 不打包

用法：
    E:\\robot_inspection\\.venv\\Scripts\\python.exe E:\\robot_inspection\\scripts\\make_release_assets.py
    # 只生成前 8 个核心附件（跳过 3 GB 的外部数据集，省时间）：
    ... make_release_assets.py --core-only

输出目录：E:\\robot_inspection\\release_assets\\
本脚本**只读取**项目文件，从不修改、不移动、不删除任何原始内容。
"""

import argparse
import hashlib
import shutil
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]          # E:\robot_inspection
OUT = ROOT / "release_assets"
VM_SHARE = Path(r"E:\vm_share")

# 已经是压缩格式的，直接 store，省 CPU
STORE_EXT = {".zip", ".7z", ".rar", ".gz", ".jpg", ".jpeg", ".png", ".bmp",
             ".webp", ".pt", ".pth", ".onnx", ".engine", ".exe", ".dll", ".pyd",
             ".mp4", ".avi", ".mkv", ".pdf"}

SKIP_DIR_NAMES = {"__pycache__", ".git", "release_assets", ".venv", ".idea", ".vscode"}


def human(n: float) -> str:
    return "{:.1f} MB".format(n / 1024 / 1024)


def sha256_file(p: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(chunk), b""):
            h.update(c)
    return h.hexdigest().upper()


def iter_files(src: Path):
    """Yield every file under src, skipping cache / venv folders."""
    for p in sorted(src.rglob("*")):
        if not p.is_file():
            continue
        if any(part in SKIP_DIR_NAMES for part in p.parts):
            continue
        yield p


def make_zip(zip_path: Path, sources):
    """sources: list of (Path, arcname_prefix). Directories are walked."""
    t0 = time.time()
    n_files = 0
    raw = 0
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=1,
                         allowZip64=True) as z:
        for src, prefix in sources:
            if src.is_file():
                arc = "/".join(x for x in [prefix, src.name] if x)
                z.write(src, arc, compress_type=zipfile.ZIP_STORED)
                n_files += 1
                raw += src.stat().st_size
                continue
            if not src.is_dir():
                print("   [WARN] missing source: {}".format(src))
                continue
            for p in iter_files(src):
                rel = p.relative_to(src).as_posix()
                # 目录源要带上目录本身的名字，否则解压后结构会塌陷（还会撞名）
                arc = "/".join(x for x in [prefix, src.name, rel] if x)
                ctype = (zipfile.ZIP_STORED if p.suffix.lower() in STORE_EXT
                         else zipfile.ZIP_DEFLATED)
                z.write(p, arc, compress_type=ctype)
                n_files += 1
                raw += p.stat().st_size
    dt = time.time() - t0
    print("   -> {}  ({}, {} files, {:.0f}s)".format(
        zip_path.name, human(zip_path.stat().st_size), n_files, dt))
    return n_files, raw


def copy_asset(src: Path, dst: Path):
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    print("   -> {}  ({})".format(dst.name, human(dst.stat().st_size)))


# ---------------------------------------------------------------------------
# 附件定义
# ---------------------------------------------------------------------------
CORE = [
    dict(name="01_gui_app_full_package.zip", kind="copy",
         src=ROOT / "friend_transfer" / "robot_inspection_gui_v1.zip",
         note="★朋友最需要：完整 GUI 软件包（代码+模型+测试图+数据集+一键装环境）"),
    dict(name="02_model_package.zip", kind="copy",
         src=ROOT / "friend_transfer" / "robot_inspection_model_package_v1.zip",
         note="模型 + 数据集 + 推理脚本（早期版本，保留备用）"),
    dict(name="03_dataset_box_yolo.zip", kind="copy",
         src=VM_SHARE / "box_yolo_dataset.zip",
         note="原始数据集压缩包（train 20 / val 2 / test 3）"),
    dict(name="04_weights_best.pt", kind="copy",
         src=ROOT / "weights" / "best.pt",
         note="当前 baseline 模型（YOLO11n-Seg, SHA256 7E33DF62...BDFE）"),
    dict(name="05_test_images.zip", kind="zip",
         sources=[(ROOT / "test_images", "")],
         note="4 张手机测试照片（复现测试结果用）"),
    dict(name="06_experiments_full.zip", kind="zip",
         sources=[(ROOT / "experiments", "")],
         note="5 个 seed 的完整正式实验（含模型与结果图）"),
    dict(name="07_results_and_runs.zip", kind="zip",
         sources=[(ROOT / "results", ""), (ROOT / "runs", "")],
         note="检测可视化结果 + YOLO 训练输出"),
    dict(name="08_logs_and_audit.zip", kind="zip",
         sources=[(ROOT / "logs", ""), (ROOT / "_audit", "")],
         note="训练/安装日志 + 审计原图"),
]

ED = ROOT / "external_datasets"
P3 = ED / "phase3_downloads"
PRE3 = "external_datasets/phase3_downloads"

# GitHub Release 单个附件上限 2 GB，所以外部数据集必须拆成 3 份
EXTRA = [
    dict(name="09_external_data_1_original_zips.zip", kind="zip",
         sources=[(P3 / n, PRE3) for n in (
             "tless_test_primesense_01.zip", "tless_test_primesense_01.zip.manifest.json",
             "tless_test_primesense_02.zip", "tless_test_primesense_02.zip.manifest.json",
             "tless_test_primesense_03.zip", "tless_test_primesense_03.zip.manifest.json",
             "workpieces_surfaces.zip", "workpieces_surfaces.zip.manifest.json")],
         note="外部数据集原始压缩包（T-LESS 01/02/03 + Workpieces，约 1.5 GB，可重新下载）"),
    dict(name="10_external_data_2_extracted.zip", kind="zip",
         sources=[(P3 / n, PRE3) for n in (
             "tless_test_primesense_01", "tless_test_primesense_02",
             "tless_test_primesense_03", "workpieces_surfaces")],
         note="外部数据集解压后的图像（约 1.5 GB，可重新下载）"),
    dict(name="11_external_data_3_reports.zip", kind="zip",
         sources=[(p, "external_datasets") for p in sorted(ED.iterdir())
                  if p.name != "phase3_downloads"],
         note="外部数据集审计报告 / 元数据 / 样本 / 结论 md（约 24 MB）"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--core-only", action="store_true",
                    help="只生成 01~08（跳过约 3 GB 的外部数据集）")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    todo = CORE if args.core_only else CORE + EXTRA

    print("output:", OUT)
    print("assets :", len(todo))
    print()

    rows = []
    for i, a in enumerate(todo, 1):
        dst = OUT / a["name"]
        print("[{}/{}] {}".format(i, len(todo), a["name"]))
        if a["kind"] == "copy":
            if not a["src"].is_file():
                print("   [SKIP] source not found:", a["src"])
                continue
            copy_asset(a["src"], dst)
        else:
            make_zip(dst, a["sources"])
        rows.append((a["name"], sha256_file(dst), dst.stat().st_size, a["note"]))

    # ---------- manifest ----------
    man = OUT / "MANIFEST_文件清单.txt"
    with man.open("w", encoding="utf-8") as f:
        f.write("robot_inspection —— GitHub Release 附件清单\n")
        f.write("=" * 74 + "\n")
        f.write("生成时间: {}\n".format(time.strftime("%Y-%m-%d %H:%M:%S")))
        f.write("文件数  : {}\n".format(len(rows)))
        f.write("合计    : {}\n\n".format(human(sum(r[2] for r in rows))))
        f.write("上传方法：GitHub 仓库页 -> Releases -> Draft a new release\n")
        f.write("          Tag 填 v1.0-data，把这些文件拖进附件框，Publish release\n\n")
        f.write("-" * 74 + "\n")
        for name, sha, size, note in rows:
            f.write("{}\n".format(name))
            f.write("   大小  : {}\n".format(human(size)))
            f.write("   SHA256: {}\n".format(sha))
            f.write("   说明  : {}\n\n".format(note))

    sha_txt = OUT / "SHA256_校验.txt"
    with sha_txt.open("w", encoding="utf-8") as f:
        for name, sha, size, _ in rows:
            f.write("{}  {}  ({})\n".format(sha, name, human(size)))

    print()
    print("MANIFEST:", man)
    print("SHA256  :", sha_txt)
    print("TOTAL   : {} in {} files".format(
        human(sum(r[2] for r in rows)), len(rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
