# 朋友分支新一轮审核与并入记录

审核日期：2026-10-08
审核对象：`origin/feature/fusion`，尖端提交 `e04f975`
上次同步点：`aa7a844`

---

## 一、这次他新推了什么

上次同步之后，他新推了 3 个提交：

| 提交 | 说明 |
| --- | --- |
| `f2f27cb` | Add live camera and frozen photo workspace with image-bound hole selection |
| `e39abf3` | Preserve every camera capture with metadata and add parameter and readiness checks |
| `e04f975` | Unify capture photo browsing with experiment records |

改动范围：8 个文件、+607 / -10 行，其中 4 个是**新模块**：

| 文件 | 行数 | 内容 | 我们的评估 |
| --- | ---: | --- | --- |
| `inspection_gui/measurement_readiness.py` | 27 | 测量就绪检查（9 项，含 4 项"尚未实现"的标定项，不隐藏） | **要**：正好补上"什么时候才能下发测量任务"这个缺口 |
| `inspection_gui/vision_workspace.py` | 76 | 相机预览线程 + 点击选孔 + 测孔清单校验 | **要**：等接真相机就可用；选孔逻辑现在就能用 |
| `inspection_gui/capture_archive.py` | 33 | 每次拍摄存**无损 PNG + 同名 JSON**（SHA256、尺寸、接收时间、参数读回），用 `xb/x` 打开，**绝不覆盖**，写失败就不进检测 | **要**：留样策略正确，等相机到位启用 |
| `inspection_gui/camera_parameters.py` | 83 | 相机参数能力 / 读回校验 | **要**（模块先并入，暂无相机不启用） |
| `inspection_gui/CAMERA_DRIVER_CONTRACT.md` | 11 | 相机驱动接入约定 | **要**：给以后接 SDK 的人看 |

### 安全性复核

| 项目 | 结果 |
| --- | --- |
| 有没有模型 / 图片 / 压缩包进 Git | **没有**（`engine_bore_local/` 最大文件是 316 KB 的 `active_models.json`） |
| 有没有大文件（>100 MB） | **没有** |
| 有没有覆盖我们的 `app/`、`scripts/`、`docs/` | **没有**（他只在 `.gitignore` 末尾追加规则） |
| 文档是否夸大 | 没有。他自己写明"尚未绑定具体厂家 SDK，测试使用接口替身，不代表实机验证" |

---

## 二、已并入主线（GitHub `main`）

合并提交：`aff2691`（`main` ← `origin/feature/fusion`，**无冲突**，100 个文件、+26,059 行）。

做法是**合并且不裁剪**：他的 `engine_bore_local/` 整套软件源码现在在 `main` 上，
以后他再推新提交，主线只要再 `git merge origin/feature/fusion` 就能同步，不用手工挑文件。

已知重复但**故意保留**：`engine_bore_local/friend_gui_source/`（28 个文件，是我方旧界面源码的副本）
与 `engine_bore_local/friend_package/`（6 个文件，旧交付包副本），体积很小（<0.5 MB）。
删掉会让以后合并产生"改/删冲突"，所以留着，只在文档里标明是重复内容。

---

## 三、已接进你正在用的软件（`E:\robot_project\inspection_app`）

### 1. 直接复制（新文件，不与我们的改动冲突）

```
inspection_gui\camera_parameters.py
inspection_gui\capture_archive.py
inspection_gui\vision_workspace.py
inspection_gui\measurement_readiness.py
inspection_gui\CAMERA_DRIVER_CONTRACT.md
```

复制后已用 SHA256 与主线逐一比对，**完全一致**。

### 2. 新增接线（补丁 9m，`scripts/patch_friend_engine.py`）

| 改动 | 说明 |
| --- | --- |
| 左栏新增「**测量就绪检查**」按钮 | 打开他的 `ReadinessDialog`，9 项逐条列出：相机连接 / 拍照机械臂 A / 测量机械臂 B / 本次原图留样 / 测孔清单 / 相机内参标定 / 手眼标定及双臂坐标转换 / 测针 TCP 与孔轴方向 / 运动路径与测量接口 |
| 孔位表「孔号 ☑」可勾选 | 勾选＝**本次要测量这个孔**；只有圆心可靠的孔可勾选；勾选变化写进运行日志 |
| 「③ 发送测量任务」提示语 | 改为"先点测量就绪检查"，未满足标定项前**保持禁用**（不假装能联动机械臂） |

设计口径与他的 `selected_targets()` 一致：**自动全检要求 4 个可靠圆心；手动清单要求所选孔都有可靠圆心**，
两者都不允许把"没检出"当成"测过了"。

---

## 四、这次**没有**采纳的部分（以及原因）

| 内容 | 为什么暂时不并进软件 |
| --- | --- |
| 他 `gui.py` 的 +292 行（相机工作区整合进主界面） | 我们的 `gui.py` 已经整体重排过（浅色主题、三栏布局、诊断面板、批次历史…）。直接覆盖会**抹掉全部界面修复**，而且他的接线基于他自己的 `_build_ui`。正确做法是等接了真实相机后，按功能点逐个移植 |
| 他 `records_view.py` 的 +86 行（拍摄记录与实验记录合并浏览） | 功能与我们已经做的「打开历史批次」重叠，两边都留会变成两套入口 |
| 他 `devices_view.py` 的 +9 行（相机参数校验） | 需要真实相机 SDK 才有意义，模块已并入，等设备到位再接 |

---

## 五、复测证据（2026-10-08）

1. 补丁脚本连跑两遍：第二遍 `9m) 融合同步: 已打过补丁（跳过）` —— 幂等 ✅
2. `gui.py` / `measurement_readiness.py` 语法检查通过 ✅
3. 界面截图：左栏 7 个按钮完整显示，「测量就绪检查」窗口 9 行全部可见、无裁切 ✅
4. 无头脚本验证勾选逻辑（载入历史批次，不新增实验记录）：
   - 4 个孔行均可勾选，勾选 H01+H03 后 `measure_targets = ['H01','H03']`，`confirmed_targets = ['H01','H03']`
   - 取消 H01 后只剩 `['H03']`
   - 就绪检查项按实际状态返回（无相机/无机械臂 = 未满足；标定类固定未满足）✅
5. 检测链路未受影响：同一批测试图仍是 **16/16**（改界面不碰 `vision.py`）✅

---

## 六、下一步（等设备到位再启用）

1. 拿到工业相机 SDK 后，按 `CAMERA_DRIVER_CONTRACT.md` 实现 `connect/disconnect/is_connected/start/stop/get_frame`，
   用 `register_device_backend("camera", backend)` 注册；
2. 启用 `capture_archive.save_capture()` 做**原图留样**（无损 PNG + SHA256 + 参数读回），
   这一步做完，「本次原图留样」那一行才会变"已满足"；
3. 相机内参标定 → 手眼标定 → 测针 TCP 三项做完，才允许把「③ 发送测量任务」打开。

> 一句话：**就绪检查不是形式主义**——现在它 9 项里有 4 项是硬编码的"尚未实现"，
> 这不是 bug，而是提醒我们：连接成功 ≠ 能测量。
