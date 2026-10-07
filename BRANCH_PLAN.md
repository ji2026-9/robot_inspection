# 分支规划（BRANCH PLAN）

> 目的：两个人各改各的，互不踩脚；`main` 永远能跑。

---

## 分支总览

| 分支 | 谁负责 | 状态 | 内容 |
| --- | --- | --- | --- |
| `main` | 共用 | 稳定 | 比赛 / 演示用的稳定版本 |
| `feature/vision` | 我 | 开发中 | 视觉检测与 GUI |
| `feature/fusion` | 朋友 | 开发中 | 数据融合与训练实验 |
| `feature/robot` | 以后谁做谁建 | 未开始 | 机器人接口与坐标转换 |

---

## `main` —— 比赛稳定版本

只有**确认能跑通**的内容才合并进来。合并前至少确认：

1. GUI 能启动：`app\run_gui.bat`
2. 自测通过：`.venv\Scripts\python.exe app\selftest_full.py`
3. 安全检查通过：`.venv\Scripts\python.exe scripts\check_git_safety.py`

---

## `feature/vision` —— 我的工作

负责范围：

- YOLO 推理（`app\vision.py`）
- 孔检测、mask 后处理
- 椭圆拟合（`cv2.fitEllipse`）求孔中心
- `H01~H04` 编号（PCA 主轴排序）
- GUI 界面与交互（`app\gui.py`、`app\view_render.py`）
- 检测任务生成与结果保存（`app\task_manager.py`）
- 视觉接口（给机器人层调用的稳定接口）

我改这些文件前，先确认朋友没在改同一处（在群里说一声即可）。

---

## `feature/fusion` —— 朋友的工作

负责范围：

- 朋友自己的数据整理与审计
- 数据融合（把新数据并进训练集）
- 训练（`scripts\train_seg.py`，换超参 / 换 seed / 换模型规模）
- 模型比较（和 `best.pt` baseline 对比）
- 实验记录（写进 `experiments\*.md`）

注意：

1. **不要覆盖 `weights\best.pt`**，新模型叫 `fusion_v1_best.pt`。
2. 不要把数据集 / 模型 commit 进 Git，用云盘传。
3. 评估必须用同一套 4 张测试图和 `conf=0.50`，结果才有可比性。

---

## `feature/robot` —— 未来

负责范围：

- 机器人接口（`app\robot_interface.py`：实现 `connect / move_to_target / execute_measurement / stop`）
- 相机接口（`app\camera_interface.py`：换成真实工业相机）
- 像素坐标 → 机器人坐标转换
- 手眼标定
- 运动规划与执行

> 提醒：目前 `app\robot_interface.py` 里只有 `MockRobot`，**机器人状态永远显示"未连接"**，
> 不要把它当成已经接通真机。

---

## 合并流程（Pull Request）

1. 在自己分支上 `git push`
2. 到 GitHub 仓库页面点 **Compare & pull request**
3. 标题写清楚做了什么，例如 `feature/vision -> main: 完成 GUI 检测状态显示`
4. 另一个人看一遍改动（重点看有没有误提交模型/数据）
5. 没问题再 **Merge**

> 谁做的分支谁负责推，合并前先 `git checkout main && git pull` 保证本地 main 是最新的。
