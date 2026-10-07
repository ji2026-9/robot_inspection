# 朋友分支审核报告与合并方案

审核日期：2026-10-07
审核对象：`origin/feature/fusion`（commit `d32f575`）
附带产物：Release 标签 `v1.0-fusion-data`（29 个附件，2,292.2 MB）

---

## 一、总体结论

**上传是规范、干净的，可以放心继续协作。** 三件事他做对了：

1. 分支是从本仓库 `main`（`7952f01`）**正常分出来的**，不是另起炉灶的独立仓库 → 以后合并不会有"无关历史"的麻烦。
2. **没有把模型/数据集/图片塞进 Git**：他分支里最大的文件是 316 KB 的 `active_models.json`，全仓库 180 个文件里没有任何 `.pt / .zip / .jpg / 数据集`。
3. 大文件（2.29 GB）全部走 Release 附件，并且**在说明里写清了自己没做完的部分**（"三维定位与机械臂自动测量尚未完成"）。

他对 `.gitignore` 的改动只有一处（末尾追加规则），没有覆盖任何原有内容，**没有污染 main，也没有改动本仓库 `app/` 里的任何代码**。

### 审核数据

| 项目 | 结果 |
| --- | --- |
| 与 main 的关系 | 从 `7952f01` 分出，可正常合并（**非**无关历史） |
| 新增文件 | 93 个（其中 `engine_bore_local/` 占 93 个） |
| 修改文件 | 1 个：`.gitignore`（只追加，没删原有的） |
| 总行数 | +25,343 行 |
| 分支内最大文件 | `engine_bore_local/active_models.json`，316.6 KB |
| 是否有 `.pt/.zip/图片/数据集` 进入 Git | **没有** ✅ |
| 敏感信息扫描（token/密码/私钥） | **没有** ✅ |
| 硬编码盘符 | 142 处，但绝大多数在他自己的脚本默认值/归档脚本里，核心模块用的是相对路径 |

---

## 二、他做了什么（值得肯定的部分）

他的 `engine_bore_local/` 是一套**独立可运行的 Windows 桌面软件**（"箱体孔检测系统 1.0.0"），而不是简单复制：

| 内容 | 说明 |
| --- | --- |
| 双模型方案 | 一个 **part 模型**（定位箱体区域）+ 一个 **bore 模型**（找孔），用 part 约束筛选哪些孔属于目标工件 |
| 稳健椭圆拟合 | `robust_bore_ellipse.py`：轮廓按弧长重采样 + 残差/梯度加权，不是直接 `cv2.fitEllipse` |
| 反光孔口精修 | `edge_bore_refinement.py`：沿法线做亚像素梯度搜索，专门处理孔内壁高反光 |
| 补检策略 | 多尺度 + 旋转 90/270/180 复查 + 箱体方向补检，**漏检时提示复核，不自动编造圆心** |
| 机器人只读接入 | `dobot_feedback.py`：DOBOT V4 反馈协议（30004 端口）纯只读解码，**不发任何运动指令** |
| 数据管理 | 内置 Labelme 标注、增量训练、实验记录、CSV 导出 |
| 打包 | `packaging/`：Inno Setup 安装包 + C# 启动器，可产出双击安装的 exe |
| 文档 | 每份实验都写了结论、限制和"不能外推"的说明，没有夸大 |

特别值得注意的一条**他自己的负面结论**：

> "本地验证集 021~025 中，022~025 被朋友用于训练。因此不能用这 5 张作为两个既有模型公平的共同验证集。"

这说明他清楚数据泄漏的坑，没有拿重叠数据刷分数。

---

## 三、他的实测结果（**读的时候注意视角**）

> ⚠️ 他在文档里说的"**朋友模型**"指的是**我们这边的 `best.pt`**（以他的视角，我们才是"朋友"）；
> 他说的"**当前模型**"指的是他本机软件用的 `engine_part_bore_100.pt`。别读反了。

照片：他那边第二组实验 3 张 + 我方交付包 `test_images` 4 张 = 7 张。固定阈值 0.5。

