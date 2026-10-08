# 双人协作流程（TEAM WORKFLOW）

> 这份文件只讲一件事：**我和朋友两个人怎么用 Git 一起改这个项目。**
> 每条命令都可以直接复制粘贴执行。
> 项目路径（本机）：`E:\robot_project\robot_inspection`

---

## 一、项目协作原则

1. **`main` 永远保持可运行** —— 任何时候别人 clone 下来都能跑起来。
2. **不直接在 `main` 上长期开发** —— 只在自己分支上写代码。
3. **每个人使用自己的 branch**（我的 = `feature/vision`，朋友的 = `feature/fusion`）。
4. **完成一个功能后就 commit**（不要攒一大堆再提交）。
5. **commit 之后 push 到 GitHub**。
6. **通过 Pull Request（PR）合并到 `main`**。
7. **合并前检查代码** —— 至少确认：改动文件符合预期、没有把模型/数据集带进去。

---

## 二、推荐分支

| 分支 | 谁用 | 内容 |
| --- | --- | --- |
| `main` | 共用 | 最终稳定版本（比赛/演示用） |
| `feature/vision` | 我 | 视觉检测、孔中心、H01~H04、GUI |
| `feature/fusion` | 朋友 | 数据审计、数据融合、训练、模型比较 |
| `feature/robot`（以后再加） | 谁做机器人谁建 | 机器人接口、坐标转换、运动规划 |

---

## 三、日常操作

### 开始工作前（每次都要做）

```bat
cd /d E:\robot_project\robot_inspection
git checkout main
git pull
```

然后进入自己的分支：

```bat
git checkout feature/vision
```

### 第一次创建分支（分支还不存在时）

我的：

```bat
git checkout -b feature/vision
```

朋友的：

```bat
git checkout -b feature/fusion
```

> 分支只需要创建一次。以后每次用 `git checkout feature/vision` 切回去就行。

---

## 四、提交（commit）

```bat
git status
git add 你改过的具体文件
git commit -m "简短说明修改内容"
```

例子：

```bat
git commit -m "完成视觉检测GUI"
git commit -m "增加融合训练实验脚本"
```

> 建议用 `git add <具体文件>`，不要无脑 `git add .`。
> 改完先跑一次安全检查：`python scripts\check_git_safety.py`

---

## 五、上传（push）

我的：

```bat
git push -u origin feature/vision
```

朋友的：

```bat
git push -u origin feature/fusion
```

> `-u` 只需要第一次加，之后直接 `git push`。

---

## 六、不要提交的东西

```
*.pt        *.pth       *.onnx      *.engine
dataset/    test_images/
runs/       logs/       results/
external_datasets/      friend_transfer/
.venv/
```

这些已经被 `.gitignore` 忽略。想确认有没有漏网，跑：

```bat
E:\robot_project\robot_inspection\.venv\Scripts\python.exe E:\robot_project\robot_inspection\scripts\check_git_safety.py
```

看到 6 行全部 `PASS` 才算安全。

---

## 七、模型和数据怎么共享（不走 Git）

| 内容 | 怎么传 |
| --- | --- |
| 模型权重 `best.pt` | 模型交付 ZIP / 云盘 / U 盘 |
| 数据集 | Google Drive / OneDrive / NAS / 移动硬盘 |
| 训练输出 `runs/` | 需要时单独打包传，不进 Git |

**GitHub 只管**：代码、配置、文档、实验说明。

细节见 `DATA_AND_MODEL_MANAGEMENT.md`。

---

## 八、如果发生冲突（conflict）

1. **不要直接删除对方代码。**
2. 先看清楚状态：

```bat
git status
```

3. 冲突文件里会出现这样的标记，两边内容都要保留判断：

```
<<<<<<< HEAD
（我的版本）
=======
（对方的版本）
>>>>>>> feature/fusion
```

4. **如果不会处理：停下来。** 把 `git status` 的输出发给对方，一起看。
5. 绝对不要执行下面这两条（会永久丢代码）：

```bat
git reset --hard      ← 禁止
git clean -fd         ← 禁止
```

除非你明确知道自己在做什么，并且已经确认过。

---

## 九、常见问题

**Q: 我改了代码但不想提交，只想先拉别人的更新？**

```bat
git stash          :: 先把自己的改动收起来
git checkout main
git pull
git checkout feature/vision
git stash pop      :: 再把改动放回来
```

**Q: 想看自己改了什么？**

```bat
git diff           :: 还没 add 的改动
git diff --staged  :: 已经 add 的改动
git log --oneline -10
```

**Q: 不小心把模型加进暂存区了？**

```bat
git restore --staged weights/best.pt
```

然后跑一次 `scripts\check_git_safety.py` 确认。
