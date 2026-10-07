# -*- coding: utf-8 -*-
"""
Phase 2 外部数据集：T-LESS / Workpieces 视觉审计 + 对比评分 + 最终报告
=====================================================================
输出：
  external_datasets\\tless_sample\\tless_visual_audit.html
  external_datasets\\workpieces\\workpieces_visual_audit.html
  external_datasets\\workpieces\\DOWNLOAD_FAILED.md
  external_datasets\\phase2_comparison.csv
  external_datasets\\phase2_comparison.json
  external_datasets\\phase2_conclusion.md
  external_datasets\\reports\\phase2_external_audit.html

用法：
    python scripts\\build_phase2_report.py
"""

import csv
import json
import os
import sys
from datetime import datetime
from pathlib import Path

EXT = Path(r"E:\robot_project\robot_inspection\external_datasets")
REPORTS = EXT / "reports"
TLESS = EXT / "tless_sample"
WP = EXT / "workpieces"
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
.wrap{max-width:1150px;margin:0 auto}
h1{font-size:26px;margin:0 0 6px}
h2{font-size:20px;margin:32px 0 14px;padding-left:10px;border-left:5px solid var(--blue)}
h3{font-size:16px;margin:20px 0 8px}
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
.kpi{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px}
.kpi div{background:#eef6ff;border:1px solid #dbeafe;border-radius:10px;padding:12px 14px}
.kpi b{display:block;font-size:21px;color:var(--blue);font-variant-numeric:tabular-nums}
.kpi span{font-size:12px;color:var(--muted)}
img{max-width:100%;border:1px solid var(--line);border-radius:10px;display:block}
.mono{font-family:Consolas,monospace;font-size:12px}
.verdict{background:#ecfdf5;border:1px solid #a7f3d0;border-radius:12px;padding:16px 18px;color:#065f46}
.risk{background:#fffbeb;border:1px solid #fde68a;border-radius:10px;padding:12px 14px;
      color:#92400e;font-size:14px;margin-bottom:10px}
ul{margin:8px 0 8px 20px}
"""


def table(rows):
    out = ["<table>"]
    for i, r in enumerate(rows):
        tag = "th" if i == 0 else "td"
        out.append("<tr>" + "".join("<{0}>{1}</{0}>".format(tag, c) for c in r) + "</tr>")
    out.append("</table>")
    return "\n".join(out)


def main() -> int:
    REPORTS.mkdir(parents=True, exist_ok=True)
    WP.mkdir(parents=True, exist_ok=True)

    an_path = TLESS / "metadata" / "tless_object_analysis.json"
    an = json.loads(an_path.read_text(encoding="utf-8")) if an_path.is_file() else []
    n_obj = len(an)
    h1r = sum(1 for r in an if r["n_holes_relaxed"] >= 1)
    h3r = sum(1 for r in an if r["n_holes_relaxed"] >= 3)
    hg = sum(1 for r in an if r["hough_circles"] >= 1)
    hg3 = sum(1 for r in an if r["hough_circles"] >= 3)
    spec = sum(1 for r in an if r["specular_ratio"] > 0.005)

    # ---------------- T-LESS 视觉审计 ----------------
    sheet_obj = TLESS / "previews" / "objects_contact_sheet.jpg"
    sheet_sc = TLESS / "previews" / "scenes_contact_sheet.jpg"
    rows = [["编号", "严格孔数", "放宽孔数", "近圆孔", "霍夫圆数", "镜面高光比", "平均亮度"]]
    for r in an:
        rows.append([r["object"], r["n_holes"], r["n_holes_relaxed"], r["round_holes_relaxed"],
                     r["hough_circles"], "{:.4f}".format(r["specular_ratio"]), r["mean_brightness"]])
    P = []
    A = P.append
    A("<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>")
    A("<title>T-LESS 视觉审计</title><style>{}</style></head><body><div class='wrap'>".format(CSS))
    A("<h1>T-LESS 视觉审计（基于官方图片的实测）</h1>")
    A("<div class='sub'>来源：官方站点 <span class='mono'>https://cmp.felk.cvut.cz/t-less/</span>　"
      "License：<b>CC BY 4.0</b>（官网原文 “This work is licensed under Creative Commons Attribution 4.0 International”）<br>"
      "审计时间：{}　|　抽样：30 个物体官方预览图 + 20 个场景官方预览图（共 50 张，3.82 MB）</div>".format(NOW))
    A("<div class='panel'><h2>1. 为什么用官方预览图</h2>"
      "<p>T-LESS 的 RGB 归档为 <span class='mono'>tless_test_primesense_bop19.zip</span>（825 MB）、"
      "<span class='mono'>tless_train_primesense.zip</span>（2.49 GB）、"
      "<span class='mono'>tless_train_pbr.zip</span>（23 GB）。本机实测 Zenodo ≈22 KB/s、Hugging Face 间歇不可达，"
      "下载 825 MB 需 &gt;5 小时，因此改用<b>官方站点的 30 个物体图 + 20 个真实场景图</b>做审计——它们同为官方发布，"
      "足以判断“有没有孔、有没有内壁、有没有成排多孔”。测试集图像未取得，已在下方标注。</p></div>")
    A("<h2>2. 30 个物体官方图</h2>")
    A("<div class='panel'><img src='{}' alt='objects'></div>".format(rel(sheet_obj, TLESS)))
    A("<h2>3. 20 个真实场景官方图</h2>")
    A("<div class='panel'><img src='{}' alt='scenes'></div>".format(rel(sheet_sc, TLESS)))
    A("<h2>4. 程序化统计（对 30 张物体图逐张计算）</h2><div class='panel'>")
    A("<div class='kpi'>")
    A("<div><b>{}/30</b><span>检出 ≥1 个孔/开口</span></div>".format(h1r))
    A("<div><b>{}</b><span>检出 ≥3 个孔（成排多孔）</span></div>".format(h3r))
    A("<div><b>{}/30</b><span>霍夫圆 ≥1</span></div>".format(hg))
    A("<div><b>{}</b><span>霍夫圆 ≥3</span></div>".format(hg3))
    A("<div><b>{}</b><span>明显镜面高光对象</span></div>".format(spec))
    A("</div>")
    A(table(rows))
    A("<p class='mono' style='color:#6b7280'>严格阈值 = 物体内部亮度&lt;60 且面积占比 0.4%–55%；"
      "放宽阈值 = 低于物体中位亮度−35；霍夫圆 = HoughCircles(dp=1.5, param2=45, r=28–220)。</p></div>")
    A("<h2>5. 人工目视结论（主要证据）</h2><div class='panel'><table>")
    A("<tr><th>观察项</th><th>计数</th><th>说明</th></tr>")
    for k, v, note in [
        ("出现明显大圆孔/圆形开口的物体", "约 21 / 30", "01–12、17、18、23、24、30 等，开口占物体宽度比例很大"),
        ("开口内有可见内壁的物体", "约 13 / 30", "05–09、13–18、23、24：可见筒壁、台阶或螺纹"),
        ("含金属螺纹/反光件的物体", "约 6 / 30", "13、14、15、16、18、24 内有黄铜/金属螺纹环"),
        ("成排的 3–4 个孔", "6 / 30", "07（3 孔）、08（4 孔）、09（3 孔）、19/20、28（2 孔）"),
        ("方形箱体/外壳形状", "5 / 30", "25、26（接线盒）、27、28、29（方形外壳/盒体）"),
        ("斜视角 / 透视变形", "20 / 20 场景图", "场景图存在明显俯视、斜视与堆叠遮挡"),
        ("多背景 / 多光照", "20 / 20 场景图", "黑幕、纸板、杂志、桌面等多种背景"),
    ]:
        A("<tr><td>{}</td><td><b>{}</b></td><td>{}</td></tr>".format(k, v, note))
    A("</table>")
    A("<div class='risk'><b>局限：</b>以上计数来自官方“标准视图”预览图（每个物体 1 张、黑幕背景）。"
      "T-LESS 实际测试图像（斜视角、杂乱、遮挡、多光照）<b>本次未能下载</b>，"
      "斜视角表现只能从 20 张场景预览图间接判断。</div></div>")
    A("<h2>6. 结论：T-LESS 到底有没有“孔”</h2><div class='panel'>"
      "<p><b>有，且比例很高。</b>程序化检测显示 30 个物体中 <b>29 个</b>存在被轮廓包围的开口，"
      "<b>24 个</b>能检出 ≥3 个圆；人工目视确认约 <b>21 个</b>有明显大圆孔，"
      "其中 <b>6 个</b>具“成排多个孔”结构（07/08/09 分别 3/4/3 个孔），"
      "与“工件上连续排列的 4 个大孔”在结构上高度相似。</p>"
      "<p>但 T-LESS 物体以<b>白色塑料</b>为主（金属螺纹仅少数），因此其价值集中在"
      "「孔结构 / 多孔排列 / 内壁」，而「金属高反光」上价值中等。</p></div>")
    A("</div></body></html>")
    (TLESS / "tless_visual_audit.html").write_text("\n".join(P), encoding="utf-8")
    print("[OK]", TLESS / "tless_visual_audit.html")

    # ---------------- Workpieces（下载失败） ----------------
    (WP / "DOWNLOAD_FAILED.md").write_text("\n".join([
        "# Workpieces image dataset — 下载失败记录",
        "",
        "- 目标：`https://zenodo.org/api/records/16361102/files/surfaces.zip/content`（411.5 MB, CC BY 4.0）",
        "- 实测速度：**约 22 KB/s**（多轮 15–22 KB/s；短时突发曾达 620 KB/s）",
        "- 推算 ETA：**> 5 小时**，超出本次任务可接受范围，已主动中止",
        "- 已下载字节：约 2.4 MB（不完整，已删除，避免误用）",
        "- 失败原因：**网络吞吐不足**，非数据集不可访问（直链 HTTP 200）",
        "",
        "## 已获得的官方信息（Zenodo API 元数据，非推测）",
        "",
        "- License：`cc-by-4.0`（明确）",
        "- 采集设备：industrial boroscope（工业内窥镜）+ microscope camera",
        "- 照明：白色 LED 经光纤导光，亮度可调",
        "- 分辨率：2592 × 1944 RGB，300 ppi",
        "- 内容：机加工零件的**内表面与外表面**",
        "- 标注：**专家人工标注、按表面磨损分类（图像级分类标签）**",
        "  → **没有 mask、没有 bbox、没有孔类别**",
        "",
        "## 结论",
        "",
        "域相似度（孔内壁 + 工业照明）理论很高，但**本次无法用真实图像验证**，",
        "且标注是分类标签，**不能直接用于 YOLO-Seg 分割训练**。",
        "",
    ]), encoding="utf-8")

    rows = [["项目", "结果"]]
    for k, v in [("下载状态", "FAILED（网络吞吐不足，约 22 KB/s，ETA &gt; 5 小时）"),
                 ("License", "CC BY 4.0（已确认）"),
                 ("图片总数", "未确认（单一 zip 411.5 MB，无法枚举）"),
                 ("文件格式", "未确认（zip 内，推测 jpg/png）"),
                 ("分辨率", "2592 × 1944 RGB（官方描述）"),
                 ("是否有 mask", "否（官方描述为按表面磨损分类）"),
                 ("是否有 bbox", "否"),
                 ("是否有分类标签", "是（按表面磨损人工分类）"),
                 ("是否有孔类别", "否（类别是磨损等级，不是孔）"),
                 ("是否有内孔", "官方描述为“机加工零件内表面与外表面”，很可能存在，**未验证**"),
                 ("是否有孔内壁", "官方描述支持（内窥镜拍内表面），**未目视验证**"),
                 ("是否有圆形/椭圆形孔", "未确认"),
                 ("是否有反光", "未确认（金属内壁 + LED 照明，理论上很可能）"),
                 ("是否有阴影", "未确认"),
                 ("是否有工业照明", "是（白 LED 光纤，亮度可调）")]:
        rows.append([k, v])
    P = []
    A = P.append
    A("<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>")
    A("<title>Workpieces 视觉审计</title><style>{}</style></head><body><div class='wrap'>".format(CSS))
    A("<h1>Workpieces image dataset 视觉审计</h1>")
    A("<div class='sub'>Zenodo DOI <span class='mono'>10.5281/zenodo.16361102</span>　|　License：CC BY 4.0　|　"
      "审计时间：{}</div>".format(NOW))
    A("<div class='panel'><div class='risk'><b>下载失败：</b>实测吞吐约 22 KB/s，411.5 MB 需 &gt;5 小时，已中止"
      "（详见 <span class='mono'>workpieces/DOWNLOAD_FAILED.md</span>）。因此<b>本数据集没有真实图像审计结果</b>，"
      "下表全部来自 Zenodo 官方元数据，未验证项一律标注“未确认”。</div>")
    A(table(rows))
    A("<div class='risk' style='margin-top:14px'><b>关键限制：</b>官方描述明确写的是 "
      "“the dataset with surface images that are <b>classified according to surface wear</b>”，"
      "即标注是<b>图像级磨损分类</b>，<b>没有分割 mask，也没有孔的位置/形状标注</b>。"
      "所以即使下载成功，也<b>不能直接用于本项目 YOLO-Seg 的 mask 训练</b>，"
      "只能作为无监督/自监督预训练或域适应素材。</div></div>")
    A("<h2>该数据集对“孔检测”有没有帮助？</h2><div class='panel'>")
    A("<p><b>有潜在帮助，属于“域接近、标注无用”类型：</b></p><ul>"
      "<li>采集方式（工业内窥镜 + 可调 LED）与“测量孔内壁”的实际场景高度一致 → 对<b>反光/内壁域</b>有潜在价值；</li>"
      "<li>但它是分类标注，<b>无法直接提供孔的 mask</b>；</li>"
      "<li>且本次未能目视验证“是否真的有圆形孔、是否有明显反光”。</li></ul>"
      "<p>结论：<b>值得在解决下载问题后重新审计</b>，但不应把它当作分割训练数据。</p></div>")
    A("</div></body></html>")
    (WP / "workpieces_visual_audit.html").write_text("\n".join(P), encoding="utf-8")
    print("[OK]", WP / "workpieces_visual_audit.html")
    print("[OK]", WP / "DOWNLOAD_FAILED.md")

    # ---------------- 评分 ----------------
    cand = [
        {"id": "A_own", "name": "A. 当前自己的 25 张数据（box_yolo）",
         "domain": 30, "hole": 30, "metal": 15, "reflect": 10, "seg": 10, "license": 5,
         "imagery_evidence": "完整（自建数据集，含 4 孔 mask + 反光孔案例）",
         "verdict": "基准：域与类别完全匹配，但样本量仅 25 张"},
        {"id": "B_tless", "name": "B. T-LESS（BOP，工业零件）",
         "domain": 22, "hole": 26, "metal": 9, "reflect": 5, "seg": 7, "license": 5,
         "imagery_evidence": "已用 30 物体图 + 20 场景图实测（程序化 + 目视）",
         "verdict": "孔结构/多孔排列/内壁迁移价值高；金属反光中等；许可最清晰"},
        {"id": "C_workpieces", "name": "C. Workpieces（内窥镜拍机加工件内外表面）",
         "domain": 20, "hole": 15, "metal": 12, "reflect": 7, "seg": 2, "license": 5,
         "imagery_evidence": "无（下载失败，仅元数据）",
         "verdict": "域最接近孔内壁/工业照明，但仅分类标签、未目视验证"},
        {"id": "D_container", "name": "D. Container Hole Localization（大型集装箱孔位）",
         "domain": 30, "hole": 28, "metal": 14, "reflect": 6, "seg": 8, "license": 0,
         "imagery_evidence": "官方预览图 1 张（论文图）",
         "verdict": "主题最接近，但 License 无法确认 → 暂不可用"},
    ]
    for c in cand:
        c["total"] = c["domain"] + c["hole"] + c["metal"] + c["reflect"] + c["seg"] + c["license"]
    ranked = sorted(cand, key=lambda c: -c["total"])

    (EXT / "phase2_comparison.json").write_text(json.dumps({
        "generated_at": NOW,
        "scoring": {"domain_similarity": 30, "hole_similarity": 30, "industrial_metal": 15,
                    "reflection_similarity": 10, "segmentation_usefulness": 10, "license": 5},
        "container_hole_license": "LICENSE_UNCLEAR",
        "tless": {"license": "CC BY 4.0", "objects": n_obj,
                  "objects_with_holes_relaxed": h1r, "objects_with_ge3_holes": h3r,
                  "hough_ge1": hg, "hough_ge3": hg3, "specular_objects": spec,
                  "evidence": "30 official object images + 20 official scene images"},
        "workpieces": {"download": "FAILED", "measured_speed_kBs": "~22",
                       "license": "CC BY 4.0", "labels": "image-level surface wear classification (no mask/bbox)"},
        "candidates": ranked,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    with (EXT / "phase2_comparison.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["name", "domain_/30", "hole_/30", "industrial_metal_/15",
                    "reflection_/10", "segmentation_/10", "license_/5", "total_/100",
                    "imagery_evidence", "verdict"])
        for c in ranked:
            w.writerow([c["name"], c["domain"], c["hole"], c["metal"], c["reflect"],
                        c["seg"], c["license"], c["total"], c["imagery_evidence"], c["verdict"]])
    print("[OK]", EXT / "phase2_comparison.csv")
    print("[OK]", EXT / "phase2_comparison.json")

    # ---------------- phase2 主报告 ----------------
    P = []
    A = P.append
    A("<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>")
    A("<title>Phase 2 外部数据集审计</title><style>{}</style></head><body><div class='wrap'>".format(CSS))
    A("<h1>Phase 2　外部数据集审计（T-LESS / Workpieces / Container Hole）</h1>")
    A("<div class='sub'>目标：工业箱体上 4 个大型结构孔（cylinder_bore）　|　生成时间：{}<br>"
      "本阶段<b>未训练任何模型</b>，未修改正式数据集 / best.pt / 已有实验。</div>".format(NOW))
    A("<h2>1. Container Hole 许可证核验结果</h2><div class='panel'>")
    A(table([
        ["检查项", "结果"],
        ["仓库文件", "只有 README.md(1,581B) + dataset.png(963,351B)，<b>没有 LICENSE / TERMS / COPYRIGHT 文件</b>"],
        ["GitHub API license", "None（无许可证）"],
        ["论文", "Diao et al., <i>A large-scale container dataset and a baseline method for container hole localization</i>, J. Real-Time Image Processing 19 (2022) 577-589"],
        ["DOI / 出版页", "10.1007/s11554-022-01199-y　https://link.springer.com/article/10.1007/s11554-022-01199-y"],
        ["Crossref 许可字段", "仅 <span class='mono'>Springer TDM</span>（文本/数据挖掘条款），<b>不是数据使用许可，也不是 CC 许可</b>"],
        ["OpenAlex", "is_oa=False, oa_status=<b>closed</b>, license=None（论文非开放获取）"],
        ["Data availability 声明", "未获取到（付费墙，页面未返回该段落）"],
        ["数据规模（README）", "144 个集装箱视频 / 1700 张集装箱图像 / 4810 张孔位图像"],
        ["下载渠道", "BaiduYun（密码 0cue）或 Google Drive；两者均无使用条款说明"],
        ["公开联系方式", "dyf@my.swjtu.edu.cn（README 公开，<b>仅记录，未发信</b>）"],
        ["最终判定", "<span class='tag warn'>LICENSE_UNCLEAR</span>"],
        ["本项目可用性", "<b>不能确认可用于本项目训练，因此暂不使用。</b>"],
    ]))
    A("</div>")
    A("<h2>2. T-LESS 实际审计结果</h2><div class='panel'>")
    A(table([
        ["项目", "结果"],
        ["官方来源 / License", "cmp.felk.cvut.cz/t-less（原始站）+ BOP；官网原文 <b>CC BY 4.0</b>"],
        ["本次抽样", "官方 30 个物体图 + 20 个真实场景图（共 50 张，3.82 MB，全部成功下载）"],
        ["RGB 测试集图像", "<b>未下载</b>（825MB / 2.49GB / 23GB 三档，本机速度不支持）"],
        ["程序化：检出 ≥1 个孔/开口", "{}/30（{:.0f}%）".format(h1r, 100 * h1r / max(n_obj, 1))],
        ["程序化：检出 ≥3 个孔", "{} / 30".format(h3r)],
        ["霍夫圆 ≥1 / ≥3", "{} / {}（30 个物体）".format(hg, hg3)],
        ["目视：明显大圆孔", "约 21 / 30"],
        ["目视：可见内壁", "约 13 / 30"],
        ["目视：成排 3–4 孔", "6 / 30（07/08/09/19/20/28）"],
        ["目视：方形箱体/外壳", "5 / 30（25/26/27/28/29）"],
        ["斜视角 / 透视", "20 张场景图中普遍存在"],
        ["反光", "仅 3 个物体镜面高光 &gt;0.5%（多为白色塑料）"],
        ["详细报告", "<a href='{}' target='_blank'>tless_visual_audit.html</a>".format(
            rel(TLESS / "tless_visual_audit.html", REPORTS))],
    ]))
    A("</div>")
    A("<h2>3. Workpieces 实际审计结果</h2><div class='panel'>")
    A(table([
        ["项目", "结果"],
        ["下载", "<b>FAILED</b>：实测约 22 KB/s，411.5 MB 需 &gt;5 小时，已中止（直链 HTTP 200）"],
        ["License", "CC BY 4.0（已确认）"],
        ["采集", "工业内窥镜 + 显微镜相机，白 LED 光纤照明（亮度可调）"],
        ["分辨率", "2592 × 1944 RGB"],
        ["内容", "机加工零件的<b>内表面与外表面</b>"],
        ["标注", "<b>按表面磨损的人工分类标签（图像级）</b> → 无 mask、无 bbox、无孔类别"],
        ["可视化审计", "<b>未完成</b>（无图像）"],
        ["详细报告", "<a href='{}' target='_blank'>workpieces_visual_audit.html</a>".format(
            rel(WP / "workpieces_visual_audit.html", REPORTS))],
    ]))
    A("</div>")
    A("<h2>4. 评分对比（Domain/30 · Hole/30 · Metal/15 · Reflection/10 · Seg/10 · License/5）</h2>")
    A("<div class='panel'>")
    rows = [["数据集", "Domain", "Hole", "Metal", "Reflection", "Seg", "License", "总分", "图像证据"]]
    for c in ranked:
        rows.append([c["name"], c["domain"], c["hole"], c["metal"], c["reflect"], c["seg"],
                     c["license"], "<b>{}</b>".format(c["total"]), c["imagery_evidence"]])
    A(table(rows))
    A("<p class='mono' style='color:#6b7280'>D（Container Hole）原始得分最高，但 license=0 且许可无法确认，"
      "按约定标记为<b>暂不可用</b>。</p></div>")
    A("<h2>5. 特别关注：反光孔问题</h2><div class='panel'>")
    A(table([
        ["特征", "T-LESS", "Workpieces", "结论"],
        ["金属反光", "弱（3/30 有明显高光，主体白色塑料）", "未验证（金属内表面 + 可调 LED，理论上强）", "Workpieces 理论更强，未证实"],
        ["孔内暗区/亮区", "有（29/30 检出内部暗区）", "未验证", "T-LESS 已证实"],
        ["内壁高光", "有（13 个物体可见内壁，含金属螺纹）", "未验证", "T-LESS 已证实"],
        ["椭圆透视", "有（20 张场景图普遍斜视）", "未验证", "T-LESS 已证实"],
        ["不同曝光/光照", "有（场景图多种光照）", "有（LED 亮度可调，描述）", "两者都有"],
    ]))
    A("<div class='verdict'><b>结论：</b>就「反光孔」而言，<b>Workpieces 在域上最接近</b>"
      "（内窥镜拍孔内壁 + 可调工业照明），但本次<b>无法用图像证实</b>；"
      "<b>T-LESS 已被证实包含大量带内壁的孔</b>，但以白色塑料为主，对「金属高反光」帮助有限。"
      "因此：<b>T-LESS 是已证实有用的选择，Workpieces 是有潜力的待验证选择。</b></div></div>")
    A("<h2>6. 不要直接混合训练</h2><div class='panel'>"
      "<div class='risk'><b>仍然不做</b>「external images + 我的 cylinder_bore 标签」直接混合训练："
      "外部数据的类别语义（工业零件 / 表面磨损 / 集装箱角件）与 cylinder_bore 完全不一致，"
      "直接套标签会产生错误监督信号。本阶段只准备数据与方案，不执行训练。</div></div>")
    A("<h2>7. 最终必须回答的 8 个问题</h2><div class='panel'><table>")
    for q, a in [
        ("1. T-LESS 是否值得用于 external pretraining？",
         "<b>值得。</b>官方图已证实 30 个物体中约 21 个含大圆孔、6 个具成排 3–4 孔、13 个可见内壁；"
         "许可 CC BY 4.0（可商用），并有 2D binary mask（BOP 格式）。"),
        ("2. Workpieces 是否值得用于 external pretraining？",
         "<b>有条件值得，优先级低于 T-LESS。</b>域（孔内壁 + 工业照明）最接近，"
         "但标注仅为图像级磨损分类（无 mask），且本次<b>下载失败、未获图像证据</b>。"),
        ("3. 哪个对“反光孔”最有帮助？",
         "理论上 <b>Workpieces</b> 最对口，但未证实；<b>T-LESS 已证实含内壁孔</b>但对金属反光帮助有限。"
         "建议先解决 Workpieces 下载再做判断。"),
        ("4. 哪个对“孔内壁”最有帮助？",
         "<b>Workpieces</b>（就是拍内表面）；T-LESS 次之（13 个物体可见内壁）。"),
        ("5. 哪个对“工业箱体整体视觉”最有帮助？",
         "若可用则 Container Hole 最佳；可用的里面是 <b>T-LESS</b>"
         "（25/26 接线盒、27/28/29 方形外壳，共 5 个箱体类物体 + 真实杂乱场景）。"),
        ("6. Container Hole 是否已经确认 License？",
         "<b>没有。</b>仓库无 LICENSE；Crossref 仅 Springer TDM；OpenAlex 显示 closed access；"
         "数据在 BaiduYun/Google Drive 且无条款 → <b>LICENSE_UNCLEAR</b>。"),
        ("7. 如果仍然无法确认，是否应该暂时放弃？",
         "<b>是，暂时不使用</b>（不下载、不训练、不写入训练数据）。保留为候选，"
         "并记录官方联系方式 dyf@my.swjtu.edu.cn，待你决定是否联系作者。"),
        ("8. 下一步最推荐的实验顺序",
         "<b>B &gt; C &gt; D &gt; A &gt; E</b>（按证据强度与可执行性排序）。"),
    ]:
        A("<tr><th style='width:300px'>{}</th><td>{}</td></tr>".format(q, a))
    A("</table></div>")
    A("<h2>8. 下一步实验顺序（本阶段均不执行）</h2><div class='panel'>")
    A(table([
        ["排序", "实验", "理由", "前置条件"],
        ["1", "<b>B. T-LESS → 当前 17/5/3 fine-tune</b>",
         "唯一「许可清晰 + 有 mask + 已证实含大量孔/内壁」的方案",
         "下载 tless_test_primesense_bop19.zip(825MB) 或 train_primesense(2.49GB)"],
        ["2", "<b>C. Workpieces → 当前数据 fine-tune</b>",
         "域最接近孔内壁与工业照明，对反光孔最有潜力",
         "先解决下载（411MB）；并确认只能做无监督预训练（无 mask）"],
        ["3", "<b>D. T-LESS + Workpieces → 当前数据 fine-tune</b>",
         "两者互补（孔结构 + 内壁域）", "需先完成 B 与 C 的取数"],
        ["4", "<b>A. 不加外部数据，直接优化当前模型</b>",
         "当前 5 seed 已 38/40=95%、最低 conf 0.6233，问题集中在个别临界漏检",
         "无需下载"],
        ["5", "<b>E. 等 Container Hole License 确认后再做</b>",
         "主题最接近但许可未知，风险最高", "需作者明确许可"],
    ]))
    A("</div></div></body></html>")
    (REPORTS / "phase2_external_audit.html").write_text("\n".join(P), encoding="utf-8")
    print("[OK]", REPORTS / "phase2_external_audit.html")

    # ---------------- phase2_conclusion.md ----------------
    md = [
        "# Phase 2 外部数据集审计 —— 结论文档",
        "",
        "生成时间：{}".format(NOW),
        "",
        "> 本阶段未训练任何模型；未修改正式数据集 / best.pt / 已有实验。",
        "",
        "## 1. Container Hole License 最终结果",
        "",
        "**LICENSE_UNCLEAR** —— 仓库无 LICENSE 文件（GitHub API license=None），"
        "Crossref 仅有 Springer TDM 条款，OpenAlex 显示论文 closed access，"
        "数据托管在 BaiduYun / Google Drive 且无使用条款。",
        "",
        "→ **不能确认可用于本项目训练，因此暂不使用。**",
        "",
        "官方公开联系方式（仅记录，未发信）：dyf@my.swjtu.edu.cn",
        "",
        "## 2. T-LESS 实际审计结果",
        "",
        "- License：**CC BY 4.0**（官方站点原文确认，可商用）",
        "- 抽样：官方 30 个物体图 + 20 个场景图（50 张，全部下载成功）",
        "- 程序化：{}/30 物体检出 ≥1 个孔/开口；{} 个检出 ≥3 个孔；霍夫圆 ≥1 的 {} 个、≥3 的 {} 个".format(
            h1r, h3r, hg, hg3),
        "- 目视：约 21/30 有明显大圆孔；约 13/30 可见内壁；6/30 具成排 3–4 孔；5/30 为方形箱体/外壳",
        "- 反光：仅 3/30 有明显镜面高光（主体为白色塑料）",
        "- 未取得：RGB 测试集图像（825MB / 2.49GB / 23GB 三档，本机速度不支持）",
        "",
        "## 3. Workpieces 实际审计结果",
        "",
        "- **下载失败**：实测约 22 KB/s，411.5 MB 需 >5 小时，已中止（直链 HTTP 200 可访问）",
        "- License：CC BY 4.0（已确认）",
        "- 采集：工业内窥镜 + 显微镜相机，白 LED 光纤照明（可调），2592×1944 RGB",
        "- 内容：机加工零件的内表面与外表面",
        "- 标注：**按表面磨损的人工分类标签（图像级）** → 无 mask、无 bbox、无孔类别",
        "- 可视化审计：**未完成**（无图像）",
        "",
        "## 4. 评分对比（满分 100）",
        "",
        "| 数据集 | Domain/30 | Hole/30 | Metal/15 | Reflection/10 | Seg/10 | License/5 | 总分 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for c in ranked:
        md.append("| {} | {} | {} | {} | {} | {} | {} | **{}** |".format(
            c["name"], c["domain"], c["hole"], c["metal"], c["reflect"],
            c["seg"], c["license"], c["total"]))
    md += [
        "",
        "> D（Container Hole）原始得分最高，但 license=0 且无法确认许可 → 按约定标记为**暂不可用**。",
        "",
        "## 5. 最推荐哪个",
        "",
        "**B. T-LESS → 当前 17/5/3 fine-tune**：唯一同时满足「许可清晰（CC BY 4.0）+ 有分割标注 + "
        "已用真实图像证实含大量圆孔/内壁/成排多孔」的方案。",
        "",
        "## 6. 下一步具体应该做哪个实验",
        "",
        "1. **B**：T-LESS → 当前数据 fine-tune（先下载 tless_test_primesense_bop19.zip 825MB 或 train_primesense 2.49GB）",
        "2. **C**：Workpieces → 当前数据 fine-tune（需先解决下载；它只有分类标签，只能做无监督预训练）",
        "3. **D**：T-LESS + Workpieces 联合预训练",
        "4. **A**：不加外部数据，直接优化当前模型（增强 / 更多种子 / 阈值策略）",
        "5. **E**：等 Container Hole 许可澄清后再做",
        "",
        "以上实验**本阶段均未执行**。",
        "",
    ]
    (EXT / "phase2_conclusion.md").write_text("\n".join(md), encoding="utf-8")
    print("[OK]", EXT / "phase2_conclusion.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
