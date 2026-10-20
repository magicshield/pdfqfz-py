"""GUI 启动入口。"""

from __future__ import annotations

import sys
from pathlib import Path


def run_gui(argv: list[str] | None = None) -> int:
    from PySide6.QtWidgets import QApplication

    from pdfqfz.gui.main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv[:1])
    preset = [Path(a) for a in (argv or []) if a.lower().endswith(".pdf")]
    win = MainWindow(preset_files=preset)
    win.resize(1100, 720)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run_gui())
