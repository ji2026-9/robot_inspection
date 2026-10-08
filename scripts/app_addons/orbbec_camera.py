"""Orbbec Gemini 335Le 工业相机驱动。

通过**已安装**的 OrbbecSDK v2（`OrbbecSDK.dll`）的 C 接口取彩色图，
对齐 `devices_view.DeviceConnection` / `CameraConnection` 约定：

    connect(settings) / disconnect() / is_connected()
    start() / stop() / get_frame()          # get_frame 返回 uint8 BGR 三通道图像

边界（与 `CAMERA_DRIVER_CONTRACT.md` 一致）：

* 只取彩色图，用于孔检测；**不连接、不使能、不发送任何机械臂运动**；
* 连接成功**只代表能取到图像**，不代表完成相机内参标定或手眼标定；
* 设备地址等参数由「设备连接 → 工业相机」保存，本模块不写任何配置文件。

SDK 位置查找顺序：环境变量 ``ORBBEC_SDK_BIN`` → 已安装的默认路径。
"""
from __future__ import annotations

import ctypes
import os
import threading
from ctypes import POINTER, byref, c_char_p, c_int32, c_uint8, c_uint32, c_void_p
from pathlib import Path

import numpy as np

OB_STREAM_COLOR = 2
OB_FORMAT_YUYV = 0
OB_FORMAT_YUY2 = 1
OB_FORMAT_RGB = 22          # OB_FORMAT_RGB888
OB_FORMAT_BGR = 23

DEFAULT_BIN_DIRS = (
    r"D:\OrbbecSDK_v2.9.3\OrbbecSDK 2.9.3\bin",
    r"C:\Program Files\Orbbec\OrbbecSDK\bin",
    r"C:\Program Files (x86)\Orbbec\OrbbecSDK\bin",
)

# 依次尝试的彩色流配置：分辨率、帧率、像素格式
PROFILE_CANDIDATES = (
    (1280, 800, 30, OB_FORMAT_RGB),
    (1280, 720, 30, OB_FORMAT_RGB),
    (848, 480, 30, OB_FORMAT_RGB),
    (640, 480, 30, OB_FORMAT_RGB),
    (1280, 800, 30, OB_FORMAT_YUYV),
    (640, 480, 30, OB_FORMAT_YUYV),
)


def find_sdk_bin():
    """返回含 OrbbecSDK.dll 的目录，找不到返回 None。"""
    override = os.environ.get("ORBBEC_SDK_BIN", "").strip()
    for candidate in ((override,) if override else ()) + DEFAULT_BIN_DIRS:
        if candidate and Path(candidate, "OrbbecSDK.dll").is_file():
            return Path(candidate)
    return None


