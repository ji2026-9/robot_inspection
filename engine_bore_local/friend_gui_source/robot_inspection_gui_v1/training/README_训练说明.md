# 训练 / 评估脚本（二次优化用）

这四个文件是从开发机项目里复制出来的**逐字副本，只改了一行路径常量**：
原来的 `E:\robot_inspection\...` 改成了"相对于本包根目录"，所以放到任何盘符都能跑。

| 文件 | 作用 |
|---|---|
| `train_seg.py` | YOLO11n-Seg 训练（默认 epochs=100, imgsz=640, batch=2, workers=2, patience=20, device=0；显存不足自动降 batch/imgsz） |
| `predict_holes.py` | 4 张测试图推理 + 椭圆拟合 + PCA 编号 H01~H04 + 可视化 |
| `check_dataset.py` | 检查 images/labels 数量是否一一对应 |
| `eval_confidences.py` | 逐图逐孔打印置信度 |

## 运行前

先双击包根目录的 **`setup_env.bat`**（创建 `.venv` 并装依赖），然后：

```bat
cd /d <本包根目录>
.venv\Scripts\python.exe training\check_dataset.py
.venv\Scripts\python.exe training\train_seg.py --epochs 1 --name smoke_test      :: 先冒烟 1 轮
.venv\Scripts\python.exe training\train_seg.py                                    :: 正式 100 轮
.venv\Scripts\python.exe training\predict_holes.py --weights weights\best.pt
```

## 必须知道的几点

1. `train_seg.py` 默认会把训练出的 `best.pt` **覆盖到 `<包根>\weights\best.pt`**。
   想保留现在的模型，先把它改名备份，例如 `weights\best_v1_backup.pt`。
2. 预训练权重 `yolo11n-seg.pt` 第一次运行会**联网自动下载**。
3. 训练输出在 `<包根>\runs\`，日志在 `<包根>\logs\`。
4. 数据集是 `<包根>\dataset\box_yolo`（20 train / 2 val / 3 test）。
   注意：这个样本量很小，换超参后结果会有随机波动——评估请用**同一套**测试图和**同样的 conf=0.50**，
   并且至少跑多个 seed（开发机上 5 个 seed 的结果是 38/40 = 95%）。
5. RTX 3050 Ti 4GB 请保持 `batch<=2`；脚本已内置 OOM 自动降级。
6. 所有脚本都带命令行参数（`--data`、`--project`、`--weights`、`--source` 等），
   默认值全部指向本包内部。
