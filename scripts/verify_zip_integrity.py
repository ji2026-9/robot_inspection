# -*- coding: utf-8 -*-
"""
ZIP 完整性校验
=============
对下载的 zip 做：zipfile.testzip()（逐条 CRC 校验）、文件数量、目录结构、
压缩包大小、解压后总大小、扩展名分布，并把结果写成 JSON。

用法：
    python scripts\verify_zip_integrity.py <zip1> [<zip2> ...]
"""

import json
import sys
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path


def verify(p: Path) -> dict:
    info = {"zip": str(p), "size_bytes": p.stat().st_size,
            "size_mb": round(p.stat().st_size / 1024 / 1024, 1)}
    t0 = datetime.now()
    with zipfile.ZipFile(p) as z:
        names = z.namelist()
        info["entries"] = len(names)
        info["compressed_total"] = sum(i.compress_size for i in z.infolist())
        info["uncompressed_total"] = sum(i.file_size for i in z.infolist())
        info["uncompressed_mb"] = round(info["uncompressed_total"] / 1024 / 1024, 1)
        ext = Counter(Path(n).suffix.lower() for n in names if not n.endswith("/"))
        info["extensions"] = dict(ext.most_common(12))
        top = Counter(n.split("/")[0] for n in names if "/" in n)
        info["top_level"] = dict(top.most_common(8))
        info["sample_paths"] = [n for n in names if not n.endswith("/")][:12]
        bad = z.testzip()          # 逐条 CRC 校验
        info["crc_bad_entry"] = bad
        info["crc_ok"] = bad is None
    info["verify_seconds"] = round((datetime.now() - t0).total_seconds(), 1)
    return info


def main() -> int:
    paths = [Path(a) for a in sys.argv[1:]]
    if not paths:
        print("用法: python scripts\\verify_zip_integrity.py <zip> [...]")
        return 2
    out = {}
    for p in paths:
        if not p.is_file():
            print("[跳过] 不存在:", p)
            continue
        print("校验:", p.name, "...", flush=True)
        r = verify(p)
        out[p.name] = r
        print("  entries={}  CRC_OK={}  解压后={} MB  扩展名={}".format(
            r["entries"], r["crc_ok"], r["uncompressed_mb"], r["extensions"]))
        print("  顶层目录={}".format(r["top_level"]))
        print("  示例路径={}".format(r["sample_paths"][:5]))
        print("  校验耗时 {} s".format(r["verify_seconds"]))
    dest = Path(r"E:\robot_inspection\external_datasets\metadata\zip_integrity.json")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n已保存:", dest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
