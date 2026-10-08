# Orbbec Gemini 335Le 工业相机接入记录

日期：2026-10-08　　软件：`E:\robot_project\inspection_app`

---

## 一、相机信息（实测）

| 项目 | 值 | 来源 |
| --- | --- | --- |
| 型号 | **Orbbec Gemini 335Le** | OrbbecViewer 标题栏 + SDK 设备列表 |
| 序列号 | **CPEB4630005D** | OrbbecViewer 标题栏；软件驱动读回一致 |
| 接口 | **USB-Ethernet**（相机通过 USB 虚拟出一块网卡，走以太网协议） | 设备管理器 `USB\VID_38A2&PID_0153` |
| 相机地址 | **192.168.1.10** | OrbbecSDK 枚举结果 |
| 通信端口 | **8090** | SDK 报错日志 |
| 取流 | 彩色 1280×800@30，RGB888 | 实测取帧结果 |

---

## 二、为什么一开始连不上

OrbbecSDK 能**发现**相机，但连不上，日志写得很清楚：

```
VendorTCPClient: Connect to server failed!
addr=192.168.1.10, port=8090, err=socket is not ready & timeout
```

原因：相机挂在 USB 虚拟网卡「以太网 2」上，相机自己是 `192.168.1.10`，
而电脑这块网卡拿到的是 `169.254.209.66`（APIPA，也就是"没分配到地址"），
**两边不在同一网段，自然 ping 不通、TCP 也连不上**。

---

## 三、解决办法（已执行）

把电脑这一侧设成与相机同网段：

```powershell
netsh interface ip set address name="以太网 2" static 192.168.1.100 255.255.255.0
```

* **只改这一块相机专用网卡**，不设网关 → 不影响 Wi-Fi 上网；
* 需要管理员权限，所以做成了脚本，方便随时重做：
  * `E:\robot_project\tools\set_camera_ip.ps1`（主脚本）
  * `E:\robot_project\tools\设置相机网段.bat`（**双击即可**，会弹一次"用户账户控制"，点"是"）
  * 执行结果写在 `E:\robot_project\tools\set_camera_ip_result.txt`

### 验证结果（全部实测）

| 检查 | 结果 |
| --- | --- |
| 网卡地址 | `192.168.1.100 /24` ✅ |
| ARP | `192.168.1.10 → 54-14-fd-24-60-90` ✅ |
| TCP 8090 | `TcpTestSucceeded = True` ✅ |
| OrbbecViewer | 标题栏显示 `Orbbec Gemini 335Le SN:CPEB4630005D Ethernet`，日志持续读取传感器参数 ✅ |
| 自研驱动取帧 | 40 帧 / 9 秒，图 1280×800×3，画面正常 ✅ |

> 注：这块相机**不响应 ping（ICMP）**，`ping 不通` 不代表没连上，要看 TCP 8090。

---

## 四、软件里做了什么

### 1. 新增相机驱动 `inspection_gui/orbbec_camera.py`

用 ctypes 调用**已安装的 OrbbecSDK v2**（`D:\OrbbecSDK_v2.9.3\...\bin\OrbbecSDK.dll`），
实现 `devices_view` 约定的 `connect / disconnect / is_connected / start / stop / get_frame`：

* 自动按「设备连接」里填的**序列号**找设备；
* 依次尝试 1280×800@30 RGB → 1280×720 → 848×480 → 640×480 → YUYV，取第一个能用的；
* `get_frame()` 返回 **BGR uint8 三通道**，和检测管线直接对接；
* SDK 路径可用环境变量 `ORBBEC_SDK_BIN` 覆盖。

### 2. 在设备页注册（`devices_view.py`）

```python
try:
    from .orbbec_camera import OrbbecCamera
    _registered_backends['camera'] = OrbbecCamera()
except (ImportError, OSError):
    pass        # 没装 SDK 时保持"未接入"，不假装已连接
```

### 3. 「设备连接 → 工业相机」已填入真实信息

厂家 `Orbbec`／型号 `Gemini 335Le`／连接方式 `网口`／地址 `192.168.1.10`／端口 `8090`／
序列号 `CPEB4630005D`（配置文件 `inspection_gui/device_settings.json`）。

### 4. 主界面新增「**用工业相机拍照**」按钮

位置：左侧「操作」栏，紧跟在「① 选择照片」下面。

点一下做的事：连相机 → 取一帧 → **无损留样**（`capture_archive.save_capture`：
PNG + 同批 JSON，含 SHA256/尺寸/时间/参数，绝不覆盖）→ 自动放进工作区 →
接着就能点「② 开始检测」。

留样目录：`inspection_app\captures\<日期>\capture_*.png` 与同名 `.json`。

---

## 五、边界（不要误解）

1. **连接成功 ≠ 能测量。** 「测量就绪检查」里 6 项仍然是"未满足"：
   相机内参标定、手眼标定及双臂坐标转换、测针 TCP 与孔轴方向、运动路径与测量接口，
   以及未接的两条机械臂。这些做完之前，「③ 发送测量任务」保持禁用。
2. 留样里的时间是**电脑接收帧时间**，不是相机硬件曝光时间（JSON 里已注明）。
3. **实时预览已接好**（见下一节）：预览本身不写文件，"抓拍"才留样。
4. 只取彩色图；深度图暂未使用（本项目孔检测只需要彩色图）。

---

## 五之二、实时预览（2026-10-08 追加）

入口：主界面左下「其他功能 → **相机实时预览**」。

取流线程**直接复用朋友分支的 `vision_workspace.CameraPreviewWorker`**，
后台线程持续取帧、界面线程只负责显示，所以预览不会卡住界面。
界面文件 `inspection_gui/camera_preview.py`（我们写的，放在仓库
`scripts/app_addons/` 里做版本管理，由补丁脚本部署到软件目录）。

窗口里能做的事：

| 按钮 | 作用 |
| --- | --- |
| 开始预览 / 停止预览 | 开关实时画面；停止时只停取流，**相机保持连接** |
| 抓拍并放入工作区 | 用当前帧做无损留样，并放进主窗口工作区（不自动检测） |
| 抓拍并直接检测 | 同上，并立刻触发主窗口的「② 开始检测」 |

实测：**1280×800，约 22 帧/秒**；画面正常，抓拍后主窗口「本组照片」变成 1/1，
「② 开始检测」随即可用。

细节处理：实时预览正在取流时，点主界面的「用工业相机拍照」不会去抢相机，
而是直接交给预览窗口用当前帧抓拍——避免两条取流互相打断（相机 SDK 同一条管线不能并发取帧）。

---

## 六、换电脑 / 重装后怎么恢复（三步）

1. 装 OrbbecSDK v2（默认装到 `D:\OrbbecSDK_v2.9.3\...`，或装好后设 `ORBBEC_SDK_BIN`）。
2. 双击 `E:\robot_project\tools\设置相机网段.bat`，在"用户账户控制"里点"是"。
3. 打开软件的「设备连接 → 工业相机」→ 点「连接设备」，状态应变成"● 已连接"；
   再回主界面点「用工业相机拍照」即可。

出问题时先看两处：`tools\set_camera_ip_result.txt` 和相机网卡的地址是不是
`192.168.1.100`（Windows 有时会把 USB 网卡识别成"以太网 3"，那就再双击一次那个 bat）。
