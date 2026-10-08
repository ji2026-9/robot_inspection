# 工业箱体孔位智能检测系统

面向**机械臂自动测量**的视觉检测系统：从工业相机或手机拍摄的图像中，自动识别工件端面上的 4 个大型圆孔，
拟合出亚像素级的孔口椭圆并给出孔心坐标，供后续机器人定位与自动测量使用。

```
图像采集 → 目标检测与分割 → mask → 孔口椭圆拟合 → 孔心坐标 → PCA 主轴排序(H01~H04)
        → （规划中）相机标定 → 手眼标定 → 机器人坐标 → 自动测量
```

---

## 1. 项目简介

| 项目 | 说明 |
| --- | --- |
| 检测目标 | 工业箱体端面上的 4 个大型圆孔 |
| 类别 | `cylinder_bore`（单类别） |
| 模型 | YOLO11n-Seg（实例分割），可在 4 GB 显存显卡上完成训练与推理 |
| 后处理 | 稳健椭圆拟合 + 孔口边缘亚像素精修 → 孔心；4 孔心做 PCA 主轴排序 |
| 交付形态 | 图形界面软件「双机械臂孔检测系统」**融合版**（`inspection_app`，见 §6.4）+ 命令行脚本 |
| 当前状态 | **视觉检测与孔心定位已跑通并验证；工业相机（Orbbec Gemini 335Le）已接入实时画面与抓拍**；标定与机器人接入尚未开始 |

---

## 2. 主要能力

- **端到端检测**：一张图直接给出 4 个孔的分割掩膜、椭圆参数与孔心像素坐标
- **抗反光孔口拟合**：对孔内壁高反光、mask 边界不可靠的情形，改由原图梯度沿法线搜索真实孔口边缘
- **工件约束**：另有 part 分割模型，用于排除不属于目标工件的孔
- **补检策略**：候选孔不足 4 个时，自动做多尺度 + 90°/180°/270° 旋转复查
- **孔位编号**：4 个孔心做 PCA 求主轴，沿主轴排序得到 H01~H04（当前图像内编号）
- **数据闭环**：内置标注（Labelme）→ 增量训练 → 模型验证选择
- **实验记录**：每次检测结果按组追加保存，可导出 CSV

---

## 3. 技术方案

### 3.1 检测

- **模型**：YOLO11n-Seg，单类别分割
- **推理参数**：`conf = 0.50`、`iou = 0.70`、`imgsz = 640`（部分流程使用 960）
- **低置信度处理**：**不补检、不编造**。低于阈值的孔如实报"未检出"，界面提示复核

### 3.2 椭圆拟合（本项目的关键技术点）

分三级，逐级回退，任一环节不通过就退回上一级：

1. `cv2.fitEllipse`（基线）
2. **稳健拟合**：轮廓按弧长重采样，RANSAC + 内点重拟合，并做支持率/角度覆盖/稳定性校验
3. **孔口边缘精修**：沿椭圆法线做亚像素梯度搜索，找到真实孔口边缘后再拟合

> 实测结论：只做第 2 级时，15/16 个孔仍停留在分割掩膜边界上，而掩膜边界并不等于物理孔口
> （会跟随倒角与反光）。启用第 3 级后，椭圆落在图像梯度上的强度提升了 **6.6 倍**
> （25% 分位 2.03 → 13.32），并与独立训练的另一个模型给出的孔心相差中位 **1.97 px**。
> 详见 [`docs/ELLIPSE_FIT_COMPARISON.md`](docs/ELLIPSE_FIT_COMPARISON.md)。

### 3.3 孔位编号

对 4 个孔心做 PCA（SVD）取第一主成分作为工件长轴，将孔心投影到长轴后排序，得到 H01~H04。

> **H01~H04 是"当前图像内的编号"**，不是永久物理孔号：把同一张图旋转 180°，H01 与 H04 会对调。
> 程序输出中 `orientation_status` 恒为 `uncertain`，界面上也如实标注。

