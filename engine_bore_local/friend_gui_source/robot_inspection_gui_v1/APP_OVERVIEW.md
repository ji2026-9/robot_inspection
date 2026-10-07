# 软件结构说明（给二次开发者）

## 一、分层架构

```
gui.py  ──► view_render.py      把照片画进画布 + 在画布坐标里画标注/模拟执行叠加
   │
   ├────► vision.py             YOLO-Seg 推理 → mask → 最大轮廓 → cv2.fitEllipse → 中心 → PCA 编号 H01~H04
   ├────► task_manager.py       任务生成 / 执行状态 / 结果落盘（时间戳目录，不覆盖）
   ├────► robot_interface.py    机器人抽象（当前 MockRobot；永不假装已连接）
   ├────► camera_interface.py   相机抽象（当前 ImageFileCamera / MockCamera）
   ├────► imageio_util.py       Unicode 安全读写（中文路径必须走这里）
   └────► config.py             路径（自动适配包位置）与参数
```

GUI **不含**推理代码、**不含**机器人代码，只调用上面这些接口，因此替换相机/机器人不需要动界面。

## 二、关键数据结构

单个孔（`vision.HoleDetector.detect()` 返回的 `holes[i]`）：

```json
{
  "id": "H03",
  "center_px": [1237.23, 1631.37],
  "confidence": 0.925,
  "ellipse": {"center": [1237.23, 1631.37], "width": 458.35, "height": 559.17,
              "angle": 62.92, "major": 559.17, "minor": 458.35, "aspect": 0.820},
  "orientation_status": "uncertain",
  "status": "detected"
}
```

检测任务（`task_manager`）：

```json
{"target_id": "H03", "center_px": [1237.23, 1631.37], "confidence": 0.925,
 "status": "pending", "simulated": null}
```

> `ellipse.width/height/angle` 是 **OpenCV 原始三元组**（angle 绑定 width 那根轴），
> **不要**把长短轴互换而不调整角度 —— 那样画出来会歪约 90°（本项目踩过这个坑）。

## 三、模拟执行做了什么

`gui.exec_step()` 由 `QTimer` 驱动（320 ms/步）：
每孔先 3 步"接近"（探针在图像坐标里线性插值），再 1 步"测量"（标记完成、写任务状态、写日志）。
叠加层由 `view_render.overlay_execution()` 绘制（路径 / 完成环 / 探头 / HUD）。
执行记录写入 `detection.json` 的 `execution*` 字段，其中 `robot_layer_result`
来自 `MockRobot.simulate_execute()`，每条都带 `"simulated": true`。

**它不代表真实运动学**，只是流程演示；接真机时把这个动画改成指令下发进度即可。

## 四、已知限制（请勿粉饰）

1. `orientation_status` 恒为 `uncertain` —— 当前没有可靠的物理方向参考，
   180° 旋转会让 H01/H04 对调（`experiments\stable_hole_id\` 有实测证据）。
2. 没有相机标定 / 手眼标定 / 像素→机器人坐标转换（字段已预留）。
3. `conf=0.50` 严格阈值下，`测试3` 的反光孔只有 ~0.17~0.47，会报"检测不完整"（这是**如实反映**，不是 bug）。
4. 首次检测要加载模型（约 2 秒），之后每次推理约 0.15 秒（RTX 3050 Ti）。
5. 检测是同步执行的，未来换大模型或多图批处理建议改成 `QThread`。

## 五、测试

| 脚本 | 覆盖 |
|---|---|
| `app\selftest_full.py` | 73 项：视觉层（含模型/图片缺失、损坏图、椭圆配对回归）、相机层、机器人层、任务层、GUI 每个按钮与异常路径，外加冷启动回归（子进程） |
| `app\selftest_coldstart.py` | 真实用户顺序：启动 GUI → **先选图片**（此时模型尚未加载）→ 才检测 |
| `app\selftest_realwindow.py` | 在真实窗口跑完整流程并截图 |
| `app\diag_imread.py` | 图片读取方案实测（中文路径 / ASCII 路径 / PNG） |
| `app\diag_ellipse.py` | 椭圆拟合质量实测（轮廓点到椭圆的 RMS 偏差） |

改完代码请至少跑前两个。
