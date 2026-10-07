# 项目文件分类与共享说明

> 一句话原则：**Git 管代码，Release 附件管数据，没用的不上传。**
>
> 生成日期：2026-10-07　　仓库：<https://github.com/ji2026-9/robot_inspection>

---

## 一、先看这张总表

| 类别 | 放哪儿 | 内容 | 体积 |
| --- | --- | --- | --- |
| **A 类** | **Git 仓库**（已上传） | 代码、脚本、配置、文档、轻量实验记录 | 0.26 MB |
| **B 类** | **GitHub Release 附件**（8 个文件，待上传） | 模型、数据集、图片、训练输出 | 1,227 MB |
| **C 类** | **不上传** | `.venv`、`__pycache__`、`_installers` | 5,465 MB |

为什么这么分：

1. GitHub 对**单个文件有 100 MB 硬上限**（超过直接拒绝整个 push），所以模型/数据集不能进 Git。
2. Git 会**永久保留历史**，大文件一旦提交就删不掉、仓库会一直很重。
3. `.venv` 里有写死的绝对路径（`E:\robot_inspection\.venv\...`），拷到别人电脑上**跑不起来**，
   必须各人自己装；`_installers` 里的安装包官网随时能下。
4. GitHub Release 附件**单个上限 2 GB、数量不限**，正好用来放大文件。

---

## 二、A 类：进 Git 仓库（已经上传，84 个文件 0.26 MB）

```
仓库根目录    .gitignore  README.md  TEAM_WORKFLOW.md
              DATA_AND_MODEL_MANAGEMENT.md  BRANCH_PLAN.md
              requirements*.txt  run_*.bat
app\          21 个：GUI 全部源码（gui / vision / task_manager / robot_interface /
              camera_interface / imageio_util / config / main / selftest_* / README）
scripts\      24 个：train_seg.py  predict_holes.py  check_dataset.py
              eval_confidences.py  check_git_safety.py  make_release_assets.py 等
experiments\  23 个：实验代码 + 结论 md/csv/json/html（**不含 .pt 和图片**）
docs\         文档索引 + 本文件
configs\      配置目录（说明）
weights\      只有 best_source.txt 和两个置信度 json（**不含 .pt**）
```

朋友 `git clone` 之后就有这些；**代码永远通过 Git 同步**，这样两个人改的东西不会互相覆盖。

---

## 三、B 类：Release 附件（8 个，共 1,227 MB）

全部已生成在：**`E:\robot_inspection\release_assets\`**

**已经上传完成（2026-10-07）：**

```
https://github.com/ji2026-9/robot_inspection/releases/tag/v1.0-data
```

标签 `v1.0-data`，8 个附件全部上传成功并逐个校验过（大小与 SHA256 一致）。
仓库为**私有（Private）**，只有你和被邀请的协作者能下载。

> ⚠️ **注意（2026-10-07 更新）**：该 Release 里的 `04_weights_best.pt` 和
> `01_gui_app_full_package.zip` 内带的模型，是**旧 baseline**（`7E33DF62…`，测试3 只检出 3/4）。
> **新的 `fusion_v1` 模型（4 张测试图 16/16）已单独发布：**
>
> ```
> https://github.com/ji2026-9/robot_inspection/releases/tag/v1.1-model
> ```
>
> 该 Release 有 3 个附件：`01_fusion_v1_best.pt`（模型本体，5.71 MB）、
> `02_README_how_to_use.md`（怎么装）、`03_SHA256.txt`（校验值）。
> 朋友只要覆盖到自己项目的 `weights\best.pt` 即可，不用改代码。

### 3.1 全部附件（01–08，共 1,227 MB）—— 建议全部上传

| # | 文件名 | 大小 | 里面是什么 | 谁需要 |
| --- | --- | --- | --- | --- |
| 01 | `01_gui_app_full_package.zip` | 157.0 MB | **完整 GUI 软件包**：源码 + `best.pt` + 测试图 + 数据集 + `setup_env.bat` + `run_gui.bat` | ★★ 朋友最需要，下载这一个就能跑 |
| 02 | `02_model_package.zip` | 169.4 MB | 模型 + 数据集 + 推理脚本（早期交付版本） | 保留备用 |
| 03 | `03_dataset_box_yolo.zip` | 77.6 MB | 原始数据集压缩包（train 20 / val 2 / test 3） | 要重新训练时 |
| 04 | `04_weights_best.pt` | 5.7 MB | **旧** baseline 模型单独一份（SHA256 `7E33DF62…BDFE`）| 只想替换模型时 |
| 05 | `05_test_images.zip` | 13.1 MB | 测试1~4.jpg 四张手机照片 | 复现测试结果 |
| 06 | `06_experiments_full.zip` | 452.6 MB | 5 个 seed 的完整正式实验（含 24 个 `.pt` 和结果图） | 做模型比较 |
| 07 | `07_results_and_runs.zip` | 347.9 MB | 检测可视化结果 + YOLO 训练输出 | 看训练曲线/混淆矩阵 |
| 08 | `08_logs_and_audit.zip` | 3.5 MB | 训练/安装日志 + 审计原图 | 查历史 |

### 3.2 外部数据集（T-LESS / Workpieces）—— **暂不打包、不上传**

`external_datasets\`（3,055 MB，3,843 个文件）是 Phase 2–4 的外部数据集探索，
**和主线「4 个大孔检测」无关**，而且随时能重新下载，因此**本轮不生成、不上传**。

原始数据仍然完整保留在本机 `E:\robot_inspection\external_datasets\`。
将来确实要做数据融合实验时，一条命令就能补生成（会拆成 3 个 <2 GB 的附件）：

```bat
E:\robot_inspection\.venv\Scripts\python.exe E:\robot_inspection\scripts\make_release_assets.py --with-external
```

### 3.3 每个附件的 SHA256

见 `release_assets\SHA256_校验.txt`（同名内容也在 `MANIFEST_文件清单.txt` 里）。

---

## 四、C 类：不上传（共 5,465 MB）

| 内容 | 体积 | 为什么不上传 |
| --- | --- | --- |
| `.venv\`（34,165 个文件） | 5,347.8 MB | 含 14 个超过 100 MB 的 CUDA 库；路径写死，换电脑无效；各人自己 `setup_env.bat` 重建 |
| `_installers\` | 117.2 MB | Miniconda / Python 安装包，官网随时能下 |
| `__pycache__\`、`*.pyc` | — | Python 缓存，自动生成 |
| `release_assets\` 本身 | 1,227 MB | 就是上面 B 类的来源目录，已加入 `.gitignore` |

---

## 五、上传附件：网页操作步骤（约 3 分钟 + 上传时间）

1. 打开 <https://github.com/ji2026-9/robot_inspection/releases/new>
2. 填写：
   - **Choose a tag**：输入 `v1.0-data` → 点 **Create new tag**
   - **Target**：`main`
   - **Release title**：`数据与模型 v1.0（数据集 / 模型 / 实验结果）`
3. 打开文件夹 **`E:\robot_inspection\release_assets\`**，把里面的文件**拖进页面下方的
   "Attach binaries by dropping them here"** 方框。
   - 一共 8 个文件（1.2 GB），可以按住 Ctrl 多选后一起拖。
   - 不要拖 `MANIFEST_文件清单.txt` / `SHA256_校验.txt` / `说明_项目文件分类.md`（留着自用即可）。
4. 点 **Publish release**。传完后网页上每个附件都有下载链接和大小。

> 上传走的是本机代理，1.2 GB 大概需要几分钟到几十分钟，中途断了页面会提示，重试即可（已上传的不用重传）。

---

## 六、朋友怎么拿到完整项目

```bat
:: 1) 克隆代码（需要先接受协作者邀请）
git clone https://github.com/ji2026-9/robot_inspection.git
cd robot_inspection

