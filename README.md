# 机械臂智能检测项目（YOLO11n-Seg 孔位识别）

> 目标流程：
> 工业相机 / 手机图像 → YOLO-Seg 检测工件 4 个大型圆孔 → 椭圆拟合求孔中心
> → PCA 求工件长轴 → 沿长轴编号 H01~H04 → （后续）像素坐标 → 机器人坐标 → 自动测量

本文档记录本机（Windows + RTX 3050 Ti 4GB）已经搭好的环境，以及如何重新运行。

---

## 0. 项目总览（双人协作版，2026-10-07 补充）

**项目名称**：机械臂智能视觉检测系统

**协作方式**：本机与朋友电脑各自 clone 一份，通过 GitHub **私有仓库** 同步代码和文档：

```
我的电脑  ──push / pull──►  GitHub 私有仓库  ◄──push / pull──  朋友电脑
```

**当前主要流程**：

```
目标感知 → 位姿识别 → 检测点生成 → 机器人路径规划 → 自动检测 → 数据分析
```

**当前视觉任务**：用 YOLO-Seg 检测大型工业箱体顶部的 **4 个大型圆孔**，
再对每个孔的 mask 做椭圆拟合，求出更准确的孔中心。

**当前类别**：`cylinder_bore`（单类别）

**当前模型**：YOLO11n-Seg（权重 `weights\best.pt`，**不进 Git**，
SHA256 `7E33DF6223CC25463683131FD5098713100E8552F782111D848737BA9503BDFE`，
通过模型交付包 / 云盘共享）

**关于 H01~H04（重要）**：当前编号是**当前图像内的检测编号** ——
由 4 个孔中心做 PCA 主轴排序得到，**不是已经解决的永久物理身份**
（把同一张图旋转 180°，H01 与 H04 会对调）。程序里 `orientation_status` 恒为 `uncertain`。

**当前项目阶段**：

```
视觉检测 → 孔中心定位 → 检测任务生成 → GUI 集成 → （下一步）机器人接口
```

- 已完成：环境搭建、数据集（train 20 / val 2 / test 3）、YOLO11n-Seg 训练与 5×seed 正式对照实验、
  椭圆拟合 + PCA 编号、GUI 软件、模型交付包
- **未完成**：相机标定、像素坐标 → 机器人坐标转换、手眼标定、真实机械臂联调

**协作文档**：

| 文档 | 内容 |
| --- | --- |
| `TEAM_WORKFLOW.md` | 两个人怎么用 Git（分支 / 提交 / 冲突处理） |
| `DATA_AND_MODEL_MANAGEMENT.md` | 模型和数据怎么管、怎么共享 |
| `BRANCH_PLAN.md` | 分支规划和各自负责范围 |
| `docs\PROJECT_FILES.md` | **文件分类与共享说明（哪些进 Git、哪些做成 Release 附件、朋友怎么拿）** |
| `docs\FRIEND_UPLOAD_PROMPT.md` | **给朋友的提示词**（让他把项目上传到自己的分支，不污染 main） |
| `docs\FRIEND_REVIEW_AND_MERGE_PLAN.md` | **朋友分支审核报告 + 合并方案** |
| `docs\ELLIPSE_FIT_COMPARISON.md` | **椭圆拟合对比与采纳记录**（现默认 稳健+边缘精修） |
| `docs\FRIEND_PIPELINE_AUDIT.md` | **朋友管线复现审核**（差距来自模型/训练数据量，不是管线） |
| `docs\README.md` | 文档索引 |
| `configs\README.md` | 配置文件放哪里 |

---

## 1. 本机环境（已完成安装）

| 项目 | 位置 / 版本 |
| --- | --- |
| Python（基础发行版） | `E:\Miniconda3\python.exe`，Python 3.11.14 |
| 项目虚拟环境 | `E:\robot_inspection\.venv` |
| 虚拟环境 Python | `E:\robot_inspection\.venv\Scripts\python.exe` |
| PyTorch | 2.5.1+cu121（GPU 版，CUDA 12.1 runtime） |
| torchvision | 0.20.1+cu121 |
| ultralytics | 8.4.173 |
| OpenCV | 5.0.0 |
| numpy / matplotlib | 2.4.6 / 3.11.2 |
| 显卡 | NVIDIA GeForce RTX 3050 Ti Laptop GPU（4GB, sm_86） |
| 驱动 | 610.60（CUDA UMD 13.3；向下兼容 CUDA 12.1 runtime） |

> 说明：显卡驱动里看到的 “CUDA UMD 13.3” 是驱动支持的**最高** CUDA 版本，
> PyTorch 自带 CUDA 12.1 运行库，可以直接使用，无需单独安装 CUDA Toolkit。

---

## 2. 目录结构

