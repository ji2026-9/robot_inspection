"""End-to-end check for the 孔检测软件 (inspection_app).

Offscreen Qt run that exercises the whole chain without touching the real
experiment records:

    选择照片 -> 检测 -> 写入实验记录 -> 从实验记录载入工作区
    -> 点图选孔 -> 查看原图 / 结果图 / 检测报告 -> 删除这一组

Everything the script writes goes to a temporary folder, so the real project
files are never modified.

用法::

    set CODEX_APP_DIR=E:\\robot_project\\inspection_app
    set CODEX_E2E_DIR=%TEMP%\\inspection_e2e
    .venv\\Scripts\\python.exe scripts\\check_inspection_app.py

``CODEX_APP_DIR`` 默认是这个脚本所在的目录；``CODEX_E2E_DIR`` 是写测试产物的
可写目录（默认系统临时目录）。
"""
import os
import json
import sys
import traceback
from datetime import datetime
from pathlib import Path

_APP_DIR = os.environ.get('CODEX_APP_DIR')
BASE = Path(_APP_DIR).resolve() if _APP_DIR else Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

FAILURES = []


def check(label, condition, detail=''):
    status = 'PASS' if condition else 'FAIL'
    print(f'[{status}] {label}' + (f'  -> {detail}' if detail else ''))
    if not condition:
        FAILURES.append(label)
    return bool(condition)


