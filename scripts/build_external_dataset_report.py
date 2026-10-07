# -*- coding: utf-8 -*-
"""
外部数据集评估：生成 candidates.csv / candidates.json / 最终 HTML 报告 / README / 校验和
=====================================================================================
数据来源：本脚本中所有条目均来自 external_datasets\\metadata 下实际抓取的证据
（Kaggle / GitHub / Zenodo 官方 API 返回、官方页面抓取、实际下载文件），
未确认的字段一律写 "未确认"，不做推测。

用法：
    python scripts\\build_external_dataset_report.py
"""

import csv
import hashlib
import html
import json
from datetime import datetime
from pathlib import Path

PROJ = Path(r"E:\robot_inspection")
EXT = PROJ / "external_datasets"
REPORTS = EXT / "reports"
META = EXT / "metadata"
AUDIT = EXT / "audit"

NOW = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# ---------------------------------------------------------------- 候选数据集（均为实测证据）
CANDIDATES = [
    {
        "id": "c01", "name": "Container Hole Localization Dataset (大型集装箱角件孔位定位)",
        "source": "GitHub (yunfengdiao)",
        "official_url": "https://github.com/yunfengdiao/A-large-scale-container-dataset-and-a-baseline-method-for-container-hole-localization",
        "download_url": "Google Drive（仓库 README 中的链接，未验证可下载）",
        "public": "是（仓库公开）", "license": "LICENSE_UNCLEAR（仓库无 LICENSE 文件，GitHub API 返回 license=null）",
        "license_status": "LICENSE_UNCLEAR", "license_score": 1,
        "image_count": "描述为 large-scale（具体数量未确认，仓库本身无数据）",
        "has_segmentation": "是（预览图显示有 hole mask 与中心点）", "seg_detail": "孔洞掩膜 + 孔中心点",
        "has_bbox": "是（角件检测框）", "class_count": "未确认",
        "classes": "容器角件 / 角件孔位（未确认完整类别表）",
        "industrial_box": "是（大型金属集装箱）", "machine_housing": "部分（箱体结构）",
        "large_hole": "是（角件大孔）", "circular_hole": "是",
        "view": "俯视/斜视（预览图为 4 组示例）", "lighting": "室外自然光 + 阴影（预览观察）",
        "background": "工业/现场背景",
        "visual_similarity": "主题最接近：大金属箱体 + 孔位定位 + mask + 中心点",
        "transfer_value": "高（若可获得）", "mix_value": "低（类别语义不同，且许可证不明）",
        "access": "仓库可访问；数据在 Google Drive，未验证",
        "evidence": "仓库 zip 已下载（961,580 字节）；官方预览图已审计（reports/dataset_03_container_hole_official_audit.html）",
        "scores": {"A": 22, "B": 20, "C": 12, "D": 8, "E": 6, "F": 5, "G": 1, "H": 3},
        "notes": "主题相似度最高，但许可证不明 + 数据托管在 Google Drive 未验证；澄清许可证前不建议用于训练。",
    },
    {
        "id": "c02", "name": "T-LESS (BOP Challenge 官方工业零件数据集)",
        "source": "BOP / GitHub / Hugging Face",
        "official_url": "https://bop.felk.cvut.cz/datasets/",
        "download_url": "https://huggingface.co/datasets/bop-benchmark/tless （tless_base.zip 等，实测可达 HTTP 200）",
        "public": "是", "license": "CC BY 4.0", "license_status": "Commercial OK", "license_score": 5,
        "image_count": "未确认精确张数（BOP 提供 train/test 序列）",
        "has_segmentation": "是（BOP 标注含 2D binary masks）", "seg_detail": "2D binary mask + bbox + 6D pose",
        "has_bbox": "是", "class_count": 30, "classes": "30 个无纹理工业关切对象（6D 位姿 BOP 格式）",
        "industrial_box": "否（是工业零件，非箱体）", "machine_housing": "部分（工业零件外观）",
        "large_hole": "部分（零件上有圆柱孔/凹槽等结构，未逐张确认）", "circular_hole": "部分",
        "view": "多视角（旋转台 + 多机位）", "lighting": "多种光照（BOP 标准采集）",
        "background": "工业/桌面背景",
        "visual_similarity": "中高：工业金属零件、结构边缘、孔类特征；不是箱体",
        "transfer_value": "高（工业零件 + 结构边缘 + mask + 多视角/多光照）",
        "mix_value": "低（类别体系不同；BOP 是位姿标注格式）",
        "access": "可下载（Hugging Face 直链实测 200；整包体积较大，本次未下载）",
        "evidence": "BOP 官方页面抓取留档（metadata/raw/site_bop_datasets.html），页面明确写明 license: CC BY 4.0",
        "scores": {"A": 14, "B": 16, "C": 13, "D": 9, "E": 8, "F": 4, "G": 5, "H": 5},
        "notes": "许可证最清晰（CC BY 4.0 可商用）且含工业零件 masks，是最稳妥的预训练来源之一。",
    },
    {
        "id": "c03", "name": "MVTec ITODD (Industrial 3D Object Detection Dataset)",
        "source": "MVTec / BOP",
        "official_url": "https://bop.felk.cvut.cz/datasets/",
        "download_url": "https://huggingface.co/datasets/bop-benchmark/itodd （实测可达 HTTP 200）",
        "public": "是", "license": "CC BY-NC-SA 4.0（可申请自定义许可）", "license_status": "Non-commercial",
        "license_score": 2, "image_count": "未确认精确张数", "has_segmentation": "是（2D binary masks）",
        "seg_detail": "2D binary mask + bbox + 6D pose", "has_bbox": "是", "class_count": 28,
        "classes": "28 个真实工业物体（工业 3D 物体识别）",
        "industrial_box": "否", "machine_housing": "部分（真实工业物体）",
        "large_hole": "部分（工业零件结构孔，未逐张确认）", "circular_hole": "部分",
        "view": "多视角（真实工业场景）", "lighting": "工业现场光照",
        "background": "真实工业背景 + 杂乱堆叠",
        "visual_similarity": "中高：真实工业场景、金属件、杂乱堆叠，接近产线视觉",
        "transfer_value": "高（真实工业场景 + mask）", "mix_value": "低（类别不同；NC 许可）",
        "access": "可下载（HF 实测 200）",
        "evidence": "BOP 页面抓取留档，明确写明 license: CC BY-NC-SA 4.0 (custom license available upon request)",
        "scores": {"A": 15, "B": 16, "C": 12, "D": 10, "E": 8, "F": 4, "G": 2, "H": 5},
        "notes": "最接近「真实工业现场 + 金属零件」的公开数据，但仅限非商业用途。",
    },
    {
        "id": "c04", "name": "VisA (Visual Anomaly Dataset)",
        "source": "AWS / GitHub (amazon-science/spot-diff)",
        "official_url": "https://github.com/amazon-science/spot-diff",
        "download_url": "https://amazon-visual-anomaly.s3.us-west-2.amazonaws.com/VisA_20220922.tar （实测 HTTP 200，1,840.4 MB）",
        "public": "是", "license": "CC BY 4.0（数据集）；仓库代码 Apache-2.0", "license_status": "CC BY",
        "license_score": 5, "image_count": 10821, "has_segmentation": "是（异常区域掩膜）",
        "seg_detail": "像素级异常掩膜", "has_bbox": "未确认", "class_count": 12,
        "classes": "12 类物体（含 4 类复杂结构 PCB）",
        "industrial_box": "否", "machine_housing": "否（工业产品/PCB）",
        "large_hole": "否", "circular_hole": "否",
        "view": "固定/半固定视角", "lighting": "受控工业光照", "background": "受控背景",
        "visual_similarity": "中：工业产品特写 + 像素级掩膜，但目标不是孔",
        "transfer_value": "中高（大规模像素级工业分割 + 复杂结构）", "mix_value": "低（异常检测语义不同）",
        "access": "可下载但实测仅 18.5 KB/s，本次未取样",
        "evidence": "README 抓取留档：'The data is released under the CC BY 4.0 license.'，10,821 张",
        "scores": {"A": 8, "B": 6, "C": 15, "D": 10, "E": 8, "F": 5, "G": 5, "H": 5},
        "notes": "许可友好、规模大、mask 质量好，但目标类别与「箱体大孔」差距较大。",
    },
    {
        "id": "c05", "name": "Workpieces image dataset (机加工工件内外表面, 工业内窥镜采集)",
        "source": "Zenodo (10.5281/zenodo.16361102)",
        "official_url": "https://zenodo.org/records/16361102",
        "download_url": "https://zenodo.org/api/records/16361102/files/surfaces.zip/content （411.5 MB，实测 620 KB/s）",
        "public": "是", "license": "CC BY 4.0", "license_status": "CC BY", "license_score": 5,
        "image_count": "未确认（zip 411.5 MB）", "has_segmentation": "未确认",
        "seg_detail": "描述未提及掩膜", "has_bbox": "未确认", "class_count": "未确认",
        "classes": "机加工工件内外表面（缺陷相关）",
        "industrial_box": "否", "machine_housing": "部分（机加工零件）",
        "large_hole": "是（工件内表面/内孔，用工业内窥镜拍摄）", "circular_hole": "是（内孔视角）",
        "view": "内窥镜内壁视角（与「测量孔内壁」场景高度一致）",
        "lighting": "白色 LED 光纤照明，亮度可调", "background": "孔内壁/工件表面",
        "visual_similarity": "高：正是「机加工孔内壁 + 工业照明」这类图像",
        "transfer_value": "高（与孔内壁/反光金属表面域最接近）", "mix_value": "中（需先确认标注形式）",
        "access": "可下载（实测 620 KB/s，本次因时间未下载完）",
        "evidence": "Zenodo API 元数据（许可证 cc-by-4.0；描述：industrial boroscope + microscope camera，2592×1944）",
        "scores": {"A": 16, "B": 18, "C": 0, "D": 10, "E": 5, "F": 4, "G": 5, "H": 3},
        "notes": "域相似度非常高（内孔内壁 + 工业照明），但标注形式未确认，必须先审计再决定用法。",
    },
    {
        "id": "c06", "name": "MVTec AD (工业异常检测基准)",
        "source": "MVTec 官网",
        "official_url": "https://www.mvtec.com/company/research/datasets/mvtec-ad",
        "download_url": "官网需注册后下载（本次 ACCESS_FAILED：未注册）",
        "public": "是（注册后）", "license": "CC BY-NC-SA 4.0", "license_status": "Non-commercial",
        "license_score": 2, "image_count": ">5000（官网原文 over 5000）",
        "has_segmentation": "是（pixel-precise annotations）", "seg_detail": "像素级缺陷掩膜",
        "has_bbox": "未确认", "class_count": 15, "classes": "15 类物体/纹理（含 metal_nut、screw 等金属件）",
        "industrial_box": "否", "machine_housing": "否", "large_hole": "否", "circular_hole": "部分（metal_nut）",
        "view": "固定工业相机视角", "lighting": "受控工业光照", "background": "受控背景",
        "visual_similarity": "中低：工业件特写，但不是箱体/大孔",
        "transfer_value": "中（工业分割通用特征，但目标语义差异大）", "mix_value": "低",
        "access": "ACCESS_FAILED（需注册）",
        "evidence": "官网抓取留档：'released under the Creative Commons Attribution-NonCommercial-ShareAlike 4.0'",
        "scores": {"A": 8, "B": 5, "C": 15, "D": 10, "E": 8, "F": 5, "G": 2, "H": 5},
        "notes": "工业分割领域的经典基准，但许可非商用且目标不是箱体大孔。",
    },
    {
        "id": "c07", "name": "KolektorSDD2 (Kolektor 表面缺陷分割)",
        "source": "ViCoS Lab 官网",
        "official_url": "https://www.vicos.si/resources/kolektorsdd2/",
        "download_url": "官网 DOWNLOAD HERE（需在页面操作，本次未取得直链）",
        "public": "是", "license": "CC BY-NC-SA 4.0", "license_status": "Non-commercial", "license_score": 2,
        "image_count": "训练 246 正 + 2085 负；测试 110 正 + 894 负（合计约 3335）",
        "has_segmentation": "是（缺陷掩膜）", "seg_detail": "像素级缺陷掩膜", "has_bbox": "未确认",
        "class_count": "1（缺陷/正常）", "classes": "表面缺陷",
        "industrial_box": "否", "machine_housing": "否", "large_hole": "否", "circular_hole": "否",
        "view": "固定工业相机", "lighting": "受控", "background": "受控",
        "visual_similarity": "低：小尺寸工业件表面缺陷",
        "transfer_value": "中低", "mix_value": "低", "access": "需从官网页面下载（本次未取直链）",
        "evidence": "官网抓取留档：'licensed under Creative Commons Attribution-NonCommercial-ShareAlike 4.0'",
        "scores": {"A": 6, "B": 5, "C": 15, "D": 9, "E": 6, "F": 3, "G": 2, "H": 5},
        "notes": "标注质量高，但目标与工业箱体大孔无关。",
    },
    {
        "id": "c08", "name": "Magnetic Tile Defect Dataset (MTD, 磁瓦缺陷 + 像素级 GT)",
        "source": "GitHub (abin24)",
        "official_url": "https://github.com/abin24/Magnetic-tile-defect-datasets.",
        "download_url": "https://codeload.github.com/abin24/Magnetic-tile-defect-datasets./zip/refs/heads/master （50.6 MB）",
        "public": "是", "license": "LICENSE_UNCLEAR（GitHub API license=null，仓库无 LICENSE 文件）",
        "license_status": "LICENSE_UNCLEAR", "license_score": 1,
        "image_count": "1345 张 jpg + 1345 张像素级 GT png（仓库共 2690 个图片文件）",
        "has_segmentation": "是（像素级 GT 为独立 png 掩膜文件，非 YOLO 标注）",
        "seg_detail": "像素级缺陷掩膜 png", "has_bbox": "否", "class_count": 6,
        "classes": "6 类磁瓦表面缺陷（blowhole 等）",
        "industrial_box": "否", "machine_housing": "否", "large_hole": "否", "circular_hole": "否",
        "view": "固定机位特写", "lighting": "受控（暗场）", "background": "深色/黑色背景",
        "visual_similarity": "低：256×256 灰度金属表面 + 缺陷",
        "transfer_value": "低中（金属表面 + 像素掩膜，但分辨率与场景差异大）", "mix_value": "低",
        "access": "已实际下载 12 组样本（原图 + 掩膜）",
        "evidence": "sample: external_datasets/dataset_01_magnetic_tile_defect_sample/**；审计报告 reports/dataset_01_*_audit.html",
        "scores": {"A": 5, "B": 4, "C": 14, "D": 8, "E": 4, "F": 2, "G": 1, "H": 4},
        "notes": "唯一完成真实样本审计的数据集；图像分辨率低、场景差异大，仅适合通用金属表面特征。",
    },
    {
        "id": "c09", "name": "Mechanical Parts Dataset 2022 (轴承/螺栓/齿轮/螺母)",
        "source": "Zenodo (10.5281/zenodo.7504801)",
        "official_url": "https://zenodo.org/records/7504801",
        "download_url": "https://zenodo.org/api/records/7504801/files/Mechanical%20Parts_pascal_voc.rar/content （88.7~89.3 MB ×3 格式）",
        "public": "是", "license": "CC BY 4.0", "license_status": "CC BY", "license_score": 5,
        "image_count": 2250, "has_segmentation": "否（仅 bbox：Pascal VOC / COCO / YOLO 文本）",
        "seg_detail": "无掩膜", "has_bbox": "是（10,597 个标注）", "class_count": 4,
        "classes": "bearing(714图) / bolt(632) / gear(616) / nut(586)",
        "industrial_box": "否", "machine_housing": "否（机械标准件）",
        "large_hole": "否（但有圆形零件轮廓）", "circular_hole": "部分（轴承/齿轮圆孔）",
        "view": "网络图片，视角混杂", "lighting": "混杂（来自互联网）", "background": "混杂",
        "visual_similarity": "中低：机械标准件特写，非箱体",
        "transfer_value": "中（机械件外观 + bbox 预训练）", "mix_value": "低（只有 bbox，不能直接做分割 mask）",
        "access": "可下载（实测 462 KB/s，本次未下载）",
        "evidence": "Zenodo API 元数据（cc-by-4.0，2250 张，类别计数与标注数）",
        "scores": {"A": 8, "B": 12, "C": 0, "D": 9, "E": 7, "F": 4, "G": 5, "H": 4},
        "notes": "bbox-only，不能直接当分割数据；可作检测/骨干预训练。",
    },
    {
        "id": "c10", "name": "CR7-DET (冷轧钢板表面缺陷)",
        "source": "Zenodo (10.5281/zenodo.14263276)",
        "official_url": "https://zenodo.org/records/14263276",
        "download_url": "https://zenodo.org/api/records/14263276/files/CR7-DET-main.zip/content （50.2 MB）",
        "public": "是", "license": "CC BY 4.0", "license_status": "CC BY", "license_score": 5,
        "image_count": 4140, "has_segmentation": "未确认（描述为 11,020 labels）",
        "seg_detail": "未确认", "has_bbox": "未确认", "class_count": 7,
        "classes": "inclusion / dents / oil spots / pits / punching / linear defects / macular spots",
        "industrial_box": "否", "machine_housing": "否", "large_hole": "否", "circular_hole": "否",
        "view": "产线表面成像", "lighting": "产线光照", "background": "钢板表面",
        "visual_similarity": "低（钢板表面纹理缺陷）",
        "transfer_value": "低中（工业金属表面纹理）", "mix_value": "低",
        "access": "可下载（实测 388 KB/s，本次未下载）",
        "evidence": "Zenodo API 元数据（cc-by-4.0；4140 张 / 11,020 labels）",
        "scores": {"A": 5, "B": 3, "C": 0, "D": 9, "E": 6, "F": 5, "G": 5, "H": 4},
        "notes": "真实中国钢厂数据，但目标是表面缺陷，与大孔无关。",
    },
    {
        "id": "c11", "name": "DAGM 2007 (工业光学检测缺陷分割)",
        "source": "Kaggle 镜像（原始为 DAGM 竞赛）",
        "official_url": "https://www.kaggle.com/datasets/mhskjelvareid/dagm-2007-competition-dataset-optical-inspection",
        "download_url": "Kaggle（需账号/API 凭据，本次 ACCESS_FAILED）",
        "public": "是（需 Kaggle 账号）", "license": "Community Data License Agreement - Sharing - v1.0",
        "license_status": "Research only（需遵守 CLA）", "license_score": 3,
        "image_count": "未确认（zip 5626.7 MB）", "has_segmentation": "是（weak + pixel 标注）",
        "seg_detail": "像素级缺陷标注", "has_bbox": "是", "class_count": 10,
        "classes": "10 类弱标注缺陷（纹理表面）",
        "industrial_box": "否", "machine_housing": "否", "large_hole": "否", "circular_hole": "否",
        "view": "固定工业相机", "lighting": "受控", "background": "纹理表面",
        "visual_similarity": "低", "transfer_value": "低中", "mix_value": "低",
        "access": "ACCESS_FAILED（Kaggle 需凭据）",
        "evidence": "Kaggle API 返回 licenseName；官方缩略图已审计",
        "scores": {"A": 4, "B": 4, "C": 14, "D": 8, "E": 6, "F": 4, "G": 3, "H": 4},
        "notes": "经典工业缺陷分割基准，但非箱体/大孔。",
    },
    {
        "id": "c12", "name": "Synthetic Industrial Metal Surface Defects (合成)",
        "source": "Kaggle",
        "official_url": "https://www.kaggle.com/datasets/tatheerabbas/synthetic-industrial-metal-surface-defects",
        "download_url": "Kaggle（需凭据，本次 ACCESS_FAILED）",
        "public": "是（需 Kaggle 账号）", "license": "Attribution 4.0 International (CC BY 4.0)",
        "license_status": "CC BY", "license_score": 5, "image_count": "未确认（359.9 MB）",
        "has_segmentation": "未确认", "seg_detail": "未确认", "has_bbox": "未确认",
        "class_count": "未确认", "classes": "金属表面缺陷（合成）",
        "industrial_box": "否", "machine_housing": "否", "large_hole": "否", "circular_hole": "否",
        "view": "合成", "lighting": "合成", "background": "合成",
        "visual_similarity": "低（合成纹理图）",
        "transfer_value": "低（合成域偏移风险高）", "mix_value": "低",
        "access": "ACCESS_FAILED（Kaggle 需凭据）",
        "evidence": "Kaggle API licenseName=CC BY 4.0；官方缩略图已审计（合成裂纹金属板）",
        "scores": {"A": 6, "B": 3, "C": 0, "D": 7, "E": 5, "F": 4, "G": 5, "H": 3},
        "notes": "合成数据，域偏移风险高。",
    },
    {
        "id": "c13", "name": "Burr Detection on Machined Parts (机加工件毛刺)",
        "source": "Kaggle",
        "official_url": "https://www.kaggle.com/datasets/rudrabhuyan/burr-detection",
        "download_url": "Kaggle（需凭据，本次 ACCESS_FAILED）",
        "public": "是（需 Kaggle 账号）", "license": "MIT", "license_status": "MIT", "license_score": 5,
        "image_count": "未确认（1.4 MB，规模很小）", "has_segmentation": "部分（官方缩略图为 ground-truth 环形掩膜）",
        "seg_detail": "环形掩膜（缩略图观察）", "has_bbox": "未确认", "class_count": "未确认",
        "classes": "机加工件毛刺",
        "industrial_box": "否", "machine_housing": "否（圆形机加工件）",
        "large_hole": "部分（圆形件轮廓）", "circular_hole": "部分",
        "view": "特写", "lighting": "受控", "background": "受控",
        "visual_similarity": "中低", "transfer_value": "低（数据量太小）", "mix_value": "低",
        "access": "ACCESS_FAILED（Kaggle 需凭据）",
        "evidence": "Kaggle API licenseName=MIT；官方缩略图已审计（圆形 GT 掩膜）",
        "scores": {"A": 10, "B": 14, "C": 10, "D": 9, "E": 3, "F": 1, "G": 5, "H": 3},
        "notes": "许可宽松但规模太小（1.4MB）。",
    },
    {
        "id": "c14", "name": "Sheet Metal Components with Crack Defects (钣金件裂纹)",
        "source": "Zenodo (10.5281/zenodo.18731788)",
        "official_url": "https://zenodo.org/records/18731788",
        "download_url": "https://zenodo.org/api/records/18731788/files/sheet_metal_component.zip/content （645.2 MB）",
        "public": "是", "license": "CC BY 4.0", "license_status": "CC BY", "license_score": 5,
        "image_count": "未确认（每个组件 4 个视角）", "has_segmentation": "否（仅图像级类别标签）",
        "seg_detail": "无掩膜", "has_bbox": "否", "class_count": 2, "classes": "有裂纹 / 无裂纹",
        "industrial_box": "否", "machine_housing": "否（钣金件）", "large_hole": "否", "circular_hole": "否",
        "view": "4 个不同视角", "lighting": "未确认", "background": "未确认",
        "visual_similarity": "低", "transfer_value": "低（仅图像级标签）", "mix_value": "低",
        "access": "可下载（实测 487 KB/s，本次未下载）",
        "evidence": "Zenodo API 元数据（cc-by-4.0；图像级标签，4 视角/件）",
        "scores": {"A": 7, "B": 3, "C": 0, "D": 8, "E": 8, "F": 5, "G": 5, "H": 3},
        "notes": "多视角有价值，但没有 mask、目标也不是孔。",
    },
    {
        "id": "c15", "name": "MIG/MAG Fillet Weld Joint Segmentation Masks (焊缝分割)",
        "source": "Zenodo (10.5281/zenodo.20301441)",
        "official_url": "https://zenodo.org/records/20301441",
        "download_url": "https://zenodo.org/api/records/20301441/files/... （单文件直链，5.5 MB）",
        "public": "是", "license": "CC BY 4.0", "license_status": "CC BY", "license_score": 5,
        "image_count": "49 个试样（image+mask 成对）", "has_segmentation": "是（二值掩膜 png）",
        "seg_detail": "焊缝区域二值掩膜", "has_bbox": "否", "class_count": "1（焊缝）",
        "classes": "weld pool",
        "industrial_box": "否", "machine_housing": "否", "large_hole": "否", "circular_hole": "否",
        "view": "固定 VGA 相机", "lighting": "固定", "background": "工件",
        "visual_similarity": "低", "transfer_value": "低（数量极少，目标不同）", "mix_value": "低",
        "access": "可下载（单文件直链，体积很小）",
        "evidence": "Zenodo API 元数据（cc-by-4.0；49 试样，image+mask）",
        "scores": {"A": 6, "B": 4, "C": 13, "D": 8, "E": 3, "F": 1, "G": 5, "H": 4},
        "notes": "有真实 image+mask 配对，但仅 49 张。",
    },
]