| 方案 | 最终保留 4 孔 | 拟合出 4 圆心 | 最低保留置信度 |
| --- | ---: | ---: | ---: |
| **他的本地模型**（`engine_part_bore_100.pt`，960 输入） | 7/7 | 7/7 | 0.8963 |
| **我方的 `best.pt`**（640 输入，原尺寸掩膜） | 5/7 | 5/7 | 0.6514 |
| 双模型融合 | 7/7 | 7/7 | 0.8963 |

他另外做了一轮**统一 960 输入**的控制对照，我方 `best.pt` 仍是 5/7（`comparison_controlled_960.json`），
所以差距**不是**输入尺寸造成的。

这条要**如实记下来**：在这 7 张图上，**他的模型比我们现在的 `best.pt` 强**（7/7 vs 5/7）。
这与我方自己的实测一致 —— 我们对 `test_images` 4 张的结果是 3 张 4/4 + 1 张 3/4 = 5/7 口径吻合。

但有三条限制，不能就此下"他的模型更好"的结论：

1. 7 张里 3 张是他自己拍的；我方 4 张（测试1~4）我方模型本来就是"3 张 4/4 + 1 张 3/4"。
2. 没有人工孔口标注和圆心真值，"4 个圆心"只表示**通过了拟合质量检查**，不代表物理测量精度。
3. 他的结果来自**整套管线**（part 约束 + 旋转复查 + 反光精修 + 稳健拟合），
   不能单独归因于模型权重。他自己在 `PART修正说明.md` 里也写了同样的免责。

**结论**：他有**值得借鉴的补检与约束策略**；要判定"哪个模型更准"，必须重新采一批
两边都没训练过的新照片、人工标注孔口后再比。

---

## 四、三方分歧（必须先对齐，否则合并会打架）

| 分歧点 | 他的做法 | 本项目做法 | 建议 |
| --- | --- | --- | --- |
| 漏检时怎么办 | 早期脚本用 `conf-floor=0.1` 取前 4 个 | 固定 `conf=0.5`，不足 4 个就报"检测不完整" | **保持 0.5**（他自己实测也认可） |
| 图像输入尺寸 | 640 方形 | 960（训练 640，推理用 960 更稳） | 保留两种，用参数控制 |
| part 的语义 | 实际只覆盖"箱体上平面" | 原来没有 part 概念 | 采用他的 part，但**文档里写清它是"上平面"而不是完整零件轮廓** |
| 编号 H01~H04 | 只作当前图像排序 | 同样只作当前图像排序 | 双方一致：**都不是永久物理孔号** ✅ |
| 数据划分 | 022~025 已被他用于训练 | 021~025 是我的验证集 | **这 5 张不能当公平验证集**；要正式比较必须采新照片重新标注 |

---


## 五、合并方案（按优先级，小步走）

### 第 1 档：强烈建议合并（低风险、立刻有用）

| 文件 | 行数 | 为什么值得要 | 依赖 |
| --- | ---: | --- | --- |
| `engine_bore_local/robust_bore_ellipse.py` | 77 | 稳健椭圆拟合，比现在的 `cv2.fitEllipse` 更抗噪、抗反光 | 仅 numpy / cv2 |
| `engine_bore_local/edge_bore_refinement.py` | 163 | 反光孔口的亚像素边缘精修 | 仅 numpy / cv2（依赖上面那个） |
| `engine_bore_local/inspection_gui/dobot_feedback.py` | 120 | DOBOT V4 只读反馈解码，正好接上本项目的机器人阶段 | 纯标准库 |
| 三份审计/结论文档 | — | `PART修正说明.md`、`friend_fusion_v1/对比结论.md`、`hybrid_labels_v1/.../visual_findings.md` | 无 |

**做法**：复制到本项目 `app/`（几何部分可放 `app/geometry/`），**不修改他分支里的原文件**；
然后写一个对比脚本，用我们自己的 4 张测试图跑「现有 `cv2.fitEllipse`」vs「他的稳健拟合」，
比较圆心偏差与残差，**只有确实更好才切换默认**。

### 第 2 档：值得优先评估（要先拿模型，改动较大）

