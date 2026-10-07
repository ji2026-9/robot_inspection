"""Qt view of the existing experiment log; viewing never changes the JSON."""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QFileDialog, QHBoxLayout, QHeaderView,
    QLabel, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from experiment_records import COLUMNS, RECORD_FILE, ExperimentRecords


class RecordsDialog(QDialog):
    """Read and export all existing groups, with the first 15 fields visible.

    An optional shared ``records`` instance supplies its file path.  Refresh
    reads a separate snapshot, because ExperimentRecords.__init__ would mark
    an actively running group as interrupted and write that change to disk.
    """

    def __init__(self, parent: QWidget | None = None,
                 records: ExperimentRecords | None = None,
                 path: str | Path = RECORD_FILE):
        super().__init__(parent)
        self.setWindowTitle("实验记录")
        self.resize(1260, 720)
        self.setMinimumSize(760, 450)
        self.path = Path(records.path if records is not None else path)
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
            "孔号按图像位置排序；双击一行打开检测结果图片。"
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
        self.table.cellDoubleClicked.connect(self.open_result)
        layout.addWidget(self.table, 1)
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
        return True

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