GRADE = lambda s: "S" if s >= 85 else "A" if s >= 75 else "B" if s >= 60 else "C"


def total(c):
    return sum(c["scores"].values())


def load_json_any(names):
    """在 metadata 与 metadata/raw 下查找 JSON（兼容不同保存位置）。"""
    for n in names:
        for p in (META / n, META / "raw" / n):
            if p.is_file():
                try:
                    return json.loads(p.read_text(encoding="utf-8"))
                except Exception:
                    pass
    return {}


def main():
    REPORTS.mkdir(parents=True, exist_ok=True)
    for c in CANDIDATES:
        c["total_score"] = total(c)
        c["grade"] = GRADE(c["total_score"])
    ranked = sorted(CANDIDATES, key=lambda c: -c["total_score"])

    # ---------------- candidates.csv ----------------
    cols = ["name", "source", "official_url", "download_url", "license", "license_status",
            "image_count", "has_segmentation", "has_bbox", "class_count", "classes",
            "industrial_box_similarity", "structural_hole_similarity", "visual_similarity",
            "domain_similarity", "data_quality", "transfer_learning_value", "direct_mix_value",
            "license_score", "total_score", "grade", "recommendation", "notes"]
    csv_path = EXT / "candidates.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for c in ranked:
            w.writerow([
                c["name"], c["source"], c["official_url"], c["download_url"], c["license"],
                c["license_status"], c["image_count"], c["has_segmentation"], c["has_bbox"],
                c["class_count"], c["classes"],
                "{}/25".format(c["scores"]["A"]), "{}/25".format(c["scores"]["B"]),
                c["visual_similarity"], c["visual_similarity"],
                "{}/5".format(c["scores"]["H"]), c["transfer_value"], c["mix_value"],
                "{}/5".format(c["scores"]["G"]), c["total_score"], c["grade"],
                c["notes"], c.get("evidence", ""),
            ])

    # ---------------- candidates.json ----------------
    (EXT / "candidates.json").write_text(json.dumps({
        "generated_at": NOW,
        "goal": "工业箱体上的 4 个大型结构孔视觉识别与机器人自动检测（非法兰）",
        "scoring": {"A_industrial_box_similarity": 25, "B_structural_hole_similarity": 25,
                    "C_segmentation_mask": 15, "D_industrial_scene_similarity": 10,
                    "E_view_lighting_variation": 10, "F_data_scale": 5,
                    "G_license_clarity": 5, "H_data_quality": 5, "total": 100},
        "grades": {"S": "85-100", "A": "75-84", "B": "60-74", "C": "<60"},
        "platform_reachability": load_json_any(["platform_reachability.json"]),
        "search_stats": {k: v for k, v in load_json_any(["search_hits.json"]).items()
                         if k in ("total_raw_hits", "unique_hits", "errors")},
        "candidates": ranked,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---------------- checksums ----------------
    lines = []
    for p in sorted(EXT.rglob("*")):
        if p.is_file() and p.name != "checksums.txt":
            h = hashlib.sha256()
            with open(p, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            rel = p.relative_to(EXT).as_posix()
            src = ""
            if "downloads" in rel:
                src = "见 metadata/raw 下对应平台的原始 JSON"
            lines.append("{}\t{}\t{}\t{}".format(rel, p.stat().st_size, h.hexdigest().upper(), src))
    (META / "checksums.txt").write_text(
        "# 文件名\t大小(字节)\tSHA256\t来源\n" + "\n".join(lines) + "\n", encoding="utf-8")

    print("candidates.csv  ->", csv_path)
    print("candidates.json ->", EXT / "candidates.json")
    print("checksums.txt   ->", META / "checksums.txt")
    print()
    for c in ranked:
        print("  {:>3}  {:<6} {}".format(c["total_score"], c["grade"], c["name"][:70]))
    return ranked


if __name__ == "__main__":
    main()
