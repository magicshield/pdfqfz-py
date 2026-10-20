"""批量盖章后台线程：进度信号 + 取消。"""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from pdfqfz.core import pipeline
from pdfqfz.model.spec import StampSpec


class StampWorker(QThread):
    progress = Signal(int, int, str)      # i, total, 文本
    done = Signal(list)                   # list[FileResult]

    def __init__(self, spec: StampSpec, parent=None):
        super().__init__(parent)
        self.spec = spec
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            from pdfqfz.core.imageops import build_assets
            assets = build_assets(self.spec)
            results = pipeline.run(
                self.spec, assets,
                on_progress=lambda i, t, r: self.progress.emit(i, t, r.source.name),
                cancel=lambda: self._cancel)
            self.done.emit(results)
        except pipeline.Cancelled:
            self.done.emit([])
        except Exception as e:  # noqa: BLE001
            self.progress.emit(0, 0, f"错误: {e}")
            self.done.emit([])
