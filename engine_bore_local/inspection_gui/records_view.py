"""Qt view of the existing experiment log; viewing never changes the JSON."""
from __future__ import annotations

import json
from datetime import datetime
import uuid
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QFileDialog, QHBoxLayout, QHeaderView,
    QLabel, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QTabWidget,
    QVBoxLayout, QWidget,
)

from experiment_records import COLUMNS, RECORD_FILE, ExperimentRecords
from .capture_archive import capture_information


class RecordsDialog(QDialog):
    """Read and export all existing groups, with the first 15 fields visible.

    An optional shared ``records`` instance supplies its file path.  Refresh
    reads a separate snapshot, because ExperimentRecords.__init__ would mark
    an actively running group as interrupted and write that change to disk.
    """

    def __init__(self, parent: QWidget | None = None,
                 records: ExperimentRecords | None = None,
                 path: str | Path = RECORD_FILE, capture_root: str | Path | None = None):
        super().__init__(parent)
        self.setWindowTitle("实验记录")
        self.resize(1260, 720)
        self.setMinimumSize(760, 450)
        self.path = Path(records.path if records is not None else path)
        self.shared_records = records
        self.capture_root = Path(capture_root) if capture_root is not None else self.path.parent / 'data' / 'camera_captures'
        self.capture_rows = []
        self.records = ExperimentRecords.__new__(ExperimentRecords)
        self.records.path = self.path
        self.records.groups = []
        self.rows: list[dict] = []
        self.visible_columns = COLUMNS[:15]

        layout = QVBoxLayout(self)
        tools = QHBoxLayout()
        self.summary = QLabel("正在读取实验记录…")
        tools.addWidget(self.summary, 1)
        refresh_button = QPushButton("刷新记录")
        refresh_button.clicked.connect(self.refresh)
        tools.addWidget(refresh_button)
        export_button = QPushButton("导出全部记录（Excel / WPS）")
        export_button.clicked.connect(self.export_csv)
        tools.addWidget(export_button)
        folder_button = QPushButton('打开结果文件夹')
        folder_button.clicked.connect(self.open_results_folder)
        tools.addWidget(folder_button)
        layout.addLayout(tools)

        explanation = QLabel(
            "每批照片为一组，新实验追加保存。空白表示没有保留该孔。"
            "孔号按图像位置排序；全部拍摄照片包含尚未检测的留样。双击一行打开原图。"
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        self.table = QTableWidget(0, len(self.visible_columns))
        self.table.setHorizontalHeaderLabels([label for _, label in self.visible_columns])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(True)
        self.table.setGridStyle(Qt.PenStyle.SolidLine)
        self.table.setStyleSheet(
            "QTableWidget { gridline-color: #b8c2cf; alternate-background-color: #f3f6fa; }"
            "QHeaderView::section { padding: 6px; background: #e9eef5; "
            "border: 1px solid #b8c2cf; font-weight: 600; }"
        )
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(34)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(False)
        for index, (key, _) in enumerate(self.visible_columns):
            self.table.setColumnWidth(index, {
                "group": 95, "time": 175, "photo": 245, "count": 95,
                "fit_count": 95, "constraint": 105, "status": 155,
                "warnings": 520,
            }.get(key, 130))
        self.table.cellDoubleClicked.connect(self.open_original)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.table, '实验检测记录')
        self.capture_table = QTableWidget(0, 6)
        self.capture_table.setHorizontalHeaderLabels(['拍摄时间', '照片', '相机', '图像尺寸', '关联实验组', '状态'])
        self.capture_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.capture_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.capture_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.capture_table.setAlternatingRowColors(True)
        self.capture_table.setShowGrid(True)
        self.capture_table.setStyleSheet(self.table.styleSheet())
        self.capture_table.verticalHeader().setVisible(False)
        for column, width in enumerate([215, 360, 160, 120, 175, 180]):
            self.capture_table.setColumnWidth(column, width)
        self.capture_table.cellDoubleClicked.connect(self.open_original)
        self.tabs.addTab(self.capture_table, '全部拍摄照片')
        layout.addWidget(self.tabs, 1)
        photo_actions = QHBoxLayout()
        for label, callback in [('查看原图', self.open_original), ('查看检测结果', self.open_selected_result), ('打开照片所在文件夹', self.open_photo_folder)]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            photo_actions.addWidget(button)
        layout.addLayout(photo_actions)
        self.delete_button = QPushButton('删除选中实验组')
        self.delete_button.clicked.connect(self.delete_selected_group)
        layout.addWidget(self.delete_button)
        self.tabs.currentChanged.connect(lambda index: self.delete_button.setEnabled(index == 0))
        layout.addWidget(QLabel("导出的 CSV 保留全部字段，包括照片、结果图片及模型路径。"))
        self.refresh()

    @Slot()
    def open_results_folder(self):
        folder = Path(__file__).resolve().parents[1] / 'results'
        folder.mkdir(exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def refresh(self) -> bool:
        try:
            groups = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else []
            if not isinstance(groups, list):
                raise ValueError("记录文件的内容不是实验组列表")
            snapshot = ExperimentRecords.__new__(ExperimentRecords)
            snapshot.path, snapshot.groups = self.path, groups
            rows = snapshot.rows()
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.summary.setText("记录读取失败；已保留当前显示内容。")
            QMessageBox.warning(self, "实验记录读取失败", f"原记录文件未改动。\n{self.path}\n\n{error}")
            return False

        vertical_position = self.table.verticalScrollBar().value()
        horizontal_position = self.table.horizontalScrollBar().value()
        self.records, self.rows = snapshot, rows
        self.table.setUpdatesEnabled(False)
        try:
            self.table.setRowCount(len(rows))
            for row_index, row in enumerate(rows):
                for column_index, (key, _) in enumerate(self.visible_columns):
                    value = str(row.get(key, ""))
                    item = QTableWidgetItem(value)
                    item.setToolTip(value)
                    if key in {"count", "fit_count", "hole1", "hole2", "hole3", "hole4", "mean", "minimum", "part"}:
                        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    self.table.setItem(row_index, column_index, item)
        finally:
            self.table.setUpdatesEnabled(True)
        self.table.verticalScrollBar().setValue(vertical_position)
        self.table.horizontalScrollBar().setValue(horizontal_position)
        self.summary.setText(f"累计 {len(groups)} 组，{len(rows)} 张图片")
        self.refresh_captures()
        return True

    def refresh_captures(self):
        selected = self.selected_row().get('image')
        by_photo = {}
        for row in self.rows:
            by_photo.setdefault(str(Path(row['image']).resolve()).casefold(), []).append(row)
        captures = []
        for photo in sorted(self.capture_root.glob('*/*.png'), reverse=True):
            info = capture_information(photo) or {}
            related = by_photo.get(str(photo.resolve()).casefold(), [])
            captures.append({'image': str(photo), 'result_image': next((r['result_image'] for r in reversed(related) if r.get('result_image')), ''),
                'time': info.get('frame_received_at_local') or info.get('saved_at') or '',
                'photo': photo.name, 'camera': (info.get('camera') or {}).get('model') or '未获取',
                'size': f"{info['width_px']} × {info['height_px']}" if info.get('width_px') and info.get('height_px') else '未获取',
                'groups': '、'.join(dict.fromkeys(r['group'] for r in related)) or '—',
                'status': '拍摄信息缺失，请复核' if not info else ('已有检测记录' if related else '已留样，未检测')})
        self.capture_rows = captures
        self.capture_table.setRowCount(len(captures))
        for index, row in enumerate(captures):
            for column, key in enumerate(['time', 'photo', 'camera', 'size', 'groups', 'status']):
                item = QTableWidgetItem(row[key]); item.setToolTip(row[key] if key != 'photo' else row['image'])
                self.capture_table.setItem(index, column, item)
            if row['image'] == selected:
                self.capture_table.selectRow(index)
        self.tabs.setTabText(1, f'全部拍摄照片（{len(captures)}）')

    def selected_row(self):
        if self.tabs.currentIndex() == 1:
            index, rows = self.capture_table.currentRow(), self.capture_rows
        else:
            index, rows = self.table.currentRow(), self.rows
        return rows[index] if 0 <= index < len(rows) else {}

    def delete_selected_group(self, *_):
        if self.tabs.currentIndex() != 0:
            return
        selected = self.selected_row()
        if not selected:
            QMessageBox.information(self, '删除实验组', '请先在实验检测记录中选择一行。')
            return
        if getattr(self.parent(), 'batch_running', False):
            QMessageBox.information(self, '删除实验组', '当前正在检测，请等本组完成后再删除。')
            return
        group_label = selected['group']
        answer = QMessageBox.question(self, '删除实验组',
            f'删除{group_label}的全部实验记录吗？\n拍摄原图、检测结果文件继续保留。删除前会备份记录。',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            original = self.path.read_bytes()
            groups = json.loads(original.decode('utf-8'))
            matching = [g for g in groups if f"第{g['number']}组" == group_label]
            if len(matching) != 1 or matching[0].get('status') == '检测中':
                raise ValueError('该实验组已变化或仍在检测，请刷新后重试。')
            remaining = [g for g in groups if g['id'] != matching[0]['id']]
            backup_folder = self.path.parent / 'data' / 'record_backups'
            backup_folder.mkdir(parents=True, exist_ok=True)
            backup = backup_folder / (datetime.now().strftime('records_%Y%m%d_%H%M%S_') + uuid.uuid4().hex[:8] + '.json')
            with backup.open('xb') as stream:
                stream.write(original)
            if self.path.read_bytes() != original:
                raise ValueError('记录刚刚发生变化，已取消删除，请刷新后重试。')
            snapshot = ExperimentRecords.__new__(ExperimentRecords)
            snapshot.path, snapshot.groups = self.path, remaining
            snapshot.save()
            if self.shared_records is not None:
                self.shared_records.groups = remaining
        except (OSError, ValueError, KeyError, TypeError) as error:
            QMessageBox.warning(self, '删除未完成', str(error))
            return
        self.refresh()
        QMessageBox.information(self, '已删除实验组', f'{group_label}已删除，照片文件保留。\n记录备份：{backup}')

    def open_original(self, *_):
        self.open_photo_path(self.selected_row().get('image', ''), '拍摄原图')

    def open_selected_result(self, *_):
        self.open_photo_path(self.selected_row().get('result_image', ''), '检测结果')

    def open_photo_path(self, path_text, title):
        if not path_text or not Path(path_text).is_file():
            QMessageBox.information(self, title, '请先选择记录；尚未检测的照片没有检测结果。若文件已移动，记录仍保留。')
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path_text).resolve())))

    def open_photo_folder(self, *_):
        photo = self.selected_row().get('image')
        if photo and Path(photo).parent.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(photo).resolve().parent)))
        else:
            QMessageBox.information(self, '照片所在文件夹', '请先选择一条照片记录。')

    @Slot()
    def export_csv(self) -> None:
        # Refresh immediately before export so another completed batch is included.
        if not self.refresh():
            return
        destination, _ = QFileDialog.getSaveFileName(
            self, "导出全部实验记录", str(self.path.parent / "箱体孔实验记录.csv"),
            "CSV 表格 (*.csv)",
        )
        if not destination:
            return
        if not Path(destination).suffix:
            destination += ".csv"
        try:
            self.records.export(destination)
        except (OSError, ValueError, KeyError, TypeError) as error:
            QMessageBox.warning(self, "记录导出失败", str(error))
            return
        QMessageBox.information(self, "记录已导出", f"全部实验组和字段已导出：\n{destination}")

    @Slot(int, int)
    def open_result(self, row_index: int, _column: int = 0) -> None:
        if not 0 <= row_index < len(self.rows):
            return
        path_text = self.rows[row_index].get("result_image", "")
        if not path_text or not Path(path_text).is_file():
            QMessageBox.information(self, "图片无法打开", "该记录的检测结果图片不存在；实验记录仍保留。")
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path_text).resolve()))):
            QMessageBox.warning(self, "图片无法打开", f"未能打开检测结果图片：\n{path_text}")


ExperimentRecordsDialog = RecordsDialog
