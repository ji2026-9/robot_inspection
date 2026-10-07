# -*- coding: utf-8 -*-
"""
把外部数据集审计报告导出到桌面
==============================
1) 单文件自包含 HTML：所有图片以 data URI 内嵌，双击即可打开，换电脑不掉图
2) 完整资料包 zip：报告 + 预览图 + 官方样例图 + candidates.csv/json + README + checksums

不会覆盖桌面已有同名文件（存在则自动加时间戳后缀）。

用法：
    python scripts\export_report_to_desktop.py
"""

import base64
import mimetypes
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path

EXT = Path(r"E:\robot_inspection\external_datasets")
REP = EXT / "reports" / "external_dataset_audit.html"
DESK = Path(r"C:\Users\Administrator\Desktop")


def unique(p: Path) -> Path:
    if not p.exists():
        return p
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return p.with_name("{}_{}{}".format(p.stem, stamp, p.suffix))


def main() -> int:
    if not REP.is_file():
        print("[错误] 找不到报告：{}".format(REP))
        return 2
    DESK.mkdir(parents=True, exist_ok=True)

    # ---------- 1) 单文件自包含 HTML ----------
    doc = REP.read_text(encoding="utf-8")
    pattern = r"""(src|href)\s*=\s*(['"])([^'"]+\.(?:jpg|jpeg|png|gif|webp))\2"""
    refs = sorted({m.group(3) for m in re.finditer(pattern, doc, flags=re.I)})

    embedded = 0
    skipped = []
    for rel in refs:
        p = (REP.parent / rel).resolve()
        if not p.is_file():
            skipped.append(rel)
            continue
        mime = mimetypes.guess_type(str(p))[0] or "image/jpeg"
        b64 = base64.b64encode(p.read_bytes()).decode("ascii")
        data_uri = "data:{};base64,{}".format(mime, b64)
        doc = re.sub(r"""(src|href)\s*=\s*(['"])""" + re.escape(rel) + r"""\2""",
                     lambda m, u=data_uri: "{}=\"{}\"".format(m.group(1), u), doc, flags=re.I)
        embedded += 1

    banner = (
        "<div style='background:#ecfdf5;border:1px solid #a7f3d0;border-radius:10px;"
        "padding:12px 14px;margin-bottom:18px;font-size:13px;color:#065f46'>"
        "<b>单文件自包含版本</b>：所有图片已内嵌（data URI），可直接复制到任何电脑打开，"
        "不需要附带其它文件。<br>原始工作目录："
        "<code>E:\\robot_inspection\\external_datasets\\</code></div>"
    )
    doc = doc.replace("<h1>", banner + "<h1>", 1)
    out1 = unique(DESK / "external_dataset_audit.html")
    out1.write_text(doc, encoding="utf-8")
    print("[OK] 单文件报告 : {}  ({:.0f} KB, 内嵌图片 {})".format(
        out1, out1.stat().st_size / 1024, embedded))
    if skipped:
        print("     (跳过缺失图片: {})".format(skipped))

    # ---------- 2) 完整资料包 ----------
    items = [EXT / "README.md", EXT / "candidates.csv", EXT / "candidates.json",
             EXT / "best_candidate" / "README.md",
             EXT / "metadata" / "checksums.txt", EXT / "metadata" / "audit_summary.json",
             EXT / "metadata" / "search_hits.json", EXT / "metadata" / "official_site_probe.json"]
    for d in (EXT / "reports", EXT / "audit", EXT / "samples", EXT / "metadata" / "raw"):
        if d.is_dir():
            items += [p for p in d.rglob("*") if p.is_file()]
    items = [p for p in items if p.is_file()]

    out2 = unique(DESK / "external_datasets_audit_bundle.zip")
    with zipfile.ZipFile(out2, "w", zipfile.ZIP_DEFLATED) as z:
        for p in items:
            try:
                z.write(p, p.relative_to(EXT).as_posix())
            except Exception:
                pass
    print("[OK] 完整资料包 : {}  ({:.0f} KB, {} 个文件)".format(
        out2, out2.stat().st_size / 1024, len(items)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
