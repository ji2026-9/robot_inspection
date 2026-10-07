# 精简记录（2026-10-07）

项目从 **12.4 GB 精简到 6.1 GB**，释放约 6.3 GB。
原则：**能重新生成的、已经上传到 GitHub Release 的、以及审核临时资料，一律本地删除。**

---

## 一、删了什么、为什么可以删

| 删除内容 | 体积 | 为什么可以删 | 备份在哪 |
| --- | ---: | --- | --- |
| `external_datasets\phase3_downloads\`（T-LESS / Workpieces 原始包与解压） | 3,031 MB | 公开数据集，随时可重新下载；**审计结论与报告已保留** | 重新下载（脚本 `scripts\chunked_download.py`） |
| `results\gui_runs\`（旧界面每次检测的结果目录） | 352 MB | 已经上传 | Release `v1.0-data` 的 `07_results_and_runs.zip` |
| `runs\`（YOLO 训练输出） | 27 MB | 已经上传 | 同上 |
| `results\测试N_result.jpg`、两个 html 报告 | 12 MB | 已经上传 | 同上 |
| `experiments\` 里的 247 个 `.pt` 与图片 | 478 MB | 已经上传（**csv/json/yaml/md 等轻量记录全部保留**） | Release `v1.0-data` 的 `06_experiments_full.zip` |
| `friend_transfer\` 里的两个交付 zip + 两套解压中间产物 | 666 MB | 已经上传 | Release `v1.0-data` 的 `01` / `02` |
| `release_assets\` 里的 8 个附件与模型副本 | 1,233 MB | 已经上传（**只留生成脚本 `upload_release.ps1` 与清单**） | Release `v1.0-data` / `v1.1-model` |
| `_installers\`（Miniconda / Python 安装包） | 117 MB | 官网随时可下 | python.org / anaconda.com |
| `E:\robot_project\_reference\`（审核时的代码、模型包、下载缓存） | 273 MB | 审核结论已写进 `docs\FRIEND_*` 与 `docs\COMPARE_*` | 结论在 docs；资料可用 `git archive` 重新导出 |
| `E:\robot_project\fusion_train\`（28 张训练集） | 172 MB | 一行命令可重建（源图都还在） | `scripts\make_fusion_dataset.py`（约 2 秒） |
| `inspection_app\friend_gui_source\`（我方旧界面的副本） | 0.2 MB | 与 `_archive\gui_v1_pyside6\` 重复 | `_archive\` |
| `_archive\` 里 18 张测试截图 | 24 MB | 旧界面的自测截图，已无意义 | 无（可重新生成） |

合计释放：**约 6.3 GB**。

## 二、明确保留的（都是"不能再省"的核心）

| 内容 | 体积 | 说明 |
| --- | ---: | --- |
| `.venv\` | 5,348 MB | 唯一的 Python 环境，删了要重装 5 GB 依赖 |
| `inspection_app\`（含 `.labelme_env`） | 699 MB | **最终版软件** + 模型 + 28 张标注数据 + 标注环境 |
| `dataset\` | 145 MB | 原始数据集（20/2/3） |
| `weights\` | 28 MB | 现役模型 + 历史模型备份 |
| `external_datasets\`（只留报告/元数据） | 24 MB | 外部数据集审计结论 |
| `test_images\` | 13 MB | 4 张评估图（不可再生） |
| `results\`（只留两个对比目录） | 11 MB | 拟合方式对比的叠加图与 json |

## 三、以后怎么把删掉的东西拿回来

```bat
:: 实验结果 / 训练输出 / 交付包 / 数据集包  → 从 GitHub Release 下载
::   https://github.com/ji2026-9/robot_inspection/releases

:: 28 张融合训练集  → 重新生成（约 2 秒）
E:\robot_project\robot_inspection\.venv\Scripts\python.exe ^
  E:\robot_project\robot_inspection\scripts\make_fusion_dataset.py

:: 交付包 zip  → 重新打包（
E:\robot_project\robot_inspection\.venv\Scripts\python.exe ^
  E:\robot_project\robot_inspection\friend_transfer\_build\build_gui_package.py

:: 外部数据集  → 用审计脚本重新下载
E:\robot_project\robot_inspection\.venv\Scripts\python.exe ^
  E:\robot_project\robot_inspection\scripts\chunked_download.py
```
