# 机械臂智能视觉检测系统 —— 项目进度与后续计划

更新日期：2026-10-08
项目路径：`E:\robot_project\robot_inspection`
仓库：https://github.com/ji2026-9/robot_inspection （私有）

---

## 一、一句话现状

> **2026-10-07 目录整理**：原来散落在 `E:\` 根目录的 4 个项目文件夹，
> 已全部归纳到 **`E:\robot_project\`**（见文末「十四」）。
> 本文所有路径均已更新为新位置。

**视觉检测这条线已经跑通并验证**：4 张实拍测试图 **16/16** 个孔全部检出，
椭圆拟合 + PCA 编号 + GUI + 任务生成都能用；代码和文档已上 Git，
模型通过 GitHub Release 分发。**下一步是"标定 + 接真机"**，这部分还没开始。

> **2026-10-08 更新**：界面统一到融合版软件 `E:\robot_project\inspection_app`
> （朋友的双机械臂孔检测系统 + 我方补丁），本轮完成：
> ① 工业相机 Orbbec Gemini 335Le 接入（启动自动连接 + 视觉检测区实时画面 + 无损抓拍）；
> ② 视觉检测区**左右分屏**（左＝实时画面，右＝检测结果），在结果图上**点孔选择本次要测的孔**并给出图上反馈；
> ③ 实验记录窗口补齐**载入到工作区 / 打开原图·结果图·检测报告 / 删除整批记录**；
> ④ **设备参数不落本机**（换电脑不需要清配置）；
> ⑤ 补丁脚本幂等化 + 新增端到端自检脚本（见「九、常用命令」）。
> 「二、硬件与环境」里旧的「机械臂智能视觉检测系统」桌面入口已由融合版取代。

---

## 二、硬件与环境

| 项目 | 值 |
| --- | --- |
| 显卡 | NVIDIA GeForce RTX 3050 Ti Laptop（4 GB） |
| 驱动 | 610.60（CUDA UMD 13.3） |
| Python | 3.11.14（`E:\Miniconda3`）+ 虚拟环境 `E:\robot_project\robot_inspection\.venv` |
| 关键库 | torch 2.5.1+cu121、ultralytics 8.4.173、opencv 5.0.0、numpy 2.4.6、PySide6 6.11.2 |
| 启动软件 | 双击桌面「机械臂孔检测系统」＝融合版 `E:\robot_project\inspection_app\app.py`（`.venv\Scripts\pythonw.exe` 启动） |
| 排查用 | 用同一条命令但把 `pythonw.exe` 换成 `python.exe`，报错会打在控制台里 |
| 界面来源 | 朋友「双机械臂孔检测系统」源码 `engine_bore_local\` + 我方补丁 `scripts\patch_friend_engine.py` |
| 早期界面 | 我方旧版 PySide6 界面已归档到 `_archive\gui_v1_pyside6\`，不再日常使用 |

---

## 三、已完成（按阶段）

| # | 阶段 | 状态 | 产物 / 证据 |
| ---: | --- | --- | --- |
| 1 | 环境搭建（Python + CUDA + ultralytics） | ✅ | `.venv`、`requirements.txt` |
| 2 | 数据集整理与校验 | ✅ | `dataset\box_yolo`（20/2/3） |
| 3 | 基线训练 | ✅ | Mask mAP50 ≈ 0.995 |
| 4 | 5 个 seed 正式对照实验 | ✅ | **38/40 = 95%**（`experiments\formal_seed*`） |
| 5 | 椭圆拟合 + PCA 编号 H01~H04 | ✅ | `scripts\predict_holes.py` |
| 6 | GUI 软件（检测 / 任务 / 模拟执行 / 保存） | ✅ | `app\`，**73/73 自测通过** |
| 7 | 编号稳定性研究 | ✅ | `experiments\stable_hole_id`（证明 H01~H04 非永久身份） |
| 8 | 外部数据集审计（T-LESS 等，未做伪标签） | ✅ | `external_datasets\reports` |
| 9 | 模型交付包 | ✅ | `friend_transfer\robot_inspection_gui_v1.zip` |
| 10 | Git 双人协作体系 | ✅ | `.gitignore`、`TEAM_WORKFLOW.md`、`check_git_safety.py` |
| 11 | 审核并合并朋友分支 | ✅ | 3 个文件 + 3 份审计结论（`docs\FRIEND_*`） |
| 12 | **椭圆拟合升级**（稳健 + 反光孔口边缘精修） | ✅ | 边缘贴合度 7 倍；最深处偏差 34.8 px → 7.05 px |
| 13 | **fusion_v1 重训**（28 张数据） | ✅ | **16/16**，`weights\best.pt` 已提升 |
| 14 | 发布新模型 | ✅ | Release `v1.1-model` |

---

## 四、当前性能（可复现）

条件：`conf = 0.50`，同一套检测流程（`app\vision.py`），椭圆拟合 = robust_edge。

| 图片 | 旧模型 | **现役 fusion_v1** | 最低置信度 |
| --- | --- | --- | ---: |
| 测试1.jpg | 4/4 | **4/4** | 0.886 |
| 测试2.jpg | 4/4 | **4/4** | 0.978 |
| 测试3.jpg | **3/4** | **4/4** | **0.775**（旧模型只有 0.172） |
| 测试4.jpg | 4/4 | **4/4** | 0.960 |
| **合计** | 15/16 | **16/16** | — |

- 单张推理 0.6~0.7 秒（RTX 3050 Ti）
- GUI 自测 73/73、冷启动回归 PASS
- 模型：YOLO11n-Seg，单类别 `cylinder_bore`，SHA256 `EAEDA05109C1F696…`

---

## 五、数据与模型资产

| 资产 | 位置 | 说明 |
| --- | --- | --- |
| 原始数据集（25 张） | `dataset\box_yolo\` | 20 train / 2 val / 3 test |
| 训练集（28 张） | `E:\robot_project\fusion_train\dataset_v28\` | 25 自有 + 朋友新增 3 张，25/3 划分 |
| 原始压缩包 | `E:\vm_share\box_yolo_dataset.zip` | 81 MB |
| 现役模型 | `weights\best.pt` | fusion_v1（16/16） |
| 模型留档 | `weights\fusion_v1_best.pt` | 同一份副本 |
| 旧模型备份 | `weights\best_backup_20261007_before_fusion.pt` | 可一键回退 |
| 朋友的代码与数据 | 分支 `feature/fusion` + `E:\robot_project\_reference\friend_engine_audit\` | 他的 Release：`v1.0-fusion-data` |

---

## 六、GitHub 协作现状

| 项目 | 状态 |
| --- | --- |
| 仓库 | **私有**（只有你和被邀请的协作者能访问） |
| 分支 | `main`（稳定）、`feature/vision`（你）、`feature/fusion`（朋友） |
| 最新提交 | 见 `git log -1 --oneline`（截至 2026-10-08：融合版界面 + 工业相机 + 补丁工程化） |
| Release | `v1.1-model`（新模型 3 个附件）、`v1.0-data`（数据集/结果 8 个）、`v1.0-fusion-data`（朋友的 29 个） |
| 协作规范 | `TEAM_WORKFLOW.md`、`BRANCH_PLAN.md`、`DATA_AND_MODEL_MANAGEMENT.md` |
| 每次提交前 | 跑 `scripts\check_git_safety.py`（保证模型/数据不会误进 Git） |

完整文档索引见 `docs\README.md`。

---

## 七、还没做的（重要）

| # | 未完成项 | 为什么关键 |
| ---: | --- | --- |
| 1 | **孔口定义统一**：测的是"倒角外圈"还是"缸孔内壁"？ | 两者圆心可差 26 px；不定清楚，坐标转换一定系统性偏 |
| 2 | 相机标定（内参 + 畸变） | 像素 → 真实尺寸的前提 |
| 3 | 手眼标定（像素坐标 → 机器人坐标） | 机械臂对准孔的前提 |
| 4 | 真实机械臂接入 | 现在只有 `MockRobot`，界面恒显示"未连接" |
| 5 | ~~工业相机接入~~（**2026-10-08 已完成**） | Orbbec Gemini 335Le 已接入：启动自动连接、实时画面、无损抓拍留样 |
| 6 | 孔编号的永久物理身份 | 现在 H01~H04 只是当前图像内的排序，旋转 180° 会对调 |
| 7 | 多箱体 / 多光照泛化验证 | 只在这 4 张同箱体照片上验证过 |
| 8 | 深度 / 高度信息 | 当前只有平面像素坐标，没有三维信息 |

---

## 八、后续方向（建议按这个顺序）

### P0 · 先做（1~2 天，不需要新硬件）

1. **定死测量目标**：放大确认要测的是缸孔内壁（推荐，它是圆柱面）还是倒角外圈，写进 `README.md`。
2. **补测试集**：再拍 10~20 张（不同角度/光照，最好换一个箱体），跑现有模型看漏检率。
3. 每有进展就更新本文件一行，让它当主进度表。

### P1 · 标定（需要标定板）

4. 相机内参标定：拍 15~20 张棋盘格 → `cv2.calibrateCamera` → 存 `configs\camera_intrinsics.json`。
5. 手眼标定：
   - 只要平面测量：用 3~4 个已知点求单应矩阵（像素 → 机器人 XY）。
   - 要三维：加深度相机，或用已知高度的标定块。
6. 标定结果（小文件）进 `configs\`；标定照片放数据区，不进 Git。

### P2 · 接真机

7. `app\robot_interface.py` 实现 `connect / move_to_target / execute_measurement / stop`。
   - `app\dobot_feedback.py` 已有 DOBOT V4 **只读**反馈解码，可直接做状态监测。
   - **先只读 → 再点动 → 最后自动**，必须加软限位和急停。
8. `app\camera_interface.py` 接工业相机 SDK（网口/USB3），替换 `ImageFileCamera`。

### P3 · 模型与数据继续提升

9. 数据集继续扩：重点补"孔内壁高反光""斜视大角度"两类难样本。
10. 重训保持同一评估口径（4 张测试图 + `conf=0.50`），新模型用新文件名（如 `fusion_v2_best.pt`）。
11. 朋友侧：把数据融合实验结果并进来做 A/B 对照。

### P4 · 软件体验

12. GUI 增加"坐标转换面板"（像素 → 机器人坐标，显示标定状态）。
13. 批量检测（一次选多张）+ 导出 Excel 报告。
14. 把检测任务和实验记录汇总成可打印的质检单。

---

## 九、常用命令

```bat
:: 启动软件（也可以直接双击桌面「机械臂孔检测系统」）
E:\robot_project\robot_inspection\.venv\Scripts\pythonw.exe E:\robot_project\inspection_app\app.py

