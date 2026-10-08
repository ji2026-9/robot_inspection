"""Orbbec Gemini 335Le 工业相机驱动。

通过**已安装**的 OrbbecSDK v2（`OrbbecSDK.dll`）的 C 接口取彩色图，
对齐 `devices_view.DeviceConnection` / `CameraConnection` 约定：

    connect(settings) / disconnect() / is_connected()
    start() / stop() / get_frame()          # get_frame 返回 uint8 BGR 三通道图像

边界（与 `CAMERA_DRIVER_CONTRACT.md` 一致）：

* 取得彩色与原始深度图，用于孔检测及相机坐标估计；**不连接、不使能、不发送任何机械臂运动**；
* 连接成功仅代表打开设备；有效深度和工厂内参仍需检查，机械臂坐标需另行标定；
* 设备地址等参数由「设备连接 → 工业相机」保存，本模块不写任何配置文件。

SDK 位置查找顺序：环境变量 ``ORBBEC_SDK_BIN`` → 已安装的默认路径。
"""
from __future__ import annotations

import ctypes
import os
import threading
import time
import ipaddress
from ctypes import POINTER, byref, c_char_p, c_int32, c_uint8, c_uint16, c_uint32, c_void_p
from pathlib import Path
from .rgbd_geometry import CameraParam, camera_param_dict

import numpy as np

OB_STREAM_COLOR = 2
OB_FORMAT_YUYV = 0
OB_FORMAT_YUY2 = 1
OB_FORMAT_RGB = 22          # OB_FORMAT_RGB888
OB_FORMAT_BGR = 23
OB_FORMAT_MJPG = 5

DEFAULT_BIN_DIRS = (
    r"C:\Program Files\OrbbecSDK 2.9.3\bin",
    r"D:\OrbbecSDK_v2.9.3\OrbbecSDK 2.9.3\bin",
    r"C:\Program Files\Orbbec\OrbbecSDK\bin",
    r"C:\Program Files (x86)\Orbbec\OrbbecSDK\bin",
)

