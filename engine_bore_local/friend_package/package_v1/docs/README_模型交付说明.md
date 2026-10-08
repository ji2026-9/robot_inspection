# 模型交付说明（robot_inspection_model_package_v1）

交付时间：2026-10-06　｜　来源项目：`E:\robot_inspection`

---

## 1. 项目名称

**机械臂智能视觉检测 / 机械臂自主控制与智能检测**

## 2. 模型任务

使用 **YOLO-Seg（实例分割）** 检测大型工业箱体顶部的**四个大型结构孔**。

- 输入：一张工业相机/手机拍摄的箱体照片
- 输出：每个目标孔的**分割掩膜（mask）**、边界框与置信度

## 3. 类别

```
class 0 : cylinder_bore
```

只有 **1 个类别**，数据集内所有目标孔统一标注为 `cylinder_bore`。

## 4. 模型

**YOLO11n-Seg**（`yolo11n-seg.pt` 预训练权重迁移训练）

## 5. 当前模型文件

```
weights/best.pt
```

（约 5.99 MB；SHA256 见 `docs/SHA256.txt`）

## 6. 当前模型用途

检测四个目标大孔，并通过 segmentation mask 提取孔区域。

## 7. 后处理流程

当前项目使用：

```
YOLO segmentation mask
   → 取最大轮廓（cv2.findContours）
   → 椭圆拟合（cv2.fitEllipse）
   → 孔中心（椭圆中心）
```

编号：4 个孔中心做 **PCA 求长轴** → 沿主轴排序 → `H01–H04`。

## 8. 当前模型不是最终机器人控制模型

当前已完成：

- 目标检测 / 分割
- 孔中心定位
- 当前图像中的 H01–H04 编号

## 9. 关于 H01–H04 的重要说明

**当前 H01–H04 是「当前检测图像中的编号」，不是已经解决的永久物理 H01–H04。**

已实测（见本项目 `experiments\stable_hole_id\`）：

- PCA 只能给出「轴」，不能给出「方向」；
- 把同一张图**旋转 180°** 后，同一个物理孔的编号会**全部对调**（H01↔H04、H02↔H03）；
- 因此当前编号**不满足 180° 旋转不变性**，不能直接用于机器人"测量 H03"这类物理语义指令。

## 10. 当前尚未完成

- 工业相机标定
- 像素坐标到机械臂坐标转换
- 手眼标定
- 真实机器人运动控制
- 永久物理孔身份识别（需要稳定的方向参考：固定标记 / 工装基准 / 可靠的箱体轮廓分割）

## 11. 朋友下一步工作（建议顺序）

1. **先验证这个模型**：运行 `verify\verify_package.py`，再用 `inference\predict_holes.py` 对 `test_images\` 做一次推理；
2. **再检查你自己的数据**：类别名称、class id、标注格式（YOLO-Seg 多边形？）、标注对象是否也是"四个大型孔"；
3. **再考虑数据融合训练**：请**先读 `docs/FUSION_PLAN.md`**，按其中的检查清单逐项确认，再建立独立实验目录 `experiments\fusion_v1\`，**不要覆盖 baseline**。

---

## 附：目录结构

```
package_v1\
├── weights\best.pt                 交付模型（原始 baseline）
├── dataset\
│   └── box_yolo\                   data.yaml + images/{train,val,test} + labels/{train,val,test}
├── test_images\                    测试1.jpg ~ 测试4.jpg
├── inference\predict_holes.py      推理 + 椭圆拟合 + PCA 编号脚本
├── docs\
│   ├── README_模型交付说明.md      ← 本文件
│   ├── TRAINING_INFO.txt           真实训练环境与超参数
│   ├── DATASET_INFO.txt            数据集统计与标注对象说明
│   ├── FUSION_PLAN.md              融合训练方案与检查清单
│   └── SHA256.txt                  关键文件校验表
└── verify\
    ├── verify_package.py           包完整性 + 模型可加载性验证
    └── inference_check\            交付前的只读推理结果（JSON + 可视化）
```

## 附：使用注意（实机踩过的坑）

1. **`dataset\box_yolo\data.yaml` 里写的是 `path: .`**（相对路径）。Ultralytics 对相对 `path` 的解析依赖当前工作目录，可能报
   `images not found`。最稳妥的做法是把 `path` 改成绝对路径，例如：
   `path: <你的解压目录>/dataset/box_yolo`。
2. `inference\predict_holes.py` 里的默认路径是原项目的绝对路径（`E:\robot_inspection\...`）。
   在你自己电脑上运行时，请用参数指定，例如：
   ```
   python predict_holes.py --weights ../weights/best.pt --source ../test_images --out ../verify/inference_check
   ```
3. 环境要求：Python 3.11 + PyTorch（GPU 版）+ ultralytics + opencv-python。参考 `docs/TRAINING_INFO.txt` 中的版本号。

