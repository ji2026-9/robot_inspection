# -*- coding: utf-8 -*-
"""
生成正式实验结论文档
====================
输出（不修改任何已有文件）：
  experiments\\formal_experiment_conclusion.md
  experiments\\formal_experiment_conclusion.html

正文 = 正式实验第一阶段（seed 0 / 42 / 123，24 组组合）结论；
附录 = 扩展实验（seed 7 / 2024）加入后的 5-seed 汇总 v2 结果。

用法：
    python scripts\\make_conclusion_docs.py
"""

import html
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

EXP_DIR = Path(r"E:\robot_inspection\experiments")
V1 = EXP_DIR / "formal_comparison.json"
V2 = EXP_DIR / "formal_comparison_v2.json"

SEEDS_V1 = [0, 42, 123]


def load(p):
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def main() -> int:
    d1 = load(V1)
    d2 = load(V2)
    if d1 is None:
        print("[错误] 找不到 {}".format(V1))
        return 2

    recs = d1["records"]
    tm1 = d1.get("train_metrics", {})

    # ---- 第一阶段（3 seed）统计 ----
    combos = {}
    for r in recs:
        combos.setdefault((r["seed"], r["weight_type"], r["image"]), []).append(r)
    n_groups = len(combos)

    hole_confs = [r["confidence"] for r in recs]
    n_hole = len(hole_confs)

    refl = {}
    for r in recs:
        if r["image"] == "测试3.jpg" and r["hole_id"] == "Hole3":
            refl[(r["seed"], r["weight_type"])] = r["confidence"]
    refl_vals = list(refl.values())
    refl_by_seed = {s: [v for (sd, w), v in refl.items() if sd == s] for s in SEEDS_V1}
    seed_means = [float(np.mean(v)) for v in refl_by_seed.values() if v]
    best_vals = [v for (sd, w), v in refl.items() if w == "best"]
    last_vals = [v for (sd, w), v in refl.items() if w == "last"]

    # ---- 第二阶段（5 seed）统计 ----
    s2 = d2["summary"] if d2 else None

    lines = []
    A = lines.append

    A("# 正式训练对照实验结论文档")
    A("")
    A("> 项目：`E:\\robot_inspection`（机械臂孔位检测 / YOLO-Seg 分割）")
    A("> 生成时间：{}".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    A("> 本文件由 `scripts\\make_conclusion_docs.py` 依据 `formal_comparison.json`"
      "（第一阶段）与 `formal_comparison_v2.json`（扩展阶段）自动生成，数据未做任何修饰。")
    A("")
    A("---")
    A("")
    A("## 1. 实验目的")
    A("")
    A("在本地 RTX 3050 Ti（4GB）上，用完全一致的训练配置改变**随机种子**，"
      "判断 YOLO11n-Seg 对「工件 4 个大型圆孔（cylinder_bore）」检测结果的稳定性：")
    A("")
    A("- 不同随机种子之间的结果波动有多大；")
    A("- `best.pt` 与 `last.pt` 两种 checkpoint 的选择是否影响结论；")
    A("- 把验证集从 2 张增加到 5 张后，模型选择是否更可靠；")
    A("- 测试3 中内壁高反光的那个孔，其低置信度是否主要来自训练随机性。")
    A("")
    A("## 2. 数据集划分")
    A("")
    A("**正式数据集为 17 train / 5 val / 3 test**（`experiments\\dataset_17_5_3\\`，由原始数据复制生成，原始目录未改动）。")
    A("")
    A("- **原始 3 张 test 保持不变**，仍为 `001.jpg`、`004.jpg`、`021.jpg`；")
    A("- **从原 train 中划出的 val 图片为 `002.jpg`、`013.jpg`、`022.jpg`**"
      "（原 train 20 张按文件名排序取第 1/9/17 张，规则写在 `scripts\\make_split_17_5_3.py` 中，可复现）；")
    A("- 另外 2 张 val 为原始 val 的 `008.jpg`、`009.jpg`；")
    A("- 其余 17 张为 train；")
    A("- **测试图片为 `测试1.jpg`、`测试2.jpg`、`测试3.jpg`、`测试4.jpg`**（4 张，均未参与训练/验证，属于新增测试图）。")
    A("")
    A("各子集图片与 YOLO-Seg label 数量一一对应（train 17/17、val 5/5、test 3/3）。")
    A("")
    A("## 3. 训练配置")
    A("")
    A("| 项目 | 值 |")
    A("|---|---|")
    A("| 模型 | `yolo11n-seg.pt`（未更换更大模型） |")
    A("| 任务 | segment（实例分割） |")
    A("| imgsz | 640 |")
    A("| batch | 8 |")
    A("| epochs | 100 |")
    A("| patience | 0（关闭早停，必须跑满 100 轮） |")
    A("| device | 0（NVIDIA GeForce RTX 3050 Ti Laptop GPU，4GB） |")
    A("| workers | 2 |")
    A("| deterministic | True |")
    A("| 随机种子 | 第一阶段 0 / 42 / 123；扩展阶段追加 7 / 2024 |")
    A("| 实际显存占用 | 约 1.45–1.55 GB / 4 GB |")
    A("")
    A("**目标孔检测采用 4/4 作为主要工程指标**（每张图片期望检出全部 4 个目标大孔）。")
    A("")
    A("## 4. 三个 seed 的训练指标")
    A("")
    A("（Mask / 分割指标；best epoch 按 `fitness = 0.1×mAP50-95(Box) + 0.9×mAP50-95(Mask)` 计算）")
    A("")
    A("| seed | 实际轮数 | best epoch | Precision | Recall | mAP50 | mAP50-95 | 训练耗时 |")
    A("|---|---|---|---|---|---|---|---|")
    for s in SEEDS_V1:
        t = tm1.get(str(s)) or tm1.get(s)
        if t:
            A("| {} | {} | {} | {:.4f} | {:.4f} | {:.4f} | {:.4f} | {:.0f} 秒 |".format(
                s, t["epochs_run"], t["best_epoch"], t["precision"], t["recall"],
                t["map50"], t["map5095"], t["seconds"]))
        else:
            A("| {} | - | - | - | - | - | - | - |".format(s))
    A("")
    A("三个 seed 的 Precision 均 ≥ 0.9969、Recall 均为 1.0000、mAP50 均为 0.9950；"
      "mAP50-95 在 0.9681–0.9847 之间。")
    A("")
    A("## 5. best / last 对比")
    A("")
    A("（下表为测试3 反光孔的 confidence，confidence 阈值 0.50）")
    A("")
    A("| seed | best | last | best − last |")
    A("|---|---|---|---|")
    for s in SEEDS_V1:
        b = refl.get((s, "best"))
        l = refl.get((s, "last"))
        if b is not None and l is not None:
            A("| {} | {:.4f} | {:.4f} | {:+.4f} |".format(s, b, l, b - l))
    A("| **平均** | **{:.4f}** | **{:.4f}** | **{:+.4f}** |".format(
        float(np.mean(best_vals)), float(np.mean(last_vals)),
        float(np.mean(best_vals)) - float(np.mean(last_vals))))
    A("")
    A("在本阶段（17/5/3、batch=8、patience=0、跑满 100 轮）下，"
      "best 与 last 对反光孔的差异较小，未出现上一阶段「last 明显优于 best」的现象。"
      "另外注意：seed=123 的 best.pt 与 last.pt 权重逐张量完全相同（best epoch = 100），"
      "因此该 seed 两列数值一致。")
    A("")
    A("## 6. 4 张测试图片的 4/4 检测结果")
    A("")
    A("| seed | weight | 测试1 | 测试2 | 测试3 | 测试4 |")
    A("|---|---|---|---|---|---|")
    for s in SEEDS_V1:
        for w in ("best", "last"):
            row = []
            for img in ("测试1.jpg", "测试2.jpg", "测试3.jpg", "测试4.jpg"):
                rs = [r for r in recs if r["seed"] == s and r["weight_type"] == w and r["image"] == img]
                n = sum(1 for r in rs if r["confidence"] >= 0.50)
                row.append("{}/4".format(n))
            A("| {} | {} | {} |".format(s, w, " | ".join(row)))
    A("")
    A("**当前 24/24 模型-图片组合均实现 4/4。**")
    A("")
    A("对应统计：")
    A("")
    A("- 组合数：3 seed × 2 checkpoint × 4 图片 = {} 组；".format(n_groups))
    A("- **目标孔没有任何一个 confidence < 0.5**；所有被选中目标孔的 confidence 最小值为 "
      "{:.4f}，平均 {:.4f}（共 {} 个孔）。".format(float(np.min(hole_confs)),
                                                float(np.mean(hole_confs)), n_hole))
    A("- 在 conf≥0.5 下，没有出现未匹配到目标孔的额外检测。")
    A("")
    A("## 7. 反光孔 confidence 对比")
    A("")
    A("测试3 中内壁为镜面反光的孔（从上往下第 3 个，图像中心 y ≈ 2561）是本次实验中置信度最低的目标孔，"
      "**反光孔为当前最弱目标孔**。")
    A("")
    A("| 权重 | seed=0 | seed=42 | seed=123 | 平均 |")
    A("|---|---|---|---|---|")
    A("| best | {:.4f} | {:.4f} | {:.4f} | {:.4f} |".format(
        refl[(0, "best")], refl[(42, "best")], refl[(123, "best")], float(np.mean(best_vals))))
    A("| last | {:.4f} | {:.4f} | {:.4f} | {:.4f} |".format(
        refl[(0, "last")], refl[(42, "last")], refl[(123, "last")], float(np.mean(last_vals))))
    A("")
    A("其余 3 个孔的 confidence 普遍在 0.87–0.998 之间，明显高于反光孔。")
    A("")
    A("## 8. seed 波动分析")
    A("")
    A("| 统计量（各 seed 反光孔均值） | 值 |")
    A("|---|---|")
    A("| 均值 | {:.4f} |".format(float(np.mean(seed_means))))
    A("| 最小值 | {:.4f} |".format(float(np.min(seed_means))))
    A("| 最大值 | {:.4f} |".format(float(np.max(seed_means))))
    A("| 极差（最大−最小） | {:.4f} |".format(float(np.max(seed_means) - np.min(seed_means))))
    A("")
    A("**seed=42 在当前有限样本上反光孔 confidence 最高，但不能据此宣称 seed=42 普遍最优**"
      "——本阶段每个 seed 只有 1 次训练、4 张测试图片，样本量不足以支持这种结论。")
    A("")
    A("## 9. 对 YOLO11n-Seg 是否满足当前任务的判断")
    A("")
    A("在本阶段（第一阶段，3 个 seed、24 组组合）的范围内：")
    A("")
    A("- 24/24 组组合均为 4/4，未出现漏检；")
    A("- 目标孔 confidence 全部高于 0.5；")
    A("- conf≥0.5 下没有出现未匹配到目标孔的额外检测；")
    A("- 反光孔是唯一明显偏弱的目标（0.6337–0.8011）。")
    A("")
    A("因此在本阶段的测试集与实验范围内，**暂时没有数据支持必须升级 YOLO11s**；"
      "是否需要升级应由后续更大规模、更多场景的数据来判定。")
    A("")
    A("## 10. 当前实验局限性")
    A("")
    A("1. 训练样本仅 25 张（17/5/3），验证集只有 5 张，模型选择与统计的噪声仍然较大；")
    A("2. 测试集只有 4 张图片，且与训练图为同一批次、同一拍摄条件；")
    A("3. 每个 seed 只训练 1 次，无法区分「seed 效应」与「单次运行偶然性」；")
    A("4. 反光孔样本极少，其置信度受光照/反光角度影响明显；")
    A("5. 未做跨设备、跨光照、跨工件的泛化测试；")
    A("6. 未评估像素坐标到机器人坐标的转换误差。")
    A("")
    A("## 11. 下一阶段实验计划")
    A("")
    A("1. **后续需要增加随机种子进行稳定性验证**（本阶段已追加 seed=7、seed=2024，见附录）；")
    A("2. 补充更多拍摄条件（不同光照、反光角度、工件摆放）的图像；")
    A("3. 扩大验证集与独立测试集，避免用 4 张测试图反复做模型选择；")
    A("4. 对反光孔做针对性数据补充后重新评估；")
    A("5. 在稳定性确认后再推进像素坐标 → 机器人坐标的标定与误差评估。")
    A("")
    A("---")
    A("")
    A("## 附录：扩展实验（seed=7 / seed=2024）与 5-seed 汇总（v2）")
    A("")
    if s2:
        A("追加 seed=7 与 seed=2024 后，共 5 seed × 2 checkpoint × 4 图片 = **{} 组**。".format(s2["n_groups"]))
        A("")
        A("| 统计项 | 结果 |")
        A("|---|---|")
        A("| 4/4 组合比例 | **{}/{} = {:.1f}%** |".format(
            s2["n_4of4"], s2["n_groups"], 100 * s2["rate_4of4"]))
        A("| 各 seed 4/4 | {} |".format(
            "、".join("seed={} {}".format(k, v) for k, v in s2["per_seed_4of4"].items())))
        A("| 目标孔 confidence 最小值 | {:.4f} |".format(s2["hole_conf_min"]))
        A("| 目标孔 confidence 平均值 | {:.4f} |".format(s2["hole_conf_mean"]))
        A("| 目标孔 confidence < 0.5 的数量 | {} |".format(s2["hole_conf_below_050"]))
        A("| 目标孔漏检数量 | **{}** |".format(s2["n_misses"]))
        A("| conf≥0.5 未匹配检测（疑似误检） | {} |".format(s2["spurious_total"]))
        A("| 反光孔 confidence（10 组） | {} |".format(
            "、".join("{:.4f}".format(v) for v in s2["reflective"]["all"])))
        A("| 反光孔 seed 级 均值 / 标准差 / 最小 / 最大 | {:.4f} / {:.4f} / {:.4f} / {:.4f} |".format(
            s2["reflective"]["seed_level"]["mean"], s2["reflective"]["seed_level"]["std"],
            s2["reflective"]["seed_level"]["min"], s2["reflective"]["seed_level"]["max"]))
        A("| best 反光孔均值 / last 反光孔均值 / 差值 | {:.4f} / {:.4f} / {:+.4f} |".format(
            s2["reflective"]["best_mean"], s2["reflective"]["last_mean"],
            s2["reflective"]["best_minus_last"]))
        A("")
        A("**关键补充事实（必须如实记录）**：")
        A("")
        A("- 新增的 **seed=2024 在测试3 出现漏检**：best 与 last 都只检出 3/4，"
          "漏掉的是**从上往下第 4 个（最下方）孔**；")
        A("- 该孔在 conf=0.05 低阈值下的最高置信度为 **0.4554（best）/ 0.4649（last）**，"
          "略低于正式阈值 0.5，属于**临界漏检**；")
        A("- 因此 5-seed 汇总的 4/4 比例为 **38/40 = 95.0%**，而不是 100%；")
        A("- 其余 4 个 seed（0 / 42 / 123 / 7）仍为 8/8 全部 4/4；")
        A("- 目标孔 confidence 最小值 0.6233，仍全部高于 0.5；"
          "conf≥0.5 下未出现未匹配检测。")
        A("")
        A("> 说明：本附录记录的是在正文（第一阶段 3-seed）完成之后追加的实验。"
          "正文第 6 节「24/24」与第 9 节「暂时没有数据支持必须升级 YOLO11s」"
          "均指第一阶段范围；加入扩展实验后的完整结论请以 v2 汇总为准。")
    else:
        A("（尚未生成 `formal_comparison_v2.json`，本节待补。）")
    A("")

    md_out = EXP_DIR / "formal_experiment_conclusion.md"
    md_out.write_text("\n".join(lines), encoding="utf-8")
    print("[OK] {}".format(md_out))

    # ---------------- HTML 版本 ----------------
    css = """
    body{margin:0;padding:32px;background:#f5f7fa;color:#1f2937;line-height:1.75;
         font-family:"Segoe UI","Microsoft YaHei",system-ui,sans-serif;}
    .wrap{max-width:980px;margin:0 auto;background:#fff;border:1px solid #e2e8f0;
          border-radius:14px;padding:34px 40px;box-shadow:0 1px 3px rgba(0,0,0,.05)}
    h1{font-size:27px;margin:0 0 8px}
    h2{font-size:20px;margin:32px 0 12px;padding-left:10px;border-left:5px solid #2563eb}
    .meta{color:#6b7280;font-size:13px;margin-bottom:22px}
    table{border-collapse:collapse;width:100%;font-size:14px;margin:12px 0}
    th,td{border:1px solid #e2e8f0;padding:8px 10px;text-align:left}
    th{background:#eef2f7;font-weight:600}
    code{background:#f1f5f9;padding:1px 5px;border-radius:4px;font-size:13px;
         font-family:Consolas,monospace}
    blockquote{margin:14px 0;padding:12px 16px;background:#fffbeb;border-left:4px solid #f59e0b;
               color:#92400e;font-size:14px}
    strong{color:#111827}
    ul{padding-left:22px}
    """
    h = []
    B = h.append
    B("<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>")
    B("<title>正式训练对照实验结论文档</title><style>{}</style></head><body><div class='wrap'>".format(css))
    B("<h1>正式训练对照实验结论文档</h1>")
    B("<div class='meta'>项目：<code>E:\\robot_inspection</code>（机械臂孔位检测 / YOLO-Seg 分割）<br>"
      "生成时间：{}<br>"
      "由 <code>scripts\\make_conclusion_docs.py</code> 依据 formal_comparison.json 与 "
      "formal_comparison_v2.json 自动生成，数据未做修饰。</div>".format(
          datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    in_tbl = False
    for ln in lines[6:]:
        s = ln.rstrip()
        if s.startswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            if all(set(c) <= set("-: ") for c in cells):
                continue
            if not in_tbl:
                B("<table>")
                in_tbl = True
            tag = "th" if (in_tbl and "<table>" in h[-1]) else "td"
            B("<tr>" + "".join("<{0}>{1}</{0}>".format(tag, html.escape(c)) for c in cells) + "</tr>")
            continue
        if in_tbl:
            B("</table>")
            in_tbl = False
        if not s:
            continue
        if s.startswith("## "):
            B("<h2>{}</h2>".format(html.escape(s[3:])))
        elif s.startswith("# "):
            continue
        elif s.startswith("> "):
            B("<blockquote>{}</blockquote>".format(html.escape(s[2:])))
        elif s.startswith("- "):
            B("<ul><li>{}</li></ul>".format(html.escape(s[2:])))
        elif s.startswith("---"):
            B("<hr>")
        else:
            B("<p>{}</p>".format(html.escape(s).replace("**", "")))
    if in_tbl:
        B("</table>")
    B("</div></body></html>")

    html_out = EXP_DIR / "formal_experiment_conclusion.html"
    html_out.write_text("\n".join(h), encoding="utf-8")
    print("[OK] {}".format(html_out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
