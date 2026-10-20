import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, Qt

from pdfqfz.gui.main_window import MainWindow


@pytest.fixture
def win(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    return w


def test_normalize_clamps(win):
    win.size_ed.setText("150")
    win._normalize(win.size_ed, 1, 100, signed=False)
    assert win.size_ed.text() == "100"
    win.rot_ed.setText("--1a2-3")
    win._normalize(win.rot_ed, -360, 360, signed=True)
    assert win.rot_ed.text() == "-123"


def test_current_spec_maps_widgets(win, seal_png):
    win.seal_cb.addItem(str(seal_png))
    win.mode_cb.setCurrentIndex(1)
    win.size_ed.setText("35")
    spec = win.current_spec()
    assert spec.size_mm == 35
    assert spec.stamp_image == seal_png
    assert spec.seam.value == 0


def test_preview_click_position(win, qtbot, make_pdf, seal_png):
    win.seal_cb.addItem(str(seal_png))
    win._params_changed()
    assert win.assets is not None
    src = make_pdf(pages=3)
    win.mode_cb.setCurrentIndex(1)
    win.sources = [src]
    win._open_preview(src)
    assert win.preview.page_count == 3
    qtbot.waitUntil(lambda: win.preview._img is not None, timeout=8000)

    win.stamp_cb.setCurrentIndex(4)  # 自定义(点击定位)
    win._params_changed()
    qtbot.mouseClick(win.preview, Qt.LeftButton, pos=QPoint(120, 160))
    key = (str(src.resolve()), 1)
    assert key in win.positions
    px, py = win.positions[key]
    assert 0.0 <= px <= 1.0 and 0.0 <= py <= 1.0

    # 双击删除该页定位
    qtbot.mouseDClick(win.preview, Qt.LeftButton, pos=QPoint(120, 160))
    assert key not in win.positions


def test_gui_end_to_end_stamp(win, qtbot, tmp_path, make_pdf, seal_png, monkeypatch):
    from pdfqfz.config import paths
    monkeypatch.setattr(paths, "config_path", lambda: tmp_path / "cfg.ini")
    src = make_pdf(pages=2)
    win.seal_cb.addItem(str(seal_png))
    win.mode_cb.setCurrentIndex(1)
    win.sources = [src]
    win.out_dir = tmp_path / "guiout"
    win.seam_cb.setCurrentIndex(1)  # 不加骑缝，只测普通章
    win.stamp_cb.setCurrentIndex(3)  # 所有页
    win._open_preview(src)
    qtbot.waitUntil(lambda: win.preview._img is not None, timeout=8000)
    win._start()
    assert win.worker is not None
    with qtbot.waitSignal(win.worker.done, timeout=30000) as blocker:
        pass
    results = blocker.args[0]
    assert len(results) == 1 and results[0].ok
    out = win.out_dir / "in.pdf"
    assert out.exists()
    import pymupdf
    doc = pymupdf.open(str(out))
    assert len(doc[0].get_image_info()) == 1
    doc.close()


def test_drag_drop_pdf(win, make_pdf):
    from PySide6.QtCore import QUrl

    src = make_pdf(pages=2)

    class Mime:
        def hasUrls(self):
            return True

        def urls(self):
            return [QUrl.fromLocalFile(str(src)), QUrl.fromLocalFile("x.txt")]

    class Ev:
        def mimeData(self):
            return Mime()

        def acceptProposedAction(self):
            pass

    win.dropEvent(Ev())
    assert win.mode_cb.currentIndex() == 1
    assert win.sources == [src]
    assert win.preview.page_count == 2


def test_seam_custom_click_toggles_pages(win, qtbot, make_pdf, seal_png):
    win.seal_cb.addItem(str(seal_png))
    win.seam_cb.setCurrentIndex(4)  # 随意骑缝
    win._params_changed()
    src = make_pdf(pages=2)
    win.mode_cb.setCurrentIndex(1)
    win.sources = [src]
    win._open_preview(src)
    qtbot.waitUntil(lambda: win.preview._img is not None, timeout=8000)
    qtbot.mouseClick(win.preview, Qt.LeftButton, pos=QPoint(50, 50))
    key = (str(src.resolve()), 1)
    assert key in win.positions
    qtbot.mouseClick(win.preview, Qt.LeftButton, pos=QPoint(50, 50))
    assert key not in win.positions  # 再点取消