:: 融合版界面端到端自检（改完界面/补丁务必跑；离屏跑真实检测器 + 界面对象，不碰真实实验记录）
set CODEX_APP_DIR=E:\robot_project\inspection_app
set CODEX_E2E_DIR=%TEMP%\inspection_e2e
E:\robot_project\robot_inspection\.venv\Scripts\python.exe E:\robot_project\robot_inspection\scripts\check_inspection_app.py

:: 从朋友的源码重新生成融合版软件（幂等；他更新源码后重跑）
E:\robot_project\robot_inspection\.venv\Scripts\python.exe E:\robot_project\robot_inspection\scripts\patch_friend_engine.py

:: 提交前安全检查（确认模型/数据没进 Git）
E:\robot_project\robot_inspection\.venv\Scripts\python.exe E:\robot_project\robot_inspection\scripts\check_git_safety.py

:: 椭圆拟合方式对比（顺带相当于跑一遍 4 张测试图）
E:\robot_project\robot_inspection\.venv\Scripts\python.exe E:\robot_project\robot_inspection\scripts\compare_ellipse_fit.py

:: 回退到旧模型
copy /Y E:\robot_project\robot_inspection\weights\best_backup_20261007_before_fusion.pt E:\robot_project\robot_inspection\weights\best.pt
```

---

## 十、文件地图（哪里找什么）

| 想找什么 | 去哪 |
| --- | --- |
| 软件源码 | `app\`（界面 `gui.py`、视觉 `vision.py`、任务 `task_manager.py`） |
| 训练与推理脚本 | `scripts\`（`train_seg.py`、`predict_holes.py`、`compare_ellipse_fit.py`） |
| 项目总说明 | `README.md` |
| 协作文档 | `TEAM_WORKFLOW.md`、`BRANCH_PLAN.md`、`DATA_AND_MODEL_MANAGEMENT.md` |
| 技术报告 | `docs\`（分类说明 / 椭圆拟合对比 / 朋友分支审核 / fusion_v1 训练记录 / 本文件） |
| 检测结果 | `results\gui_runs\<时间戳>\` |
| 训练输出 | `experiments\`、`runs\` |

---

## 十一、软件只有一个版本（2026-10-07 融合完成）

**最终版**：`E:\robot_project\inspection_app\`，桌面快捷方式「机械臂孔检测系统」。

他是"我方原界面"和"朋友版界面"融合后的唯一版本，取了两边的长处：

| 来自 | 内容 |
| --- | --- |
| 朋友版（主体） | 完整界面框架、设备连接窗口、实验记录、模型与数据管理、part 工件约束、旋转/多尺度补检、3D 模拟、his bore+part 模型 |
| 我方 | **椭圆拟合策略**（总是尝试孔口边缘精修，实测边缘贴合度提升 6.6 倍）、`_archive` 保留的 73 项自测与诊断脚本、中文路径安全读写 |

对比测量与取舍依据见 `docs\COMPARE_FIT_AND_MODEL.md`。
我方早期界面已归档到 `_archive\gui_v1_pyside6\`（只作参考，不再使用）。

**软件更新时**（拿到新代码后）：

```bat
cd /d E:\robot_project\robot_inspection
git fetch origin
git archive origin/feature/fusion engine_bore_local | tar -x -C E:\robot_project\inspection_app --strip-components=1
E:\robot_project\robot_inspection\.venv\Scripts\python.exe scripts\patch_friend_engine.py
```

> 第二行是**必须的**——他覆盖代码后要把我们的拟合策略重新打回去；
> `models\`、`data\`、`results\` 不在 Git 里，不会被覆盖。

---

## 十二、诚实边界（避免误用）

1. **H01~H04 是"当前图像内的编号"**，不是永久物理孔号（旋转 180° 会对调）。
2. **机器人状态永远显示"未连接"**；界面里的"模拟执行"是软件动画，不动真机。
3. 检测输出是**原图像素坐标**，**没有**做过标定/手眼转换，不能直接当机械臂坐标用。
4. 只在 4 张同箱体、有限视角的照片上验证过 16/16，**不代表所有工况**。
5. 外部数据集（T-LESS 等）只做过审计，**没有**用于训练，也没有制造伪标签。

---

## 十三、目录结构（2026-10-07 整理后）

```
E:\robot_project\                     ← 项目所有东西都在这一个文件夹里
├── robot_inspection\                 ← 主项目（Git 仓库 + .venv + 代码/数据/结果）
│   ├── app\ scripts\ docs\ configs\  ← 代码与文档
│   ├── weights\best.pt               ← 现役模型 fusion_v1
│   ├── dataset\ test_images\         ← 数据
│   ├── results\ runs\ experiments\   ← 结果与训练输出
│   └── .venv\                        ← 唯一的 Python 环境（5.3 GB）
├── inspection_app\              ← 朋友的软件（可直接运行）
│   ├── app.py                        ← 入口
│   ├── models\                       ← 他的 bore/part 模型（+ 我们的 fusion_v1 副本）
│   ├── data\database_seed\           ← 28 张标注图
│   └── .labelme_env\                 ← 标注环境（2026-10-07 新装）
├── fusion_train\dataset_v28\         ← 训练用的 28 张数据
└── _reference\                       ← 参考资料（可删）
    └── friend_engine_audit\          ← 审核时下载/导出的原始资料
```

**最近一次验证（2026-10-08）**：

- 4 张测试图 **16/16**（`scripts\predict_holes.py`，conf=0.50）
- `scripts\check_git_safety.py` **PASS**（模型/数据/大文件都没有进 Git）
- 融合版软件端到端自检 `scripts\check_inspection_app.py` **全部通过**（离屏跑真实检测器 + 界面对象）
- 桌面快捷方式「机械臂孔检测系统」可正常启动融合版（相机自动连接）

> 旧记录（仅供回溯）：我方早期 PySide6 界面 `selftest_full` **73/73**、冷启动 PASS ——
> 该界面已归档到 `_archive\gui_v1_pyside6\`，不再是日常使用的软件。

> `E:\Miniconda3`（Python 基础环境）和 `E:\vm_share`（你的共享文件夹）**没有动**。
