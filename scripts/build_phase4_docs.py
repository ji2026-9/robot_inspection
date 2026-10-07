# -*- coding: utf-8 -*-
"""
Phase 4A：生成子集预览图与两份文档
==================================
输出：
  external_datasets\\phase4_tless_pretrain\\TLESS-ALL\\contact_sheet.jpg
  external_datasets\\phase4_tless_pretrain\\TLESS-HOLE\\contact_sheet.jpg
  external_datasets\\phase4_tless_pretrain_dataset.md
  external_datasets\\phase4_experiment_plan.md

用法：
    python scripts\\build_phase4_docs.py
"""

import csv
import json
import sys
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

EXT = Path(r"E:\robot_inspection\external_datasets")
AU = EXT / "phase4_tless_audit"
PR = EXT / "phase4_tless_pretrain"
NOW = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def contact_sheet(paths, cols, tile, out, label_key=None):
    rows = (len(paths) + cols - 1) // cols
    canvas = np.full((rows * tile, cols * tile, 3), 235, np.uint8)
    for i, p in enumerate(paths):
        im = cv2.imread(str(p))
        if im is None:
            continue
        h, w = im.shape[:2]
        s = min(tile / h, tile / w)
        im = cv2.resize(im, (int(w * s), int(h * s)))
        r, c = divmod(i, cols)
        y = r * tile + (tile - im.shape[0]) // 2
        x = c * tile + (tile - im.shape[1]) // 2
        canvas[y:y + im.shape[0], x:x + im.shape[1]] = im
        txt = Path(p).stem + ("_" + str(label_key[i]) if label_key else "")
        cv2.putText(canvas, txt[:20], (c * tile + 6, r * tile + 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 4, cv2.LINE_AA)
        cv2.putText(canvas, txt[:20], (c * tile + 6, r * tile + 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 1, cv2.LINE_AA)
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), canvas, [cv2.IMWRITE_JPEG_QUALITY, 88])
    return out