def main():
    # 受限运行环境里临时目录可能不允许再建子目录，用 CODEX_E2E_DIR 指一个可写目录。
    root = Path(os.environ.get('CODEX_E2E_DIR') or os.environ.get('TEMP') or '.')
    root.mkdir(parents=True, exist_ok=True)
    workspace = root / ('run_' + datetime.now().strftime('%H%M%S_%f'))
    workspace.mkdir(parents=True, exist_ok=True)
    print('临时工作目录:', workspace)

    # 测试照片可能在 inspection_app，也可能在 robot_inspection/test_images；
    # 都没有时退回本机抓拍或数据种子图。
    override = os.environ.get('CODEX_E2E_IMAGE')
    candidates = [Path(override)] if override else []
    for pattern in ('test_images/*.jpg', 'test_images/*.png',
                    '../robot_inspection/test_images/*.jpg',
                    'captures/*/*.png', 'data/database_seed/*.jpg'):
        found = sorted(BASE.glob(pattern))
        if found:
            candidates.extend(found)
    image = candidates[0] if candidates else None
    check('找到测试照片', image is not None and image.is_file(), str(image))
    if image is None:
        return 1

    from experiment_records import ExperimentRecords
    from inspection_gui.vision import HoleDetector

    records = ExperimentRecords(workspace / 'experiment_records.json')
    detector = HoleDetector(output_dir=workspace / 'results')
    print('开始检测（这一步最慢）…')
    result = detector.detect(image)
    report = result.get('raw_report')
    check('检测返回原始报告', isinstance(report, dict), f'errors={result.get("errors")}')
    if not isinstance(report, dict):
        return 1
    check('检测出 4 个孔', result.get('detections') == 4, f"detections={result.get('detections')}")
    check('拟合出 4 个可靠圆心', result.get('reliable_center_count') == 4,
          f"reliable={result.get('reliable_center_count')} / fitted={result.get('center_count')}")
    check('结果图片已写盘', bool(report.get('result_image')) and Path(report['result_image']).is_file(),
          str(report.get('result_image')))
    check('检测报告 CSV 已写盘', bool(report.get('result_csv')) and Path(report['result_csv']).is_file(),
          str(report.get('result_csv')))

    # ---- 实验记录：一组照片的写入 / 读取 ----
    group_id = records.begin([str(image)], report.get('model', ''))
    check('新组状态为“检测中”', records.groups[-1]['status'] == '检测中')
    records.update(group_id, report=report)
    records.update(group_id, status='已完成')
    rows = records.rows()
    check('实验记录有 1 行', len(rows) == 1, f'rows={len(rows)}')
    row = rows[0] if rows else {}
    check('行里带原图路径', Path(row.get('image', '')).resolve() == image.resolve(), str(row.get('image')))
    check('行里带结果图路径', bool(row.get('result_image')), str(row.get('result_image')))
    check('行里带检测报告路径', bool(row.get('result_csv')), str(row.get('result_csv')))
    check('行里保留 4 个孔置信度', all(row.get(f'hole{i}') for i in range(1, 5)),
          str([row.get(f'hole{i}') for i in range(1, 5)]))
    check('组状态为已完成', row.get('status') == '已完成', str(row.get('status')))
    export_csv = workspace / '导出检查.csv'
    records.export(export_csv)
    check('导出 CSV 成功', export_csv.is_file() and export_csv.stat().st_size > 0)

    # ---- Qt 界面（离屏）----
    from PySide6.QtWidgets import QApplication, QMessageBox
    import inspection_gui.gui as gui
    import inspection_gui.records_view as records_view

    # 离屏检查不碰真设备：相机自动连接/状态轮询都跳过。
    gui.MainWindow.auto_connect_camera = lambda self: None
    gui.MainWindow.refresh_device_states = lambda self: None
    records_view.QDesktopServices.openUrl = staticmethod(lambda url: True)
    asked = {}

    def fake_question(*args, **kwargs):
        asked['text'] = args[2] if len(args) > 2 else ''
        return QMessageBox.StandardButton.Yes

    class FakeMessageBox:
        """弹窗替身：离屏运行不能让 QMessageBox 阻塞。"""
        StandardButton = QMessageBox.StandardButton

        @staticmethod
        def information(*args, **kwargs):
            asked.setdefault('information', []).append(args[2] if len(args) > 2 else '')
            return QMessageBox.StandardButton.Ok

        @staticmethod
        def warning(*args, **kwargs):
            asked.setdefault('warning', []).append(args[2] if len(args) > 2 else '')
            return QMessageBox.StandardButton.Ok

        question = staticmethod(fake_question)

    records_view.QMessageBox = FakeMessageBox

    app = QApplication.instance() or QApplication([])
    window = gui.MainWindow(records=records)
    window.resize(1300, 860)
    window.show()
    for _ in range(6):
        app.processEvents()

    buttons = {b.text() for b in window.findChildren(gui.QPushButton)}
    check('「其他功能」不再有独立的“打开历史批次”入口', '打开历史批次' not in buttons, str(sorted(buttons)))
    check('「其他功能」不再有独立的“相机实时预览”入口', '相机实时预览' not in buttons)
    check('视觉检测区有“相机实时画面”', '相机实时画面' in {c.text() for c in window.findChildren(gui.QCheckBox)})
    check('视觉检测区有“抓拍”', '抓拍' in buttons)

    # 从实验记录载入工作区（不重新检测、不新增记录）
    window.load_reports(records.reports_of(group_id))
    for _ in range(4):
        app.processEvents()
    check('载入工作区后照片数正确',
          len(window.paths) == 1 and Path(window.paths[0]).resolve() == image.resolve(),
          f'paths={window.paths}')
    check('载入没有新增实验记录', len(records.groups) == 1, f'groups={len(records.groups)}')
    check('孔位表格 4 行', window.table.rowCount() == 4, f'rows={window.table.rowCount()}')
    check('检测结果集成为 4 个孔', len(window.current_result.get('fitted_holes', [])) == 4)

    # ---- 左右分屏：左格实时画面、右格检测结果（点选只作用于右格）----
    check('视觉检测区分成左右两格',
          hasattr(window, 'visual_split') and hasattr(window, 'live_view')
          and hasattr(window, 'result_view'))
    check('左格是只读画面，不能点选孔', not isinstance(window.live_view, gui.ClickablePhoto))
    check('默认不显示实时格（结果图占满整格）', window.live_column.isHidden())
    check('右格带当前照片的角标', Path(window.result_caption.text()).stem in window.result_caption.text()
          or image.stem in window.result_caption.text(), window.result_caption.text())
    import numpy as _np
    window.live_frame = _np.zeros((800, 1280, 3), _np.uint8)
    window._show_live_column()
    for _ in range(3):
        app.processEvents()
    window._paint_live_frame()
    check('打开实时格后能显示画面',
          not window.live_column.isHidden() and window.live_view.pixmap() is not None)
    # 拖到头也不能把某一格拖没（真机上拖没之后找不回来）
    total_w = window.visual_split.width()
    window.visual_split.setSizes([0, total_w])
    for _ in range(4):
        app.processEvents()
    check('往左拖到头，实时格不会被拖没', window.live_column.width() >= 150,
          f'live={window.live_column.width()}')
    window.visual_split.setSizes([total_w, 0])
    for _ in range(4):
        app.processEvents()
    check('往右拖到头，结果格不会被拖没', window.result_column.width() >= 200,
          f'result={window.result_column.width()}')
    window._show_live_column()
    for _ in range(3):
        app.processEvents()
    window.render_view()
    check('实时画面开着时，右格检测结果照常显示', window.result_view.pixmap() is not None)
    window.chk_live.blockSignals(True)
    window.chk_live.setChecked(True)
    window.chk_live.blockSignals(False)
    window.set_status('相机实时画面中', '#a86613')
    window.refresh_current_summary()
    check('实时画面开着时状态栏不被改写', '相机实时画面中' in window.lbl_system.text(),
          window.lbl_system.text())
    window.chk_live.blockSignals(True)
    window.chk_live.setChecked(False)
    window.chk_live.blockSignals(False)
    window.live_frame = None
    window._live_placeholder()
    window.live_column.hide()
    check('关掉实时后恢复占满，且提示不冒充画面',
          window.live_column.isHidden() and '未开启' in window.live_caption.text(),
          window.live_caption.text())

    # 改变分格大小后，右格坐标映射必须重新对到当前画布，否则点孔会点偏（真机上踩到过）。
    # 判据：compose 把图居中放，ox/oy 必然等于 (画布尺寸 - 图尺寸) / 2；映射要是旧的就不等。
    window._show_live_column()
    for _ in range(3):
        app.processEvents()
    total = window.visual_split.width()
    window.visual_split.setSizes([max(150, total - 220), min(220, max(150, total - 150))])
    for _ in range(5):
        app.processEvents()
    mapping_after = dict(window.display_mapping or {})
    view_size = window.result_view.size()
    check('改分格大小后映射与当前画布对得上',
          bool(mapping_after)
          and mapping_after['ox'] == (view_size.width() - mapping_after['tw']) // 2
          and mapping_after['oy'] == (view_size.height() - mapping_after['th']) // 2,
          f"画布 {view_size.width()}x{view_size.height()} 映射 ox={mapping_after.get('ox')} "
          f"tw={mapping_after.get('tw')} (期望 ox={(view_size.width() - mapping_after.get('tw', 0)) // 2})")
    hole = window.current_result['fitted_holes'][0]
    cx, cy = hole['center_px']
    mapping_now = window.display_mapping
    window.canvas_clicked((cx - mapping_now['crop'][0]) * mapping_now['scale'] + mapping_now['ox'],
                          (cy - mapping_now['crop'][1]) * mapping_now['scale'] + mapping_now['oy'])
    check('按新的映射点孔仍能选中（没点偏）', hole['id'] in window.measure_targets,
          f"选中={sorted(window.measure_targets)}")
    window.measure_targets.clear()
    window.refresh_current_summary()
    window.live_frame = None
    window._live_placeholder()
    window.live_column.hide()
    for _ in range(3):
        app.processEvents()

    # 点图片选孔：把某个孔的图像坐标换算成画布坐标再点
    window.render_view()
    mapping = getattr(window, 'display_mapping', None)
    check('画布有坐标映射', bool(mapping), str(mapping))
    if mapping:
        hole = window.current_result['fitted_holes'][0]
        cx, cy = hole['center_px']
        canvas_x = (cx - mapping['crop'][0]) * mapping['scale'] + mapping['ox']
        canvas_y = (cy - mapping['crop'][1]) * mapping['scale'] + mapping['oy']

        def green_pixels():
            """数一下孔周围有多少"选中绿"像素（绿圈 + 白勾的中心盘）。"""
            image = window.result_view.pixmap().toImage()
            total = 0
            for dx in range(-14, 15, 2):
                for dy in range(-14, 15, 2):
                    x, y = int(round(canvas_x)) + dx, int(round(canvas_y)) + dy
                    if not (0 <= x < image.width() and 0 <= y < image.height()):
                        continue
                    color = image.pixelColor(x, y)
                    if (abs(color.red() - 95) < 60 and abs(color.green() - 215) < 60
                            and abs(color.blue() - 80) < 60):
                        total += 1
            return total

        before = green_pixels()
        window.canvas_clicked(canvas_x, canvas_y)
        after = green_pixels()
        check('点孔后进入本次测量清单', hole['id'] in window.measure_targets,
              f"选中={sorted(window.measure_targets)}")
        check('图上出现选中标记（绿色圈 / 白勾）', after >= 4 and after > before,
              f'绿色像素 {before} -> {after}')
        check('角标写清本次要测哪些孔', '本次要测：H01' in window.result_caption.text(),
              window.result_caption.text())
        check('表格勾选与点选同步',
              window.table.item(int(hole['id'][1:]) - 1, 0).checkState() == gui.Qt.CheckState.Checked)
        check('确认的测量目标包含该孔', hole['id'] in window.confirmed_targets())
        # 再点一次应该取消
        window.canvas_clicked(canvas_x, canvas_y)
        check('再点一次取消该孔', hole['id'] not in window.measure_targets,
              f"选中={sorted(window.measure_targets)}")
        check('取消后绿色标记消失', green_pixels() < after, f'绿色像素={green_pixels()}')
        check('取消后角标回到“未选中”', '（未选中' in window.result_caption.text(),
              window.result_caption.text())
        # 点空白处不应该误选
        window.canvas_clicked(mapping['ox'] + 2, mapping['oy'] + 2)
        check('点空白处不改变测量清单', not window.measure_targets, f"选中={sorted(window.measure_targets)}")

    # ---- 实验记录窗口：看图 / 报告 / 载入 / 删除 ----
    dialog = gui.RecordsDialog(window, records=records)
    dialog.refresh()
    check('实验记录窗口读到 1 行', dialog.table.rowCount() == 1, f'rows={dialog.table.rowCount()}')
    dialog.table.selectRow(0)
    current = dialog.current_row()
    check('能取到当前行的原图 / 结果图 / 报告',
          bool(current) and current.get('image') and current.get('result_image') and current.get('result_csv'))
    opened = []
    records_view.QDesktopServices.openUrl = staticmethod(lambda url: opened.append(url.toString()) or True)
    dialog.open_field('image', '原图')
    dialog.open_field('result_image', '结果图')
    dialog.open_field('result_csv', '检测报告')
    check('三个“打开”按钮都能打开文件', len(opened) == 3, str(opened))
    window.paths = []
    dialog.load_group()
    check('“载入到工作区”把这一组放回主界面', len(window.paths) == 1, f'paths={window.paths}')
    check('“载入到工作区”没有新增记录', len(records.groups) == 1)
    dialog.delete_group()
    check('删除弹了二次确认（写清楚删的是什么）',
          '要删除实验记录里的' in asked.get('text', '') and '整批记录都会从实验记录里去掉' in asked.get('text', ''),
          asked.get('text', '')[:60])
    check('删除后记录里没有这一组', len(records.groups) == 0, f'groups={len(records.groups)}')
    check('删除后记录文件已同步', '[]' in (workspace / 'experiment_records.json').read_text(encoding='utf-8'))
    check('删除不动磁盘上的原图', image.is_file())
    check('删除不动磁盘上的结果图', Path(row.get('result_image', '')).is_file())

    # 回归检查：删除之后再检测一组，不能把删掉的那一组“复活”。
    new_id = records.begin([str(image)], report.get('model', ''))
    records.update(new_id, report=report)
    disk_groups = json.loads((workspace / 'experiment_records.json').read_text(encoding='utf-8'))
    check('删除后新建一组不会带回已删除的组',
          len(disk_groups) == 1 and disk_groups[0].get('id') == new_id,
          f'磁盘上的组数={len(disk_groups)}')
    check('删除后再写入时组号从 1 继续', disk_groups[0].get('number') == 1,
          f"number={disk_groups[0].get('number')}")

    window.close()
    print()
    if FAILURES:
        print(f'共 {len(FAILURES)} 项未通过：')
        for item in FAILURES:
            print('  -', item)
        return 1
    print('全流程检查全部通过。')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException:
        traceback.print_exc()
        raise SystemExit(2)
