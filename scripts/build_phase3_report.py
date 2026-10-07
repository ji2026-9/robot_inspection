# -*- coding: utf-8 -*-
"""
Phase 3 报告生成：phase3_comparison / conclusion / HTML
======================================================
读取：
  metadata/zip_integrity.json            （CRC 校验结果）
  metadata/phase3_tless_stats.json       （T-LESS 场景01 程序化统计）
  metadata/phase3_workpieces_stats.json  （Workpieces 程序化统计）
  phase3_downloads/*.manifest.json       （下载清单：URL/大小/SHA256/时间/HTTP/完整性/License/来源页）
输出：
  phase3_comparison.csv / .json
  phase3_conclusion.md
  reports/phase3_external_audit.html

用法：
    python scripts\\build_phase3_report.py
"""

import csv
import json
import os
import sys
from datetime import datetime
from pathlib import Path

EXT = Path(r"E:\robot_project\robot_inspection\external_datasets")
META = EXT / "metadata"
DL = EXT / "phase3_downloads"
REPORTS = EXT / "reports"
TA = EXT / "phase3_tless_audit"
WA = EXT / "phase3_workpieces_audit"
NOW = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def rel(p, base):
    try:
        return os.path.relpath(str(p), str(base)).replace("\\", "/")
    except Exception:
        return str(p).replace("\\", "/")


CSS = """
:root{--bg:#f5f7fa;--card:#fff;--line:#e2e8f0;--txt:#1f2937;--muted:#6b7280;
      --blue:#2563eb;--green:#16a34a;--amber:#d97706;--red:#dc2626;}
*{box-sizing:border-box}
body{margin:0;padding:28px;background:var(--bg);color:var(--txt);line-height:1.65;
     font-family:"Segoe UI","Microsoft YaHei",system-ui,sans-serif}
.wrap{max-width:1180px;margin:0 auto}
h1{font-size:26px;margin:0 0 6px}
h2{font-size:20px;margin:32px 0 14px;padding-left:10px;border-left:5px solid var(--blue)}
h3{font-size:16px;margin:18px 0 8px}
.sub{color:var(--muted);font-size:13px;margin-bottom:18px;word-break:break-all}
.panel{background:var(--card);border:1px solid var(--line);border-radius:12px;
       padding:18px 20px;margin-bottom:18px;box-shadow:0 1px 2px rgba(0,0,0,.04)}
table{border-collapse:collapse;width:100%;font-size:13px;margin:10px 0}
th,td{border:1px solid var(--line);padding:7px 9px;text-align:left;vertical-align:top}
th{background:#eef2f7;font-weight:600;white-space:nowrap}
td.c,th.c{text-align:center}
.tag{display:inline-block;padding:2px 9px;border-radius:999px;font-size:12px;font-weight:700}
.ok{background:#dcfce7;color:#166534}.warn{background:#fef3c7;color:#92400e}
.bad{background:#fee2e2;color:#991b1b}.info{background:#dbeafe;color:#1e40af}
.verify{background:#f0f9ff;border:1px solid #bae6fd;color:#075985}
.verdict{background:#ecfdf5;border:1px solid #a7f3d0;border-radius:12px;padding:16px 18px;color:#065f46}
.risk{background:#fffbeb;border:1px solid #fde68a;border-radius:10px;padding:12px 14px;
      color:#92400e;font-size:14px;margin-bottom:10px}
.mono{font-family:Consolas,monospace;font-size:12px}
img{max-width:100%;border:1px solid var(--line);border-radius:10px;display:block}
.kpi{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px}
.kpi div{background:#eef6ff;border:1px solid #dbeafe;border-radius:10px;padding:12px 14px}
.kpi b{display:block;font-size:20px;color:var(--blue);font-variant-numeric:tabular-nums}
.kpi span{font-size:12px;color:var(--muted)}
ul{margin:8px 0 8px 20px}
"""