:: 2) 建立自己的分支
git checkout -b feature/fusion

:: 3) 到仓库的 Releases 页面下载附件
::    https://github.com/ji2026-9/robot_inspection/releases
```

然后按情况解压（三个 zip 都是**按项目目录结构**打包的，直接解压到项目根目录即可还原）：

| 想做什么 | 下载 | 解压到 |
| --- | --- | --- |
| 只想跑起来看效果 | `01_gui_app_full_package.zip` | 任意目录，双击里面的 `setup_env.bat` |
| 要训练 / 复现实验 | `03` + `05` + `04` | 项目根目录（还原出 `dataset\`、`test_images\`、`weights\`） |
| 要做模型比较 | `06` + `07` | 项目根目录（还原出 `experiments\`、`results\`、`runs\`） |
| 要做数据融合 | 先按第 3.2 节补生成 09–11 并上传 | 项目根目录（还原出 `external_datasets\`） |

解压完成后检查一下：

```bat
dir dataset\box_yolo\images\train     :: 应该是 20 张
dir weights\best.pt                   :: 5,989,021 字节
python scripts\check_dataset.py
```

---

## 七、每个目录的归属（速查）

| 项目里的目录 | 归属 | 怎么拿到 |
| --- | --- | --- |
| `app\` `scripts\` `docs\` `configs\` `experiments\`(文字) | **A 类 Git** | `git clone` |
| `weights\` | **B 类 04 / 01** | Release 附件 |
| `dataset\` | **B 类 03 / 01** | Release 附件 |
| `test_images\` | **B 类 05 / 01** | Release 附件 |
| `experiments\`（模型与图片） | **B 类 06** | Release 附件 |
| `results\` `runs\` | **B 类 07** | Release 附件 |
| `logs\` `_audit\` | **B 类 08** | Release 附件 |
| `external_datasets\` | **暂不上传**（本轮排除，可重新下载） | 需要时用 `--with-external` 补生成 |
| `friend_transfer\` | **B 类 01 / 02** | Release 附件（内容相同） |
| `.venv\` `_installers\` | **C 类** | 各自安装，不上传 |

---

## 八、以后想重新生成附件

附件的生成脚本已经进 Git，随时可以重跑：

```bat
:: 默认：核心 8 个附件
E:\robot_inspection\.venv\Scripts\python.exe E:\robot_inspection\scripts\make_release_assets.py

:: 需要外部数据集时（额外生成 09~11，约 3 GB，1 分钟）
E:\robot_inspection\.venv\Scripts\python.exe E:\robot_inspection\scripts\make_release_assets.py --with-external
```

脚本**只读取**项目文件，不会修改、移动或删除任何原始内容；
输出固定到 `E:\robot_inspection\release_assets\`（该目录已被 `.gitignore` 忽略）。

> 注意：GitHub Release 单个附件上限 **2 GiB**，所以外部数据集被拆成 09/10/11 三份，
> 不要试图把 `external_datasets\` 整包压成一个文件。
