# -*- coding: utf-8 -*-
"""
Entry point for the 1st version GUI of 机械臂智能视觉检测系统.

Run:
    python app/main.py
or double-click app/run_gui.bat

This program never trains a model and never writes to weights/ or dataset/.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtGui import QFont, QFontDatabase  # noqa: E402

from gui import MainWindow  # noqa: E402


def pick_cjk_font():
    """Prefer a font that renders Chinese well on Windows."""
    families = set(QFontDatabase.families())
    for name in ("Microsoft YaHei UI", "Microsoft YaHei", "SimHei", "SimSun",
                 "Noto Sans CJK SC", "Sans Serif"):
        if name in families:
            return QFont(name, 10)
    return QFont()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Robot Vision Inspection GUI")
    app.setFont(pick_cjk_font())
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
