# 机械臂智能视觉检测系统 —— 软件包使用说明

> 这是一个可直接在你电脑上运行并继续开发的完整软件包。
> 模型：YOLO11n-Seg（单类别 `cylinder_bore`，检测工件上的 4 个大型圆孔）

---

## 一、三步跑起来

| 步骤 | 操作 |
|---|---|
| **1** | 安装 **Python 3.11**（若还没装）：<https://www.python.org/downloads/release/python-3119/>，安装时**务必勾选 `Add python.exe to PATH`** |
| **2** | 双击 **`setup_env.bat`** —— 自动创建 `.venv` 并安装依赖（**会检测是否有 NVIDIA 显卡**：有则装 CUDA 版 PyTorch，没有则装 CPU 版）。国内源，约 3–10 分钟 |
| **3** | 双击 **`run_gui.bat`** —— 启动软件 |

安装是否成功：**双击 `verify\verify_env.bat`** 自检，会打印 `VERIFY: PASS`。
（若 `.venv` 还没创建，只会打印一行 `[INFO]`，**不算失败**。）

## 二、界面怎么用

1. **选择图片** → 默认打开 `test_images\`（4 张手机测试照片）
2. **开始 AI 检测** → 左侧显示 mask/椭圆/中心点/`H01~H04`，右侧显示检出数量与平均置信度
   - 检测满 4 个孔 → 自动生成 4 个检测任务
   - **不足 4 个**（如 `测试3` 在 conf=0.50 下只有 3 个）→ 显示"检测不完整"，**不生成任务、不伪造缺失孔**
3. **手动指定检测**（模式 B）→ 下拉选 `H03` → 点 `生成任务：H03`，只生成这一个孔的任务
4. **模拟执行** → 逐孔动画演示：橙色探头沿路径移动、完成后套绿环、底部进度条同步。
   **这是软件仿真**：机器人状态恒为"未连接"，不会驱动任何真实设备
5. **双击任务表某一行** → 弹出该孔的放大视图（裁剪图 + 椭圆 + 中心 + 尺寸角度 + 长短轴比）

结果显示在 **`results\gui_runs\<时间戳>\`**：`detection.json` + 标注图（每次一个独立目录，不覆盖）。

快捷键：`Ctrl+O` 选图、`F5` 检测、`Ctrl+S` 保存。

## 三、包里有什么

```
robot_inspection_gui_v1\
├── app\                    软件全部源码（GUI / 视觉 / 任务 / 机器人 / 相机分层）
├── weights\best.pt         YOLO11n-Seg 模型（5.99 MB）
├── test_images\            4 张手机测试照片
├── dataset\box_yolo\       YOLO-Seg 数据集（20 train / 2 val / 3 test），可用于重训
├── setup_env.bat           一键安装环境
├── run_gui.bat             一键启动软件
├── training\               训练 / 评估脚本（改好相对路径，可直接重训）
├── requirements.txt        依赖版本清单
├── verify\verify_env.bat   双击即自检（调用 verify_app.py）
├── verify\verify_app.py    环境与模型自检脚本
└── docs\SHA256.txt         全部文件的 SHA256 校验表
```

## 四、重要说明（避免误用）

1. **模型用途**：只做"4 个大孔的检测 + 分割 + 椭圆中心"，
   **不是**最终机器人控制模型；**尚未完成**相机标定、像素→机器人坐标转换、手眼标定。
2. **H01~H04 是"当前图像内的编号"**，不是永久物理身份。
   实测：把同一张图**旋转 180°**，`H01` 与 `H04` 会对调。
   界面里 `orientation_status` 恒为 `uncertain`，必须保持这个诚实标注。
3. **机器人状态永远显示"未连接"** —— 包里只有 `MockRobot`，不会假装连上真机。
4. **不要**把外部数据集（如 T-LESS）的 object mask 当作孔标签使用。
5. OpenCV 5.0 在 Windows 上读不了含中文的路径，代码里已统一用
   `imageio_util.imread_unicode()`（`np.fromfile + cv2.imdecode`）规避，**新代码请沿用**。

## 五、想优化什么，从哪下手

| 目标 | 改哪个文件 |
|---|---|
| 界面/交互（配色、布局、新按钮） | `app\gui.py`、`app\view_render.py` |
| 检测逻辑（阈值、多模型、批处理） | `app\vision.py` |
| 任务流程 / 结果保存 | `app\task_manager.py` |
| **换成真实工业相机** | `app\camera_interface.py`（实现 `start/stop/get_frame/is_connected/set_source`） |
| **换成真实机械臂** | `app\robot_interface.py`（实现 `connect/disconnect/is_connected/move_to_target/execute_measurement/stop`） |
| 参数集中配置 | `app\config.py`（路径已自动适配包位置，无需改绝对路径） |
| **重新训练 / 换超参** | `training\train_seg.py`（详见 `training\README_训练说明.md`） |
| 换测试图、批量看置信度 | `training\predict_holes.py`、`training\eval_confidences.py` |

### 回归测试（改完务必跑）

```
.venv\Scripts\python.exe app\selftest_full.py       # 73 项功能与异常路径
.venv\Scripts\python.exe app\selftest_coldstart.py  # 冷启动读图回归
```

详见 `APP_OVERVIEW.md`。
