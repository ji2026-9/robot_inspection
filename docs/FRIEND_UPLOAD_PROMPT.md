# 给朋友的提示词：把他电脑上的项目安全上传到协作仓库

> 用法：把下面「提示词正文」整段复制，发给你朋友；
> 他再整段粘贴给自己电脑上的 AI 助手（或自己照着做）。
> 本文档同时保存在仓库里，方便以后另一个人照着做。

---

## 一、这套做法的核心原则（你先知道）

| 原则 | 具体做法 |
| --- | --- |
| **不污染你的 main** | 朋友只往 **自己新建的分支 `feature/fusion`** 推，永远不碰 `main`、不碰 `feature/vision` |
| **不污染仓库体积** | 模型 / 数据集 / 图片 / zip 一律**不进 Git**，改走 GitHub **Release 附件**（标签 `v1.0-fusion-data`） |
| **不丢原始数据** | 全程只读 + 复制；不删、不移、不覆盖、不训练 |
| **合并由你决定** | 合并前你可以先 `git diff` 看他改了什么，再按文件挑选，不用整包吞下 |
| **双保险** | 他的分支推上去后，推送历史里**没有**任何模型/数据集；两边各自保留完整本地副本 |

为什么不让朋友 push 到 `main`：他电脑上那份项目是**独立初始化**的仓库（历史跟你不同），
如果推到 `main` 要么被 GitHub 拒绝（non-fast-forward），要么真的覆盖掉你的工作。
推到**新分支**则 100% 安全，而且以后合并只需要一条命令。

---

## 二、提示词正文（复制这一段发给朋友）

```
你现在在我（朋友的电脑）上操作这个项目：<把项目路径填在这里，例如 D:\robot_inspection>

目标：把我电脑上这个项目的全部文件，安全地上传到一个协作 GitHub 仓库的**独立分支**上，
不能碰别人的 main 分支，也不能把大文件塞进 Git 历史。

协作仓库（我已经被加为协作者，账号登录好）：
    https://github.com/ji2026-9/robot_inspection

========================
一、最高优先级安全规则（必须遵守）
========================
1. 全程**只读 + 复制**：绝对不删除、不移动、不重命名、不覆盖我电脑上的任何原始文件。
2. **不要训练模型**：不要调用 model.train()，不要启动任何训练。
3. **不要修改数据集、测试图片、已有模型**（weights\*.pt）。
4. **绝对不许把模型 / 数据集 / 图片 / zip 提交进 Git**（后面有分类规则）。
5. **绝对不许 push 到 main**，也不许改别人的分支。
   如果 push 出现 "rejected" / "non-fast-forward" / "would overwrite"，**立刻停下**，
   把完整报错发给我，**不要**加 -f / --force / --force-with-lease。
6. 不许执行：git reset --hard、git clean -fd、git push --force、rm -rf 等破坏性命令。
7. 每一步做完都告诉我结果；失败先诊断再重试，不确定就停下来问我，不要跳过。

========================
二、先做只读检查，并向我报告
========================
1. git --version                      （有没有 Git）
2. git config --global user.name      （没有就问我，不要自己编）
   git config --global user.email
3. 列出项目根目录、每个目录的文件数和总体积（MB）
4. 列出所有**超过 100 MB** 的文件（GitHub 单文件硬上限 100 MB）
5. 如果 git 连不上 GitHub（Connection reset / timeout）：
   先让我打开代理，然后执行（端口号用我自己代理的）：
       git config --global http.https://github.com.proxy http://127.0.0.1:端口号

========================
三、文件分类（严格照做）
========================
【A 类 — 进 Git】
   所有 .py / .bat / .ps1 / .md / .txt / .yaml / .yml
   小的 .json / .csv（单文件 < 5 MB）
   代码目录：app\ scripts\ configs\ docs\、以及 experiments\ 里的 .py 和说明文档
   requirements.txt 之类依赖清单

【B 类 — 不进 Git，改成 Release 附件】
   *.pt / *.pth / *.onnx / *.engine / *.ckpt
   任何数据集目录（dataset\ 等）
   任何图片目录（test_images\、图片\、samples\ 等）
   runs\ / results\ / logs\ / weights\
   任何 *.zip / *.7z / *.rar / *.tar / *.gz
   任何单个文件 > 50 MB 的内容
   .venv\ / venv\ / __pycache__\ / *.pyc

【C 类 — 不打包也不上传】
   安装包（.exe 安装器）、临时文件、缓存

========================
四、创建 .gitignore（内容必须包含）
========================
__pycache__/
*.pyc
*.pyo
*.pyd
.venv/
venv/
env/
*.pt
*.pth
*.onnx
*.engine
*.ckpt
*.zip
*.7z
*.rar
*.tar
*.gz
dataset/
datasets/
test_images/
images/
runs/
results/
logs/
weights/
external_datasets/
friend_transfer/
release_assets/
tmp/
temp/
.vscode/
.idea/
.DS_Store
Thumbs.db
.pytest_cache/
.mypy_cache/

（如果项目里已经有 .gitignore，先读一遍，**保留原有合理规则再补充**，不要直接覆盖。）

========================
五、初始化并做第一次提交
========================
1. 在项目根目录：git init -b main
2. 把我的分支命名成 feature/fusion：
       git branch -M feature/fusion
3. **不要用 git add .**，改成明确列文件：
       git add .gitignore
       git add app scripts configs docs
       git add *.md *.txt *.bat *.ps1 requirements.txt
       （按实际存在的目录/文件写，没有的跳过）
4. 检查暂存区，确认里面**没有** .pt / dataset / 大量图片 / zip：
       git status --short
   如果发现有 → 立刻 git restore --staged <该文件>，并告诉我。
5. 再确认一次体积：暂存的文件总共应该只有几十 MB 以内。
6. 提交：git commit -m "friend project snapshot: <一句话说明这是什么版本>"

========================
六、推送到独立分支（关键一步）
========================
git remote add origin https://github.com/ji2026-9/robot_inspection.git
git fetch origin
git push -u origin feature/fusion

注意：
- 只推 feature/fusion 这一个分支。
- 如果报错说 feature/fusion 已存在（可能对方已经建过），**停下问我**，
  不要用 --force 覆盖，我们可以改用 feature/fusion-<我的名字>。
- 成功后在 GitHub 网页上应该能看到 feature/fusion 分支，并且里面**没有**模型和数据文件。

========================
七、把大文件做成 Release 附件
========================
1. 在项目里新建一个文件夹 release_assets\（这个文件夹不要提交到 Git）。
2. 把 B 类文件按下面方式打包（**每个 zip 必须小于 2 GB**，GitHub 单个附件上限 2 GB）：
   - 模型：weights 里的 *.pt 单独放一份
   - 数据集：整个 dataset 目录压成一个 zip
   - 测试图片：整个 test_images 目录压成一个 zip
   - 实验输出：runs / results 各压成 zip
   - 如果某个 zip 超过 2 GB，就按子目录拆成多个
3. 计算每个 zip 的 SHA256，写进 release_assets\SHA256.txt。
4. 上传方式（二选一，让我选）：
   (a) 网页手传：GitHub 仓库页 → Releases → Draft a new release
       - Tag 填： v1.0-fusion-data
       - Title 填：<我的名字> 的项目快照数据
       - 把 release_assets 里的 zip 拖进去 → Publish release
   (b) 命令行上传：需要一个 GitHub Token（我会另外确认要不要给）
5. 上传完把 Release 链接发给我。

========================
八、最后给我一份报告
========================
1. Git 版本、我的分支名、commit hash
2. 上传了哪些文件（按目录列，多少个）
3. 确认：**没有**模型/数据集/图片进入 Git
4. 确认：**没有** push 到 main，没有用 --force
5. 原始文件核验：列出几个关键文件（模型、数据集、测试图片）的 SHA256，
   并说明和任务开始前一致、全程没有修改
6. Release 链接 + 每个附件的大小 + 总大小
7. 如果中途卡住了，说明卡在哪一步、报错是什么

========================
九、禁止事项（再强调一遍）
========================
不要 push 到 main；不要 git push --force；不要 git reset --hard；
不要 git clean -fd；不要删除或移动我的任何原始文件；不要训练模型。
```