> **优先级已上调**：因为第三节那张表显示，他的"part 约束 + 补检 + 稳健拟合"整套管线
> 在 7 张图上做到 7/7，而我方 `best.pt` 直出只有 5/7。**最值得先复现的就是他的补检策略。**

| 内容 | 说明 |
| --- | --- |
| `detect_core.py`（369 行）+ `part_predictor.py` | 他的完整检测管线（part 约束 + 旋转复查 + 反光处理）。需要 Release 里 `models.zip` 的 `part_best.pt` / `bore_best.pt`。功能与现有 `app/vision.py` 重叠，建议作为**可切换的第二方案**，不要直接替换 |
| `inspection_gui/` 整套界面（约 2,000 行） | 功能更全（设备连接窗口、3D 模拟、界面内训练）。但本项目 GUI 已能跑，**两套界面同时维护成本高**，建议二选一；可先借鉴 `devices_view.py`、`simulation_scene3d.py`、`dataset_window.py`、`training_bridge.py` 的思路 |
| `packaging/` | 想做成"双击安装的 exe"时可直接复用（Inno Setup + C# 启动器） |
| `runtime_versions.json` | 他的依赖版本清单，可用于版本对齐 |
| `hybrid_annotations.py` / `dataset_update.py` | 融合标注与增量训练，等确定要"扩数据集"时再评估 |

### 第 3 档：不建议合并（重复或只作归档）

| 内容 | 原因 |
| --- | --- |
| `engine_bore_local/friend_gui_source/`（34 个文件） | **是我方交付包源码的副本**，和仓库根的 `app/` 完全重复，合并会变成两份同源代码 |
| `engine_bore_local/friend_package/package_v1/`（8 个文件） | 同上，早期交付包副本 |
| Release 里的 `archive_*.zip`（约 2.2 GB） | 归档资料，留在 Release 就够了，不要进 Git |
| `experiments/hybrid_labels_v1/spotcheck_images/visual_spotcheck.py` | 里面写死了他机器的 `C:\Users\86189\...`，属于一次性归档脚本 |

---

## 六、建议的执行顺序

1. **先做第 1 档**（约 360 行代码 + 3 份文档），在 `feature/vision` 上做，跑通对比脚本后再合进 `main`。
2. **复现他的补检策略**：把他 `models.zip` 里的 part 模型和 `detect_core.py` 在**我们自己的 4 张图 + 他说的那 3 张**上跑一遍，
   确认 5/7 → 7/7 的差距到底来自哪里（part 约束？旋转复查？反光精修？还是模型本身）。这是本次审核里**信息量最大的一步**。
3. **对齐分歧表**（第四节），把结论写进 `README.md`，避免以后两边做法打架。
4. **决定"一套界面还是两套"** —— 建议以本项目 `app/` 为主界面，他的界面作为参考实现保留在 `feature/fusion`。
5. **决定要不要 part 模型** —— 如果要，从 Release 的 `models.zip` 取 `part_best.pt`、`bore_best.pt`，放进本地 `weights\`（不进 Git）。
6. **要正式比较两个模型时**，先**新拍一批照片**（不要用 021~025 里被训练过的），人工标好孔口多边形，再算圆心误差。在那之前，任何"谁更准"的说法都只能算工程判断，不能算实验结论。

---

## 七、合并命令（只取文件，不要他的历史）

```bat
cd /d E:\robot_inspection
git fetch origin

:: 先看一眼差异（只读）
git diff --stat main origin/feature/fusion

:: 只想拿某几个文件
git checkout origin/feature/fusion -- engine_bore_local/robust_bore_ellipse.py
git checkout origin/feature/fusion -- engine_bore_local/edge_bore_refinement.py
git checkout origin/feature/fusion -- engine_bore_local/inspection_gui/dobot_feedback.py

:: 拿文档
git checkout origin/feature/fusion -- engine_bore_local/PART修正说明.md

:: 提交前检查
E:\robot_inspection\.venv\Scripts\python.exe E:\robot_inspection\scripts\check_git_safety.py
```

> 不要直接 `git merge origin/feature/fusion`：那会把 `friend_gui_source/`、`friend_package/`
> 这些重复副本一起合进来，还会改 `.gitignore`。**按文件挑**才是我们要的方式。
