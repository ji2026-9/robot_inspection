"""Device settings and honest connection states for the inspection shell.

The supplied camera and robot package has no hardware driver.  These panels
therefore keep configuration separate from connection state; saving settings
must never imply that a camera or arm is online.  A future driver can implement
the interfaces below and be registered through ``register_device_backend``.
No motion or image acquisition is initiated from this window.

[no-local-config] 设备参数（型号、地址、序列号等）只对本次运行有效：软件
不再把它们写到这台电脑上。换一台电脑时，打开软件就按那台电脑实际连接的
设备填写或由驱动自动读取，避免把上一台机器的参数带过去。
"""

from __future__ import annotations

import ipaddress
import re
import weakref
import threading
from copy import deepcopy
from pathlib import Path
from typing import Protocol

from PySide6.QtCore import Qt, Signal, QTimer
from .dobot_feedback import DobotFeedback
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFrame,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


# [no-local-config] 这个路径只用来兼容旧调用，程序不会再读写它。
SETTINGS_PATH = Path(__file__).with_name("device_settings.json")
DEVICE_TITLES = {
    "camera": "工业相机",
    "robot_a": "拍照机械臂 A",
    "robot_b": "测量机械臂 B",
}


class DeviceConnection(Protocol):
    """A driver's explicit connection contract, with no motion side effects."""

    def connect(self, settings: dict) -> bool: ...
    def disconnect(self) -> None: ...
    def is_connected(self) -> bool: ...


class CameraConnection(DeviceConnection, Protocol):
    """Compatible lifecycle with the friend's CameraBase."""

    def start(self) -> bool: ...
    def stop(self) -> None: ...
    def get_frame(self): ...


class RobotConnection(DeviceConnection, Protocol):
    """Compatible lifecycle with the friend's RobotBase."""

    def move_to_target(self, target): ...
    def execute_measurement(self, target): ...
    def stop(self) -> None: ...


_registered_backends: dict[str, DeviceConnection] = {}
_registered_backends['robot_b'] = DobotFeedback()
# [camera-sync] 真实相机驱动：Orbbec Gemini 335Le（USB-Ethernet）。
# 没有安装 OrbbecSDK 时保持“未接入”，绝不假装已连接。
try:
    from .orbbec_camera import OrbbecCamera
    _registered_backends['camera'] = OrbbecCamera()
except (ImportError, OSError):
    pass
_dialog_ref = None


def register_device_backend(device_id: str, backend: DeviceConnection) -> None:
    """Register an implemented driver; this does not open or move a device.

    A camera's connect() must not start acquisition.  A robot's connect() must
    not enable, home, or move the arm.  Drivers should handle their own bounded
    connection timeout.  The current integration registers no real drivers.
    """
    if device_id not in DEVICE_TITLES:
        raise ValueError(f"Unknown device: {device_id}")
    for name in ("connect", "disconnect", "is_connected"):
        if not callable(getattr(backend, name, None)):
            raise TypeError(f"Device backend must implement {name}()")
    _registered_backends[device_id] = backend


def _default_settings() -> dict:
    return {
        device: {
            "manufacturer": "",
            "model": "",
            "transport": "网口",
            "address": "",
            "port": 0,
            "serial_number": "",
        }
        for device in DEVICE_TITLES
    }


# [no-local-config] 设备参数不再从磁盘读取、也不再写入磁盘。
# 只保留一份“本次运行”的副本：用户在设备连接窗口里填写/应用的内容，
# 或者驱动探测到的真实信息，都放进这个内存字典里。
_runtime_settings = _default_settings()


def current_settings() -> dict:
    """[no-local-config] 本次运行中填写或自动读取到的设备信息（不落盘）。"""
    return deepcopy(_runtime_settings)


def remember_settings(settings: dict) -> None:
    """[no-local-config] 把设备窗口里确认过的内容留在本次运行的内存中。"""
    for device_id, values in (settings or {}).items():
        if device_id in _runtime_settings and isinstance(values, dict):
            _runtime_settings[device_id] = dict(values)


def _load_settings(path: Path | None = None) -> tuple[dict, str]:
    """[no-local-config] 兼容旧调用：直接返回本次运行的设备信息。

    参数 ``path`` 只是为了让旧代码可以照原样调用，已经不再读写。
    """
    return current_settings(), ""


