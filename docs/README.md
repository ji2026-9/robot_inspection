# docs\ 文档目录

这个目录放**项目文档**（不是代码，也不是数据）。目前项目的主要文档放在仓库根目录，
这里作为索引 + 以后放长文档 / 图纸 / 报告的地方。

---

## 一、仓库根目录的文档（先看这些）

| 文档 | 内容 |
| --- | --- |
| [`README.md`](../README.md) | 项目总览、本机环境、怎么训练 / 怎么检测、实际执行记录 |
| [`TEAM_WORKFLOW.md`](../TEAM_WORKFLOW.md) | 两个人怎么用 Git 协作（分支、提交、冲突处理） |
| [`DATA_AND_MODEL_MANAGEMENT.md`](../DATA_AND_MODEL_MANAGEMENT.md) | 模型和数据怎么管理 / 怎么共享 |
| [`BRANCH_PLAN.md`](../BRANCH_PLAN.md) | 分支规划与各自负责范围 |
| [`PROJECT_FILES.md`](PROJECT_FILES.md) | **文件分类与共享说明**（Git / Release 附件 / 不上传 三类） |
| [`FRIEND_UPLOAD_PROMPT.md`](FRIEND_UPLOAD_PROMPT.md) | **给朋友的提示词**：让他把自己的项目安全上传到独立分支 |
| [`FRIEND_REVIEW_AND_MERGE_PLAN.md`](FRIEND_REVIEW_AND_MERGE_PLAN.md) | **朋友分支审核报告 + 合并方案**（哪些值得合并、哪些别合并） |
| [`ELLIPSE_FIT_COMPARISON.md`](ELLIPSE_FIT_COMPARISON.md) | **椭圆拟合方式对比与采纳记录**（已采纳稳健+边缘精修） |
| [`FRIEND_PIPELINE_AUDIT.md`](FRIEND_PIPELINE_AUDIT.md) | **朋友管线复现审核**：5/7 vs 7/7 差距来自模型与训练数据量 |
| [`PROJECT_STATUS.md`](PROJECT_STATUS.md) | **项目进度与后续计划**（进度总表 + 未完成项 + 后续方向） |
| [`app\README.md`](../app/README.md) | GUI 软件说明（界面、分层结构、已知限制） |
| [`configs\README.md`](../configs/README.md) | 配置文件放哪里 |

## 二、不在 Git 里的报告（本机生成物）

下面这些是**生成结果**，体积大，**故意不进 Git**，只在本机（或用云盘传）：

| 路径 | 内容 |
| --- | --- |
| `results\` | 检测可视化图片、`detection_report.json`、`training_report.html` |
| `runs\` | YOLO 训练输出（权重、曲线、混淆矩阵） |
| `experiments\*.html` | 5 个 seed 的正式对照实验结果页（轻量的在 Git 里，图片不在） |
| `external_datasets\reports\` | 外部数据集审计报告（T-LESS / Workpieces） |
| `friend_transfer\` | 模型 + GUI 交付包 |

## 三、往这里放什么

- 阶段报告、验收文档、比赛材料（`.md` / `.pdf`）
- 标定说明、坐标系定义、接口约定
- 图片：**尽量别放**。确需放时请单独说明并调整 `.gitignore`，否则会被忽略规则挡掉。

## 四、提交前检查

```bat
E:\robot_project\robot_inspection\.venv\Scripts\python.exe E:\robot_project\robot_inspection\scripts\check_git_safety.py
```

确认输出 `RESULT: PASS`。
