"""PyMuPDF 操作层：打开/贴章/光栅化合并/加密/保存。

坐标策略：布局全部在"显示空间"(左上原点, pt)，插入前经 visual_to_unrotated
换算到 MuPDF 未旋转空间，并对像素做 -rotation 补偿，使章在阅读器观感端正
（等价 C# 中 iText 自动处理的页面旋转）。
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf
from PIL import Image

from pdfqfz.core import geometry as G
from pdfqfz.core import policies as P
from pdfqfz.core.imageops import to_png
from pdfqfz.model.spec import Edge, SeamType, StampSpec, StampType

CCW = {90: Image.ROTATE_90, 180: Image.ROTATE_180, 270: Image.ROTATE_270}
SCALE = Image.BILINEAR


class DocPasswordError(Exception):
    pass


def open_doc(path: Path, password: str | None = None) -> pymupdf.Document:
    doc = pymupdf.open(str(path))
    if doc.needs_pass:
        if not password or not doc.authenticate(password):
            doc.close()
            raise DocPasswordError(f"PDF 密码错误: {path}")
    return doc


def page_metrics(page: pymupdf.Page) -> tuple[int, float, float, float, float]:
    """(rotation, 视觉宽pt, 视觉高pt, 未旋转宽pt, 未旋转高pt)，尺寸基于 CropBox。"""
    crop = page.cropbox
    return (page.rotation % 360, page.rect.width, page.rect.height,
            crop.width, crop.height)


def insert_visual(page: pymupdf.Page, img: Image.Image, vrect: G.Rect) -> None:
    rot = page.rotation % 360
    _, _, _, uw, uh = page_metrics(page)
    work = img.transpose(CCW[rot]) if rot else img
    unrot = pymupdf.Rect(*G.visual_to_unrotated(vrect, rot, uw, uh))
    page.insert_image(unrot, stream=to_png(work), keep_proportion=False, overlay=True)


@dataclass
class StampPlan:
    """单文件盖章计划（dry-run 输出与 M5 签名几何共用）。"""
    seam: list[tuple[int, G.Rect]] = field(default_factory=list)       # (1-based 页, 视觉rect)
    normal: list[tuple[int, G.Rect, int]] = field(default_factory=list)  # (页, rect, 视觉倾角°)
    sig_page: int = 0
    sig_rect: G.Rect | None = None       # 签名域 = sig_page 章 rect 外扩 2pt
    sig_box_bl: tuple[float, float, float, float] | None = None  # 未旋转 PDF 左下坐标
    sig_page_index: int = 0
    sig_ccw: int = 0                     # 签名外观像素需逆时针补偿的页面旋转
    skipped_seam_reason: str = ""

    def seam_pages(self) -> list[int]:
        return [p for p, _ in self.seam]

    def normal_pages(self) -> list[int]:
        return [p for p, _, _ in self.normal]


def build_plan(doc: pymupdf.Document, spec: StampSpec, assets,
               file_key: str, positions: dict[tuple[str, int], tuple[float, float]],
               rng) -> StampPlan:
    import math
    W_px = assets.full.width
    sfbl = G.sfbl_percent(spec.size_mm, assets.xzbl, W_px)
    n = doc.page_count
    plan = StampPlan()

    # ---- 骑缝 ----
    custom_seam = sorted({p for (k, p) in positions if k == file_key})
    seam_pages = P.seam_target_pages(n, spec.seam, custom_seam)
    if spec.seam != SeamType.NONE and 0 < len(seam_pages) <= 1 and not P.should_skip_seam_single_page(n, spec.seam):
        plan.skipped_seam_reason = "骑缝目标页不足 2 页，已跳过"
    if len(seam_pages) > 1:
        idx = 0
        for group in P.seam_groups(len(seam_pages), spec.max_strips):
            widths = tuple(P.strip_widths(W_px, group))
            strip_imgs = assets.strip_images(widths, spec.edge)
            for i, page_no in enumerate(seam_pages[idx: idx + group]):
                s_img = strip_imgs[i]
                w_pt = G.scale_px(s_img.width, sfbl)
                h_pt = G.scale_px(s_img.height, sfbl)
                _, pW, pH, _, _ = page_metrics(doc[page_no - 1])
                plan.seam.append((page_no, G.seam_visual_rect(w_pt, h_pt, pW, pH, spec.edge, spec.wz)))
            idx += group

    # ---- 普通章 ----
    if P.should_render_normal_stamp(spec.normal):
        custom_norm = custom_seam if spec.normal == StampType.CUSTOM else []
        excluded, sig_page, seq = P.normal_page_plan(n, spec.normal, custom_norm)
        sig_on = spec.cert_mode.value != 0
        plan.sig_page = sig_page if sig_on else 0
        w0_pt = G.scale_px(assets.full.width, sfbl)
        h0_pt = G.scale_px(assets.full.height, sfbl)
        for page_no in range(1, n + 1):
            if not P.should_draw_normal_on_page(page_no, excluded, sig_page if sig_on else 0, sig_on):
                continue
            if spec.normal == StampType.CUSTOM and (file_key, page_no) not in positions:
                continue
            _, pW, pH, _, _ = page_metrics(doc[page_no - 1])
            pos = positions.get((file_key, page_no))
            if pos is not None:
                px, py = pos
            elif spec.normal == StampType.CUSTOM:
                continue
            else:
                px, py = spec.px, spec.py
                if spec.random_jitter:
                    px = P.jitter_position(px, rng.randint(P.JITTER_MIN, P.JITTER_MAX))
                    py = P.jitter_position(py, rng.randint(P.JITTER_MIN, P.JITTER_MAX))
            angle = P.jitter_angle(page_no, sig_page, spec.random_jitter,
                                   rng.randint(P.JITTER_MIN, P.JITTER_MAX))
            base = G.normal_visual_rect(w0_pt, h0_pt, pW, pH, px, py)
            if angle:
                a = math.radians(abs(angle))
                wb = (assets.full.width * math.cos(a) + assets.full.height * math.sin(a)) * sfbl / 100
                hb = (assets.full.width * math.sin(a) + assets.full.height * math.cos(a)) * sfbl / 100
                vrect = G.rect_with_size_centered(base, wb, hb)
            else:
                vrect = base
            plan.normal.append((page_no, vrect, angle))
        if sig_on and 1 <= sig_page <= n and spec.normal != StampType.NONE:
            rot, pW, pH, uw, uh = page_metrics(doc[sig_page - 1])
            pos = positions.get((file_key, sig_page))
            px, py = pos if pos else (spec.px, spec.py)
            plan.sig_rect = G.expand_rect(
                G.normal_visual_rect(w0_pt, h0_pt, pW, pH, px, py), 2.0)
            plan.sig_box_bl = G.unrotated_topleft_to_pdf_bottomleft(
                G.visual_to_unrotated(plan.sig_rect, rot, uw, uh), uh)
            plan.sig_page_index = sig_page - 1
            plan.sig_ccw = rot
        elif sig_on:
            plan.sig_page_index = n - 1   # 不可见签名：末页（C# numberOfPages）
    if spec.cert_mode.value != 0 and plan.sig_rect is None:
        plan.sig_page_index = n - 1
    return plan


def apply_plan(doc: pymupdf.Document, spec: StampSpec, assets, plan: StampPlan) -> int:
    from pdfqfz.core.imageops import rotate
    from pdfqfz.model.spec import RotCrop
    count = 0
    W_px = assets.full.width
    if plan.seam:
        seam_pages = plan.seam_pages()
        idx = 0
        for group in P.seam_groups(len(seam_pages), spec.max_strips):
            widths = tuple(P.strip_widths(W_px, group))
            strip_imgs = assets.strip_images(widths, spec.edge)
            for i in range(group):
                page_no, vrect = plan.seam[idx + i]
                insert_visual(doc[page_no - 1], strip_imgs[i], vrect)
                count += 1
            idx += group
    for page_no, vrect, angle in plan.normal:
        img = assets.full
        if angle:
            img, _ = rotate(img, angle, RotCrop.EXPAND)
        insert_visual(doc[page_no - 1], img, vrect)
        count += 1
    return count


def rasterize_merge(path: Path, dpi: int = 300) -> None:
    src = open_doc(path)
    out = pymupdf.open()
    for page in src:
        pix = page.get_pixmap(dpi=dpi)
        np = out.new_page(width=pix.width * 72 / dpi, height=pix.height * 72 / dpi)
        np.insert_image(pymupdf.Rect(0, 0, np.rect.width, np.rect.height),
                        pixmap=pix, keep_proportion=False)
    src.close()
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False, dir=str(path.parent)) as tf:
        tmp = Path(tf.name)
    out.save(str(tmp), garbage=3, deflate=True)
    out.close()
    tmp.replace(path)


def encrypt_copy(src: Path, dst: Path, password: str) -> None:
    doc = pymupdf.open(str(src))
    if doc.needs_pass:
        raise DocPasswordError(str(src))
    perm = pymupdf.PDF_PERM_PRINT | pymupdf.PDF_PERM_PRINT_HQ
    doc.save(str(dst), encryption=pymupdf.PDF_ENCRYPT_AES_256,
             owner_pw=password, user_pw=password, permissions=perm,
             garbage=3, deflate=True)
    doc.close()


def save_doc(doc: pymupdf.Document, out: Path) -> None:
    # encryption=KEEP(0)：加密 PDF 盖章后保持原加密（save 默认值 1 会丢加密）
    doc.save(str(out), garbage=3, deflate=True, encryption=pymupdf.PDF_ENCRYPT_KEEP)
