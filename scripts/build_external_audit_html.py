# -*- coding: utf-8 -*-
"""
生成外部数据集最终审计报告 HTML + README（读取 candidates.json 与审计产物）
==========================================================================
输出：
  external_datasets\\reports\\external_dataset_audit.html   九段式最终报告
  external_datasets\\README.md
  external_datasets\\best_candidate\\README.md

用法：
    python scripts\\build_external_audit_html.py
"""

import html
import json
import os
from datetime import datetime
from pathlib import Path

PROJ = Path(r"E:\robot_inspection")
EXT = PROJ / "external_datasets"
REPORTS = EXT / "reports"
META = EXT / "metadata"
AUDIT = EXT / "audit"
NOW = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def rel(p, base):
    try:
        return os.path.relpath(str(p), str(base)).replace("\\", "/")
    except Exception:
        return str(p).replace("\\", "/")


def main():
    d = json.loads((EXT / "candidates.json").read_text(encoding="utf-8"))
    ranked = d["candidates"]
    reach = d.get("platform_reachability", {})
    stats = d.get("search_stats", {})
    def load_any(names, default=None):
        for n in names:
            for p in (META / n, META / "raw" / n):
                if p.is_file():
                    try:
                        return json.loads(p.read_text(encoding="utf-8"))
                    except Exception:
                        pass
        return default if default is not None else {}

    zen = load_any(["zenodo_targeted.json"])
    audit_sum = json.loads((META / "audit_summary.json").read_text(encoding="utf-8")) \
        if (META / "audit_summary.json").is_file() else {"datasets": []}

    base = REPORTS
    css = """
    :root{--bg:#f5f7fa;--card:#fff;--line:#e2e8f0;--txt:#1f2937;--muted:#6b7280;
          --blue:#2563eb;--green:#16a34a;--amber:#d97706;--red:#dc2626;--purple:#7c3aed;}
    *{box-sizing:border-box}
    body{margin:0;padding:28px;background:var(--bg);color:var(--txt);line-height:1.65;
         font-family:"Segoe UI","Microsoft YaHei",system-ui,sans-serif}
    .wrap{max-width:1180px;margin:0 auto}
    h1{font-size:27px;margin:0 0 6px}
    h2{font-size:20px;margin:34px 0 14px;padding-left:10px;border-left:5px solid var(--blue)}
    h3{font-size:16px;margin:20px 0 8px}
    .sub{color:var(--muted);font-size:13px;margin-bottom:18px;word-break:break-all}
    .panel{background:var(--card);border:1px solid var(--line);border-radius:12px;
           padding:18px 20px;margin-bottom:18px;box-shadow:0 1px 2px rgba(0,0,0,.04)}
    table{border-collapse:collapse;width:100%;font-size:13px}
    th,td{border:1px solid var(--line);padding:7px 9px;text-align:left;vertical-align:top}
    th{background:#eef2f7;font-weight:600;white-space:nowrap}
    td.c,th.c{text-align:center}
    .tag{display:inline-block;padding:2px 9px;border-radius:999px;font-size:12px;font-weight:700}
    .gA{background:#dcfce7;color:#166534}.gB{background:#dbeafe;color:#1e40af}
    .gC{background:#f1f5f9;color:#475569}.gS{background:#ede9fe;color:#5b21b6}
    .ok{background:#dcfce7;color:#166534}.warn{background:#fef3c7;color:#92400e}
    .bad{background:#fee2e2;color:#991b1b}
    .kpi{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px}
    .kpi div{background:#eef6ff;border:1px solid #dbeafe;border-radius:10px;padding:12px 14px}
    .kpi b{display:block;font-size:21px;color:var(--blue);font-variant-numeric:tabular-nums}
    .kpi span{font-size:12px;color:var(--muted)}
    img{max-width:100%;border:1px solid var(--line);border-radius:10px;display:block}
    .mono{font-family:Consolas,monospace;font-size:12px}
    .verdict{background:#ecfdf5;border:1px solid #a7f3d0;border-radius:12px;padding:16px 18px;color:#065f46}
    .risk{background:#fffbeb;border:1px solid #fde68a;border-radius:10px;padding:12px 14px;color:#92400e;font-size:14px}
    ul{margin:8px 0 8px 20px}
    """
    P = []
    A = P.append
    A("<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>")
    A("<title>外部工业视觉数据集审计报告</title><style>{}</style></head><body><div class='wrap'>".format(css))
    A("<h1>外部工业视觉数据集审计报告</h1>")
    A("<div class='sub'>目标：<b>工业箱体上的 4 个大型结构孔视觉识别与机器人自动检测</b>（不是法兰）<br>"
      "项目：<span class='mono'>E:\\robot_inspection</span>　|　生成时间：{}<br>"
      "本阶段只做「搜索 → 筛选 → 小规模下载/抽样 → 审计 → 排名」，<b>未训练任何模型，未改动任何现有数据</b>。</div>".format(NOW))

    # 1
    A("<h2>第一部分　当前任务说明</h2><div class='panel'>")
    A("<p>最终系统流程：目标感知 → 四个大型孔识别 → 孔中心/轮廓提取 → H01/H02/H03/H04 编号 → 指定孔（如“测量 H03”）"
      " → 转换到机器人坐标系 → 机器人移动探头 → 对指定孔做实际尺寸/几何检测。</p>")
    A("<ul><li>当前正式数据集：<span class='mono'>E:\\robot_inspection\\dataset\\box_yolo</span>（25 张 Labelme 图，类别仅 <span class='mono'>0: cylinder_bore</span>）</li>"
      "<li>正式实验划分：<span class='mono'>E:\\robot_inspection\\experiments\\dataset_17_5_3</span>（17 train / 5 val / 3 test）</li>"
      "<li>已完成 5 个随机种子（0/42/123/7/2024）× best/last × 4 张测试图 = 40 组；4/4 检测率 38/40 = 95%；"
      "seed=2024 在测试3 最下方孔为临界漏检（0.455/0.465）</li></ul>")
    A("<div class='kpi'><div><b>{}</b><span>原始检索命中</span></div>"
      "<div><b>{}</b><span>去重后候选</span></div>"
      "<div><b>{}</b><span>深入评估候选</span></div>"
      "<div><b>{}</b><span>Zenodo 可下载命中</span></div></div>".format(
          stats.get("total_raw_hits", "-"), stats.get("unique_hits", "-"), len(ranked), len(zen)))
    A("</div>")

    # 2
    A("<h2>第二部分　候选数据集总排名</h2><div class='panel'><table>")
    A("<tr><th class='c'>排名</th><th>数据集</th><th class='c'>总分</th><th class='c'>等级</th>"
      "<th class='c'>A箱体<br>/25</th><th class='c'>B大孔<br>/25</th><th class='c'>C mask<br>/15</th>"
      "<th class='c'>D场景<br>/10</th><th class='c'>E视角<br>/10</th><th class='c'>F规模<br>/5</th>"
      "<th class='c'>G许可<br>/5</th><th class='c'>H质量<br>/5</th><th>License</th></tr>")
    for i, c in enumerate(ranked, 1):
        s = c["scores"]
        A("<tr><td class='c'>{}</td><td>{}</td><td class='c'><b>{}</b></td>"
          "<td class='c'><span class='tag g{}'>{}</span></td>".format(
              i, html.escape(c["name"]), c["total_score"], c["grade"], c["grade"]))
        for k in ("A", "B", "C", "D", "E", "F", "G", "H"):
            A("<td class='c'>{}</td>".format(s[k]))
        A("<td>{}</td></tr>".format(html.escape(str(c["license"])[:60])))
    A("</table><p class='mono' style='color:#6b7280;margin-top:8px'>"
      "评分体系：A 与工业箱体外观相似度 25 + B 与大型结构孔视觉相似度 25 + C 是否有 segmentation mask 15 + "
      "D 工业机械场景相似度 10 + E 视角/光照变化 10 + F 数据规模 5 + G License 清晰度 5 + H 数据质量 5 = 100。"
      "等级：S 85-100 / A 75-84 / B 60-74 / C &lt;60。</p></div>")

    # 3
    A("<h2>第三部分　每个数据集详细介绍</h2>")
    for i, c in enumerate(ranked, 1):
        A("<div class='panel'><h3>#{}. {}　<span class='tag g{}'>{}</span>　总分 {}</h3>".format(
            i, html.escape(c["name"]), c["grade"], c["grade"], c["total_score"]))
        A("<table>")
        for label, key in [("来源平台", "source"), ("官方页面", "official_url"),
                           ("下载地址", "download_url"), ("是否公开", "public"),
                           ("License", "license"), ("License 状态", "license_status"),
                           ("图片数量", "image_count"), ("是否有 segmentation", "has_segmentation"),
                           ("segmentation 形式", "seg_detail"), ("是否有 bbox", "has_bbox"),
                           ("类别数量", "class_count"), ("类别名称", "classes"),
                           ("是否存在工业箱体", "industrial_box"), ("是否存在机械外壳", "machine_housing"),
                           ("是否存在大型结构孔", "large_hole"), ("是否存在圆孔/通孔/bore", "circular_hole"),
                           ("图像视角", "view"), ("光照情况", "lighting"), ("背景情况", "background"),
                           ("与当前数据视觉相似度", "visual_similarity"),
                           ("适合 transfer learning", "transfer_value"),
                           ("适合直接混入 YOLO-Seg", "mix_value"),
                           ("许可风险", "license_status"), ("获取情况", "access"),
                           ("实测证据", "evidence"), ("备注", "notes")]:
            A("<tr><th style='width:200px'>{}</th><td>{}</td></tr>".format(
                html.escape(label), html.escape(str(c.get(key, "未确认")))))
        A("</table></div>")

    # 4
    A("<h2>第四部分　图片审计</h2><div class='panel'>")
    A("<p>实际抽样情况（本轮因网络速度限制，仅对下列数据集取得真实图像并做视觉审计）：</p>")
    A("<table><tr><th>数据集</th><th>抽样数量</th><th>图像特征（实际观察）</th><th>预览</th></tr>")
    A("<tr><td>Magnetic Tile Defect (MTD)</td><td>12 组原图 + 12 张像素级掩膜</td>"
      "<td>256×256 <b>灰度</b>金属表面，暗场拍摄，白色条纹/斑点为缺陷；有像素级 GT。"
      "与「工业箱体 + 大型孔」外观差异大，属金属表面纹理类。</td>"
      "<td><a href='{}' target='_blank'>preview</a></td></tr>".format(
          rel(AUDIT / "dataset_01_magnetic_tile_defect_sample_preview.jpg", base)))
    A("<tr><td>多个 Kaggle 数据集官方缩略图 + VisA 官方样例图</td><td>9 张官方样例图</td>"
      "<td>实际观察：合成裂缝金属板、PCB 阵列、圆形 GT 掩膜（机加工毛刺）、金属薄板缺陷框、"
      "螺丝、铸造件、焊接件。多数是<b>表面缺陷特写</b>，不是箱体；其中「机加工圆形件 + 环形 GT 掩膜」相对接近。</td>"
      "<td><a href='{}' target='_blank'>preview</a></td></tr>".format(
          rel(AUDIT / "dataset_02_official_samples_preview.jpg", base)))
    A("<tr><td>Container Hole Localization（官方预览图）</td><td>1 张官方论文预览图</td>"
      "<td>实际观察：<b>大型金属集装箱</b> + 角件孔位检测框 + 孔的<b>掩膜与中心点</b>。"
      "这是全部候选中与「大金属箱体 + 孔位定位」主题最接近的一个。</td>"
      "<td><a href='{}' target='_blank'>preview</a></td></tr>".format(
          rel(AUDIT / "dataset_03_container_hole_official_preview.jpg", base)))
    A("</table>")
    A("<h3>未能取得真实样本的数据集（如实记录）</h3><table>"
      "<tr><th>数据集</th><th>原因</th></tr>"
      "<tr><td>Kaggle 上的全部数据集（Screw Defect / Casting / Burr / GC10-DET / DAGM 等）</td>"
      "<td>Kaggle 下载接口需要账号 API 凭据，未认证请求失败 → <b>ACCESS_FAILED</b>（仅取得官方缩略图）</td></tr>"
      "<tr><td>VisA</td><td>直链可达（HTTP 200，1,840.4 MB），但实测速度仅 <b>18.5 KB/s</b>，无法在合理时间取样</td></tr>"
      "<tr><td>MVTec AD / KolektorSDD2</td><td>官网需注册或页面交互下载，本次未取得直链 → <b>ACCESS_FAILED</b></td></tr>"
      "<tr><td>Zenodo（Workpieces / Mechanical Parts / CR7-DET / Sheet Metal）</td>"
      "<td>直链可达（实测 388–620 KB/s），但体积 50–645 MB，本次任务时间内未完成下载（其中 CR7-DET 曾中断）</td></tr>"
      "<tr><td>Roboflow Universe</td><td>搜索页返回 403 → <b>ACCESS_FAILED</b></td></tr>"
      "<tr><td>Hugging Face</td><td>首次 DNS 解析失败，随后恢复（HTTP 200）；BOP/T-LESS 等可下载但未取样</td></tr>"
      "</table>")
    A("<p class='mono' style='color:#6b7280'>说明：上述「未取样」不代表数据无价值，仅表示本次未取得图像证据，"
      "不应据此对该数据集下视觉相似度结论。</p></div>")

    # 5
    A("<h2>第五部分　License 审计</h2><div class='panel'><table>")
    A("<tr><th>数据集</th><th>License</th><th>分类</th><th>科研/竞赛可用</th><th>商用</th><th>风险</th></tr>")
    for c in ranked:
        lic = str(c["license"])
        st = c["license_status"]
        cls = "ok" if st in ("CC BY", "MIT", "Commercial OK") else ("warn" if "Research" in st else "bad")
        research = "是" if "UNCLEAR" not in st and "Unknown" not in st else "需先澄清"
        comm = "是" if st in ("CC BY", "MIT", "Commercial OK") else "否"
        A("<tr><td>{}</td><td>{}</td><td><span class='tag {}'>{}</span></td>"
          "<td>{}</td><td>{}</td><td>{}</td></tr>".format(
              html.escape(c["name"][:60]), html.escape(lic[:70]), cls, html.escape(st),
              research, comm, "许可证不明，默认不可用于项目" if "UNCLEAR" in st or "Unknown" in st else "可接受"))
    A("</table>")
    A("<p><b>许可证明确标记：</b>Container Hole Localization 与 Magnetic Tile Defect 记为 "
      "<span class='tag bad'>LICENSE_UNCLEAR</span>；Roboflow 整体 "
      "<span class='tag bad'>ACCESS_FAILED</span>。未澄清前不应使用其数据训练或分发。</p></div>")

    # 6
    A("<h2>第六部分　Transfer Learning 价值</h2><div class='panel'><table>")
    A("<tr><th>数据集</th><th>backbone 预训练</th><th>检测预训练</th><th>分割迁移</th><th>域适应</th><th>综合</th></tr>")
    rates = {
        "c01": ("中", "中", "中", "高", "主题最近但许可不明"),
        "c02": ("高", "高", "高", "高", "工业零件+mask+多光照，CC BY 4.0"),
        "c03": ("高", "高", "高", "高", "真实工业场景，NC 许可"),
        "c04": ("高", "中", "高", "中", "大规模像素级工业分割，CC BY 4.0"),
        "c05": ("高", "未确认", "未确认", "高", "孔内壁域最接近，标注待审计"),
        "c06": ("高", "中", "高", "中", "经典工业分割基准，NC"),
        "c07": ("中", "低", "中", "低", "缺陷分割，目标无关"),
        "c08": ("中", "低", "中", "低", "低分辨率灰度金属表面"),
        "c09": ("中", "中", "低", "低", "只有 bbox"),
        "c10": ("中", "中", "低", "低", "钢表面缺陷"),
        "c11": ("中", "中", "中", "低", "纹理缺陷"),
        "c12": ("低", "低", "低", "低", "合成数据"),
        "c13": ("低", "低", "低", "低", "数据量过小"),
        "c14": ("低", "低", "低", "低", "仅图像级标签"),
        "c15": ("低", "低", "中", "低", "仅 49 张"),
    }
    for c in ranked:
        r = rates.get(c["id"], ("未确认",) * 5)
        A("<tr><td>{}</td><td class='c'>{}</td><td class='c'>{}</td><td class='c'>{}</td>"
          "<td class='c'>{}</td><td>{}</td></tr>".format(
              html.escape(c["name"][:56]), *[html.escape(x) for x in r]))
    A("</table><p class='mono' style='color:#6b7280'>"
      "注：仅有 bbox 的数据（如 Mechanical Parts）<b>不能直接当成本项目的 YOLO-Seg mask 数据</b>；"
      "它们只能用于 backbone / 检测预训练。</p></div>")

    # 7
    A("<h2>第七部分　直接混合训练价值</h2><div class='panel'><table>")
    A("<tr><th>数据集</th><th>能否直接混入当前 YOLO-Seg 数据</th><th>原因</th></tr>")
    mix = {
        "c01": ("不能", "类别语义为「角件孔位」，且许可证不明"),
        "c02": ("不能直接混", "BOP 为 6D 位姿标注格式，类别体系不同"),
        "c03": ("不能直接混", "同上，且 NC 许可"),
        "c04": ("不能直接混", "异常检测语义（正常/异常），非「孔」实例"),
        "c05": ("待确认", "若为无标注图像，只能做无监督/预训练"),
        "c06": ("不能直接混", "异常检测语义 + NC 许可"),
        "c07": ("不能直接混", "缺陷分割语义 + NC 许可"),
        "c08": ("不能直接混", "缺陷掩膜，非目标孔；分辨率差异大"),
        "c09": ("不能", "只有 bbox，没有 mask"),
        "c10": ("不能", "表面缺陷，非孔"),
        "c11": ("不能", "纹理缺陷"),
        "c12": ("不能", "合成数据，域偏移风险"),
        "c13": ("不能", "数据量过小"),
        "c14": ("不能", "仅图像级标签"),
        "c15": ("不能", "仅 49 张，目标不同"),
    }
    for c in ranked:
        m = mix.get(c["id"], ("未确认", "未确认"))
        A("<tr><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            html.escape(c["name"][:56]), html.escape(m[0]), html.escape(m[1])))
    A("</table><p>结论：<b>目前没有找到任何一个可以直接混入本项目 YOLO-Seg 训练数据的外部数据集</b>。"
      "外部数据的合理用法是「预训练 / 域适应」，而不是直接混合标注。</p></div>")

    # 8
    A("<h2>第八部分　风险</h2><div class='panel'>")
    A("<div class='risk'><b>1) 类别语义风险</b>：所有候选数据集的类别都不是 <span class='mono'>cylinder_bore</span>，"
      "直接混合训练会引入错误标签语义。</div>")
    A("<div class='risk' style='margin-top:10px'><b>2) 数据域偏移风险</b>：外部多为固定机位、受控光照、小尺寸工业件；"
      "本项目是 2592×4608、手持/手机拍摄、含反光内壁与复杂现场背景。域偏移明显。</div>")
    A("<div class='risk' style='margin-top:10px'><b>3) License 风险</b>：MVTec AD / ITODD / KolektorSDD2 为 "
      "CC BY-NC-SA 4.0（非商用）；Container Hole Localization 与 MTD 许可证不明（LICENSE_UNCLEAR）。"
      "若项目涉及竞赛/公开发表，务必先确认许可。</div>")
    A("<div class='risk' style='margin-top:10px'><b>4) 获取风险</b>：Kaggle 类数据集需要凭据；"
      "Roboflow 403；MVTec 需注册；Zenodo 大文件在本机网络下下载耗时很长。本报告已如实标注 ACCESS_FAILED。</div>")
    A("<div class='risk' style='margin-top:10px'><b>5) 证据不足风险</b>：本次只对 1 个数据集（MTD）完成了真实样本审计，"
      "其余为官方缩略图/元数据级证据；因此视觉相似度评分带有不确定性。</div>")
    A("</div>")

    # 9
    A("<h2>第九部分　最终推荐 Top 3</h2><div class='panel'>")
    top = ranked[:3]
    for i, c in enumerate(top, 1):
        A("<h3>Top {}：{}　（总分 {}，{} 级）</h3>".format(i, html.escape(c["name"]),
                                                          c["total_score"], c["grade"]))
        A("<ul><li>主要价值：{}</li><li>License：{}</li><li>获取：{}</li>"
          "<li>注意：{}</li></ul>".format(
              html.escape(c["transfer_value"]), html.escape(c["license"]),
              html.escape(c["access"]), html.escape(c["notes"])))
    A("<div class='verdict' style='margin-top:14px'><b>推荐结论：推荐继续（有条件）</b><br>"
      "外部数据对本项目的价值主要在「工业金属结构 / 像素级分割 / 孔内壁域」的<b>预训练与域适应</b>，"
      "而不是直接混合标注。当前 5 个 seed 的 4/4 率 95%、目标孔 confidence 最低 0.6233，"
      "问题集中在「反光内壁置信度」与「个别临界漏检」，属于数据多样性不足，而不是模型容量不足。</div>")
    A("<p><b>建议的下一步实验（本阶段不执行）：</b></p><ul>"
      "<li>Experiment A：当前数据训练 baseline（已有，可直接复用 5 个 seed 结果）</li>"
      "<li>Experiment B：external pretrain → 当前数据 fine-tune（推荐先做：先用 T-LESS / VisA 做通用工业分割预训练，"
      "再用 17/5/3 微调）</li>"
      "<li>Experiment C：external + current data mixed training（风险最高，类别语义不一致，暂不推荐）</li></ul>")
    A("</div>")

    # 8 questions
    A("<h2>附：必须回答的 8 个问题</h2><div class='panel'><table>")
    qa = [
        ("Q1 有没有真正适合「工业箱体」的公开数据集？",
         "有 1 个主题接近的：<b>Container Hole Localization</b>（大型金属集装箱 + 角件孔位 + 孔掩膜/中心点），"
         "但其许可证不明、数据托管在 Google Drive 未验证；其余候选都是「工业零件特写 / 表面缺陷」，不是箱体。"),
        ("Q2 有没有适合「大型结构孔 / through hole / bore」的公开数据集？",
         "没有找到以「大型结构孔」为类别的公开数据集。最接近的是 Container Hole Localization（角件孔位）、"
         "T-LESS / ITODD（工业零件上的圆柱孔结构）、以及 Workpieces image dataset（用工业内窥镜拍摄工件内孔内壁）。"),
        ("Q3 哪个数据集和我的视觉场景最像？",
         "主题最像：<b>Container Hole Localization</b>（大金属箱体 + 孔 + 中心）。"
         "域（孔内壁 + 工业照明）最像：<b>Workpieces image dataset</b>（工业内窥镜拍机加工件内表面）。"),
        ("Q4 哪个最适合 external pretrain → my dataset fine-tune？",
         "<b>T-LESS（CC BY 4.0）</b>：工业无纹理零件、含孔/圆柱结构、带 2D binary mask、视角与光照多样，许可最清晰。"
         "其次 VisA（CC BY 4.0，10,821 张像素级工业分割）。"),
        ("Q5 哪个最适合直接加入我的训练数据？",
         "<b>没有</b>。所有候选的类别语义、标注形式或图像域都与 cylinder_bore 不一致；"
         "bbox-only 数据（如 Mechanical Parts）尤其不能当作分割 mask 使用。"),
        ("Q6 是否真的值得加入外部数据？",
         "有条件值得：作为<b>预训练 / 域适应</b>使用值得；作为<b>直接混合标注</b>不值得。"
         "当前主要瓶颈是数据多样性（反光内壁、临界漏检），外部工业数据在理论上可缓解。"),
        ("Q7 加入外部数据最可能改善哪几项？",
         "按证据强弱排序：<b>F mask 边界</b>（外部有大量像素级掩膜）＞ <b>D 反光</b>（T-LESS/ITODD 多光照金属件）"
         "＞ <b>C 视角变化</b>（BOP/多视角数据）＞ <b>E 背景变化</b>；"
         "对 <b>A 漏检</b> 和 <b>B 低置信度</b> 的改善最不确定，因为外部数据没有相同的大孔结构。"),
        ("Q8 有没有明显的数据域偏移风险？",
         "<b>有，且明显</b>：外部数据多为受控机位、小尺寸工业件、灰度或低分辨率；本项目是 2592×4608 手持拍摄、"
         "含反光内壁与复杂现场背景。直接混合会引入域偏移；建议只用于预训练，并保留原数据微调。"),
    ]
    for q, a in qa:
        A("<tr><th style='width:330px'>{}</th><td>{}</td></tr>".format(html.escape(q), a))
    A("</table></div>")

    A("<p class='sub'>本报告所有数据集信息均来自实际抓取的官方页面 / 平台 API / 实际下载文件；"
      "无法确认的字段写“未确认”，无法获取的写 ACCESS_FAILED，许可证不明写 LICENSE_UNCLEAR。"
      "未训练任何模型，未修改 <span class='mono'>dataset\\box_yolo</span>、<span class='mono'>weights\\best.pt</span>、"
      "<span class='mono'>test_images</span>、<span class='mono'>runs</span>、<span class='mono'>experiments</span>。</p>")
    A("</div></body></html>")

    out = REPORTS / "external_dataset_audit.html"
    out.write_text("\n".join(P), encoding="utf-8")
    print("[OK]", out)

    # ---------------- README ----------------
    readme = [
        "# external_datasets　外部数据集审计工作区",
        "",
        "> 目标：为「工业箱体 4 个大型结构孔的视觉识别与机器人自动检测」寻找可迁移的外部公开数据。",
        "> 本目录**只做搜索 / 抽样 / 审计 / 排名**，不参与训练，不影响主项目数据。",
        "",
        "## 目录说明",
        "",
        "| 路径 | 内容 |",
        "| --- | --- |",
        "| `candidates.csv` / `candidates.json` | 15 个候选数据集的完整字段与评分（22 字段） |",
        "| `reports/external_dataset_audit.html` | **最终审计报告（九段式）** |",
        "| `reports/dataset_*_audit.html` | 各抽样数据集的单集审计报告 |",
        "| `audit/*_preview.jpg` | 抽样 contact sheet（画 mask/bbox） |",
        "| `samples/official_thumbnails/` | 各数据集官方样例图 |",
        "| `dataset_01_magnetic_tile_defect_sample/` | MTD 真实样本（12 原图 + 12 像素级掩膜） |",
        "| `dataset_02_official_samples/` | Kaggle 官方缩略图 + VisA 官方样例图 |",
        "| `dataset_03_container_hole_official/` | 集装箱孔位数据集仓库内容（README + 官方预览图） |",
        "| `metadata/raw/` | 各平台 API 原始返回（证据留档） |",
        "| `metadata/checksums.txt` | 实际下载文件的 sha256 与来源 |",
        "| `best_candidate/` | 最优候选的说明与后续建议 |",
        "",
        "## 关键结论",
        "",
        "1. **没有**公开数据集直接把「工业箱体上的大型结构孔」作为类别。",
        "2. 主题最接近的是 Container Hole Localization（大金属箱体 + 孔 + 中心点），但其 **LICENSE_UNCLEAR**、数据在 Google Drive 未验证。",
        "3. 许可最清晰、最适合预训练的是 **T-LESS（CC BY 4.0，工业零件 + mask）** 与 **VisA（CC BY 4.0，10,821 张像素级工业分割）**。",
        "4. 域最接近的是 **Workpieces image dataset**（工业内窥镜拍机加工件内孔内壁，CC BY 4.0）。",
        "5. **目前没有任何外部数据可以直接混入本项目的 YOLO-Seg 标注**。",
        "",
        "## 平台可达性（实测）",
        "",
    ]
    for k, v in reach.items():
        readme.append("- {}：{}".format(k, v))
    readme += ["",
               "## 重要提醒",
               "",
               "- `LICENSE_UNCLEAR` 的数据在许可证澄清前不要用于训练或分发；",
               "- Kaggle 类数据集需要账号凭据，本次为 `ACCESS_FAILED`，仅取得官方缩略图；",
               "- 仅有 bbox 的数据**不能**当作 YOLO-Seg 的 mask 数据；",
               "- 本目录不修改主项目任何文件。",
               ""]
    (EXT / "README.md").write_text("\n".join(readme), encoding="utf-8")
    print("[OK]", EXT / "README.md")

    best = EXT / "best_candidate"
    best.mkdir(parents=True, exist_ok=True)
    b = ranked[0]
    (best / "README.md").write_text("\n".join([
        "# 最优候选：{}".format(b["name"]),
        "",
        "- 总分：**{} / 100**（{} 级）".format(b["total_score"], b["grade"]),
        "- 官方页面：{}".format(b["official_url"]),
        "- 下载地址：{}".format(b["download_url"]),
        "- License：**{}**".format(b["license"]),
        "- 图片数量：{}".format(b["image_count"]),
        "- 类别：{}".format(b["classes"]),
        "",
        "## 为什么选它",
        "",
        b["notes"],
        "",
        "## 可能对本项目有帮助的部分",
        "",
        "- 大型金属箱体外观与工业现场背景；",
        "- 孔位检测框 + 孔掩膜 + 孔中心点（与 H01~H04 的中心定位流程一致）；",
        "",
        "## 不建议使用的部分",
        "",
        "- 与「角件」无关的类别；",
        "- **在许可证澄清之前，任何部分都不建议用于训练或再分发**。",
        "",
        "## 建议下一步",
        "",
        "1. 先联系仓库作者澄清 License（这是能否使用的先决条件）；",
        "2. 若许可允许：走 **external pretrain → 本项目 17/5/3 fine-tune**；",
        "3. 不建议 `external + current` 直接混合训练（类别语义不一致）。",
        "",
        "> 备选（许可更清晰）：T-LESS（CC BY 4.0）与 VisA（CC BY 4.0）更适合直接开始预训练实验。",
        "",
    ]), encoding="utf-8")
    print("[OK]", best / "README.md")
    return 0


if __name__ == "__main__":
    main()