```
E:\robot_inspection\
├── .venv\                     # 虚拟环境（不要删除）
├── dataset\
│   └── box_yolo\              # ← 数据集解压到这里
│       ├── images\{train,val,test}
│       ├── labels\{train,val,test}
│       └── data.yaml
├── scripts\
│   ├── check_dataset.py       # 数据集检查
│   ├── train_seg.py           # 训练（含显存不足自动降 batch）
│   └── predict_holes.py       # 检测 + 椭圆拟合 + PCA 编号
├── runs\                      # 每次训练的完整输出（权重、曲线、混淆矩阵）
├── weights\
│   ├── best.pt                # ← 训练完成后永久保存的最优权重
│   └── last.pt
├── results\                   # 检测可视化图片 + detection_report.json
├── logs\                      # 训练 / 安装日志
├── requirements.txt           # 依赖清单（不含 PyTorch）
├── requirements-torch-cu121.txt
├── run_check_dataset.bat      # 双击即可检查数据集
├── run_train.bat              # 双击即可训练
└── run_test.bat               # 双击即可检测
```

---

## 3. 数据集放置位置（重要）

把 `box_yolo_dataset.zip` 放到 **`E:\robot_inspection\dataset\`** 目录下，
然后解压，最终必须是：

```
E:\robot_inspection\dataset\box_yolo\images\train\   （20 张）
E:\robot_inspection\dataset\box_yolo\images\val\     （2 张）
E:\robot_inspection\dataset\box_yolo\images\test\    （3 张）
E:\robot_inspection\dataset\box_yolo\labels\train\   （20 个 .txt）
E:\robot_inspection\dataset\box_yolo\labels\val\     （2 个 .txt）
E:\robot_inspection\dataset\box_yolo\labels\test\    （3 个 .txt）
E:\robot_inspection\dataset\box_yolo\data.yaml
```

解压后运行一次检查：

```bat
E:\robot_inspection\run_check_dataset.bat
```

---

## 4. 训练

```bat
E:\robot_inspection\run_train.bat
```

等价于：

```bat
E:\robot_inspection\.venv\Scripts\python.exe E:\robot_inspection\scripts\train_seg.py
```

默认参数（针对 4GB 显存）：

| 参数 | 值 |
| --- | --- |
| 模型 | YOLO11n-Seg (`yolo11n-seg.pt`) |
| epochs | 100 |
| imgsz | 640 |
| batch | 2 |
| workers | 2 |
| patience | 20 |
| device | 0（RTX 3050 Ti） |

如果显存不足，脚本会**自动**按下面的顺序降级重试，无需人工排查：

```
(batch=2, imgsz=640) → (1,640) → (2,512) → (1,512) → (1,416)
```

先跑 1 轮做冒烟测试（验证流程是否通）：

```bat
"E:\robot_inspection\.venv\Scripts\python.exe" "E:\robot_inspection\scripts\train_seg.py" --epochs 1 --name smoke_test
```

训练完成后：

- 完整结果：`E:\robot_inspection\runs\<run_name>\`
- 永久权重：`E:\robot_inspection\weights\best.pt`（脚本自动复制）
- 训练日志：`E:\robot_inspection\logs\train_<run_name>.log`

---

## 5. 检测（椭圆拟合 + PCA 编号）

```bat
E:\robot_inspection\run_test.bat
```

脚本会按顺序自动查找测试图片：

1. `E:\robot_inspection\test_images\`
2. `E:\vm_share\训练照片（箱体）\`（当前的 测试1~4.jpg 就在这里）
3. `E:\robot_inspection\dataset\box_yolo\images\test\`
4. `E:\vm_share\训练照片\`

也可以手动指定：

```bat
E:\robot_inspection\.venv\Scripts\python.exe E:\robot_inspection\scripts\predict_holes.py --source "E:\path\to\图片.jpg"
```

输出：

- 每张图片一张可视化：`E:\robot_inspection\results\<图片名>_result.jpg`
  - 半透明彩色 mask、白色轮廓、绿色椭圆、红色椭圆中心、`H01~H04` 标签、蓝色 PCA 长轴
- 结构化结果：`E:\robot_inspection\results\detection_report.json`
  （每孔含 confidence / mask 中心 / ellipse center / angle / width / height）
- 控制台打印每张图片的检测个数（期望 4/4）与每孔参数

### 关键参数

| 参数 | 值 |
| --- | --- |
| CONF_THRESHOLD | 0.50 |
| CONF_FLOOR（补检下限） | 0.10 |
| IOU | 0.70 |
| imgsz | 640 |
| 椭圆拟合 | `cv2.fitEllipse()` 作用于 mask 最大外轮廓 |
| 编号规则 | 4 个椭圆中心做 PCA 求长轴，沿主轴投影排序 |

### 关于「低置信度补检」（重要，不是造假）

工件固定在 4 个大型圆孔，因此脚本先用 `--conf-floor`（默认 0.10）推理，
再按置信度取前 4 个孔。这样做的原因：**孔内壁是高反光金属面时，模型置信度会明显下降**
（例如测试3 的第 3 个孔只有 0.17），只用 0.5 阈值会漏检。

- 置信度 ≥ 0.50 的孔：正常显示
- 置信度 < 0.50 的孔：椭圆画成**橙色**、标签加 `LOW`、控制台打印 `*低置信度`、
  JSON 里 `"low_confidence": true`

所有孔的**真实置信度都会如实输出**，需要严格模式时加 `--conf-floor 0.5` 即可退化为纯 0.5 阈值。

### H01~H04 编号约定

- 对 4 个孔的椭圆中心做 PCA（SVD），取第一主成分作为工件长轴；
- 主轴向量的 x 分量强制为正（统一指向图像右侧），因此编号是可复现的；
- 把 4 个中心投影到长轴上，按投影值从小到大排序：
  最左端 = `H01`，依次 `H02`、`H03`，最右端 = `H04`。
- 如果实际工件的物理起点方向与上面相反，只需把编号整体反过来即可
  （修改 `predict_holes.py` 中 `pca_long_axis()` 里的方向判定）。

---

## 6. 如果要在新电脑 / 重装后重建环境

```bat
:: 1) 基础 Python 3.11（本项目用 Miniconda 作为基础发行版）
::    安装包：E:\robot_inspection\_installers\Miniconda3-py311-Windows-x86_64.exe
Miniconda3-py311-Windows-x86_64.exe /InstallationType=JustMe /RegisterPython=0 /AddToPath=0 /S /D=E:\Miniconda3

