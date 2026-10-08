"""Qt view of the existing experiment log.

[records-tools] 这里是「实验记录」的唯一入口：查看 / 刷新 / 导出 / 载入到
工作区 / 打开原图·结果图·检测报告 / 删除这一组。原来的「打开历史批次」已经
并进来，不再单独开一个窗口。

打开窗口本身不改记录；只有「删除这一组」会写文件，并且和主界面共用同一个
ExperimentRecords 对象，避免两边数据不一致。
"""
from __future__ import annotations

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

    ``records`` is the main window's live ExperimentRecords instance; the
    dialog refreshes from disk into that same object so a delete here is
    never overwritten later by a stale in-memory copy.
    """

    def __init__(self, parent: QWidget | None = None,
                 records: ExperimentRecords | None = None,
                 path: str | Path = RECORD_FILE):
        super().__init__(parent)
        self.setWindowTitle("实验记录")
        _screen = self.screen()
        self.resize(min(1400, _screen.availableGeometry().width() - 60),
                    min(780, _screen.availableGeometry().height() - 60))
        self.setMinimumSize(760, 450)
        # [records-tools] 有主界面传进来的 records 就直接共用同一个对象，
        # 这样在这里删除/刷新之后主界面内存里的记录不会滞后。
        if records is not None:
            self.records = records
        else:
            self.records = ExperimentRecords.__new__(ExperimentRecords)
            self.records.path = Path(path)
            self.records.groups = []
        self.path = Path(self.records.path)
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
        # [records-tools] 载入 / 看图 / 报告 / 删除（合并了原来的「打开历史批次」）
        load_button = QPushButton('载入到工作区')
        load_button.setToolTip('把选中的这一组照片和检测结果载入主界面（不会重新检测、不会新增记录）')
        load_button.clicked.connect(self.load_group)
        tools.addWidget(load_button)
        original_button = QPushButton('打开原图')
        original_button.clicked.connect(lambda: self.open_field('image', '原图'))
        tools.addWidget(original_button)
        result_button = QPushButton('打开结果图')
        result_button.clicked.connect(lambda: self.open_field('result_image', '结果图'))
        tools.addWidget(result_button)
        report_button = QPushButton('打开检测报告')
        report_button.setToolTip('打开这一张图对应的检测报告（CSV，可用 Excel / WPS 打开）')
        report_button.clicked.connect(lambda: self.open_field('result_csv', '检测报告'))
        tools.addWidget(report_button)
        delete_button = QPushButton('删除整批记录')
        delete_button.setToolTip('删除选中的这一批记录（这批的全部照片行）；删除后无法撤销，磁盘上的原图/结果图/报告不受影响')
        delete_button.clicked.connect(self.delete_group)
        tools.addWidget(delete_button)
        layout.addLayout(tools)

        explanation = QLabel(
            "每批照片为一组，新实验追加保存。空白表示没有保留该孔。"
            "孔号按图像位置排序。选中一行后可以：载入到工作区 / 打开原图 / 打开结果图 / "
            "打开检测报告 / 删除整批记录（把这一批的记录一起去掉）。"
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
            "QTableWidget { background: white; color: #172b4d; gridline-color: #e2e8f0; alternate-background-color: #f5f8fc; }"
            "QHeaderView::section { padding: 7px; background: #eef3fa; "
            "border: none; border-bottom: 1px solid #dbe4ee; font-weight: 600; }"
        )
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(34)
        header = self.table.horizontalHeader()
        # [local patch] fit every column instead of clipping the right ones
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)
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
            # 重新读盘，成功后 self.records 就是磁盘上的真实内容（读失败时原有内容不变）。
            groups = self.records.refresh_from_disk()
            rows = self.records.rows()
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.summary.setText("记录读取失败；已保留当前显示内容。")
            QMessageBox.warning(self, "实验记录读取失败", f"原记录文件未改动。\n{self.path}\n\n{error}")
            return False

        vertical_position = self.table.verticalScrollBar().value()
        horizontal_position = self.table.horizontalScrollBar().value()
        self.rows = rows
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

    def current_row(self):
        """[records-tools] 当前选中的那一行记录。"""
        row = self.table.currentRow()
        return self.rows[row] if 0 <= row < len(self.rows) else None

    @Slot()
    def open_field(self, key, label):
        """[records-tools] 打开这一行的原图 / 结果图 / 检测报告。"""
        row = self.current_row()
        if row is None:
            QMessageBox.information(self, '请先选一行', '请先在表格里选中一张图片。')
            return
        path_text = row.get(key, '') or ''
        if not path_text or not Path(path_text).is_file():
            QMessageBox.information(self, label + '无法打开',
                                    f'这条记录没有可用的{label}文件。\n'
                                    f'路径：{path_text or "（记录里没有记录路径）"}')
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path_text).resolve()))):
            QMessageBox.warning(self, label + '无法打开', f'未能打开：\n{path_text}')

    @Slot()
    def load_group(self):
        """[records-tools] 把选中的这一组载入主界面工作区（不重新检测）。"""
        row = self.current_row()
        if row is None:
            QMessageBox.information(self, '请先选一行', '请先选中要载入的那一组里的任意一行。')
            return
        reports = self.records.reports_of(row.get('group_id', ''))
        if not reports:
            QMessageBox.information(self, '无法载入', '这一组里没有可显示的照片记录。')
            return
        main = self.parent()
        if main is None or not hasattr(main, 'load_reports'):
            QMessageBox.information(self, '无法载入', '当前主界面不支持载入，请用主界面的「选择照片」。')
            return
        main.load_reports(reports)
        if hasattr(main, 'log'):
            main.log(f'已从实验记录载入第{row.get("group_number", "?")}组：{len(reports)} 张'
                     '（未重新检测、未新增记录）。')

    @Slot()
    def delete_group(self):
        """[records-tools] 删除选中的这一批记录（二次确认）。"""
        row = self.current_row()
        if row is None:
            QMessageBox.information(self, '请先选一行', '请先选中要删除的那一批里的任意一行。')
            return
        group_id = row.get('group_id', '')
        number = row.get('group_number', '?')
        batch = len(self.records.reports_of(group_id)) if group_id else 0
        confirm = QMessageBox.question(
            self, '确认删除',
            f'要删除实验记录里的「第{number}组」吗？\n\n'
            f'这批共 {batch} 张照片，整批记录都会从实验记录里去掉，删除后无法撤销。\n'
            '磁盘上的原图、结果图、检测报告文件都会保留（需要的话可以重新检测一遍）。',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if confirm != QMessageBox.StandardButton.Yes:
            return
        ok, message = self.records.delete_group(group_id)
        self.refresh()
        QMessageBox.information(self, '删除完成' if ok else '未删除', message)

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