def _validate_address(address: str) -> bool:
    """Accept an IP or hostname, never a URL, path, or embedded credential."""
    if not address:
        return True
    try:
        ipaddress.ip_address(address)
        return True
    except ValueError:
        pass
    if len(address) > 253 or any(char in address for char in " /\\:@?#"):
        return False
    # An invalid numeric IP must not be accepted as a hostname.
    if re.fullmatch(r"[0-9.]+", address):
        return False
    labels = address.rstrip(".").split(".")
    return all(
        0 < len(label) <= 63
        and re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?", label)
        for label in labels
    )


class DevicePage(QWidget):
    connection_status_changed = Signal(str, bool, str)

    def __init__(self, device_id: str, settings: dict, parent=None):
        super().__init__(parent)
        self.device_id = device_id
        self._backend = None
        self._connection_pending = False
        self._connection_result = None
        self.connection_timer = QTimer(self)
        self.connection_timer.setInterval(50)
        self.connection_timer.timeout.connect(self._finish_connect)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)   # [compact-device]
        outer.setSpacing(10)   # [compact-device]

        purpose = {
            "camera": "安装在机械臂 A 上，拍摄发动机箱体孔口。",
            "robot_a": "承载工业相机，负责拍照位置与姿态。",
            "robot_b": "承载测针，负责后续孔测量。",
        }
        note = QLabel(purpose[device_id])
        note.setObjectName("devicePurpose")
        note.setWordWrap(True)
        outer.addWidget(note)

        connection_box = QGroupBox("本软件连接状态")
        connection_layout = QVBoxLayout(connection_box)
        self.status = QLabel("● 未连接")
        self.status.setObjectName("deviceOffline")
        connection_layout.addWidget(self.status)
        self.connection_note = QLabel(
            "已接入连接功能：点「连接设备」即可连接，连不上会如实提示原因。"
            if device_id in _registered_backends else
            "尚未接入此设备的连接功能，填写配置后也不会自动连接。")
        self.connection_note.setWordWrap(True)
        connection_layout.addWidget(self.connection_note)
        outer.addWidget(connection_box)

        settings_box = QGroupBox("设备信息")
        box_layout = QVBoxLayout(settings_box)
        self.fields = QTableWidget(6, 2)
        self.fields.setHorizontalHeaderLabels(["设置项", "填写内容"])
        self.fields.verticalHeader().hide()
        self.fields.setShowGrid(True)
        self.fields.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.fields.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.fields.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.fields.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.fields.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.fields.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.manufacturer = QLineEdit(settings["manufacturer"])
        self.manufacturer.setPlaceholderText("例如：设备厂家名称")
        self.model = QLineEdit(settings["model"])
        self.model.setPlaceholderText("填写铭牌上的完整型号")
        self.transport = QComboBox()
        self.transport.addItems(["网口", "USB"] if device_id == "camera" else ["网口"])
        self.transport.setCurrentText(settings["transport"])
        self.address = QLineEdit(settings["address"])
        self.address.setPlaceholderText("例如：192.168.1.10")
        self.port = QSpinBox()
        self.port.setRange(0, 65535)
        self.port.setSpecialValueText("未填写")
        self.port.setValue(settings["port"])
        self.serial_number = QLineEdit(settings["serial_number"])
        self.serial_number.setPlaceholderText("选填，填写设备序列号")
        for edit in (self.manufacturer, self.model, self.address, self.serial_number):
            edit.setMaxLength(256)
            edit.setClearButtonEnabled(True)

        for row, (label, widget) in enumerate([
            ("厂家", self.manufacturer),
            ("型号", self.model),
            ("连接方式", self.transport),
            ("设备地址", self.address),
            ("端口", self.port),
            ("序列号", self.serial_number),
        ]):
            self.fields.setItem(row, 0, QTableWidgetItem(label))
            self.fields.setCellWidget(row, 1, widget)
            self.fields.setRowHeight(row, 36)
        self.fields.setFixedHeight(256)   # [compact-device] 6 行 x 36 + 表头
        self.fields.verticalHeader().setDefaultSectionSize(36)
        self.fields.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        box_layout.addWidget(self.fields)
        explanation = QLabel(
            "相机可以不填地址：插好相机后软件按实际连接的设备自动识别；"
            "机械臂如需连接，请填写这台电脑上实际使用的 IP。"
            "内容只在本次运行中使用，不会保存到这台电脑。")
        explanation.setWordWrap(True)
        explanation.setObjectName("deviceHint")
        box_layout.addWidget(explanation)
        outer.addWidget(settings_box)

        if device_id == 'robot_b':
            evidence_box = QGroupBox('测量机械臂后台信息与状态')
            evidence_layout = QVBoxLayout(evidence_box)
            self.robot_evidence_label = QLabel()
            self.robot_evidence_label.setWordWrap(True)
            evidence_layout.addWidget(self.robot_evidence_label)
            self.live_robot_status = QLabel('实时状态：未连接只读反馈，无法确认使能、运行、报警及速度比例。')
            self.live_robot_status.setWordWrap(True)
            evidence_layout.addWidget(self.live_robot_status)
            telemetry = QLabel('实时关节角 J1–J6：等待连接只读反馈\n'
                               '末端位置／姿态：等待反馈接口接入\n'
                               '控制器模式／报警／使能状态：尚未读取\n'
                               '测针 TCP／工具坐标与工件坐标：待标定确认')
            telemetry.setWordWrap(True)
            self.telemetry_label = telemetry
            evidence_layout.addWidget(telemetry)
            refresh_evidence = QPushButton('重新读取控制器资料')
            evidence_layout.addWidget(refresh_evidence)
            def refresh_local():
                if self._backend and self._backend.is_connected():
                    self._backend.refresh_identity()
                else:
                    self.robot_evidence_label.setText('设备型号／控制器版本：未获取。\n填写机械臂 IP 并连接后自动读取，不再使用截图资料。')
            refresh_evidence.clicked.connect(refresh_local)
            refresh_local()
            outer.addWidget(evidence_box)

        actions = QHBoxLayout()
        self.connect_button = QPushButton("连接设备")
        self.connect_button.setObjectName("deviceConnect")
        self.connect_button.clicked.connect(self._connect)
        self.disconnect_button = QPushButton("断开连接")
        self.disconnect_button.setEnabled(False)
        self.disconnect_button.clicked.connect(self._disconnect)
        actions.addWidget(self.connect_button)
        actions.addWidget(self.disconnect_button)
        actions.addStretch()
        outer.addLayout(actions)
        if device_id == 'robot_b':
            self.connect_button.setText('连接只读反馈')
            self.disconnect_button.setText('断开反馈')
            self.connection_note.setText('使用 30004 反馈端口，只读取状态；不使能、不发送运动。')
            self.port.setValue(30004)
            self.port.setReadOnly(True)
            self.port.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
            self.port.setToolTip('本窗口只连接 30004 状态反馈端口，不能配置控制端口。')
            self.feedback_timer = QTimer(self)
            self.feedback_timer.setInterval(250)
            self.feedback_timer.timeout.connect(self._refresh_feedback)
            self.feedback_timer.start()
        outer.addStretch()

        self.transport.currentTextChanged.connect(self._transport_changed)
        self._transport_changed(self.transport.currentText())

    def _transport_changed(self, transport: str) -> None:
        network = transport == "网口"
        self.address.setEnabled(network)
        self.port.setEnabled(network)

    def _refresh_feedback(self):
        backend = self._backend
        if backend is None:
            self.live_robot_status.setText('实时状态：未连接只读反馈，当前状态未知。')
            self.robot_evidence_label.setText('设备资料：未连接，当前型号和版本未获取。\n设备信息表中的内容仅为连接配置。')
            return
        if not backend.is_connected():
            reason = backend.error or '超过两秒未收到有效数据'
            backend.disconnect()
            self._backend = None
            self.telemetry_label.setText('反馈已中断，旧坐标不再有效。\n' + reason)
            self.live_robot_status.setText('实时状态：反馈已中断，使能、运行、报警和速度数据已失效。')
            self.robot_evidence_label.setText('设备资料：反馈已中断，不能确认当前连接设备。')
            self._set_status(False, '只读反馈已中断，请重新连接。')
            return
        data = backend.latest
        import datetime
        identity = backend.identity
        if identity:
            responses = identity['responses']
            self.robot_evidence_label.setToolTip('\n'.join(identity.get('errors',{}).values()))
            model = responses.get('/properties/controllerType',{}).get('name','未获取')
            cabinet = responses.get('/properties/cabinetType',{}).get('name','未获取')
            version = responses.get('/settings/version',{}).get('control','未获取')
            acquired = datetime.datetime.fromtimestamp(identity['received_at']).strftime('%Y-%m-%d %H:%M:%S')
            self.robot_evidence_label.setText(
                f'协议厂商：DOBOT　设备型号：{model}\n控制器：{cabinet}\n'
                f'控制器版本：{version}\n实际反馈连接地址：{backend.address}:30004\n'
                f'资料读取时间（电脑）：{acquired}\n来源：当前控制器只读接口；每 30 秒刷新。')
            if model != '未获取':
                self.model.setText(str(model))
                self.manufacturer.setText('DOBOT')
            if data['received_at']-identity['received_at']>30:
                backend.refresh_identity()
        else:
            self.robot_evidence_label.setText('实际反馈连接地址：'+str(backend.address)+':30004\n正在读取型号和版本…')
        updated = datetime.datetime.fromtimestamp(data['received_at']).strftime('%H:%M:%S')
        self.live_robot_status.setText(
            f"实时反馈：已连接　使能：{'已使能' if data['enabled'] else '未使能'}"
            f"　运行：{'运行中' if data['running'] else '未运行'}\n"
            f"报警：{'有报警' if data['error'] else '无报警'}"
            f"　速度比例：{data.get('speed_percent', 0)}%　模式代码：{data['mode']}\n"
            f"最近接收时间（电脑）：{updated}")
        joints = '　'.join(f'J{i+1} {v:.2f}°' for i,v in enumerate(data['joints']))
        pose = '　'.join(f'{axis} {value:.2f}' for axis,value in zip(['X','Y','Z','Rx','Ry','Rz'],data['pose']))
        self.telemetry_label.setText(
            '六轴关节角：\n' + joints + '\n末端姿态（位置 mm，角度 °）：\n' + pose +
            f"\n模式代码：{data['mode']}　使能：{'是' if data['enabled'] else '否'}"
            f"　运行：{'是' if data['running'] else '否'}　报警：{'有' if data['error'] else '无'}"
            f"\n用户坐标索引：{data['user_index']}　工具坐标索引：{data['tool_index']}"
            '\n反馈坐标尚未验证为测针针尖；孔位到机械臂坐标转换仍待标定。')

    def settings(self) -> dict:
        return {
            "manufacturer": self.manufacturer.text().strip(),
            "model": self.model.text().strip(),
            "transport": self.transport.currentText(),
            "address": self.address.text().strip(),
            "port": self.port.value(),
            "serial_number": self.serial_number.text().strip(),
        }

    def adopt_runtime_identity(self, backend) -> None:
        """[device-autofill] 把驱动探测到的真实身份填进界面。

        别人电脑上相机地址/序列号可能不同，所以不依赖保存的参数：
        探测到什么就显示什么；用户自己填过的内容不会被覆盖。
        """
        name = str(getattr(backend, 'device_name', '') or '')
        serial = str(getattr(backend, 'device_serial', '')
                     or getattr(backend, 'device_uid', ''))
        if not self.manufacturer.text() and name:
            self.manufacturer.setText(name.split(' ')[0])
        if not self.model.text() and name:
            self.model.setText(name.replace('Orbbec', '').strip() or name)
        if not self.serial_number.text() and serial:
            self.serial_number.setText(serial)

    def validate(self) -> str:
        settings = self.settings()
        if settings["transport"] == "网口" and not _validate_address(settings["address"]):
            return "设备地址请填写有效的 IP 地址或设备名称，不要填写网页链接。"
        return ""

    def _connect(self) -> None:
        if self._connection_pending:
            return
        error = self.validate()
        if error:
            QMessageBox.warning(self, "请检查设备信息", error)
            self.address.setFocus()
            return
        backend = _registered_backends.get(self.device_id)
        if backend is None:
            self._set_status(False, "尚未接入此设备的连接功能。")
            QMessageBox.information(
                self,
                "设备尚未接入",
                f"{DEVICE_TITLES[self.device_id]}目前未连接。\n\n"
                "这份软件包没有真实设备的连接功能。请先保存厂家、型号和连接信息，"
                "后续接入设备厂家提供的配套连接程序后再使用。",
            )
            return
        # Only explicitly registered real drivers can reach this path.  Their
        # contract excludes acquisition, enablement, homing, and all motion.
        try:
            if not self.settings()["model"] and self.device_id != 'robot_b':
                QMessageBox.warning(self, "请检查设备信息", "请先填写设备型号。")
                self.model.setFocus()
                return
            settings = self.settings()
            # [no-local-config] 相机由驱动自动识别，不强制填写地址；
            # 机械臂是网络设备，必须填写这台电脑实际连到的 IP。
            if not settings['address'] and self.device_id != 'camera':
                self.connection_note.setText('请先填写机械臂的 IP 地址（相机可以不填，插好会自动识别）。')
                self.address.setFocus()
                return
            self._connection_pending = True
            self.connect_button.setEnabled(False)
            self.status.setText('● 正在连接…')
            self.connection_note.setText('正在后台等待设备响应，窗口可以继续操作。')
            def connect_worker():
                try:
                    connected = bool(backend.connect(settings)) and bool(backend.is_connected())
                    self._connection_result = (backend, connected, '')
                except Exception as exc:
                    self._connection_result = (backend, False, str(exc))
            self.connection_timer.start()
            threading.Thread(target=connect_worker, daemon=True).start()
        except Exception as exc:
            self._backend = None
            self._set_status(False, "连接失败，请核对设备信息。")
            QMessageBox.warning(self, "连接失败", str(exc))

    def _finish_connect(self):
        if self._connection_result is None:
            return
        backend, connected, error = self._connection_result
        self._connection_result = None
        self._connection_pending = False
        self.connection_timer.stop()
        self._backend = backend if connected else None
        note = ('只读反馈已建立，不具备运动下发功能。' if self.device_id == 'robot_b' else '连接已建立。') if connected else ('连接失败：' + error if error else '未能连接，请核对设备信息。')
        self._set_status(connected, note)

    def _disconnect(self) -> None:
        backend = self._backend
        if backend is None:
            self._set_status(False, "设备未连接。")
            return
        try:
            backend.disconnect()
            connected = bool(backend.is_connected())
            if not connected:
                self._backend = None
            self._set_status(connected, "断开未完成，请检查设备。" if connected else "连接已断开。")
        except Exception as exc:
            QMessageBox.warning(self, "断开未完成", str(exc))

    def _set_status(self, connected: bool, note: str) -> None:
        self.status.setText("● 已连接" if connected else "● 未连接")
        self.status.setStyleSheet("color: #15803d;" if connected else "color: #b45309;")
        self.connection_note.setText(note)
        self.connect_button.setEnabled(not connected)
        self.disconnect_button.setEnabled(connected)
        self.connection_status_changed.emit(self.device_id, connected, note)


