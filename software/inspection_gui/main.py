"""Start the integrated Qt shell without preloading detection models."""
import sys
from pathlib import Path
from PySide6.QtCore import QTimer, QLockFile
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QMessageBox

from .gui import MainWindow


def main(open_records=False, open_simulation=False):
    application = QApplication.instance() or QApplication(sys.argv)
    application.setApplicationName('Engine Bore Inspection')
    # [local patch] force the LIGHT colour scheme so the Windows title bar
    # and frame match the light UI instead of staying dark-mode black
    try:
        from PySide6.QtCore import Qt as _Qt
        application.styleHints().setColorScheme(_Qt.ColorScheme.Light)
    except Exception:
        try:
            application.setStyle('Fusion')
        except Exception:
            pass
    # [local patch] application icon
    _icon_file = Path(__file__).resolve().parents[1] / 'app_icon.ico'
    if _icon_file.is_file():
        from PySide6.QtGui import QIcon
        application.setWindowIcon(QIcon(str(_icon_file)))
    # Explicitly load the Windows Chinese font for consistent screenshot and UI glyphs.
    chinese_font = Path('C:/Windows/Fonts/msyh.ttc')
    if chinese_font.is_file():
        QFontDatabase.addApplicationFont(str(chinese_font))
    instance_lock = QLockFile(str(Path(__file__).resolve().parents[1] / '.inspection_gui.lock'))
    instance_lock.setStaleLockTime(0)
    if not instance_lock.tryLock(0):
        QMessageBox.information(None, '软件已经打开', '请返回已打开的检测窗口继续操作。')
        return 0
    fonts = set(QFontDatabase.families())
    for family in ('Microsoft YaHei UI', 'Microsoft YaHei', 'SimHei', 'Noto Sans CJK SC'):
        if family in fonts:
            application.setFont(QFont(family, 10))
            break
    try:
        window = MainWindow()
    except (OSError, ValueError, KeyError) as error:
        QMessageBox.critical(None, '软件未能启动', f'请保留现有实验记录和模型文件。\n{error}')
        return 1
    window.show()
    if open_records:
        QTimer.singleShot(200, window.show_records)
    if open_simulation:
        QTimer.singleShot(250, window.show_simulation)
    return application.exec()


if __name__ == '__main__':
    raise SystemExit(main())