---

## 三、他上传完之后，你（本机主人）怎么按需合并

```bat
cd /d E:\robot_project\robot_inspection

:: 1) 先把他的分支取回本地（不会改你的工作区）
git fetch origin

:: 2) 看他和你到底差在哪（只读，安全）
git log --oneline main..origin/feature/fusion
git diff --stat main origin/feature/fusion
git diff main origin/feature/fusion -- app\vision.py     :: 只看某个文件

:: 3) 按需合并，三种粒度任选
:: (a) 只要他的某几个文件，不要他的历史
git checkout origin/feature/fusion -- app\vision.py scripts\train_seg.py

:: (b) 想要他整个分支的改动（会提示 unrelated histories）
git merge origin/feature/fusion --allow-unrelated-histories

:: (c) 只想看某个 commit 的改动，再决定
git cherry-pick <commit-hash>
```

建议：**先 diff 再合并**，一次只挑一两个文件，合并后立刻跑

```bat
E:\robot_project\robot_inspection\.venv\Scripts\python.exe E:\robot_project\robot_inspection\app\selftest_full.py
E:\robot_project\robot_inspection\.venv\Scripts\python.exe E:\robot_project\robot_inspection\scripts\check_git_safety.py
```

确认没问题再 `git commit`，然后 `git push`。

---

## 四、为什么不建议用同一个 main 上传

| 做法 | 后果 |
| --- | --- |
| 朋友直接 push 到 `main` | 会被拒绝（非快进）；若强行 `--force` 会**覆盖掉你的提交**，历史永久丢失 |
| 朋友 push 到 `feature/fusion` | ✅ 完全隔离，你随时可以看、可以挑、可以不要 |
| 朋友把模型/数据集 commit 进去 | 仓库瞬间变成几百 MB~几 GB，clone 变慢；而且一旦提交**删不掉**（历史永久保留） |
| 朋友把大文件放 Release 附件 | ✅ 仓库保持轻量，需要时单独下载 |
