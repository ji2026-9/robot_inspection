# 按任务找文件，不必全盘读取

以下路径相对仓库根；日常应用从 `software/` 导入。运行副本同名模块需同步。

| 要改什么 | 优先文件 | 对应测试/证据 |
|---|---|---|
| 首页、检测流程、布局、入口路由 | `software/inspection_gui/gui.py` | `scripts/qa_workflows_offline.py` |
| 主导航、设置常用/高级、懒加载与复用 | `software/inspection_gui/workbench.py` | `tests/test_settings_navigation.py`, `test_standard_workbench.py` |
| 控制页按钮、输入、原点、多点与保存 | `software/inspection_gui/manual_control_view.py` | `test_standard_workbench.py`, `test_workflow_audit.py`, `test_origin_selection.py` |
| 工具总质量自动保存/恢复 | `software/inspection_gui/tool_payload.py`, `manual_control_view.py` | `test_tool_payload.py` |
| 控制状态文案与目标距离 | `software/inspection_gui/control_overview.py`, `ui_feedback.py` | `test_control_overview.py`, `test_visible_feedback.py` |
| 真实运动通道、停止优先、点动状态机 | `software/inspection_gui/manual_control.py` | `test_manual_control.py`, `test_stop_dispatch.py`, `test_continuous_jog.py` |
| 工具反馈、倍率、网络帧 | `software/inspection_gui/dobot_feedback.py`, `devices_view.py` | `test_feedback_speed.py`；设备配置不等于连接 |
| 目标预览、关节动画、耗时、相机适配 | `software/inspection_gui/manual_preview.py`, `simulation_scene3d.py`, `joint_preview.py` | `test_preview_timing.py`, `test_preview_camera.py`, `test_integrated_target.py` |
| 保存返回点/任务格式 | `software/inspection_gui/manual_origin.py`, `target_task.py`, `target_table.py` | `test_standard_workbench.py`, `test_workflow_audit.py` |
| 全局墙配置、碰撞拦截、弹窗 | `software/inspection_gui/global_wall.py`, `wall_guard.py`, `safety_wall.py`, `safety_wall_view.py`, `wall_alert.py` | `test_global_wall_guard.py`, `test_wall_deployment.py`, `test_wall_collision.py` |
| DI触发记录、停止诊断、白球 | `software/inspection_gui/probe_trigger.py`, `probe_stop.py`, `probe_workspace_view.py`, `sphere_analysis_view.py` | `test_circle_and_config.py`及对应probe测试；`docs/probe_trigger.md`, `probe_stop.md` |
| 圆孔只读采点、拟合、导出 | `software/inspection_gui/circle_measurement.py`, `circle_measurement_view.py` | `test_circle_and_config.py`, `test_workflow_audit.py` |
| 自动测孔（示教、接触、退让、中心、撤离） | `software/inspection_gui/hole_probe.py`, `hole_probe_view.py`, `contact_points.py` | `test_contact_points.py`, `test_manual_control.py`（release_probe）；实机验收未完成 |
| 日志与历史回滚 | `software/inspection_gui/ui_events.py`, `event_history_view.py`, `config_history.py`, `config_history_view.py` | `test_standard_workbench.py`, `test_circle_and_config.py` |
| 视觉推理与拟合 | `software/detect_core.py`, `edge_bore_refinement.py`, `robust_bore_ellipse.py`, `part_predictor.py`；早期库在 `app/` | 历史 `docs/ELLIPSE_FIT_COMPARISON.md`；先查本次使用的检测入口，别默认重训 |
| 模型维护/数据流程 | `software/inspection_gui/model_management_view.py`, `software/dataset_update.py`, `software/validation_view.py` | 依赖模型/数据，不要默认载入全部权重 |

## 数据位置（不能用代码覆盖）

本机运行根 `E:/robot_project/inspection_app`，主要用户数据在 `data/probe_workspace/`：

- `manual_origin.json`：XYZ返回位置+工具/用户上下文。
- `tool_payload.json`：上次声明的工具总质量（0–5 kg，仅人工确认记录，不写入控制器）。
- `safety_wall.json`：墙面与工具包络；文件存在不等于已实物验收。
- `positions.json`、`probe_triggers/`、`circle_sessions/`：位置库、触发接收帧、圆孔采集。
- `hole_probe_holes.json`、`contact_points.json`、`contact_sessions/`：示教孔位、累积接触点库、每次测孔会话。
- `manual_control_logs/`、`ui_events.jsonl`、`config_versions/`：控制日志、UI事件、配置历史。
- 用户保存的目标任务JSON位置由文件对话框选择，不能只找默认targets.json。

模型/大数据不默认进Git；源码齐全不代表另一台电脑已具备模型、相机SDK和硬件配置。

## 最小验证命令

在仓库根，用正确解释器，PowerShell例：

```powershell
$env:PYTHONPATH = "$PWD/software"
& ./.venv/Scripts/python.exe -m unittest discover -s tests -p test_settings_navigation.py
& ./.venv/Scripts/python.exe -m unittest discover -s tests -p test_standard_workbench.py
# 流程或拟合变化时再加：
& ./.venv/Scripts/python.exe -m unittest discover -s tests -p test_workflow_audit.py
& ./.venv/Scripts/python.exe -m unittest discover -s tests -p test_circle_and_config.py
# 如需真实Qt/OpenGL离线布局验收；会显示独立测试窗口，不连接实机：
& ./.venv/Scripts/python.exe scripts/qa_workflows_offline.py
# 更新/检查交接快照（不启动UI，不连设备）：
& ./.venv/Scripts/python.exe scripts/refresh_handoff.py
& ./.venv/Scripts/python.exe scripts/refresh_handoff.py --check
```

测试产物默认在 `.test-output/`。临时目录权限问题要单列，不计作通过。机器快照只追踪指定轻量文件及元数据，不读取模型和原始采点内容。
