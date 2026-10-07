# configs\ 配置目录

这个目录放**可共享的配置文件**（`.yaml` / `.json` / `.ini`），它们体积小、适合进 Git。

---

## 一、当前配置在哪儿（先看这些，别重复建）

| 配置项 | 现在的位置 | 说明 |
| --- | --- | --- |
| 检测参数（阈值、imgsz、类别名、路径） | `app\config.py` | GUI 与推理脚本共用；`PROJ` 会自动适配包/仓库位置 |
| 训练默认参数（epochs/batch/patience/seed…） | `scripts\train_seg.py` 的 `argparse` 默认值 | 命令行可覆盖，例如 `--epochs 100 --seed 42` |
| 数据集定义（类别名、train/val/test） | `dataset\box_yolo\data.yaml` | **不进 Git**（在 `dataset\` 下），随数据集一起分发 |
| 17/5/3 划分的数据集绝对路径版本 | `experiments\dataset_17_5_3_abs.yaml` | 轻量记录，在 Git 里 |

> 关键默认值（截至 2026-10-07）：
> `CONF = 0.50`，`IOU = 0.70`，`IMGSZ = 640`，`EXPECTED_HOLES = 4`，类别 `cylinder_bore`，
> 训练 `epochs=100 / imgsz=640 / batch=2 / workers=2 / patience=20 / device=0`。

## 二、这个目录以后放什么

- 新的**实验配置**：例如 `configs\fusion_v1.yaml`（朋友做融合训练时用）
- 不同**场景参数**：例如 `configs\camera_industrial.yaml`（换工业相机后）
- **标定结果**：例如 `configs\handeye_2026xxxx.json`（手眼标定矩阵，纯数值，小文件）

约定：

1. 一个实验一个文件，文件名带版本号或日期，例如 `fusion_v1.yaml`、`handeye_20261010.json`。
2. **不要**在这里放模型、图片、数据集路径下的内容。
3. 改配置后请在 `experiments\` 里补一条简短记录（用了什么配置、seed 多少、结果如何）。

## 三、安全提醒

配置里**不要写**账号密码、GitHub token、API key。
如果确实要放敏感信息，用环境变量，不要进 Git。