---

## 4. 实测性能

评估集为**未参与训练**的 4 张实拍图像，阈值 `conf = 0.50`：

| 图像 | 检出 | 最低置信度 | 备注 |
| --- | ---: | ---: | --- |
| 测试1 | 4 / 4 | 0.964 | |
| 测试2 | 4 / 4 | 0.973 | |
| 测试3 | 4 / 4 | **0.904** | 含一个孔内壁高反光的难样本 |
| 测试4 | 4 / 4 | 0.954 | |
| **合计** | **16 / 16** | — | 16 个孔全部通过孔口边缘精修 |

其它已完成的验证：

- **多随机种子对照实验**：5 个 seed × 2 个模型 × 4 张图，**38/40 = 95%** 达到 4/4
- **训练集验证集指标**：Mask mAP50 ≈ 0.995（小样本，指标偏乐观，不作为泛化证据）
- **推理速度**：单张约 0.6~0.7 s（RTX 3050 Ti Laptop，4 GB 显存）

> ⚠️ 以上数字仅代表**该评估集**。换箱体、换相机、换光照后必须重新验证。
> 这些图像**没有人工标注的孔心真值**，"检出 4 个孔"不等于测量准确。

---

## 5. 环境要求

| 项目 | 要求 |
| --- | --- |
| 操作系统 | Windows 10 / 11（64 位） |
| Python | 3.11 |
| 显卡 | NVIDIA GPU，**显存 ≥ 4 GB**（CPU 也能跑，推理较慢） |
| 内存 / 磁盘 | 建议 16 GB 内存；完整环境约 12 GB 磁盘 |
| 主要依赖 | `torch 2.5.1+cu121`、`ultralytics 8.4.173`、`opencv-python 5.0`、`numpy`、`PySide6` |

依赖清单见 [`requirements.txt`](requirements.txt) 与 [`requirements-torch-cu121.txt`](requirements-torch-cu121.txt)。

---

## 6. 快速开始

> 下面命令中的 `<项目根目录>` 指本仓库克隆/解压后的目录。

### 6.1 图形界面（推荐）

界面源码就在本仓库：**[`fused_app/`](fused_app/README.md)**（我们这套「双机械臂孔检测系统」的完整源码，
所有本地补丁已应用）。本机运行/交付的那一份在 `E:\robot_project\inspection_app`，
桌面快捷方式「机械臂孔检测系统」就是启动它：

```bat
:: 把源码铺到交付位置（模型见 §6.4）
xcopy /E /I E:\robot_project\robot_inspection\fused_app E:\robot_project\inspection_app
:: 启动
E:\robot_project\robot_inspection\.venv\Scripts\pythonw.exe E:\robot_project\inspection_app\app.py
```

界面提供：**相机实时画面 + 抓拍／离线检测（可一次选多张）／点孔选择本次要测的孔／设备连接／
实验记录（载入工作区·看图·看检测报告·删除整批）／模型与数据管理（标注 + 增量训练）**。

