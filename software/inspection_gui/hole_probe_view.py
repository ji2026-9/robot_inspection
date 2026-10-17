"""自动测孔页面：手动示教孔位、预览参数、按孔执行、保存接触点。

本页只调度 ManualControl 的预览/执行/停止。运动必须先由操作者在实机控制页
启用本轮控制；任何异常都会停止并锁定，不自动跳到下一个孔。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QFileDialog, QGridLayout, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton,
                               QScrollArea, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .contact_points import ContactStore, export_csv, new_session
from .hole_probe import ProbeRunner, default_safe_z, validate_params
from .manual_origin import load_origin
from .probe_workspace import atomic_json, capture_position
from .stepper import DoubleParameter, IntegerParameter
from .ui_feedback import FeedbackLabel

HOLES_NAME = 'hole_probe_holes.json'


class HoleProbePage(QWidget):
    def __init__(self, workspace, parent=None):
        super().__init__(parent)
        from .page_style import PAGE_STYLE
        self.setStyleSheet(PAGE_STYLE)
        self.workspace = workspace
        self.store = ContactStore(workspace.storage_path.parent)
        self.holes_path = workspace.storage_path.parent / HOLES_NAME
        self.holes = []
        self.runner = None
        self.session = None
        self.saved_points = 0
        self.results = []
        self.park = None

        root = QVBoxLayout(self)
        title = QLabel('自动测孔 · 手动示教孔位 → 逐孔接触 → 回中心 → 安全高度换孔')
        title.setStyleSheet('font-size:16px;font-weight:600;color:#214567;')
        root.addWidget(title)
        self.status = FeedbackLabel('先到实机控制页连接并启用本轮控制；本页不自动测，需你点击开始。')
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        hint = QLabel('记录孔位时：把测针移到孔内约 4–5 mm 深、尽量对准孔中心，再点“记录当前孔位”。安全高度必须高于零件所有凸起。')
        hint.setWordWrap(True); hint.setObjectName('muted')
        root.addWidget(hint)

        split = QSplitter()
        root.addWidget(split, 1)
        left_scroll = QScrollArea(); left_scroll.setWidgetResizable(True)
        left_widget = QWidget(); left = QVBoxLayout(left_widget)
        left_scroll.setWidget(left_widget); left_scroll.setMinimumWidth(340); left_scroll.setMaximumWidth(430)
        split.addWidget(left_scroll)

        grid = QGridLayout()
        self.safe_z = DoubleParameter(); self.safe_z.setRange(-2500, 2500); self.safe_z.setDecimals(3); self.safe_z.setSuffix(' mm')
        self.search = DoubleParameter(); self.search.setRange(0.2, 6); self.search.setDecimals(2); self.search.setValue(4.0); self.search.setSuffix(' mm')
        self.probe_speed = IntegerParameter(); self.probe_speed.setRange(1, 5); self.probe_speed.setValue(2); self.probe_speed.setSuffix(' mm/s')
        self.travel_speed = IntegerParameter(); self.travel_speed.setRange(1, 100); self.travel_speed.setValue(20); self.travel_speed.setSuffix(' mm/s')
        self.retract_speed = IntegerParameter(); self.retract_speed.setRange(1, 20); self.retract_speed.setValue(5); self.retract_speed.setSuffix(' mm/s')
        self.release = DoubleParameter(); self.release.setRange(0.5, 3); self.release.setDecimals(2); self.release.setValue(1.5); self.release.setSuffix(' mm')
        rows = (('安全高度 Z', self.safe_z), ('搜索上限', self.search), ('探测速度', self.probe_speed),
                ('空移速度', self.travel_speed), ('退离速度', self.retract_speed), ('释放退让', self.release))
        for index, (label, widget) in enumerate(rows):
            grid.addWidget(QLabel(label), index, 0); grid.addWidget(widget, index, 1)
        left.addLayout(grid)
        self.payload_label = QLabel('工具总质量：未设置（将使用 1.000 kg，需现场核对）')
        self.payload_label.setWordWrap(True); self.payload_label.setObjectName('muted')
        left.addWidget(self.payload_label)

        self.record_name = QLineEdit(); self.record_name.setPlaceholderText('孔位名称，例如 A1')
        self.record_diameter = DoubleParameter(); self.record_diameter.setRange(3, 200); self.record_diameter.setDecimals(2)
        self.record_diameter.setValue(10); self.record_diameter.setSuffix(' mm')
        row = QHBoxLayout(); row.addWidget(self.record_name, 1); row.addWidget(self.record_diameter)
        left.addLayout(row)
        buttons = QHBoxLayout()
        self.record_button = QPushButton('记录当前孔位'); self.record_button.clicked.connect(self.record_hole)
        buttons.addWidget(self.record_button)
        for text, callback in (('删除', self.remove_hole), ('清空', self.clear_holes)):
            button = QPushButton(text); button.clicked.connect(callback); buttons.addWidget(button)
        left.addLayout(buttons)

        self.hole_table = QTableWidget(0, 5)
        self.hole_table.setHorizontalHeaderLabels(['孔位', 'X / mm', 'Y / mm', 'Z / mm', '孔径'])
        self.hole_table.verticalHeader().setVisible(False)
        self.hole_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.hole_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.hole_table.setMinimumHeight(130)
        left.addWidget(self.hole_table)

        self.park_box = QCheckBox('全部测完回到保存的“返回位置”')
        self.park_box.setChecked(True); left.addWidget(self.park_box)
        self.confirm_box = QCheckBox('逐孔确认（推荐首次；取消则连续测完全部）')
        self.confirm_box.setChecked(True); left.addWidget(self.confirm_box)
        self.start_button = QPushButton('开始自动测孔'); self.start_button.setObjectName('primary')
        self.start_button.setMinimumHeight(42); self.start_button.clicked.connect(self.start_run)
        self.continue_button = QPushButton('继续下一个孔'); self.continue_button.setEnabled(False)
        self.continue_button.clicked.connect(self.continue_run)
        self.stop_button = QPushButton('停止测孔（不自动恢复）'); self.stop_button.clicked.connect(self.stop_run)
        left.addWidget(self.start_button); left.addWidget(self.continue_button); left.addWidget(self.stop_button)
        self.export_button = QPushButton('导出接触点 CSV'); self.export_button.clicked.connect(self.export_points)
        left.addWidget(self.export_button)
        left.addStretch()

        right = QWidget(); right_layout = QVBoxLayout(right)
        self.progress = QLabel('尚未开始'); self.progress.setWordWrap(True)
        self.progress.setStyleSheet('padding:8px;background:#eef4fb;color:#365b84;')
        right_layout.addWidget(self.progress)
        self.result_table = QTableWidget(0, 5)
        self.result_table.setHorizontalHeaderLabels(['孔位', '中心 X', '中心 Y', 'X 偏差', 'Y 偏差'])
        self.result_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.result_table.verticalHeader().setVisible(False)
        right_layout.addWidget(self.result_table, 1)
        self.log = QPlainTextEdit(); self.log.setReadOnly(True); self.log.setMaximumBlockCount(400)
        right_layout.addWidget(self.log, 1)
        self.warning = QLabel('接触点来自接收帧，非控制器锁存；停止距离、测球半径与 TCP 未标定，中心值仅供定位参考，不能当作已认证测量精度。')
        self.warning.setWordWrap(True); self.warning.setStyleSheet('padding:8px;background:#fff4dc;color:#795014;')
        right_layout.addWidget(self.warning)
        split.addWidget(right)
        split.setStretchFactor(1, 1)

        self.timer = QTimer(self); self.timer.setInterval(50); self.timer.timeout.connect(self.tick)
        self.load_holes(); self.load_payload(); self.refresh_holes()
        self.set_status('先到实机控制页连接并启用本轮控制；参数与孔位可先在此设置。')

    # ---- 基础 ---------------------------------------------------------
    def set_status(self, text, error=False):
        self.status.show_message(text, 'error' if error else 'info')
        self.progress.setText(text)

    def note(self, text):
        self.log.appendPlainText(time.strftime('%H:%M:%S ')+text)

    def load_payload(self):
        try:
            from .tool_payload import load_payload as load_tool_payload
            saved = load_tool_payload(self.workspace.storage_path.parent / 'tool_payload.json')
        except (OSError, ValueError, TypeError):
            saved = None
        self.payload_kg = saved['mass_kg'] if saved else 1.0
        self.payload_label.setText(f"工具总质量：{self.payload_kg:.3f} kg" + ('' if saved else '（未保存，先用 1.000 kg，请现场核对）'))

    def load_holes(self):
        path = Path(self.holes_path)
        if not path.is_file():
            return
        try:
            data = json.loads(path.read_text(encoding='utf-8-sig'))
            values = data.get('holes') if isinstance(data, dict) else None
            if not isinstance(values, list):
                raise ValueError('孔位列表无效')
            from .hole_probe import validate_hole
            self.holes = [validate_hole(v) for v in values]
        except (OSError, ValueError, TypeError, KeyError) as exc:
            self.note('孔位文件读取失败：'+str(exc))
        if self.holes and self.safe_z.value() <= max(h['xyz'][2] for h in self.holes):
            self.safe_z.setValue(default_safe_z(self.holes))

    def save_holes(self):
        atomic_json(self.holes_path, {'schema_version': 1, 'kind': 'hole_probe_holes', 'holes': self.holes})
        self.refresh_holes()

    def refresh_holes(self):
        self.hole_table.setRowCount(len(self.holes))
        for row, hole in enumerate(self.holes):
            values = (hole['name'], f"{hole['xyz'][0]:.3f}", f"{hole['xyz'][1]:.3f}",
                      f"{hole['xyz'][2]:.3f}", f"{hole['diameter_mm']:.2f}")
            for column, text in enumerate(values):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.hole_table.setItem(row, column, item)
        self.start_button.setEnabled(bool(self.holes) and self.runner is None)

    def record_hole(self):
        try:
            frame = self.workspace.backend().snapshot()
            point = capture_position('孔位示教_'+time.strftime('%H%M%S'), frame)
            name = self.record_name.text().strip() or f"孔{len(self.holes)+1}"
            hole = {'id': point['id'], 'name': name[:64], 'pose': point['tcp_pose'],
                    'xyz': point['tcp_pose'][:3], 'diameter_mm': self.record_diameter.value(),
                    'note': '', 'recorded_at': point['recorded_at']}
            from .hole_probe import validate_hole
            self.holes.append(validate_hole(hole))
            if self.safe_z.value() <= max(h['xyz'][2] for h in self.holes):
                self.safe_z.setValue(default_safe_z(self.holes))
            self.save_holes(); self.record_name.clear()
            self.note(f'已记录 {name}：X {hole["xyz"][0]:.3f}  Y {hole["xyz"][1]:.3f}  Z {hole["xyz"][2]:.3f}')
        except (ValueError, OSError, TypeError, KeyError) as exc:
            self.set_status('记录孔位失败：'+str(exc), True)

    def remove_hole(self):
        rows = sorted({index.row() for index in self.hole_table.selectedIndexes()}, reverse=True)
        for row in rows:
            if 0 <= row < len(self.holes):
                self.holes.pop(row)
        self.save_holes()

    def clear_holes(self):
        if self.holes and QMessageBox.question(self, '清空孔位', '确定清空全部孔位？点位库不会被清除。') != QMessageBox.StandardButton.Yes:
            return
        self.holes = []; self.save_holes()

    def params(self):
        return {
            'safe_z_mm': self.safe_z.value(), 'search_limit_mm': self.search.value(),
            'probe_speed_mm_s': self.probe_speed.value(), 'travel_speed_mm_s': self.travel_speed.value(),
            'retract_speed_mm_s': self.retract_speed.value(), 'release_mm': self.release.value(),
            'release_speed_mm_s': 2, 'payload_kg': self.payload_kg, 'holes': self.holes,
        }

    # ---- 运行 ---------------------------------------------------------
    def start_run(self):
        if self.runner is not None:
            return
        try:
            params = validate_params(self.params(), self.holes)
            backend = self.workspace.backend()
            controller = getattr(backend, 'manual_control', None)
            if controller is None:
                raise ValueError('请先到实机控制页连接控制')
            state = controller.snapshot()
            frame = backend.snapshot()
            if not isinstance(frame, dict):
                raise ValueError('反馈不可用，请先连接只读反馈')
            if not state.get('unlocked'):
                raise ValueError('请先在实机控制页勾选确认并启用本轮控制')
            park = None
            if self.park_box.isChecked():
                origin = load_origin(self.workspace.storage_path.parent / 'manual_origin.json')
                if origin:
                    park = [float(v) for v in origin['xyz']] + [float(v) for v in frame['pose'][3:6]]
                else:
                    self.note('没有保存的“返回位置”，本次不会自动撤离到该点。')
            summary = (f"共 {len(params['holes'])} 个孔\n安全高度 Z {params['safe_z_mm']:.2f} mm\n"
                       f"搜索上限 {params['search_limit_mm']:.2f} mm\n探测 {params['probe_speed_mm_s']} mm/s · "
                       f"空移 {params['travel_speed_mm_s']} mm/s\n工具总质量 {params['payload_kg']:.3f} kg\n\n"
                       '请确认现场无人、实体急停在手。开始后接触即停止；异常会锁定，不会自动继续。')
            if QMessageBox.question(self, '开始自动测孔', summary) != QMessageBox.StandardButton.Yes:
                return
            self.results = []
            self.result_table.setRowCount(0)
            self.saved_points = 0
            self.park = park
            self.runner = ProbeRunner(controller, params, park=park,
                                      confirm_each_hole=self.confirm_box.isChecked())
            self.session = new_session(params={k: v for k, v in params.items() if k != 'holes'})
            self.runner.start(state, frame)
            self.timer.start()
            self.start_button.setEnabled(False); self.stop_button.setEnabled(True)
            self.set_status('已开始；接触后会停止、记录并小步退让，请盯住现场。')
            self.note('开始自动测孔')
        except (ValueError, OSError, TypeError, KeyError) as exc:
            self.set_status('无法开始：'+str(exc), True)

    def continue_run(self):
        if self.runner and self.runner.continue_next():
            self.continue_button.setEnabled(False)
            self.note('继续下一个孔')

    def stop_run(self):
        if self.runner is None:
            return
        try:
            self.runner.abort('操作者停止自动测孔')
            controller = getattr(self.workspace.backend(), 'manual_control', None)
            if controller:
                controller.request_stop('操作者停止自动测孔')
        except (ValueError, OSError):
            pass
        try:
            self.persist_points()
        except (ValueError, OSError, TypeError):
            pass
        self.note('已请求停止')
        self.finish_run()

    def tick(self):
        if self.runner is None:
            return
        try:
            backend = self.workspace.backend()
            controller = self.runner.controller
            frame = backend.snapshot()
            state = controller.snapshot()
            self.runner.step(time.monotonic(), state, frame)
            self.persist_points()
            status = self.runner.status()
            self.progress.setText(f"孔 {min(status['hole_index']+1, status['hole_count'])}/{status['hole_count']} · "
                                  f"{status['message']}")
            self.continue_button.setEnabled(status['stage'] == 'await_continue')
            self.update_results()
            if status['stage'] in ('done', 'failed'):
                self.finish_run()
        except (ValueError, OSError, TypeError, KeyError) as exc:
            self.note('测孔异常：'+str(exc))
            self.runner.abort('测孔异常：'+str(exc)); self.finish_run()

    def update_results(self):
        results = self.runner.status()['results'] if self.runner else self.results
        self.result_table.setRowCount(len(results))
        for row, result in enumerate(results):
            values = (result['hole_name'], f"{result['center'][0]:.3f}", f"{result['center'][1]:.3f}",
                      f"{result['offset_x_mm']:+.3f}", f"{result['offset_y_mm']:+.3f}")
            for column, text in enumerate(values):
                self.result_table.setItem(row, column, QTableWidgetItem(text))

    def persist_points(self):
        points = self.runner.session_points[self.saved_points:]
        for point in points:
            try:
                self.store.append(point)
                if self.session is not None:
                    self.session['points'].append(point)
            except (ValueError, OSError, TypeError) as exc:
                self.note('接触点保存失败：'+str(exc))
                self.runner.abort('接触点保存失败：'+str(exc))
                break
        self.saved_points = len(self.runner.session_points)

    def finish_run(self):
        if self.runner is not None:
            status = self.runner.status()
            if status['stage'] == 'failed':
                self.set_status('已停止：'+status['failure'], True)
                self.note('失败：'+status['failure'])
            else:
                self.set_status('本次测孔结束：'+status['message'])
                self.note('结束：'+status['message'])
        if self.session is not None:
            try:
                path = self.store.save_session(self.session)
                self.note('会话已保存：'+str(path))
            except (ValueError, OSError, TypeError) as exc:
                self.note('会话保存失败：'+str(exc))
        self.timer.stop(); self.runner = None; self.session = None
        self.saved_points = 0
        self.continue_button.setEnabled(False); self.stop_button.setEnabled(True)
        self.refresh_holes()

    def export_points(self):
        try:
            path, _ = QFileDialog.getSaveFileName(self, '导出接触点', 'contact_points.csv', 'CSV (*.csv)')
            if not path:
                return
            export_csv(path, self.store.points)
            self.note('已导出：'+path)
        except (ValueError, OSError, TypeError) as exc:
            self.set_status('导出失败：'+str(exc), True)

    def showEvent(self, event):
        super().showEvent(event)
        self.load_payload()

    def closeEvent(self, event):
        if self.runner is not None:
            self.stop_run()
        super().closeEvent(event)
