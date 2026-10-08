# software\ —— 正式版软件源码（当前使用的界面，以此为准）

这里是我们**实际在用的那套界面**（「双机械臂孔检测系统」）的完整源码，也就是正式交付版，
已经把所有本地补丁（相机接入、视觉检测区左右分屏、点孔选择测量目标、实验记录工具、
设备参数不落盘……）全部应用进去了。

**这份源码就是权威版本**：界面以这里为准，不再由朋友那版界面决定。

---

## 和仓库其它目录的关系

| 目录 | 是什么 | 和这里的关系 |
| --- | --- | --- |
| `software/`（本目录） | 我们这套界面的**权威源码** | 直接把它铺到交付目录即可运行 |
| `engine_bore_local/` | 朋友上传的源码快照（**较新**，自带他那套"实时采集 / 测量模式"界面） | 只作**引擎侧参考**；他的新界面不覆盖我们的界面 |
| `scripts/app_addons/` | 我方新增模块（Orbbec 驱动 `orbbec_camera.py`、实时预览窗口 `camera_preview.py`） | 已包含在本目录里，保留一份便于版本管理 |
| `scripts/patch_friend_engine.py` | 补丁脚本：从朋友的源码生成本套界面 | 本目录 = 该脚本的**产物快照**；他更新引擎后，用脚本比对本目录再决定改哪里 |
| `app/` | 我方视觉核心库（推理 / 拟合 / 编号） | 与本目录的 `detect_core.py` 同源，本目录是完整软件那一份 |

> 换句话说：**要交付/要跑，用本目录；要从他的新源码里取引擎改进，用 `engine_bore_local/` + 补丁脚本，
> 但界面（`inspection_gui/`）以本目录为准。**

---

## 怎么跑起来

本目录**不含模型与数据**（按仓库规则这些走发布附件 / 数据盘）：

| 需要补的东西 | 放哪里 | 来源 |
| --- | --- | --- |
| 孔 / part 模型 | `models/`（`bore_best.pt`、`part_best.pt`、`fusion_v1_best.pt` …） | GitHub Release `v1.1-model` / 朋友的模型包 |
| 训练用种子图（可选） | `data/database_seed/` | 数据盘 / 他的数据包 |

补齐后：

```bat
:: 1) 把本目录铺到交付位置
xcopy /E /I E:\robot_project\robot_inspection\software E:\robot_project\inspection_app
:: 2) 把模型放进 E:\robot_project\inspection_app\models\
:: 3) 启动
E:\robot_project\robot_inspection\.venv\Scripts\pythonw.exe E:\robot_project\inspection_app\app.py
```

依赖：`..\requirements.txt`（torch/ultralytics/opencv/PySide6 等）。

---

## 自检

```bat
set CODEX_APP_DIR=E:\robot_project\inspection_app
set CODEX_E2E_DIR=%TEMP%\inspection_e2e
E:\robot_project\robot_inspection\.venv\Scripts\python.exe E:\robot_project\robot_inspection\scripts\check_inspection_app.py
```

离屏跑真实检测器 + 真实界面对象，覆盖：检测 → 写实验记录 → 从记录载入工作区 →
点孔选测量目标（含图上绿圈/白勾与角标）→ 打开原图/结果图/检测报告 → 删除整批记录 →
分屏拖动（拖到头也不会把某一格拖没）。**不会碰真实实验记录。**

---

## 界面要点（2026-10-08）

- **视觉检测区左右分屏**：左＝相机实时画面（只看），右＝检测结果（识别/标定后的孔图）
  - 点右格的孔 = 选中/取消本次要测的孔；选中的孔**椭圆变绿 + 圆心白勾**，角标写「本次要测：H0x」，表格同步
  - 分隔条可拖，两侧都有最小宽度（拖到头也不会把某一格拖没）；关掉实时时左格收起、右格占满
- **抓拍**：把当前实时帧无损留样并放进工作区（不自动检测）；「用工业相机拍照」与它共用同一段取流代码
- **实验记录**：查看 / 导出 / 载入到工作区 / 打开原图·结果图·检测报告 / 删除整批记录（只删记录，磁盘文件保留）
- **设备参数不落本机**：设备信息只在本次运行有效（相机插上自动识别型号/序列号；机械臂按当前电脑实际 IP 填写）