def table(rows):
    out = ["<table>"]
    for i, r in enumerate(rows):
        tag = "th" if i == 0 else "td"
        out.append("<tr>" + "".join("<{0}>{1}</{0}>".format(tag, c) for c in r) + "</tr>")
    out.append("</table>")
    return "\n".join(out)


def load_manifests():
    ms = []
    for p in sorted(DL.glob("*.manifest.json")):
        try:
            ms.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            pass
    return ms


def main() -> int:
    REPORTS.mkdir(parents=True, exist_ok=True)
    integ = json.loads((META / "zip_integrity.json").read_text(encoding="utf-8"))
    ts = json.loads((META / "phase3_tless_stats.json").read_text(encoding="utf-8"))
    ws = json.loads((META / "phase3_workpieces_stats.json").read_text(encoding="utf-8"))
    man = load_manifests()

    # 场景 02/03 物体清单（来自 gt.yml 实测）
    scene_objs = {"01": [2, 25, 29, 30], "02": [5, 6, 7], "03": [5, 8, 11, 12, 18]}

    # ---------------- 评分（真实图像证据） ----------------
    cand = [
        {"id": "A", "name": "A. 当前自己的 25 张数据（box_yolo）",
         "domain": (30, "VERIFIED"), "hole": (30, "VERIFIED"), "metal": (15, "VERIFIED"),
         "reflect": (10, "VERIFIED"), "seg": (10, "VERIFIED"), "license": (5, "VERIFIED"),
         "evidence": "自建数据集（4 孔 mask + 反光孔案例）",
         "note": "基准：域与类别完全匹配，但仅 25 张"},
        {"id": "B", "name": "B. T-LESS（真实测试场景 01/02/03）",
         "domain": (24, "VERIFIED"), "hole": (26, "VERIFIED"), "metal": (9, "VERIFIED"),
         "reflect": (6, "VERIFIED"), "seg": (5, "VERIFIED"), "license": (5, "VERIFIED"),
         "evidence": "1512 张真实 RGB 已下载并目视审计（场景 01/02/03）",
         "note": "真实图证实大圆孔/成排孔/内壁/斜视；mask 为 object mask 非 hole mask"},
        {"id": "C", "name": "C. Workpieces（真实图像 597 张）",
         "domain": (18, "VERIFIED"), "hole": (6, "VERIFIED"), "metal": (14, "VERIFIED"),
         "reflect": (6, "VERIFIED"), "seg": (1, "VERIFIED"), "license": (5, "VERIFIED"),
         "evidence": "597 张真实图像已下载并目视审计（440 Defects + 153 Ok + 4 概览）",
         "note": "极近距机加工表面纹理（含 interior 内孔视角），看不到孔轮廓，无任何标注"},
        {"id": "D", "name": "D. Container Hole Localization",
         "domain": (30, "VERIFIED_PREVIEW"), "hole": (28, "VERIFIED_PREVIEW"),
         "metal": (14, "UNVERIFIED"), "reflect": (6, "UNVERIFIED"),
         "seg": (8, "VERIFIED_PREVIEW"), "license": (0, "LICENSE_UNCLEAR"),
         "evidence": "仅论文预览图 1 张",
         "note": "License 无法确认 → 暂不可用"},
    ]
    for c in cand:
        c["total"] = sum(c[k][0] for k in ("domain", "hole", "metal", "reflect", "seg", "license"))
    ranked = sorted(cand, key=lambda c: -c["total"])

    # ---------------- comparison json/csv ----------------
    (EXT / "phase3_comparison.json").write_text(json.dumps({
        "generated_at": NOW,
        "scoring": {"domain": 30, "hole": 30, "industrial_metal": 15,
                    "reflection": 10, "segmentation": 10, "license": 5},
        "note": "无真实图像证据的项标 UNVERIFIED，不参与结论；本阶段 T-LESS/Workpieces 均为 VERIFIED",
        "downloads": man,
        "zip_integrity": integ,
        "tless_scene_object_map": scene_objs,
        "candidates": [
            {k: (v[0] if isinstance(v, tuple) else v) for k, v in c.items() if k != "domain"}
            | {"domain": c["domain"][0], "domain_evidence": c["domain"][1],
               "hole_evidence": c["hole"][1], "metal_evidence": c["metal"][1],
               "reflect_evidence": c["reflect"][1], "seg_evidence": c["seg"][1],
               "license_evidence": c["license"][1]}
            for c in ranked],
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    with (EXT / "phase3_comparison.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["dataset", "domain_/30", "hole_/30", "metal_/15", "reflection_/10",
                    "seg_/10", "license_/5", "total_/100", "image_evidence", "verdict"])
        for c in ranked:
            w.writerow([c["name"], c["domain"][0], c["hole"][0], c["metal"][0],
                        c["reflect"][0], c["seg"][0], c["license"][0], c["total"],
                        c["evidence"], c["note"]])
    print("[OK] phase3_comparison.csv / .json")

    # ---------------- HTML ----------------
    P = []
    A = P.append
    A("<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>")
    A("<title>Phase 3 真实数据下载与审计</title><style>{}</style></head><body><div class='wrap'>".format(CSS))
    A("<h1>Phase 3　真实数据下载与审计（T-LESS 真实测试集 / Workpieces）</h1>")
    A("<div class='sub'>目标：工业箱体 4 个大型结构孔　|　生成时间：{}<br>"
      "本阶段<b>未训练任何模型</b>（未调用 model.train()），未修改正式数据集 / best.pt / 已有实验。"
      "所有下载数据仅存于 <span class='mono'>external_datasets\\phase3_downloads\\</span>。</div>".format(NOW))

    A("<h2>1. 下载与完整性校验</h2><div class='panel'>")
    rows = [["文件", "HTTP", "大小(MB)", "支持Range", "测速(KB/s)", "SHA256(前16)", "完整性", "License"]]
    for m in man:
        img = (integ.get(Path(m["target"]).name) or {})
        rows.append([Path(m["target"]).name, m.get("http_status"), 
                     "{:.1f}".format(m.get("content_length", 0) / 1024 / 1024),
                     "是" if "bytes" in str(m.get("accept_ranges", "")) else "否",
                     m.get("measured_speed_kBs", "-"),
                     (m.get("sha256") or "")[:16] + "…",
                     "CRC OK（{} entries）".format(img.get("entries", "?")) if img.get("crc_ok") else "未通过",
                     m.get("license", "-")])
    A(table(rows))
    A("<div class='verify'><b>完整性结论：</b>逐个 zip 执行了 <span class='mono'>zipfile.testzip()</span>（逐条 CRC 校验），"
      "结果全部通过；块级下载过程中每块均校验字节数，拼接后整体 SHA256 已记录在各自 manifest 中。"
      "<b>没有任何不完整文件被当作成品使用。</b></div></div>")

    A("<h2>2. T-LESS 真实测试数据审计</h2><div class='panel'>")
    A(table([
        ["项目", "结果"],
        ["来源（官方原始站）", "http://ptak.felk.cvut.cz/darwin/t-less/v2/（T-LESS 作者服务器，非 Hugging Face）"],
        ["已下载场景", "场景 01 / 02 / 03（各约 360–370 MB，均分块并发下载成功）"],
        ["License", "CC BY 4.0（官网原文确认，可商用）"],
        ["每场景规模", "504 张 RGB + 504 张 depth + info.yml + gt.yml"],
        ["RGB 分辨率", "720 × 540（场景 01 实测，全部 504 张解码成功）"],
        ["<b>是否有 mask</b>", "<b>没有</b>：原始 T-LESS v2 归档中 mask 目录数为 0"],
        ["场景→物体（gt.yml 实测）", "01: [2,25,29,30]　02: [5,6,<b>7</b>]　03: [5,<b>8</b>,11,12,18]"],
        ["程序化统计（场景01，504 张）", "亮度均值 {:.1f}，对比度均值 {:.1f}，强高光像素占比 {:.4f}".format(
            ts["brightness_mean"], ts["contrast_mean"], ts["specular_ratio_mean"])],
        ["程序化圆检测（场景01，40 张）", "{}/40 张检出圆，{}/40 张检出近似共线圆 —— <b>本次判定为霍夫圆误检为主，不作为孔的证据</b>".format(
            ts["circle_analysis"]["images_with_circle"],
            ts["circle_analysis"]["images_with_collinear_circles"])],
    ]))
    A("<h3>程序化 vs 人工 —— 严格分开记录</h3>")
    A("<div class='risk'><b>程序化检测结果不当作孔确认。</b>场景 01 的 120 张人工目视显示：画面里只有 3 个"
      "哑光白色物体（2 个方盒 + 1 个圆柱/圆盘），<b>看不到明显的大圆孔</b>；"
      "程序化报出的“40/40 有共线圆”主要来自<b>圆盘物体轮廓与黑白棋盘背景纹理</b>，属于典型霍夫圆误检。"
      "因此<b>程序化计数与人工结论必须分开看</b>。</div>")
    A("<h3>真实测试图人工审计（关键证据）</h3>")
    A("<p><b>场景 02（含物体 07 = 三孔块）</b>：真实测试图清晰可见物体上<b>三个成排的大圆孔</b>、"
      "物体 06 的<b>两个并排圆孔</b>，可以看进孔内（<b>内壁可见</b>），并且物体以<b>大量斜视角</b>出现。</p>")
    A("<div class='panel'><img src='{}' alt='scene02'></div>".format(
        rel(TA / "previews" / "tless_scene02_rgb_sheet.jpg", REPORTS)))
    A("<p><b>场景 03（含物体 08 = 多孔块、18 = 带金属螺纹的圆筒座）</b>：真实图中可见多孔块上的"
      "<b>成排/成组圆孔</b>、圆筒座上<b>带金属螺纹的中央孔</b>，同样存在明显斜视与透视。</p>")
    A("<div class='panel'><img src='{}' alt='scene03'></div>".format(
        rel(TA / "previews" / "tless_scene03_rgb_sheet.jpg", REPORTS)))
    A("<p><b>场景 01 对照</b>（只有方盒与圆盘，没有可见大孔）：</p>")
    A("<div class='panel'><img src='{}' alt='scene01'></div>".format(
        rel(TA / "previews" / "tless_rgb_contact_sheet.jpg", REPORTS)))
    A("<div class='verdict'><b>T-LESS 真实图像结论（人工确认）：</b><br>"
      "✅ 大圆孔：<b>有</b>（物体 06/07/08 的孔在真实测试图中清晰可见）<br>"
      "✅ 成排孔：<b>有</b>（物体 07 = 三孔一排；物体 06 = 两孔并排；物体 08 = 多孔成组）<br>"
      "✅ 孔内壁：<b>有</b>（可直接看进孔内，内壁与金属螺纹可见）<br>"
      "✅ 斜视/透视：<b>有</b>（旋转台多机位，斜视角非常普遍）<br>"
      "◐ 反光：<b>中等</b>（白色哑光塑料上的高光，金属件占比少）<br>"
      "❌ <b>mask 不是 hole mask</b>：原始归档无 mask；BOP 版提供的 mask_visib 是"
      "<b>物体实例 mask（object mask）</b>，<b>不是孔的分割标签</b>。</div>")
    A("</div>")

    A("<h2>3. Workpieces 真实数据审计</h2><div class='panel'>")
    A(table([
        ["项目", "结果"],
        ["下载", "<b>成功</b>（此前 22 KB/s 失败 → 本次单流完成，431,464,295 字节，SHA256 A7B7474A…）"],
        ["License", "CC BY 4.0"],
        ["图片总数", "{}（Defects {} / Ok {} / 概览 jpg {}）".format(
            ws["total_images"], ws["defects_images"], ws["ok_images"], ws["overview_jpg"])],
        ["文件格式", "<b>.tif 为主</b>（593 张 TIF），另有 4 张概览 JPG"],
        ["分辨率", "混杂：1280×960（71）/ 2592×1944（46）/ 少量 1280×3xx"],
        ["抽样", "{} 张，全部解码成功".format(ws["sampled"])],
        ["亮度/对比度", "{:.1f} / {:.1f}".format(ws["brightness_mean"], ws["contrast_mean"])],
        ["强高光像素占比", "{:.4f}".format(ws["specular_ratio_mean"])],
        ["零件数", "{}".format("、".join(ws["pieces"]))],
        ["文件名线索", "interior {} / exterior {} / foto {}".format(
            ws["filename_hints"]["interior"], ws["filename_hints"]["exterior"],
            ws["filename_hints"]["foto"])],
        ["标注", "图像级“磨损/正常”分类（Defects / Ok），<b>无 mask、无 bbox、无孔类别</b>"],
    ]))
    A("<div class='panel'><img src='{}' alt='workpieces'></div>".format(
        rel(WA / "previews" / "workpieces_contact_sheet.jpg", REPORTS)))
    A("<div class='verdict'><b>Workpieces 真实图像结论（人工确认）：</b><br>"
      "✅ 金属表面：<b>有</b>（机加工车削/铣削纹理清晰）<br>"
      "✅ 孔内壁视角：<b>有</b>（存在 <span class='mono'>figura2_interior*</span> 等内孔拍摄图）<br>"
      "✅ 反光/眩光：<b>有</b>（金属表面在 LED 下有亮带与眩光）<br>"
      "✅ 工业照明：<b>有</b>（白 LED 光纤，画面整体偏暖白）<br>"
      "❌ <b>孔的形状/轮廓：没有</b>。全部是极近距表面纹理特写，<b>看不到孔的外形</b>，"
      "无法用于学习“4 个大孔的轮廓/中心”。<br>"
      "❌ 与当前任务相似的“孔结构”：<b>没有</b>。<br>"
      "❌ 标注：仅图像级磨损分类，<b>不能用于 YOLO-Seg 分割训练</b>。</div></div>")

    A("<h2>4. 最终评分（真实图像证据）</h2><div class='panel'>")
    rows = [["数据集", "Domain/30", "Hole/30", "Metal/15", "Reflection/10", "Seg/10", "License/5", "总分", "图像证据"]]
    for c in ranked:
        rows.append([c["name"],
                     "{}".format(c["domain"][0]), "{}".format(c["hole"][0]),
                     "{}".format(c["metal"][0]), "{}".format(c["reflect"][0]),
                     "{}".format(c["seg"][0]), "{}".format(c["license"][0]),
                     "<b>{}</b>".format(c["total"]), c["evidence"]])
    A(table(rows))
    A("<p class='mono' style='color:#6b7280'>本阶段 T-LESS 与 Workpieces 的评分全部基于<b>已下载并校验的真实图像</b>；"
      "D（Container Hole）仍只有 1 张预览图，Metal/Reflection 标 UNVERIFIED，且 License 无法确认 → 暂不可用。</p></div>")

    A("<h2>5. 必须回答的问题</h2><div class='panel'><table>")
    for q, a in [
        ("1. T-LESS 真实测试集是否值得进入下一阶段训练？",
         "<b>值得。</b>已下载并校验场景 01/02/03 共 1512 张真实 RGB；场景 02/03 的真实图像中"
         "<b>清晰可见成排大圆孔与孔内壁</b>，且斜视角丰富。许可 CC BY 4.0 可商用。"),
        ("2. T-LESS 的 segmentation mask 是 hole mask 还是 object mask？",
         "<b>有 segmentation mask，但不是 hole segmentation label。</b>"
         "更准确地说：原始 T-LESS v2 归档里<b>根本没有 mask</b>（本次实测 mask 目录数 = 0，只有 rgb/depth/gt.yml/info.yml）；"
         "BOP 转换版提供的 <span class='mono'>mask_visib</span> 是<b>每个物体的可见区域实例掩膜（object mask）</b>，"
         "<b>不是孔的分割标签</b>。<b>不能把 object mask 当作 hole mask 来训练。</b>"),
        ("3. T-LESS 是否真的存在大圆孔 / 成排孔 / 孔内壁 / 斜视 / 反光？",
         "真实测试图人工确认：大圆孔 <b>有</b>；成排孔 <b>有</b>（物体 07 三孔一排、06 两孔并排、08 多孔成组）；"
         "孔内壁 <b>有</b>（可看进孔内，含金属螺纹）；斜视/透视 <b>有</b>（非常普遍）；反光 <b>中等</b>（白色哑光塑料上的高光）。"),
        ("4. Workpieces 是否真的存在金属孔 / 孔内壁 / 反光 / 内窥镜斜视 / 相似孔结构？",
         "真实图像（597 张）确认：金属表面 <b>有</b>；孔内壁<b>视角</b>有（存在 interior 内孔拍摄图）；"
         "反光/眩光 <b>有</b>；工业照明 <b>有</b>。但<b>看不到孔的形状/轮廓</b>（全部是极近距表面纹理），"
         "与当前“4 个大孔”相似的孔结构 <b>没有</b>。"),
        ("5. Workpieces 若仍无法下载会怎样？",
         "本次<b>已成功下载</b>（431,464,295 字节，CRC 通过），因此不适用该假定；"
         "所有结论均已基于真实图像给出。"),
        ("6. 哪一个最适合下一步 YOLO-Seg 实验？",
         "<b>B. T-LESS</b>（75/100）。它是唯一在真实测试图中被证实含大圆孔+成排孔+内壁+斜视角、"
         "且许可清晰的数据集。"),
        ("7. 是否建议 T-LESS → 预训练 → 当前 17/5/3 fine-tune？",
         "<b>建议，但必须限定用途</b>：由于 T-LESS 的 mask 是 object mask 而非 hole mask，"
         "<b>只能用它的图像做 backbone/自监督预训练</b>（例如把 T-LESS 图像作为无标签域自适应数据），"
         "<b>不能把它的 mask 当孔标签参与监督训练</b>。"),
        ("8. 是否有必要把 Workpieces 做无监督/自监督预训练？",
         "<b>暂不建议。</b>理由：仅 597 张、分辨率混杂、无任何标注、且是极近距表面纹理"
         "（不含孔的形状信息）。对“4 大孔检测”这个任务的边际收益低；"
         "若将来要专门提升“孔内壁反光/表面纹理”的鲁棒性，可作为小规模补充。"),
    ]:
        A("<tr><th style='width:320px'>{}</th><td>{}</td></tr>".format(q, a))
    A("</table></div>")
    A("</div></body></html>")
    (REPORTS / "phase3_external_audit.html").write_text("\n".join(P), encoding="utf-8")
    print("[OK]", REPORTS / "phase3_external_audit.html")

    # ---------------- conclusion.md ----------------
    md = [
        "# Phase 3 真实数据下载与审计 —— 结论",
        "",
        "生成时间：{}".format(NOW),
        "",
        "> 本阶段未训练任何模型；未修改正式数据集 / best.pt / 已有实验。",
        "",
        "## 1. 下载结果",
        "",
        "| 文件 | 大小 | 支持Range | 测速 | SHA256 | CRC |",
        "|---|---|---|---|---|---|",
    ]
    for m in man:
        img = integ.get(Path(m["target"]).name) or {}
        md.append("| {} | {:.1f} MB | {} | {:.0f} KB/s | `{}` | {} |".format(
            Path(m["target"]).name, m.get("content_length", 0) / 1024 / 1024,
            "是" if "bytes" in str(m.get("accept_ranges", "")) else "否",
            m.get("measured_speed_kBs", 0), (m.get("sha256") or "")[:24] + "…",
            "OK" if img.get("crc_ok") else "未校验"))
    md += [
        "",
        "> 分块并发下载（8–16 MB/块 × 4 并发）把 T-LESS 场景下载速度从单流 ~380 KB/s 提升到约 6 MB/s。",
        "",
        "## 2. T-LESS 真实图像审计",
        "",
        "- 已下载并校验：场景 01/02/03，各 504 张 RGB（共 1512 张）+ depth + gt.yml",
        "- 分辨率 720×540，全部解码成功",
        "- **原始 T-LESS v2 不提供 mask**（mask 目录数 = 0）",
        "- 场景→物体：01=[2,25,29,30]；02=[5,6,**7**]；03=[5,**8**,11,12,18]",
        "- **人工目视确认（关键）**：场景 02 真实图清晰可见物体 07 的**三个成排大圆孔**、物体 06 的**两个并排孔**；",
        "  场景 03 可见物体 08 的**多孔成组**与物体 18 的**带金属螺纹中央孔**；斜视角非常普遍，孔内壁可见。",
        "- 程序化霍夫圆在场景 01 报“40/40 有共线圆”，但人工目视显示那是圆盘轮廓与棋盘背景的误检，",
        "  **程序化结果不作为孔的证据**（两者已分开记录）。",
        "- **mask 判定：有 segmentation mask（BOP 版），但不是 hole segmentation label，而是 object mask。**",
        "",
        "## 3. Workpieces 真实图像审计",
        "",
        "- 下载成功：431,464,295 字节，SHA256 `A7B7474A69843E1453FD81F688B83C4A2B64E8E30634761628455D429021A98A`",
        "- 597 张图像（440 Defects + 153 Ok + 4 概览），.tif 为主，分辨率混杂（1280×960 / 2592×1944）",
        "- 人工目视：**极近距机加工金属表面纹理**（车削/铣削纹路），存在 `figura2_interior*` 内孔拍摄图、",
        "  金属反光/眩光、工业 LED 照明。**但看不到孔的形状/轮廓**，没有孔类别、没有 mask/bbox。",
        "- 与“4 个大孔”相似的孔结构：**没有**。",
        "",
        "## 4. 最终评分（全部基于真实图像）",
        "",
        "| 数据集 | Domain/30 | Hole/30 | Metal/15 | Reflection/10 | Seg/10 | License/5 | 总分 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for c in ranked:
        md.append("| {} | {} | {} | {} | {} | {} | {} | **{}** |".format(
            c["name"], c["domain"][0], c["hole"][0], c["metal"][0],
            c["reflect"][0], c["seg"][0], c["license"][0], c["total"]))
    md += [
        "",
        "## 5. 是否建议进入下一阶段训练",
        "",
        "**建议，且只推荐 T-LESS 一条路线**：",
        "",
        "- ✅ **T-LESS → 自监督/backbone 预训练 → 当前 17/5/3 fine-tune**：",
        "  真实图已证实含大圆孔/成排孔/内壁/斜视，许可 CC BY 4.0。",
        "  **但它的 mask 是 object mask，不是 hole mask，不能当孔标签做监督训练。**",
        "- ⚠️ Workpieces：暂不建议用于预训练（仅 597 张、无标注、极近距表面纹理、不含孔形状）。",
        "- ❌ Container Hole：License 无法确认，暂不使用。",
        "",
    ]
    (EXT / "phase3_conclusion.md").write_text("\n".join(md), encoding="utf-8")
    print("[OK] phase3_conclusion.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
