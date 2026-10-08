# 数据与模型管理规则

> 一句话：**Git 管代码，云盘/U盘管模型和数据。**

---

## 一、Git 管什么

- Python 代码（`app\`、`scripts\`、`experiments\` 里的 `.py`）
- GUI（`app\gui.py`、`app\view_render.py` 等）
- 推理脚本、训练脚本
- 配置（`app\config.py`、`configs\`）
- 文档（`README.md`、`TEAM_WORKFLOW.md`、`docs\`）
- 实验说明与轻量记录（`.md` / `.json` / `.csv` / `.yaml` / `.html`）

## 二、Git 不管什么

| 对象 | 体积（本机实测） | 为什么不进 Git |
| --- | --- | --- |
| `weights\best.pt` | 5.99 MB | 二进制模型，GitHub 单文件 100 MB 上限，且会撑爆仓库 |
| `dataset\box_yolo\` | 144.8 MB | 数据集，应该由数据共享渠道管 |
| `test_images\` | 13.1 MB | 现场拍摄照片，属于数据 |
| `runs\` | 26.8 MB | YOLO 训练输出（含权重、曲线、batch 图） |
| `results\` | 321.4 MB | 检测可视化结果 |
| `external_datasets\` | 3.0 GB | 外部数据集（T-LESS 等） |
| `friend_transfer\` | 666.4 MB | 模型交付包 |
| `.venv\` | 5.3 GB | 虚拟环境，每人自己装 |
| `_installers\` | 117.2 MB | Python / Miniconda 安装包 |
| 所有 `*.pt` `*.pth` `*.onnx` `*.engine` | — | 模型文件 |
| 所有 `*.zip` | — | 传输包 |

以上全部已写入 `.gitignore`。

---

## 三、当前 baseline 模型

| 项目 | 值 |
| --- | --- |
| 路径 | `weights\best.pt` |
| 类型 | YOLO11n-Seg，单类别 `cylinder_bore` |
| 版本 | **`fusion_v1`**（2026-10-07 用 28 张数据重训，4 张测试图 16/16） |
| SHA256 | `EAEDA05109C1F696…`（完整值见 `docs\FUSION_V1_TRAINING.md`） |
| 大小 | 5,990,237 字节 |

**这是当前正式 baseline。**

历史版本（都保留着，可随时回退）：

| 文件 | 说明 |
| --- | --- |
| `weights\fusion_v1_best.pt` | 与当前 baseline 完全相同的一份副本（命名留档） |
| `weights\best_backup_20261007_before_fusion.pt` | 原 baseline，SHA256 `7E33DF62…BDFE`，5,989,021 字节 |
| `experiments\fusion_v1\runs\fusion_v1_seed42\weights\best.pt` | 该次训练的原始输出 |

共享方式（按方便程度任选）：

1. 模型交付包：`E:\robot_project\robot_inspection\friend_transfer\robot_inspection_gui_v1.zip`
2. 云盘（阿里云盘 / 百度网盘 / OneDrive / Google Drive）
3. 移动硬盘 / U 盘

收到模型后，放到自己项目的 `weights\best.pt` 即可，**不要提交到 Git**。

---

## 四、命名约定（以后做融合模型时）

| 用途 | 建议文件名 | 说明 |
| --- | --- | --- |
| 当前 baseline | `best.pt` | 不覆盖、不改名 |
| 融合模型 v1 | `fusion_v1_best.pt` | 朋友训练出的融合模型 |
| 融合模型 v2 | `fusion_v2_best.pt` | 以后迭代 |
| 备份 | `best_backup_YYYYMMDD.pt` | 覆盖前先备份 |

规则：

1. **不要覆盖 `best.pt`**，新模型用新名字。
2. 新模型必须记录：训练数据、超参、seed、评估结果（写进 `experiments\` 的 `.md`）。
3. 评估必须用**同一套** 4 张测试图、**同一个** `conf=0.50`、同一套椭圆拟合 + PCA 编号流程，
   否则结果不可比。

---

## 五、数据集怎么给朋友

当前数据集：`dataset\box_yolo\`（train 20 / val 2 / test 3，54 个文件，144.8 MB）。

原始压缩包：`E:\vm_share\box_yolo_dataset.zip`（81,379,159 字节，
SHA256 `D2BCCBAA70642F7337221FEDEA276F858E6BBCD817C8E327959E44CCDBDE0F0A`）。

给朋友的方式：

1. 直接传 `box_yolo_dataset.zip`；
2. 朋友解压到自己的 `dataset\box_yolo\`，确认结构是
   `images\{train,val,test}` + `labels\{train,val,test}` + `data.yaml`；
3. 跑一次检查：`python scripts\check_dataset.py`。

> 注意：`dataset\box_yolo\data.yaml` 里的 `path:` 是相对路径（`path: .`），
> 所以换电脑不用改；如果自己机器上路径不同，用 `experiments\dataset_17_5_3_abs.yaml` 那种绝对路径写法即可。

---

## 六、每次提交前的自检

```bat
E:\robot_project\robot_inspection\.venv\Scripts\python.exe E:\robot_project\robot_inspection\scripts\check_git_safety.py
```

期望输出：

```
GIT SAFETY CHECK

MODEL FILES TRACKED:      PASS
DATASET TRACKED:          PASS
TEST IMAGES TRACKED:      PASS
RUNS TRACKED:             PASS
EXTERNAL DATA TRACKED:    PASS
TRANSFER PACKAGE TRACKED: PASS
LARGE FILES TRACKED:      PASS
```

任何一项是 `FAIL`，先修 `.gitignore` / 取消暂存，**不要提交**。
