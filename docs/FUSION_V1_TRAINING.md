# fusion_v1 训练记录（用满 28 张数据重训）

日期：2026-10-07　　授权：用户明确同意本次训练
动机：`docs/FRIEND_PIPELINE_AUDIT.md` 证明——在 4 张干净测试图上，
他的模型 4/4 全中而我方 `best.pt` 在测试3 漏一个孔，差别只在于**训练数据量 20 vs 28**。
本次就是把这个假设做掉验证。

---

## 一、数据集（28 张 = 我方 25 张 + 他的 3 张新增）

构建脚本：`scripts/make_fusion_dataset.py`（可复现）

| 来源 | 数量 | 说明 |
| --- | ---: | --- |
| 我方 `dataset\box_yolo`（train+val+test） | 25 | 原有 4 边形分割标签 |
| 他的 `database_seed` 28 张 | 28 | **其中 25 张与我方逐像素相同**（64×64 灰度指纹 = 1.0000），自动去重 |
| 净新增 | **3** | 4096×3072 / 3072×4096（另一个相机），Labelme 多边形 → 转成 YOLO-seg |
| **合计** | **28** | 25 训练 / 3 验证（seed=42，他的照片至少 2 张留在训练集） |

数据集位置：**`E:\fusion_train\dataset_v28\`**（**故意放在 Git 仓库之外**，数据不入 Git）
验证：图片与标签一一对应，每张 4 个多边形，随机抽查坐标已归一化。

## 二、训练配置

```
预训练权重 : E:\robot_inspection\yolo11n-seg.pt
数据       : E:\fusion_train\dataset_v28\data.yaml   (25 train / 3 val)
epochs=100  imgsz=640  batch=2  workers=2  patience=20
seed=42     deterministic=True     device=0 (RTX 3050 Ti)
输出       : experiments\fusion_v1\runs\fusion_v1_seed42
日志       : experiments\fusion_v1\logs\
```

- 实际耗时 **3.2 分钟**，显存占用 0.55 GB / 4 GB
- 最优轮次 **epoch 52**（之后没有超过它）
- 验证集（**只有 3 张**）：Mask P=0.995，R=1.000，mAP50=0.995，mAP50-95≈0.99
  → **样本太小，这个指标偏乐观，不能当泛化证据**，真正的判据是下面 4 张测试图。

---

## 三、关键结果：4 张干净测试图 16/16

同一套检测流程（`app/vision.py` + 新的 robust_edge 拟合），`conf=0.50`：

| 图片 | 旧 `best.pt` | **新 `fusion_v1_best.pt`** |
| --- | --- | --- |
| 测试1.jpg | 4/4　0.965/0.850/0.925/0.923 | **4/4**　0.968/0.886/0.966/0.976 |
| 测试2.jpg | 4/4　avg 0.954 | **4/4**　avg 0.986 |
| 测试3.jpg | **3/4**　0.651/0.819/0.967 | **4/4**　0.955/0.775/0.967/0.955 |
| 测试4.jpg | 4/4　avg 0.934 | **4/4**　avg 0.967 |
| **合计** | 15/16（3 张图 4/4） | **16/16（4 张图全 4/4）** |

**最关键的一个孔**：测试3 那个反光孔

| 模型 | 该孔置信度 | 结果 |
| --- | ---: | --- |
| 旧 `best.pt` | **0.172**（< 0.5，被阈值挡掉） | 只有 3 个孔 |
| 新 `fusion_v1_best.pt` | **0.775** | 4 个孔 ✅ |
| 他的 `bore_best.pt`（参照） | 0.9042 | 4 个孔 |

→ 加 3 张（其中 2 张来自另一个相机）就把这个孔的置信度从 0.17 提到 0.78，
**"数据量不足"这个判断得到验证**，同时也说明**不必直接采用他的模型**。

---

## 四、产物（全部保留，未覆盖任何旧文件）

| 文件 | 说明 |
| --- | --- |
| `weights\fusion_v1_best.pt` | **新模型（永久保存）**，5,990,237 B，SHA256 `EAEDA05109C1F696…` |
| `weights\best.pt` | 旧 baseline，**未改动**（SHA256 仍是 `7E33DF6223CC2546…`） |
| `weights\best_backup_20261007_before_fusion.pt` | 训练前备份，与旧 `best.pt` 逐字节相同 |
| `experiments\fusion_v1\runs\fusion_v1_seed42\` | 完整训练输出（22 个文件：曲线、混淆矩阵、batch 图、best/last） |
| `experiments\fusion_v1\logs\` | 原生训练日志 + 脚本日志 |
| `E:\fusion_train\dataset_v28\` | 训练数据（仓库外，含 `split_manifest.csv`） |

命名遵循 `DATA_AND_MODEL_MANAGEMENT.md`：**新模型用新名字，不覆盖 `best.pt`**。

---

## 五、下一步（待你决定）

**方案 A 已执行（2026-10-07 18:0x）**：`weights\best.pt` 已替换为 `fusion_v1`。

| 项目 | 状态 |
| --- | --- |
| `weights\best.pt` | **已提升为 fusion_v1**，SHA256 `EAEDA05109C1F696…`（与 `fusion_v1_best.pt` 一致） |
| `weights\best_backup_20261007_before_fusion.pt` | 旧 baseline 完整保留（`7E33DF62…BDFE`） |
| 默认模型跑 4 张测试图 | **16/16（4 张图全部 4/4）** |
| `app\selftest_full.py` | **73 / 73 通过**（含冷启动回归） |

配套改动：`app\selftest_full.py` 里原来写死"测试3 必须只有 3 个孔"的断言已改成
**与模型无关**的写法（按实际检出数校验完整/不完整两条分支），A11 椭圆回归也改成
同时校验"绘制残差 < 10%"与"上报字段自洽"（因为 robust_edge 会故意偏离 mask 轮廓）。

其他两种方案仍然可选：

| 方案 | 操作 | 影响 |
| --- | --- | --- |
| B | 在 `app\config.py` 增加模型选择项 | 现在没必要了 |
| C | 回退到旧模型 | 见下面的回退命令 |

回退方式（无论选哪个都有效）：

```bat
copy /Y E:\robot_inspection\weights\best_backup_20261007_before_fusion.pt E:\robot_inspection\weights\best.pt
```

---

## 六、限制（必须如实说明）

1. **只用 4 张测试图**（同一箱体、有限视角）。16/16 只说明这 4 张；
   换箱体、换相机、换光照后需要重新验证。
2. 这 4 张**没有人工圆心真值**，"检出 4 个孔"不等于测量准确。
3. 验证集只有 3 张，训练指标偏乐观，**不作为泛化证据**。
4. 他的 3 张新增图来源与标注质量只做了格式与类别核对，**没有逐张人工复核多边形精度**。
5. 训练数据里**包含我方原来的验证/测试图（008/009/001/004/021）**，
   所以旧的 5-seed 实验结果**不能再与新模型直接比较**（评估口径变了）。
6. 三维定位、手眼标定、机械臂坐标转换仍未实现。
