# app\ —— 视觉核心库

这里是**检测与拟合的核心代码**，被脚本和回归测试直接调用，不是界面。

| 文件 | 作用 |
| --- | --- |
| `vision.py` | YOLO-Seg 推理 → mask → 最大轮廓 → 椭圆拟合 → PCA 编号 H01~H04 |
| `config.py` | 路径与参数（`PROJ` 自动适配项目位置；`ELLIPSE_FIT_MODE` 选择拟合策略） |
| `robust_bore_ellipse.py` | 稳健椭圆拟合（RANSAC + 内点重拟合） |
| `edge_bore_refinement.py` | 孔口边缘亚像素精修（反光孔的关键） |
| `imageio_util.py` | 中文路径安全读写（`np.fromfile + cv2.imdecode`） |
| `dobot_feedback.py` | DOBOT V4 **只读**反馈解码（留给机器人阶段） |

谁在用：

- `scripts\compare_ellipse_fit.py`、`scripts\compare_fit_policy.py` —— 拟合方式对比
- `scripts\patch_friend_engine.py` —— 给最终版软件打补丁时读这里的模型

> ⚠️ **界面已经统一到 `E:\robot_project\inspection_app\`（融合版）。**
> 我方早期的 PySide6 界面已归档到 `_archive\gui_v1_pyside6\`，只作参考，
> 不再作为日常使用的软件。