class OrbbecCamera:
    """Orbbec Gemini 335Le（网口/USB-Ethernet）彩色相机后端。"""

    def __init__(self, bin_dir=None):
        self._bin_dir = Path(bin_dir) if bin_dir else find_sdk_bin()
        self._lib = None
        self._context = None
        self._device = None
        self._pipeline = None
        self._config = None
        self._device_list = None
        self._connected = False
        self._started = False
        self._lock = threading.RLock()
        self.last_error = ""
        self.device_name = ""
        self.device_uid = ""
        self.device_serial = ""
        self.profile = ""

    # ---------------------------------------------------------------- SDK 装载
    def _ensure_library(self) -> bool:
        if self._lib is not None:
            return True
        if self._bin_dir is None:
            self.last_error = "未找到 OrbbecSDK.dll，请先安装 OrbbecSDK 或设置 ORBBEC_SDK_BIN"
            return False
        try:
            os.add_dll_directory(str(self._bin_dir))
            self._lib = ctypes.CDLL(str(self._bin_dir / "OrbbecSDK.dll"))
        except OSError as error:
            self._lib = None
            self.last_error = f"OrbbecSDK.dll 加载失败：{error}"
            return False
        lib = self._lib
        lib.ob_create_context.restype, lib.ob_create_context.argtypes = c_void_p, [POINTER(c_void_p)]
        lib.ob_query_device_list.restype, lib.ob_query_device_list.argtypes = c_void_p, [c_void_p, POINTER(c_void_p)]
        lib.ob_device_list_get_count.restype, lib.ob_device_list_get_count.argtypes = c_uint32, [c_void_p, POINTER(c_void_p)]
        lib.ob_device_list_get_device_name.restype, lib.ob_device_list_get_device_name.argtypes = c_char_p, [c_void_p, c_uint32, POINTER(c_void_p)]
        lib.ob_device_list_get_device_uid.restype, lib.ob_device_list_get_device_uid.argtypes = c_char_p, [c_void_p, c_uint32, POINTER(c_void_p)]
        lib.ob_device_list_get_device.restype, lib.ob_device_list_get_device.argtypes = c_void_p, [c_void_p, c_uint32, POINTER(c_void_p)]
        lib.ob_device_get_device_info.restype, lib.ob_device_get_device_info.argtypes = c_void_p, [c_void_p, POINTER(c_void_p)]
        lib.ob_device_info_get_serial_number.restype, lib.ob_device_info_get_serial_number.argtypes = c_char_p, [c_void_p, POINTER(c_void_p)]
        lib.ob_delete_device_info.restype, lib.ob_delete_device_info.argtypes = None, [c_void_p, POINTER(c_void_p)]
        lib.ob_create_pipeline_with_device.restype, lib.ob_create_pipeline_with_device.argtypes = c_void_p, [c_void_p, POINTER(c_void_p)]
        lib.ob_create_config.restype, lib.ob_create_config.argtypes = c_void_p, [POINTER(c_void_p)]
        lib.ob_config_enable_video_stream.restype = None
        lib.ob_config_enable_video_stream.argtypes = [c_void_p, c_int32, c_uint32, c_uint32, c_uint32, c_int32, POINTER(c_void_p)]
        lib.ob_config_enable_stream.restype, lib.ob_config_enable_stream.argtypes = None, [c_void_p, c_int32, POINTER(c_void_p)]
        lib.ob_pipeline_start_with_config.restype, lib.ob_pipeline_start_with_config.argtypes = None, [c_void_p, c_void_p, POINTER(c_void_p)]
        lib.ob_pipeline_stop.restype, lib.ob_pipeline_stop.argtypes = None, [c_void_p, POINTER(c_void_p)]
        lib.ob_pipeline_wait_for_frameset.restype, lib.ob_pipeline_wait_for_frameset.argtypes = c_void_p, [c_void_p, c_uint32, POINTER(c_void_p)]
        lib.ob_frameset_get_color_frame.restype, lib.ob_frameset_get_color_frame.argtypes = c_void_p, [c_void_p, POINTER(c_void_p)]
        lib.ob_video_frame_get_width.restype, lib.ob_video_frame_get_width.argtypes = c_uint32, [c_void_p, POINTER(c_void_p)]
        lib.ob_video_frame_get_height.restype, lib.ob_video_frame_get_height.argtypes = c_uint32, [c_void_p, POINTER(c_void_p)]
        lib.ob_frame_get_format.restype, lib.ob_frame_get_format.argtypes = c_int32, [c_void_p, POINTER(c_void_p)]
        lib.ob_frame_get_data_size.restype, lib.ob_frame_get_data_size.argtypes = c_uint32, [c_void_p, POINTER(c_void_p)]
        lib.ob_frame_get_data.restype, lib.ob_frame_get_data.argtypes = POINTER(c_uint8), [c_void_p, POINTER(c_void_p)]
        for name, args in (("ob_delete_frame", [c_void_p, POINTER(c_void_p)]),
                           ("ob_delete_pipeline", [c_void_p, POINTER(c_void_p)]),
                           ("ob_delete_config", [c_void_p, POINTER(c_void_p)]),
                           ("ob_delete_device", [c_void_p, POINTER(c_void_p)]),
                           ("ob_delete_device_list", [c_void_p, POINTER(c_void_p)]),
                           ("ob_delete_context", [c_void_p, POINTER(c_void_p)]),
                           ("ob_delete_error", [c_void_p])):
            function = getattr(lib, name, None)
            if function is not None:
                function.restype, function.argtypes = None, args
        return True

    def _message(self, error_pointer) -> str:
        """把 SDK 的 error 对象翻成字符串并释放它。"""
        if not error_pointer:
            return ""
        lib = self._lib
        text = ""
        try:
            getter = getattr(lib, "ob_error_get_message", None)
            if getter is not None:
                getter.restype, getter.argtypes = c_char_p, [c_void_p]
                raw = getter(error_pointer)
                if raw:
                    text = raw.decode("utf-8", "ignore")
        finally:
            try:
                lib.ob_delete_error(error_pointer)
            except (AttributeError, OSError):
                pass
        return text

    # ------------------------------------------------------------- 连接与断开
    def connect(self, settings=None) -> bool:
        """按「设备连接」里保存的地址/序列号找到并打开相机。"""
        settings = dict(settings or {})
        with self._lock:
            if self._connected:
                return True
            if not self._ensure_library():
                return False
            error = c_void_p(None)
            try:
                if not self._context:
                    self._context = self._lib.ob_create_context(byref(error))
                    self._raise_if_error(error, "创建 SDK 上下文失败")
                if not self._device:
                    self._open_device(settings)
                if not self._pipeline:
                    self._pipeline = self._lib.ob_create_pipeline_with_device(self._device, byref(error))
                    self._raise_if_error(error, "创建取流管线失败")
            except Exception as exc:            # noqa: BLE001 - 一律转成用户能看懂的一句话
                self.last_error = str(exc)
                self._teardown()
                return False
            self._connected = True
            self.last_error = ""
            return True

    def _open_device(self, settings) -> None:
        error = c_void_p(None)
        self._device_list = self._lib.ob_query_device_list(self._context, byref(error))
        self._raise_if_error(error, "查询相机列表失败")
        count = self._lib.ob_device_list_get_count(self._device_list, byref(error))
        if not count:
            raise RuntimeError("没有发现 Orbbec 相机：请确认相机 USB 已插好，"
                               "且本机网卡地址与相机（192.168.1.10）在同一网段。")
        wanted = str(settings.get("serial_number", "")).strip().upper()
        index = 0
        for candidate in range(count):
            if not wanted:
                break
            uid = self._lib.ob_device_list_get_device_uid(self._device_list, candidate, byref(error)) or b""
            name = self._lib.ob_device_list_get_device_name(self._device_list, candidate, byref(error)) or b""
            if wanted in (uid + name).decode("utf-8", "ignore").upper():
                index = candidate
                break
        name = self._lib.ob_device_list_get_device_name(self._device_list, index, byref(error)) or b""
        uid = self._lib.ob_device_list_get_device_uid(self._device_list, index, byref(error)) or b""
        self.device_name = name.decode("utf-8", "ignore")
        self.device_uid = uid.decode("utf-8", "ignore")
        self._device = self._lib.ob_device_list_get_device(self._device_list, index, byref(error))
        self._raise_if_error(error, "打开相机失败")
        if not self._device:
            raise RuntimeError("打开相机失败：设备句柄为空。")
        self.device_serial = self._read_serial()

    def _read_serial(self) -> str:
        """读设备真实序列号，用来和「设备连接」里填写的序列号核对。"""
        error = c_void_p(None)
        try:
            info = self._lib.ob_device_get_device_info(self._device, byref(error))
            if not info:
                return ""
            try:
                raw = self._lib.ob_device_info_get_serial_number(info, byref(error)) or b""
            finally:
                self._lib.ob_delete_device_info(info, byref(error))
                self._message(error.value)
            return raw.decode("utf-8", "ignore")
        except (AttributeError, OSError):
            return ""

    def _raise_if_error(self, error, prefix):
        message = self._message(error.value)
        if message:
            raise RuntimeError(f"{prefix}：{message}")

    def is_connected(self) -> bool:
        return bool(self._connected)

    def disconnect(self) -> None:
        with self._lock:
            self._teardown()

    def _teardown(self) -> None:
        error = c_void_p(None)
        lib = self._lib
        self._started = False
        self._connected = False
        if lib is None:
            return
        for attribute, deleter in (("_config", "ob_delete_config"),
                                   ("_pipeline", "ob_delete_pipeline"),
                                   ("_device", "ob_delete_device"),
                                   ("_device_list", "ob_delete_device_list"),
                                   ("_context", "ob_delete_context")):
            handle = getattr(self, attribute, None)
            if handle:
                try:
                    getattr(lib, deleter)(handle, byref(error))
                    self._message(error.value)
                except (AttributeError, OSError):
                    pass
                setattr(self, attribute, None)

    # ------------------------------------------------------------------ 取流
    def start(self) -> bool:
        """按候选配置启用彩色流。失败时把原因写进 ``last_error``。"""
        with self._lock:
            if self._started:
                return True
            if not self._connected and not self.connect():
                return False
            last = ""
            for width, height, fps, pixel_format in PROFILE_CANDIDATES:
                error = c_void_p(None)
                config = self._lib.ob_create_config(byref(error))
                self._raise_if_error(error, "创建流配置失败")
                self._lib.ob_config_enable_video_stream(
                    config, OB_STREAM_COLOR, width, height, fps, pixel_format, byref(error))
                message = self._message(error.value)
                if message:
                    last = message
                    self._lib.ob_delete_config(config, byref(error))
                    continue
                self._lib.ob_pipeline_start_with_config(self._pipeline, config, byref(error))
                message = self._message(error.value)
                if message:
                    last = message
                    self._lib.ob_delete_config(config, byref(error))
                    continue
                self._config = config
                self._started = True
                self.profile = f"{width}x{height}@{fps} 格式{pixel_format}"
                self.last_error = ""
                return True
            self.last_error = last or "相机没有可用的彩色流配置。"
            return False

    def stop(self) -> None:
        with self._lock:
            error = c_void_p(None)
            if self._lib is not None and self._pipeline and self._started:
                try:
                    self._lib.ob_pipeline_stop(self._pipeline, byref(error))
                    self._message(error.value)
                except (AttributeError, OSError):
                    pass
            if self._lib is not None and self._config:
                self._lib.ob_delete_config(self._config, byref(error))
                self._message(error.value)
            self._config = None
            self._started = False

    def get_frame(self):
        """取一帧彩色图；超时返回 None。返回的数组是 BGR（uint8，三通道）。

        用锁串行化：实时预览线程和「拍照」按钮可能同时取帧，
        SDK 的同一条管线不支持并发取帧。
        """
        if not self._started:
            return None
        with self._lock:
            return self._grab_frame()

    def _grab_frame(self):
        error = c_void_p(None)
        frameset = self._lib.ob_pipeline_wait_for_frameset(self._pipeline, 1000, byref(error))
        message = self._message(error.value)
        if message:
            self.last_error = message
            return None
        if not frameset:
            return None
        frame = None
        try:
            frame = self._lib.ob_frameset_get_color_frame(frameset, byref(error))
            message = self._message(error.value)
            if message:
                self.last_error = message
                return None
            if not frame:
                return None
            width = self._lib.ob_video_frame_get_width(frame, byref(error))
            height = self._lib.ob_video_frame_get_height(frame, byref(error))
            pixel_format = self._lib.ob_frame_get_format(frame, byref(error))
            size = self._lib.ob_frame_get_data_size(frame, byref(error))
            pointer = self._lib.ob_frame_get_data(frame, byref(error))
            if not pointer or not width or not height or not size:
                return None
            buffer = ctypes.string_at(pointer, size)
            return self._to_bgr(buffer, width, height, pixel_format)
        finally:
            error = c_void_p(None)
            if frame:
                self._lib.ob_delete_frame(frame, byref(error))
                self._message(error.value)
            self._lib.ob_delete_frame(frameset, byref(error))
            self._message(error.value)

    @staticmethod
    def _to_bgr(buffer, width, height, pixel_format):
        import cv2
        array = np.frombuffer(buffer, dtype=np.uint8)
        if pixel_format in (OB_FORMAT_RGB,):
            return cv2.cvtColor(array.reshape(height, width, 3), cv2.COLOR_RGB2BGR)
        if pixel_format in (OB_FORMAT_BGR,):
            return array.reshape(height, width, 3).copy()
        if pixel_format in (OB_FORMAT_YUYV, OB_FORMAT_YUY2):
            return cv2.cvtColor(array.reshape(height, width, 2), cv2.COLOR_YUV2BGR_YUYV)
        return None


def describe_devices() -> str:
    """自检用：列出当前能被 SDK 看到的 Orbbec 设备。"""
    camera = OrbbecCamera()
    if not camera._ensure_library():
        return camera.last_error
    error = c_void_p(None)
    context = camera._lib.ob_create_context(byref(error))
    message = camera._message(error.value)
    if message:
        return f"创建上下文失败：{message}"
    devices = camera._lib.ob_query_device_list(context, byref(error))
    count = camera._lib.ob_device_list_get_count(devices, byref(error))
    lines = [f"发现 {count} 台设备"]
    for index in range(count):
        name = camera._lib.ob_device_list_get_device_name(devices, index, byref(error)) or b""
        uid = camera._lib.ob_device_list_get_device_uid(devices, index, byref(error)) or b""
        lines.append(f"  [{index}] {name.decode('utf-8', 'ignore')}  UID {uid.decode('utf-8', 'ignore')}")
    camera._lib.ob_delete_device_list(devices, byref(error))
    camera._lib.ob_delete_context(context, byref(error))
    camera._message(error.value)
    return "\n".join(lines)
