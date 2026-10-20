"""预览面板：异步渲染 PDF 页 + 叠加印章 + 点击定位（requestId 门闸丢弃过期结果）。"""

from __future__ import annotations

from pathlib import Path

import pymupdf
from PIL import Image
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QWidget

from pdfqfz.core import geometry as G
from pdfqfz.core import policies as P
from pdfqfz.core.imageops import build_assets
from pdfqfz.core.progress import PageCache, RequestGate
from pdfqfz.model.spec import SeamType, StampSpec, StampType

MAX_SIDE = 500
DPI = 72


def _qimage_from_pil(img: Image.Image) -> QImage:
    img = img.convert("RGBA")
    return QImage(img.tobytes("raw", "RGBA"), img.width, img.height,
                  QImage.Format_RGBA8888).copy()


def render_page_qimage(path: Path, password: str | None, page_index: int) -> tuple[QImage, float]:
    """返回 (页面图, pt→px 缩放系数)。"""
    doc = pymupdf.open(str(path))
    try:
        if doc.needs_pass and not doc.authenticate(password or ""):
            raise ValueError("PDF 需要密码")
        page = doc[page_index]
        pix = page.get_pixmap(dpi=DPI)
        scale = DPI / 72.0
        if max(pix.width, pix.height) > MAX_SIDE:
            k = MAX_SIDE / max(pix.width, pix.height)
            pix = None
            img = _render_scaled(doc, page_index, k)
            return _qimage_from_pil(img), scale * k
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        return _qimage_from_pil(img), scale
    finally:
        doc.close()


def _render_scaled(doc, page_index: int, k: float) -> Image.Image:
    page = doc[page_index]
    pix = page.get_pixmap(matrix=pymupdf.Matrix(k, k), dpi=DPI)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


class _TaskSignals(QObject):
    done = Signal(int, object)  # request_id, QImage|None


class _RenderTask(QRunnable):
    def __init__(self, rid, path, password, page_index, signals):
        super().__init__()
        self.rid, self.path, self.password, self.page = rid, path, password, page_index
        self.signals = signals
        self.setAutoDelete(True)

    @Slot()
    def run(self):
        try:
            img, scale = render_page_qimage(self.path, self.password, self.page)
            self.signals.done.emit(self.rid, (img, scale))
        except Exception:  # noqa: BLE001
            self.signals.done.emit(self.rid, None)


class PreviewPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(320, 420)
        self.gate = RequestGate()
        self.pool = QThreadPool.globalInstance()
        self._sig = _TaskSignals()
        self._sig.done.connect(self._on_rendered)
        self._cache: PageCache | None = None
        self.path: Path | None = None
        self.password: str | None = None
        self.page_index = 0
        self.page_count = 0
        self.spec: StampSpec | None = None
        self.assets = None
        self.positions: dict[tuple[str, int], tuple[float, float]] = {}
        self.file_key: str = ""
        self._img: QImage | None = None
        self._scale = 1.0
        self._pending_rid = 0

    # ---- 对外接口 ----

    def set_document(self, path: Path | None, password: str | None, page_count: int):
        self.path = path
        self.password = password
        self.page_count = page_count
        self.page_index = min(self.page_index, max(0, page_count - 1))
        self.file_key = str(path.resolve()) if path else ""
        self._cache = PageCache(self._load_page) if path else None
        self.refresh()

    def set_params(self, spec: StampSpec, assets, positions):
        self.spec = spec
        self.assets = assets
        self.positions = positions
        self.refresh()

    def set_page(self, index: int):
        self.page_index = max(0, min(index, max(0, self.page_count - 1)))
        self.refresh()

    def next_page(self):
        self.set_page(self.page_index + 1)

    def prev_page(self):
        self.set_page(self.page_index - 1)

    # ---- 渲染 ----

    def _load_page(self, index: int):
        return render_page_qimage(self.path, self.password, index)

    def refresh(self):
        if self.path is None or self.page_count == 0:
            self._img = None
            self.update()
            return
        if self._cache is not None:
            try:
                self._img, self._scale = self._cache.get_page(self.page_index)
                self._apply_size()
                return
            except Exception:  # noqa: BLE001 — 缓存条目失效则重渲染
                self._cache = PageCache(self._load_page)
        rid = self.gate.begin_next()
        self._pending_rid = rid
        self.pool.start(_RenderTask(rid, self.path, self.password, self.page_index, self._sig))

    @Slot(int, object)
    def _on_rendered(self, rid: int, payload):
        if not self.gate.is_current(rid) or payload is None:
            return
        self._img, self._scale = payload
        if self._cache is not None:
            self._cache._pages[self.page_index] = payload
            self._cache._order.append(self.page_index)
        self._apply_size()

    def _apply_size(self):
        if self._img:
            self.setFixedSize(self._img.width(), self._img.height())
        self.update()

    def _overlay_geom(self) -> tuple[QImage | None, float, float, float, float]:
        """返回 (章图, x, y, w, h) 像素；None 表示不叠加。"""
        if self.spec is None or self.assets is None or self._img is None:
            return None, 0, 0, 0, 0
        spec = self.spec
        if spec.normal == StampType.NONE and spec.seam != SeamType.CUSTOM:
            return None, 0, 0, 0, 0
        page = self.page_index + 1
        has_pos = (self.file_key, page) in self.positions
        if not P.overlay_visible_for_page(spec.normal, spec.seam, page,
                                          self.page_count, has_pos):
            return None, 0, 0, 0, 0
        img = _qimage_from_pil(self.assets.full)
        sfbl = G.sfbl_percent(spec.size_mm, self.assets.xzbl, self.assets.full.width)
        w_pt = G.scale_px(self.assets.full.width, sfbl)
        h_pt = G.scale_px(self.assets.full.height, sfbl)
        s = self._scale  # pt→渲染像素系数
        ov_w = max(1, int(w_pt * s))
        ov_h = max(1, int(h_pt * s))
        px, py = self.positions.get((self.file_key, page), (spec.px, spec.py))
        rect = G.normal_visual_rect(w_pt, h_pt, self._img.width() / s,
                                    self._img.height() / s, px, py)
        return img, rect[0] * s, rect[1] * s, ov_w, ov_h

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        if self._img:
            p.drawImage(0, 0, self._img)
        img, x, y, w, h = self._overlay_geom()
        if img is not None:
            p.drawImage(int(x), int(y), img.scaled(w, h))

    # ---- 交互 ----

    def mousePressEvent(self, event):  # noqa: N802
        if self.spec is None or self._img is None:
            return
        spec = self.spec
        page = self.page_index + 1
        img, x, y, w, h = self._overlay_geom()
        if spec.normal == StampType.CUSTOM:
            px, py = P.click_to_position(
                (event.position().x(), event.position().y()),
                (self._img.width(), self._img.height()), (w, h))
            self.positions[(self.file_key, page)] = (px, py)
            self.update()
        elif spec.seam == SeamType.CUSTOM:
            key = (self.file_key, page)
            if key in self.positions:
                del self.positions[key]
            else:
                self.positions[key] = (spec.px, spec.py)
            self.update()

    def mouseDoubleClickEvent(self, event):  # noqa: N802
        key = (self.file_key, self.page_index + 1)
        if key in self.positions:
            del self.positions[key]
            self.update()