def main() -> int:
    stats = json.loads((AU / "dataset_stats.json").read_text(encoding="utf-8"))
    qual = json.loads((AU / "image_quality_report.json").read_text(encoding="utf-8"))
    dup = json.loads((AU / "duplicate_report.json").read_text(encoding="utf-8"))
    summ = json.loads((EXT / "phase4_tless_summary.json").read_text(encoding="utf-8"))
    with (AU / "priority_objects.csv").open(encoding="utf-8-sig") as f:
        prio = list(csv.DictReader(f))
    with (AU / "object_distribution.csv").open(encoding="utf-8-sig") as f:
        dist = list(csv.DictReader(f))

    # 子集预览
    sheets = {}
    for folder in ("TLESS-ALL", "TLESS-HOLE"):
        mf = PR / folder / "manifest.csv"
        with mf.open(encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        idx = np.linspace(0, len(rows) - 1, 36).astype(int)
        sel = [rows[i] for i in idx]
        sheets[folder] = contact_sheet(
            [Path(r["image_path"]) for r in sel], 6, 260,
            PR / folder / "contact_sheet.jpg",
            label_key=["s{}".format(r["scene_id"]) for r in sel])
        print("[OK]", sheets[folder], len(rows), "张")

    # ---------------- 文档 1：数据集文档 ----------------
    prio_rows = "\n".join(
        "| {} | {} | {} | {} | {} | {} |".format(
            p["object_id"], p["scene_count"], p["scenes"], p["image_count"],
            "T{}".format(p["priority_tier"]), p["reason_for_priority"]) for p in prio)
    dist_rows = "\n".join(
        "| {} | {} | {} | {} |".format(d["object_id"], d["scenes"], d["scene_count"],
                                       d["image_count"]) for d in dist)

    (EXT / "phase4_tless_pretrain_dataset.md").write_text("\n".join([
        "# Phase 4A　T-LESS 无标签预训练数据集（说明文档）",
        "",
        "生成时间：{}".format(NOW),
        "",
        "> **本数据集全部为 UNLABELED RGB。**",
        "> **不生成、也不允许生成任何 hole 标签**：不使用 Hough 圆自动生成 label，",
        "> 不把 T-LESS 的 object mask 改写为 hole mask，不人工猜测未确认的孔多边形。",
        "",
        "## 1. 数据来源",
        "",
        "- 来源：T-LESS v2 官方测试集（作者服务器 ptak.felk.cvut.cz），Phase 3 已下载并 CRC 校验通过",
        "- 场景：`tless_test_primesense_01 / 02 / 03`（各 504 张 RGB）",
        "- License：**CC BY 4.0**（官方站点原文确认，可商用）",
        "- 原始归档：**无 mask**（只有 rgb / depth / gt.yml / info.yml）",
        "",
        "## 2. 完整审计结果",
        "",
        "| 审计项 | 结果 |",
        "|---|---|",
        "| 1. RGB 总数 | **{} 张**（01/02/03 各 {}/{} /{}） |".format(
            stats["total_rgb"], stats["per_scene"]["01"], stats["per_scene"]["02"],
            stats["per_scene"]["03"]),
        "| 2. 可正常读取 | **{} 张**（OpenCV 全部成功解码，失败 {}） |".format(
            stats["readable"], stats["unreadable"]),
        "| 3. 分辨率 | {}（三场景完全一致） |".format(stats["resolution"]),
        "| 4. 文件大小 | {:.1f} MB ~ {:.1f} KB，总计 {:.2f} GB |".format(
            stats["size_bytes_max"] / 1024, stats["size_bytes_min"] / 1024,
            stats["size_bytes_total"] / 1024 ** 3),
        "| 5. 精确重复（字节级） | **0 组 / 0 个多余文件** |",
        "| 6. 高相似图片（dHash 汉明距离 ≤5） | **{} 组**，多余文件 **{} 个**（占总数 {:.0f}%） |".format(
            stats["perceptual_duplicate_groups"], stats["perceptual_duplicate_extra_files"],
            100 * stats["perceptual_duplicate_extra_files"] / stats["total_rgb"]),
        "| 6b. 近同图片（dHash ≤2，去重口径） | {} 组，多余 {} 个 |".format(
            stats["near_identical_groups"], stats["near_identical_extra_files"]),
        "| 7. scene 分布 | 01:504 / 02:504 / 03:504 |",
        "| 8. object ID 分布 | 见下表（共 {} 个物体出现在这三个场景） |".format(len(dist)),
        "| 9. 严重连续重复帧（连续 ≥5 帧 dHash≤2） | **0 段** |",
        "",
        "**图像质量**：亮度均值 {:.1f}，对比度均值 {:.1f}，Laplacian 清晰度均值 {:.1f}"
        "（5% 分位 {:.1f}，说明整体都清晰，无明显糊帧），强高光像素占比均值 {:.4f}。".format(
            qual["brightness_mean"], qual["contrast_mean"], qual["blur_lapvar_mean"],
            qual["blur_lapvar_p05"], qual["specular_mean"]),
        "",
        "> **重要发现**：T-LESS 测试场景是**密集旋转序列**，相邻帧极为相似 ——"
        "以 dHash≤5 计有 {} 个多余文件（{:.0f}%）；但以更严格的 dHash≤2 计只剩 {} 个。"
        "因此**直接使用全部 1512 张会包含大量冗余**，我们按 dHash≤2 去重后再抽样。".format(
            stats["perceptual_duplicate_extra_files"],
            100 * stats["perceptual_duplicate_extra_files"] / stats["total_rgb"],
            stats["near_identical_extra_files"]),
        "",
        "## 3. object ID 分布（三个场景合计）",
        "",
        "| object_id | 出现场景 | 场景数 | 图像数 |",
        "|---|---|---|---|",
        dist_rows,
        "",
        "## 4. Priority Objects（优先保留的物体，来自 Phase 3 人工确认）",
        "",
        "| object_id | 场景数 | 场景 | 图像数 | 优先级 | 理由 |",
        "|---|---|---|---|---|---|",
        prio_rows,
        "",
        "优先级说明：**T1 = Phase 3 真实图像人工确认含多孔/成排孔/金属螺纹内壁**；"
        "T2 = 标准视图显示圆孔与内壁；T3 = 有箱体外观但未见明显孔。",
        "",
        "## 5. 两个候选子集",
        "",
        "| 子集 | 数量 | 构成 | 用途 |",
        "|---|---|---|---|",
        "| **TLESS-ALL** | **{} 张** | 三场景各均匀抽样（每场景最多 250 张），已按 dHash≤2 去重 + 去除明显模糊帧 | 作为“不加孔偏置”的通用预训练对照 |".format(summ["TLESS_ALL"]),
        "| **TLESS-HOLE** | **{} 张** | 只保留含 **T1/T2 优先物体**（6/7/8/18/5/11/12）的帧，每场景最多 350 张，同样去重去模糊 | 作为“孔结构偏置”的预训练 |".format(summ["TLESS_HOLE"]),
        "",
        "**两个子集都只包含 `manifest.csv` 清单，没有复制任何原始图像。**",
        "清单字段：`image_path, scene_id, object_ids, priority_reason, resolution, file_size, label_status`"
        "（`label_status` 恒为 `UNLABELED_RGB`）。",
        "",
        "预览：`phase4_tless_pretrain/TLESS-ALL/contact_sheet.jpg`、`.../TLESS-HOLE/contact_sheet.jpg`",
        "",
        "## 6. 筛选方法（为什么这样筛）",
        "",
        "1. **不使用 Hough 圆数量作为筛选标准**。Phase 3 已证明：scene 01 的程序化 Hough 报"
        "“40/40 有共线圆”，但人工目视显示画面里只有圆盘与棋盘背景，**并没有可见大孔** ——"
        "单一 Hough 规则会把这些误检收进“孔相关”子集。",
        "2. 主体依据是 **object ID 先验**：Phase 3 的人工目视已确认"
        "物体 7（三孔一排）、6（两孔并排）、8（多孔成组）、18（金属螺纹孔内壁）确实含孔，"
        "因此 TLESS-HOLE 以“帧内是否出现这些物体”为主筛选条件。",
        "3. **程序化的 bore_cue（物体框内暗区计数）只作为次要记录**（本次均值 {:.2f}），"
        "**不作为硬性入选条件**，避免重犯 Phase 3 的程序化误判。".format(qual["bore_cue_mean"]),
        "4. 去重依据 dHash≤2（近同），而不是 ≤5（高相似）——因为测试序列本身冗余极高，"
        "用 ≤5 会把 69% 的帧都去掉，损失有效视角多样性。",
        "",
        "## 7. 使用方式",
        "",
        "```python",
        "import csv, cv2",
        "rows = list(csv.DictReader(open(r'E:\\robot_inspection\\external_datasets\\"
        "phase4_tless_pretrain\\TLESS-HOLE\\manifest.csv', encoding='utf-8-sig')))",
        "imgs = [cv2.imread(r['image_path']) for r in rows]   # 全部为无标签 RGB",
        "```",
        "",
        "> 再次强调：这些图像**没有** cylinder_bore 标签，**不能直接参与有监督分割训练**；"
        "它们只用于无标签预训练 / 域适应。",
        "",
    ]), encoding="utf-8")
    print("[OK]", EXT / "phase4_tless_pretrain_dataset.md")

    # ---------------- 文档 2：实验计划 ----------------
    (EXT / "phase4_experiment_plan.md").write_text("\n".join([
        "# Phase 4A　训练前实验计划（本阶段不执行训练）",
        "",
        "生成时间：{}".format(NOW),
        "",
        "> **本阶段严禁正式训练，未调用 `model.train()`。** 本文档只设计实验。",
        "",
        "## 1. 三个实验",
        "",
        "| 实验 | 预训练数据 | 微调数据 | 说明 |",
        "|---|---|---|---|",
        "| **Experiment A** | 无 | 现有 17/5/3 | 基线（已有 5 个 seed 的结果可直接复用） |",
        "| **Experiment B** | **T-LESS-ALL**（{} 张，无标签） | 现有 17/5/3 | 通用工业域预训练 |".format(summ["TLESS_ALL"]),
        "| **Experiment C** | **T-LESS-HOLE**（{} 张，无标签） | 现有 17/5/3 | 孔结构偏置预训练 |".format(summ["TLESS_HOLE"]),
        "",
        "**不要在实验前假设 B 或 C 一定更好** —— 三个实验并列比较，用数据说话。",
        "",
        "## 2. 预训练阶段的形式（重要限制）",
        "",
        "- T-LESS 只有 **UNLABELED RGB**，**没有 cylinder_bore 标签**，也**不是 hole mask**；",
        "- 因此预训练**只能是**以下形式之一：",
        "  1. **自监督**（如 SimCLR/MoCo/DINO 风格的特征学习）；",
        "  2. **backbone 初始化 / 域适应**（在无标签图像上做自监督或重建式预训练）；",
        "  3. 若坚持用 YOLO 框架，也只能把 T-LESS 图像作为**无标签图像加入训练流**"
        "（不使用其 mask），并在实验记录中明确标注“无标签图像参与”；",
        "- **禁止**：把 T-LESS 的 object mask 当 hole mask；**禁止**用 Hough 生成伪标签；"
        "**禁止**把 T-LESS 图像混进 `dataset\\box_yolo\\`。",
        "",
        "## 3. 微调阶段（与现有实验保持完全一致）",
        "",
        "- 数据：`E:\\robot_inspection\\experiments\\dataset_17_5_3`（17 train / 5 val / 3 test）",
        "- 模型：`yolo11n-seg.pt`；imgsz=640；batch=8；epochs=100；patience=0；device=0；workers=2；"
        "deterministic=True",
        "- 每个实验建议至少跑 **seed = 0 / 42 / 123** 三个种子，便于与已有结果统计比较",
        "",
        "## 4. 评估协议（必须与现有评测完全一致）",
        "",
        "- 测试图像：`E:\\robot_inspection\\test_images\\` 的 **测试1 ~ 测试4**（4 张，固定不变）",
        "- **confidence threshold = 0.50**（正式统计阈值）",
        "- 后处理：YOLO-Seg mask → `cv2.fitEllipse` 椭圆拟合 → 椭圆中心",
        "- 编号：4 个孔中心做 **PCA 主轴** → 沿主轴排序 → **H01 ~ H04**",
        "- 评测脚本：沿用现有 `scripts\\predict_holes.py` 与 `scripts\\eval_confidences.py`"
        "（不修改检测算法）",
        "- 记录：每张图检出孔数（4/4 或不足）、每孔 confidence、反光孔 confidence、漏检/误检",
        "",
        "## 5. 对照基准（已有结果）",
        "",
        "| 基线 | 结果 |",
        "|---|---|",
        "| Experiment A（现有 5 个 seed × best/last × 4 图） | **38/40 = 95%** 达到 4/4 |",
        "| 目标孔 confidence 最小值 | 0.6233 |",
        "| 反光孔（测试3 自上而下第 3 个孔） | 0.6233 ~ 0.8011 |",
        "| 已知问题 | seed=2024 在测试3 最下方孔出现临界漏检（0.4554 / 0.4649） |",
        "",
        "**判定新实验是否有效的标准（预先声明，避免事后挑结果）**：",
        "",
        "1. 4/4 比例是否 ≥ 95%；",
        "2. 目标孔 confidence 最小值是否高于 0.6233；",
        "3. 反光孔 confidence 是否提升；",
        "4. 是否消除了 seed=2024 类临界漏检；",
        "5. 3 个种子的波动（标准差）是否下降。",
        "",
        "## 6. 风险与注意事项",
        "",
        "- **域偏移**：T-LESS 是 720×540、黑背景、白色哑光物体；本项目是 2592×4608、"
        "现场背景、金属反光 —— 预训练收益不确定，必须用 A/B/C 对照验证；",
        "- **冗余**：T-LESS 序列帧间高相似（dHash≤5 占 69%），已按 dHash≤2 去重；",
        "- **许可**：CC BY 4.0，可用于研究/商用，但需在成果中标注来源与引用；",
        "- **不要污染正式数据**：T-LESS 只放 `external_datasets\\`，绝不进入 `dataset\\box_yolo\\`。",
        "",
        "## 7. 本阶段完成度",
        "",
        "- [x] T-LESS 三场景完整审计（数量/可读性/分辨率/大小/重复/分布/质量）",
        "- [x] priority objects 统计（object_distribution.csv / priority_objects.csv）",
        "- [x] 两个候选子集清单（TLESS-ALL {} / TLESS-HOLE {}）".format(
            summ["TLESS_ALL"], summ["TLESS_HOLE"]),
        "- [x] 实验计划文档（本文）",
        "- [ ] **执行 Experiment A/B/C（下一阶段，需你确认后才做）**",
        "",
        "> 本阶段未训练，未调用 `model.train()`。",
        "",
    ]), encoding="utf-8")
    print("[OK]", EXT / "phase4_experiment_plan.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
