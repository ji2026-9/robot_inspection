# 下载与运行当前版本（2026-10-16）

最新源码：https://github.com/ji2026-9/robot_inspection

完整项目与现用模型包：https://github.com/ji2026-9/robot_inspection/releases/tag/v1.4-workbench

## 另一台 Windows 电脑怎么运行

推荐从发布页下载 `01_current_project_v1.4_20261016.zip` 并完整解压。它包含仓库源码、当前5个模型和训练种子数据，不包含 Python 环境。请安装 Python 3.11（包含 pip 和 Tkinter），然后在解压后的项目根目录打开命令行：

```bat
py -3.11 -m venv software\.venv
software\.venv\Scripts\python.exe -m pip install --upgrade pip
software\.venv\Scripts\python.exe -m pip install torch==2.5.1 torchvision==0.20.1 --index-url https://download.pytorch.org/whl/cpu
software\.venv\Scripts\python.exe -m pip install -r software\requirements.txt
software\.venv\Scripts\python.exe software\app.py
```

上面采用 CPU 环境，适合先阅读和启动界面。有兼容 NVIDIA 显卡并需要 GPU 加速时，可将安装 PyTorch 的命令替换为：

```bat
software\.venv\Scripts\python.exe -m pip install -r software\requirements-torch-cu121.txt --index-url https://download.pytorch.org/whl/cu121
```

后续双击项目根目录 `start_software.bat`。相机 SDK、USB 驱动等硬件依赖需在目标电脑另行安装；不接设备也可查看界面与离线示例。目标电脑环境尚未实际安装验证。

## 只读代码或参与开发

```bat
git clone https://github.com/ji2026-9/robot_inspection.git
cd robot_inspection
git pull --ff-only origin main
```

正式软件在 `software/`，入口 `software/app.py`，主界面 `software/inspection_gui/gui.py`。测头工作区见 `probe_workspace_view.py`；实机控制及保护见 `manual_control.py` 和 `manual_control_view.py`。`engine_bore_local/` 是历史引擎参考，不是当前界面的入口。

Git 仓库不存放模型二进制和种子图片；只克隆代码时，请从 v1.4 完整项目包提取 `software/models/` 和 `software/data/database_seed/`。无需下载旧版界面覆盖新版源码。

## 当前功能与验证边界

- 视觉检测、孔位选择、记录、训练管理、三维显示和离线路径预览。
- CR5A 只读反馈、DI_1 触发采点、白球拟合与重复性分析、模拟视觉坐标流程。
- 主窗口直接进入实机控制，支持原生长按点动、定距移动、停止/继续；正常松手核对停止后可再次操作，测头触发和异常会锁定。
- 156 项离线自动测试、9 项工作台流程检查通过，并进行了真实OpenGL与完整四孔路径生成离线验证。实机仅验证过静止触发与停止指令通信，未验证运动停止距离或自动测量精度。

源码有真实运动能力。阅读、离线分析无需连接机械臂；实机控制需重新核对现场、工具、负载和重心。软件停止不能替代实体急停，不会自动使能、清报警或切换 TCP 模式。

详见 `docs/manual_control_safety.md`、`docs/manual_control.md`、`docs/sphere_analysis.md`。完整包不迁移本机控制日志、采点记录、设备会话或虚拟环境；历史检测结果与旧数据附件仍可在既有 Releases 找到。可选的本机厂商三维网格不随包分发，缺少时使用软件内置几何显示。

本次按钮核对与修复清单见 [BUTTON_AUDIT_20261016.md](BUTTON_AUDIT_20261016.md)。

界面与参数增减说明见 [STEPPER_UPDATE_20261016.md](STEPPER_UPDATE_20261016.md)，切页性能与新版模型管理说明见 [PERFORMANCE_20261016.md](PERFORMANCE_20261016.md)。