:: 2) 创建虚拟环境
E:\Miniconda3\python.exe -m venv E:\robot_inspection\.venv

:: 3) 安装 PyTorch GPU 版（必须用 CUDA 专用源）
E:\robot_inspection\.venv\Scripts\python.exe -m pip install torch==2.5.1+cu121 torchvision==0.20.1+cu121 --index-url https://download.pytorch.org/whl/cu121

:: 4) 安装其余依赖
E:\robot_inspection\.venv\Scripts\python.exe -m pip install -r E:\robot_inspection\requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

:: 5) 验证
E:\robot_inspection\.venv\Scripts\python.exe -c "import torch;print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

---

## 7. 常见问题

**Q: 训练爆显存 `CUDA out of memory`？**
脚本会自动降 batch / imgsz 重试。如果仍失败，可手动指定更小配置：
`--batch 1 --imgsz 416`。

**Q: 检测不到 4 个孔？**
逐步排查：① 确认用的是 `E:\robot_inspection\weights\best.pt`；
② 适当降低 `--conf`（例如 0.35）看看漏检原因；
③ 确认测试图片与训练集拍摄条件接近。

**Q: 想让模型下次仍然能用？**
`E:\robot_inspection\weights\best.pt` 是永久文件，复制到别处也不会消失；
重装环境后只要这个文件还在，就能直接用来检测。

---

## 8. 本机实际执行记录（2026-10-06）

### 训练

```
run_name : box_yolo_yolo11n_seg
数据     : dataset/box_yolo（train 20 / val 2 / test 3）
配置     : yolo11n-seg.pt, 100 epochs, batch=2, imgsz=640, workers=2, patience=20, device=0
显存占用 : 约 0.55 GB / 4 GB（余量充足，无需降 batch）
结果     : 第 95 轮触发早停（patience=20），最佳权重出现在第 75 轮
耗时     : 约 2.8 分钟
```

最佳模型在验证集上的指标（Mask 分割）：

| 指标 | 值 |
| --- | --- |
| Precision | 0.994 |
| Recall | 1.000 |
| mAP50 | 0.995 |
| mAP50-95 | 0.983 |

### 测试（4 张新图片，未参与训练）

| 图片 | 检出孔数 | 置信度 | 备注 |
| --- | --- | --- | --- |
| 测试1.jpg | 4/4 | 0.965 / 0.925 / 0.923 / 0.850 | 全部高置信度 |
| 测试2.jpg | 4/4 | 0.979 / 0.959 / 0.946 / 0.932 | 全部高置信度 |
| 测试3.jpg | 4/4 | 0.967 / 0.819 / 0.651 / **0.172** | 第 3 孔内壁高反光，1 个低置信度补检 |
| 测试4.jpg | 4/4 | 0.963 / 0.946 / 0.936 / 0.891 | 全部高置信度 |

合计 **16/16** 个目标大孔全部检出；
其中 15 个置信度 ≥ 0.65，1 个（测试3 第 3 孔）因镜面反光只有 0.17。

> 改进建议：若要提升该反光孔的置信度，可在数据集中补充几张“孔内壁高反光”的照片重新训练，
> 或改用更大的模型（如 `yolo11s-seg.pt`，本机 4GB 显存仍有富余，把 `--weights yolo11s-seg.pt` 换掉即可）。

### 其他说明

- 训练时 Ultralytics 提示 `corrupt JPEG restored and saved`：这是它对渐进式 JPEG 的兼容处理，
  只重写了**解压后**的副本图片；`E:\vm_share\box_yolo_dataset.zip` 原始压缩包**未被改动**。
- 安装过程中把 pip 的默认源设置成了清华镜像（`C:\Users\Administrator\AppData\Roaming\pip\pip.ini`），
  以便后续安装依赖更快；如需恢复官方源，删除该文件即可。