# 依次尝试的彩色流配置：分辨率、帧率、像素格式
PROFILE_CANDIDATES = (
    (1280, 800, 30, OB_FORMAT_MJPG),
    (1280, 800, 15, OB_FORMAT_MJPG),
    (640, 480, 15, OB_FORMAT_MJPG),
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
        self._dll_directory = None
        self._last_frame_at = 0
        self._stream_started_at = 0
        self.calibration = None
        self.depth_enabled = False
        self._capture_packet = None

    # ---------------------------------------------------------------- SDK 装载
    def _ensure_library(self) -> bool:
        if self._lib is not None:
            return True
        if self._bin_dir is None:
            self.last_error = "未找到 OrbbecSDK.dll，请先安装 OrbbecSDK 或设置 ORBBEC_SDK_BIN"
            return False
        try:
            self._dll_directory = os.add_dll_directory(str(self._bin_dir))
            self._lib = ctypes.CDLL(str(self._bin_dir / "OrbbecSDK.dll"))
        except OSError as error:
            self._lib = None
            self.last_error = f"OrbbecSDK.dll 加载失败：{error}"
            return False
        lib = self._lib
        lib.ob_pipeline_get_camera_param.restype, lib.ob_pipeline_get_camera_param.argtypes = CameraParam, [c_void_p, POINTER(c_void_p)]
        lib.ob_frameset_get_depth_frame.restype, lib.ob_frameset_get_depth_frame.argtypes = c_void_p, [c_void_p, POINTER(c_void_p)]
        lib.ob_depth_frame_get_value_scale.restype, lib.ob_depth_frame_get_value_scale.argtypes = ctypes.c_float, [c_void_p, POINTER(c_void_p)]
        lib.ob_frame_get_timestamp_us.restype, lib.ob_frame_get_timestamp_us.argtypes = ctypes.c_uint64, [c_void_p, POINTER(c_void_p)]
        lib.ob_create_net_device.restype, lib.ob_create_net_device.argtypes = c_void_p, [c_void_p, c_char_p, c_uint16, POINTER(c_void_p)]
        lib.ob_device_list_get_device_serial_number.restype, lib.ob_device_list_get_device_serial_number.argtypes = c_char_p, [c_void_p, c_uint32, POINTER(c_void_p)]
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
                if self._pipeline:
                    self.stop()
                    self._teardown()
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
        wanted = str(settings.get('serial_number', '')).strip().upper()
        address = str(settings.get('address', '')).strip()
        if address:
            ipaddress.IPv4Address(address)
            port = int(settings.get('port') or 8090)
            if not 1 <= port <= 65535:
                raise ValueError('相机端口不正确')
            self._device = self._lib.ob_create_net_device(self._context, address.encode('ascii'), port, byref(error))
            self._raise_if_error(error, '按 IP 打开相机失败')
            if not self._device:
                raise RuntimeError('指定 IP 未返回相机设备')
            self.device_serial = self._read_serial()
            if wanted and self.device_serial.upper() != wanted:
                raise RuntimeError('指定 IP 的相机序列号与配置不一致，已拒绝连接')
            self.device_uid = address
            self.device_name = self._read_name()
            return
        self._device_list = self._lib.ob_query_device_list(self._context, byref(error))
        self._raise_if_error(error, "查询相机列表失败")
        count = self._lib.ob_device_list_get_count(self._device_list, byref(error))
        self._raise_if_error(error, '读取相机数量失败')
        if not count:
            raise RuntimeError("没有发现 Orbbec 相机：请确认相机 USB 已插好，"
                               "且本机网卡地址与相机（192.168.1.10）在同一网段。")
        if not wanted and count != 1:
            raise RuntimeError('发现多台相机，请填写 IP 或准确序列号')
        index = 0
        matched = not wanted
        for candidate in range(count):
            if not wanted:
                break
            serial = self._lib.ob_device_list_get_device_serial_number(self._device_list, candidate, byref(error)) or b""
            self._raise_if_error(error, '读取相机序列号失败')
            if wanted == serial.decode('utf-8', 'ignore').upper():
                index = candidate
                matched = True
                break
        if not matched:
            raise RuntimeError('没有找到指定序列号的相机，不会连接其他设备')
        name = self._lib.ob_device_list_get_device_name(self._device_list, index, byref(error)) or b""
        uid = self._lib.ob_device_list_get_device_uid(self._device_list, index, byref(error)) or b""
        self.device_name = name.decode("utf-8", "ignore")
        self.device_uid = uid.decode("utf-8", "ignore")
        self._device = self._lib.ob_device_list_get_device(self._device_list, index, byref(error))
        self._raise_if_error(error, "打开相机失败")
        if not self._device:
            raise RuntimeError("打开相机失败：设备句柄为空。")
        self.device_serial = self._read_serial()
        if wanted and self.device_serial.upper() != wanted:
            raise RuntimeError('相机真实序列号核对失败')

    def _read_name(self):
        error = c_void_p(None)
        getter = self._lib.ob_device_info_get_name
        getter.restype, getter.argtypes = c_char_p, [c_void_p, POINTER(c_void_p)]
        info = self._lib.ob_device_get_device_info(self._device, byref(error))
        self._raise_if_error(error, '读取设备信息失败')
        try:
            raw = getter(info, byref(error)) or b''
            self._raise_if_error(error, '读取设备型号失败')
            return raw.decode('utf8', 'ignore')
        finally:
            self._lib.ob_delete_device_info(info, byref(error))
            self._raise_if_error(error, '释放设备信息失败')

    def _read_serial(self) -> str:
        """读设备真实序列号，用来和「设备连接」里填写的序列号核对。"""
        error = c_void_p(None)
        try:
            info = self._lib.ob_device_get_device_info(self._device, byref(error))
            self._raise_if_error(error, '读取设备信息失败')
            if not info:
                return ""
            try:
                raw = self._lib.ob_device_info_get_serial_number(info, byref(error)) or b""
                self._raise_if_error(error, '读取真实序列号失败')
            finally:
                self._lib.ob_delete_device_info(info, byref(error))
                self._raise_if_error(error, '释放设备信息失败')
            return raw.decode("utf-8", "ignore")
        except (AttributeError, OSError):
            return ""

    def _raise_if_error(self, error, prefix):
        has_error = bool(error.value)
        message = self._message(error.value)
        error.value = None
        if has_error:
            raise RuntimeError(f"{prefix}：{message or 'SDK 未返回具体原因'}")

    def is_connected(self) -> bool:
        if self._started and time.monotonic() - (self._last_frame_at or self._stream_started_at) > 3:
            self._connected = False
            self.last_error = '相机超过3秒没有新图像，连接状态已失效，请重新连接'
            return False
        return bool(self._connected)

    def disconnect(self) -> None:
        if getattr(self, '_inspection_acquiring', False):
            raise RuntimeError('请先停止实时采集，等待采集结束后再断开相机')
        with self._lock:
            self.stop()
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
                error = c_void_p(None)
                self._lib.ob_config_enable_video_stream(config, 3, 640, 400, fps, 8, byref(error))
                message = self._message(error.value)
                self.depth_enabled = not bool(message)
                if not self.depth_enabled:
                    error = c_void_p(None)
                    self._lib.ob_config_enable_stream(config, 3, byref(error))
                    message = self._message(error.value)
                    self.depth_enabled = not bool(message)
                error = c_void_p(None)
                self._lib.ob_pipeline_start_with_config(self._pipeline, config, byref(error))
                message = self._message(error.value)
                if message:
                    last = message
                    self._lib.ob_delete_config(config, byref(error))
                    continue
                self._config = config
                self._started = True
                self._last_frame_at = 0
                self._stream_started_at = time.monotonic()
                self.profile = f"{width}x{height}@{fps} 格式{pixel_format}"
                self.calibration = None
                if self.depth_enabled:
                    error = c_void_p(None)
                    param = self._lib.ob_pipeline_get_camera_param(self._pipeline, byref(error))
                    message = self._message(error.value)
                    if not message:
                        self.calibration = camera_param_dict(param)
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
            self._capture_packet = None

    def get_frame(self):
        """取一帧彩色图；超时返回 None。返回的数组是 BGR（uint8，三通道）。

        用锁串行化：实时预览线程和「拍照」按钮可能同时取帧，
        SDK 的同一条管线不支持并发取帧。
        """
        if not self._started:
            return None
        with self._lock:
            return self._grab_frame()

    def get_capture_packet(self):
        if not self._started:
            return None
        with self._lock:
            image = self._grab_frame()
            return self._capture_packet if image is not None else None

    def _grab_frame(self):
        error = c_void_p(None)
        frameset = self._lib.ob_pipeline_wait_for_frameset(self._pipeline, 500, byref(error))
        message = self._message(error.value)
        if message:
            self.last_error = message
            return None
        if not frameset:
            return None
        frame = None
        depth_frame = None
        self._capture_packet = None
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
            image = self._to_bgr(buffer, width, height, pixel_format)
            if image is not None:
                self._last_frame_at = time.monotonic()
                packet = {'frame': image, 'calibration': self.calibration, 'depth_raw': None, 'depth_note': '未取得深度帧'}
                if self.depth_enabled and self.calibration:
                    error = c_void_p(None)
                    depth_frame = self._lib.ob_frameset_get_depth_frame(frameset, byref(error))
                    self._raise_if_error(error, '读取深度帧失败')
                    if depth_frame:
                        dw = self._lib.ob_video_frame_get_width(depth_frame, byref(error))
                        dh = self._lib.ob_video_frame_get_height(depth_frame, byref(error))
                        fmt = self._lib.ob_frame_get_format(depth_frame, byref(error))
                        dsize = self._lib.ob_frame_get_data_size(depth_frame, byref(error))
                        dp = self._lib.ob_frame_get_data(depth_frame, byref(error))
                        scale = self._lib.ob_depth_frame_get_value_scale(depth_frame, byref(error))
                        ct = self._lib.ob_frame_get_timestamp_us(frame, byref(error))
                        dt = self._lib.ob_frame_get_timestamp_us(depth_frame, byref(error))
                        self._raise_if_error(error, '读取深度参数失败')
                        packet.update(color_timestamp_us=int(ct), depth_timestamp_us=int(dt), timestamp_delta_ms=abs(int(ct)-int(dt))/1000)
                        if fmt == 8 and dsize == dw*dh*2 and dp and scale > 0 and ct > 0 and dt > 0 and abs(int(ct)-int(dt)) <= 50000:
                            packet.update(depth_raw=np.frombuffer(ctypes.string_at(dp,dsize), dtype='<u2').reshape(dh,dw).copy(), depth_scale_mm=float(scale),depth_note='已取得时间差不超过50ms的彩色与深度帧')
                        else:
                            packet['depth_note'] = '深度格式、时间差或深度单位检查未通过'
                self._capture_packet = packet
            return image
        finally:
            error = c_void_p(None)
            if depth_frame:
                self._lib.ob_delete_frame(depth_frame, byref(error))
                self._message(error.value)
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
        if pixel_format == OB_FORMAT_MJPG:
            return cv2.imdecode(array, cv2.IMREAD_COLOR)
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
