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
    """返回 (页面图, pt→px 缩放系数)。一次渲染：先算长边钳制比例再出图。"""
    doc = pymupdf.open(str(path))
    try:
        if doc.needs_pass and not doc.authenticate(password or ""):
            raise ValueError("PDF 需要密码")
        page = doc[page_index]
        k = min(1.0, MAX_SIDE / max(page.rect.width, page.rect.height))
        pix = page.get_pixmap(matrix=pymupdf.Matrix(k, k))  # 72dpi 基准: 1pt=1px
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        return _qimage_from_pil(img), k
    finally:
        doc.close()


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

    def _seam_strip_overlay(self, s: float) -> tuple[QImage, float, float, float, float] | None:
        """当前页若为骑缝目标页，返回该页实际切条的叠加 (图, x, y, w, h)px。"""
        spec = self.spec
        page = self.page_index + 1
        custom_pages = sorted({p for (k, p) in self.positions.items()
                               if k == self.file_key})
        seam_pages = P.seam_target_pages(self.page_count, spec.seam, custom_pages)
        if len(seam_pages) <= 1 or page not in seam_pages:
            return None
        idx = seam_pages.index(page)
        acc = 0
        for g in P.seam_groups(len(seam_pages), spec.max_strips):
            if idx < acc + g:
                strip_i, group = idx - acc, g
                break
            acc += g
        W_px = self.assets.full.width
        sfbl = G.sfbl_percent(spec.size_mm, self.assets.base_px_w)
        widths = tuple(P.strip_widths(W_px, group))
        strip = self.assets.strip_images(widths, spec.edge)[strip_i]
        w_pt = G.scale_px(strip.width, sfbl)
        h_pt = G.scale_px(strip.height, sfbl)
        page_w_pt, page_h_pt = self._img.width() / s, self._img.height() / s
        rect = G.seam_visual_rect(w_pt, h_pt, page_w_pt, page_h_pt, spec.edge, spec.wz)
        return (_qimage_from_pil(strip), rect[0] * s, rect[1] * s,
                max(1, int(w_pt * s)), max(1, int(h_pt * s)))

    def _build_overlays(self) -> list[tuple[QImage, float, float, float, float]]:
        """叠加项列表：骑缝切条(体现真实分割) + 整章(普通定位章)。"""
        if self.spec is None or self.assets is None or self._img is None:
            return []
        spec = self.spec
        s = self._scale  # pt→渲染像素系数
        items = []
        if spec.seam != SeamType.NONE:
            strip = self._seam_strip_overlay(s)
            if strip is not None:
                items.append(strip)
        page = self.page_index + 1
        has_pos = (self.file_key, page) in self.positions
        if spec.normal != StampType.NONE and P.overlay_visible_for_page(
                spec.normal, spec.seam, page, self.page_count, has_pos):
            img = _qimage_from_pil(self.assets.full)
            sfbl = G.sfbl_percent(spec.size_mm, self.assets.base_px_w)
            w_pt = G.scale_px(self.assets.full.width, sfbl)
            h_pt = G.scale_px(self.assets.full.height, sfbl)
            ov_w = max(1, int(w_pt * s))
            ov_h = max(1, int(h_pt * s))
            px, py = self.positions.get((self.file_key, page), (spec.px, spec.py))
            rect = G.normal_visual_rect(w_pt, h_pt, self._img.width() / s,
                                        self._img.height() / s, px, py)
            items.append((img, rect[0] * s, rect[1] * s, ov_w, ov_h))
        return items

    def _full_seal_overlay(self):
        for img, x, y, w, h in self._build_overlays():
            if img.width() == self.assets.full.width:
                return w, h
        return 0, 0

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        if self._img:
            p.drawImage(0, 0, self._img)
        for img, x, y, w, h in self._build_overlays():
            p.drawImage(int(x), int(y), img.scaled(w, h))

    # ---- 交互 ----

    def mousePressEvent(self, event):  # noqa: N802
        if self.spec is None or self._img is None:
            return
        spec = self.spec
        page = self.page_index + 1
        w, h = self._full_seal_overlay()
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