> 本仓库的 `app/` 只是**视觉核心库**（推理 / 拟合 / 编号），没有界面代码；
> 更早的我方 PySide6 界面已归档到 `_archive/gui_v1_pyside6/`。
> **界面以 `fused_app/` 为准**（朋友上传的 `engine_bore_local/` 只作引擎侧参考，不覆盖这套界面）；
> 交付、引擎更新与自检流程见 [§6.4](#64-软件怎么交付--引擎怎么更新--怎么自检)。

### 6.2 命令行推理

```bat
.venv\Scripts\python.exe scripts\predict_holes.py --weights weights\best.pt --source <图片或目录>
```

输出：每张图一张可视化结果（掩膜 + 椭圆 + 孔心 + H01~H04）与结构化 JSON。

### 6.3 训练

```bat
:: 冒烟测试（1 轮，验证流程）
.venv\Scripts\python.exe scripts\train_seg.py --epochs 1 --name smoke_test

:: 正式训练（默认 100 轮）
.venv\Scripts\python.exe scripts\train_seg.py
```

默认参数针对 4 GB 显存：`imgsz=640`、`batch=2`、`workers=2`、`patience=20`、`device=0`。
**显存不足时会自动降级重试**（batch 2→1、imgsz 640→512→416），不需要人工排查。

### 6.4 软件怎么交付 / 引擎怎么更新 / 怎么自检

**① 交付（推荐）：界面以本仓库的 [`fused_app/`](fused_app/README.md) 为准**

`fused_app/` 就是我们这套「双机械臂孔检测系统」的**完整源码**（所有本地补丁已应用，实测可跑通全流程）。
交付/使用时把它铺到运行目录，再把模型放进去即可：

```bat
xcopy /E /I E:\robot_project\robot_inspection\fused_app E:\robot_project\inspection_app
:: 模型不进 Git：把 bore_best.pt / part_best.pt / fusion_v1_best.pt 放到 inspection_app\models\
::   （GitHub Release `v1.1-model`、朋友模型包，或本机 weights\best.pt 复制改名）
E:\robot_project\robot_inspection\.venv\Scripts\pythonw.exe E:\robot_project\inspection_app\app.py
```

**② 朋友更新了引擎源码时：只取引擎，不换界面**

| 来源 | 作用 |
| --- | --- |
| `engine_bore_local/` | 他上传的源码快照，**只作引擎侧参考**；他自带的那套「实时采集 / 测量模式」界面**不覆盖我们的界面** |
| `scripts/patch_friend_engine.py` | 当初生成 `fused_app/` 的补丁脚本（幂等，每步打印 已改/已是最新/未匹配），用来比对他改了什么 |
| `scripts/app_addons/` | 我方新增模块（Orbbec 相机驱动 `orbbec_camera.py`、实时预览窗口 `camera_preview.py`） |

```bat
:: 把他的新源码铺到临时目录 → 跑补丁 → 与 fused_app\ 逐文件比对，只挑引擎（detect_core/拟合/训练）改动
git archive origin/feature/fusion engine_bore_local | tar -x -C E:\robot_project\_engine_sync --strip-components=1
E:\robot_project\robot_inspection\.venv\Scripts\python.exe E:\robot_project\robot_inspection\scripts\patch_friend_engine.py --engine E:\robot_project\_engine_sync
```

**③ 自检（改完界面或补丁必须跑）**

```bat
set CODEX_APP_DIR=E:\robot_project\inspection_app
set CODEX_E2E_DIR=%TEMP%\inspection_e2e
E:\robot_project\robot_inspection\.venv\Scripts\python.exe E:\robot_project\robot_inspection\scripts\check_inspection_app.py
```

界面要点（2026-10-08 起）：

- **视觉检测区左右分屏**：左格＝相机实时画面（只看，不响应点击），右格＝检测结果（识别/标定后的孔图）。
  点右格的孔即可选中/取消，选中的孔**椭圆变绿 + 圆心打勾**，右格角标写清「本次要测：H0x」，表格同步打勾。
  分隔条可拖，两侧都有最小宽度（**拖到头也不会把某一格拖没**）；关掉实时时左格收起、右格占满。
- **抓拍**：把当前实时帧无损留样并放进工作区（不自动检测）；「用工业相机拍照」与它共用同一段取流代码，不会抢相机。
- **实验记录**：查看/导出/载入到工作区/打开原图·结果图·检测报告/删除整批记录（只删记录，磁盘上的文件保留）。
- **设备参数不落盘**：设备信息只在本次运行有效（相机插上自动识别型号与序列号；机械臂按当前电脑实际 IP 填写），
  换一台电脑不需要清理本机配置。

> 口径说明：**界面以 `fused_app/` 为准**。`engine_bore_local/` 是朋友较新的一版源码，
> 里面是他自己的「实时采集 / 测量模式」界面，与本仓库的补丁有若干处对不上（跑补丁会打印「未匹配」）——
> 这不影响交付版；要吸收他的引擎改进时按上面 ② 的流程做，界面不跟着换。

---

## 7. 数据集

| 项目 | 值 |
| --- | --- |
| 类别 | `cylinder_bore`（单类别，YOLO-Seg 多边形标签） |
| 规模 | 28 张标注图像（自有 25 张 + 外部补充 3 张），训练/验证按 25/3 划分 |
| 结构 | `images/{train,val}` + `labels/{train,val}` + `data.yaml` |

数据集**不进入 Git**（体积大、且含现场照片），通过发布页附件或本地数据盘分发。
放置好后可用 `scripts/check_dataset.py` 校验图像与标签是否一一对应。

---

## 8. 目录结构

```
<项目根目录>/
├── app/                     视觉核心库（推理 → 掩膜 → 椭圆 → 编号）
├── fused_app/               **我们这套界面的权威源码**（融合版软件，交付直接用它）
├── scripts/                 训练 / 推理 / 评估 / 数据与实验工具
│   ├── patch_friend_engine.py   融合版软件的补丁脚本（幂等）
│   ├── check_inspection_app.py  融合版软件的端到端自检
│   └── app_addons/              我方新增模块（Orbbec 驱动、实时预览窗口）
├── engine_bore_local/       朋友的「箱体孔检测系统」源码（融合版软件的基底）
├── docs/                    文档（方案、对比、审核、进度）
├── configs/                 配置
├── experiments/             实验代码与轻量记录（模型与图片在发布附件中）
├── _archive/                历史实现归档（仅作参考）
├── weights/                 模型权重（不进 Git）
├── dataset/                 数据集（不进 Git）
├── test_images/             评估图像（不进 Git）
├── requirements.txt
└── README.md
```

---

## 9. 模型与数据管理

**原则：Git 只管代码与文档，模型与数据走发布附件或数据盘。**

- 模型与数据集体积超过 Git 的合理范围，且不可逆地撑大仓库历史
- 模型通过 **Release 附件**分发；数据集通过云盘或数据盘分发
- 每次提交前可运行 `scripts/check_git_safety.py`，确认没有模型/数据被误提交

当前基线模型：

| 项目 | 值 |
| --- | --- |
| 文件 | `weights/best.pt` |
| 类型 | YOLO11n-Seg，单类别 `cylinder_bore` |
| SHA256 | `EAEDA05109C1F69647CAA4F38BD7347848169F045A8304F16856AC48869EC5B4` |
| 大小 | 5,990,237 字节 |

---

## 10. 文档索引

| 文档 | 内容 |
| --- | --- |
| [`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md) | **项目进度与后续计划**（进度总表 + 未完成项） |
| [`docs/COMPARE_FIT_AND_MODEL.md`](docs/COMPARE_FIT_AND_MODEL.md) | 两种拟合策略与两个模型的实测对比、取舍依据 |
| [`docs/ELLIPSE_FIT_COMPARISON.md`](docs/ELLIPSE_FIT_COMPARISON.md) | 椭圆拟合方案对比（含叠加图） |
| [`docs/FUSION_V1_TRAINING.md`](docs/FUSION_V1_TRAINING.md) | 现役模型的训练记录与配置 |
| [`docs/FRIEND_PIPELINE_AUDIT.md`](docs/FRIEND_PIPELINE_AUDIT.md) | 外部方案的复现审核与数据泄漏排查 |
| [`docs/FRIEND_REVIEW_20261008.md`](docs/FRIEND_REVIEW_20261008.md) | 朋友分支的复审与合并结论 |
| [`docs/CAMERA_ORBBEC_20261008.md`](docs/CAMERA_ORBBEC_20261008.md) | 工业相机（Orbbec）接入、网段配置与「换电脑恢复」步骤 |
| [`docs/PROJECT_FILES.md`](docs/PROJECT_FILES.md) | 文件分类与分发方式 |
| [docs/UI_OPTIMIZATION_NOTES.md](docs/UI_OPTIMIZATION_NOTES.md) | 界面优化建议 |
| [docs/APP_AUDIT_20261007.md](docs/APP_AUDIT_20261007.md) | **软件实测审核记录**（发现的问题与实际修复） |
| [`TEAM_WORKFLOW.md`](TEAM_WORKFLOW.md) / [`BRANCH_PLAN.md`](BRANCH_PLAN.md) | 开发协作规范 |
| [`DATA_AND_MODEL_MANAGEMENT.md`](DATA_AND_MODEL_MANAGEMENT.md) | 模型与数据管理规则 |

---

## 11. 当前进展与路线图

**已完成**

- 环境搭建（Python + CUDA + 深度学习框架）
- 数据集整理与校验
- 基线训练 + 多随机种子对照实验（38/40 = 95%）
- 椭圆拟合升级（稳健拟合 + 孔口边缘精修）与孔心定位
- 孔位编号（PCA 主轴排序）与编号稳定性研究
- 图形界面软件（检测 / 设备连接 / 实验记录 / 模型与数据管理 / 标注）
- 外部数据集的审计（未用于训练，未生成伪标签）
- **融合版界面**（2026-10-08）：视觉检测区左右分屏（实时 / 检测结果）、点孔选择本次要测的孔并给出图上反馈、
  实验记录工具（载入工作区 / 看原图·结果图·报告 / 删除整批）、设备参数不落本机
- **工业相机接入**（2026-10-08）：Orbbec Gemini 335Le 驱动 + 启动自动连接 + 实时画面 + 无损抓拍留样
- **补丁脚本工程化**（2026-10-08）：幂等化、修掉重复插入与崩溃，新增端到端自检脚本

**待完成（按优先级）**

| 优先级 | 事项 | 说明 |
| --- | --- | --- |
| P0 | 明确测量基准 | 确定测量目标为"倒角外圈"还是"缸孔内壁"（两者孔心可差 20 px 以上），并写入文档 |
| P0 | 扩充评估集 | 增加不同角度、光照与箱体样本，统计真实漏检率 |
| P1 | 相机标定 | 内参 + 畸变校正，建立像素与实际尺寸的对应关系 |
| P1 | 手眼标定 | 像素坐标 → 机器人坐标（平面可用单应矩阵，三维需深度信息） |
| P1 | 补丁与新源码同步 | 朋友新版自带「实时采集 / 测量模式」界面，需要与我们的整合版做一轮取舍后再重建 |
| P2 | 机器人接入 | 实现运动与测量接口；**先只读 → 再点动 → 最后自动**，并加软限位与急停 |
| P3 | 模型持续迭代 | 补足难样本（高反光、大角度斜视）后重训，保持同一评估口径 |

---

## 12. 已知限制

1. **H01~H04 是当前图像内的编号**，不是永久物理孔号（旋转 180° 会对调）。
2. 检测输出为**图像像素坐标**，**尚未**完成相机标定与手眼标定，**不能**直接作为机器人坐标使用。
3. 机器人接口当前为仿真实现，界面中机器人状态恒为"未连接"，不会驱动真实设备。
4. 评估仅覆盖**有限的实拍样本**，不代表所有工况；换箱体/相机/光照后需重新验证。
5. 外部数据集仅用于审计与方案评估，**未参与训练**，也未生成伪标签。
6. **交付目录 `inspection_app` 不在本仓库内**（含模型、实验记录与现场照片）；本仓库只保存它的源码基底与生成脚本，
   仓库内任何模型/数据都由发布附件分发。

---

## 13. 许可

本仓库用于研究与工程验证。引用的第三方数据集、运行库与模型权重遵循其各自的许可协议；
商业使用前需自行复核全部依赖与权重的许可条款。