class DevicesDialog(QDialog):
    """Non-modal settings dialog.  Saved settings are not connection state.

    ``settings_saved`` emits a copied dict keyed by camera/robot_a/robot_b.
    ``connection_status_changed`` emits device id, actual connection bool,
    and a user-facing explanation; the supplied package cannot connect.
    """

    settings_saved = Signal(dict)
    connection_status_changed = Signal(str, bool, str)

    def __init__(self, parent=None, settings_path: Path = SETTINGS_PATH):
        super().__init__(parent)
        self.settings_path = Path(settings_path)
        self.setWindowTitle("设备连接 · 工业相机与双机械臂")
        # [local patch] screen-aware size so the bottom buttons are never cut off
        _screen = self.screen()
        _height = min(880, _screen.availableGeometry().height() - 30) if _screen else 820
        self.resize(760, _height)
        self.setMinimumSize(560, 620)
        self.setModal(False)
        self.setObjectName("inspectionDevices")
        self.setStyleSheet("""
            QDialog#inspectionDevices { background: #f5f7fb; }
            QDialog#inspectionDevices QWidget { font-family: 'Microsoft YaHei UI'; font-size: 14px; }
            QDialog#inspectionDevices QGroupBox {
                background: white; border: 1px solid #d5deea; border-radius: 8px;
                margin-top: 18px; padding: 14px 12px 10px; font-weight: 600;
            }
            QDialog#inspectionDevices QGroupBox::title {
                subcontrol-origin: margin; subcontrol-position: top left;
                left: 14px; padding: 0 6px; color: #1e3a5f;
            }
            QDialog#inspectionDevices QTabWidget::pane { border: 1px solid #d5deea; border-radius: 6px; }
            QDialog#inspectionDevices QTabBar::tab {
                min-width: 148px; padding: 11px 12px; background: #e8eef7; color: #37516f;
            }
            QDialog#inspectionDevices QTabBar::tab:selected { background: #2563eb; color: white; }
            QDialog#inspectionDevices QTableWidget {
                background: white; color: #234369; gridline-color: #e2e8f0; border: 1px solid #dbe4ee;
            }
            QDialog#inspectionDevices QHeaderView::section {
                background: #eef3fa; color: #37516f; padding: 7px; border: 1px solid #d5deea;
            }
            QDialog#inspectionDevices QLineEdit,
            QDialog#inspectionDevices QSpinBox,
            QDialog#inspectionDevices QComboBox { padding: 6px 8px; border: 0; background: white; }
            QDialog#inspectionDevices QPushButton {
                padding: 9px 18px; border: 1px solid #bfccde; border-radius: 6px;
                background: white; color: #234369;
            }
            QDialog#inspectionDevices QPushButton:hover { background: #edf3fe; }
            QDialog#inspectionDevices QPushButton:disabled { color: #94a3b8; background: #f1f5f9; }
            QDialog#inspectionDevices QPushButton#deviceConnect,
            QDialog#inspectionDevices QPushButton#saveDeviceSettings {
                background: #2563eb; color: white; border-color: #2563eb;
            }
            QDialog#inspectionDevices QLabel#deviceOffline { color: #b45309; font-size: 18px; font-weight: 600; }
            QDialog#inspectionDevices QLabel#devicePurpose { color: #345271; }
            QDialog#inspectionDevices QLabel#deviceHint { color: #64748b; font-size: 13px; font-weight: 400; }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)   # [compact-device]
        heading = QLabel("设备连接")
        heading.setStyleSheet("font-size: 20px; font-weight: 700; color: #183b65;")
        layout.addWidget(heading)
        subtitle = QLabel("相机采集 → 识别孔口 → 机械臂测量")
        subtitle.setObjectName("deviceHint")
        layout.addWidget(subtitle)

        settings, warning = _load_settings(self.settings_path)
        self.tabs = QTabWidget()
        self.pages: dict[str, DevicePage] = {}
        for device_id, title in DEVICE_TITLES.items():
            page = DevicePage(device_id, settings[device_id], self)
            page.connection_status_changed.connect(self.connection_status_changed.emit)
            self.pages[device_id] = page
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            page.setMinimumWidth(560)
            scroll.setWidget(page)
            self.tabs.addTab(scroll, title)
        layout.addWidget(self.tabs, 1)
        self.save_note = QLabel(warning or "设备信息只在本次运行中使用，不会保存到这台电脑；"
                                          "换电脑后按实际设备重新填写或由软件自动读取。")
        self.save_note.setWordWrap(True)
        self.save_note.setObjectName("deviceHint")
        if warning:
            self.save_note.setStyleSheet("color: #b45309;")
        layout.addWidget(self.save_note)

        footer = QHBoxLayout()
        save = QPushButton("应用到本次运行")
        save.setObjectName("saveDeviceSettings")
        save.clicked.connect(self.save_settings)
        close = QPushButton("关闭")
        close.clicked.connect(self.close)
        footer.addStretch()
        footer.addWidget(save)
        footer.addWidget(close)
        layout.addLayout(footer)

    def settings(self) -> dict:
        return {device_id: page.settings() for device_id, page in self.pages.items()}

    def save_settings(self) -> bool:
        for index, (device_id, page) in enumerate(self.pages.items()):
            error = page.validate()
            if error:
                self.tabs.setCurrentIndex(index)
                QMessageBox.warning(self, "请检查设备信息", f"{DEVICE_TITLES[device_id]}：{error}")
                page.address.setFocus()
                return False
        settings = self.settings()
        # [no-local-config] 只记在内存里：换电脑后不会带着上一台机器的参数。
        remember_settings(settings)
        self.save_note.setText("设备信息已用于本次运行，不会保存到这台电脑；连接状态保持当前状态。")
        self.save_note.setStyleSheet("color: #15803d;")
        self.settings_saved.emit(deepcopy(settings))
        return True


def show_devices(parent=None) -> DevicesDialog:
    """Show the single reusable dialog, keeping saved input between visits."""
    global _dialog_ref
    dialog = _dialog_ref() if _dialog_ref is not None else None
    if dialog is not None:
        try:
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()
            return dialog
        except RuntimeError:
            # The previous main window may have destroyed its children.
            dialog = None
    dialog = DevicesDialog(parent)
    _dialog_ref = weakref.ref(dialog)
    # Keep a strong reference even when callers do not save the return value.
    if parent is not None:
        parent._inspection_devices_dialog = dialog
    else:
        show_devices._dialog = dialog
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()
    return dialog
