"""纯几何：mm↔pt、单重缩放、视觉空间 rect、旋转空间换算。

约定：所有 *_visual 矩形处于"显示空间"（页面旋转后的观感，左上原点，y 向下，单位 pt），
对应 C# 中 iText 已自动处理旋转的坐标语义；unrotated 空间为 MuPDF 的未旋转左上原点。
"""

from __future__ import annotations

from pdfqfz.model.spec import Edge

Rect = tuple[float, float, float, float]  # x0, y0, x1, y1 (left, top, right, bottom)

PT_PER_MM = 72 / 25.4


def mm_to_pt(mm: float) -> float:
    return mm * PT_PER_MM


def sfbl_percent(size_mm: float, xzbl: float, full_stamp_px_w: int) -> float:
    """缩放百分比：整枚印章(全部竖条之和)宽 = size_mm·xzbl。单重缩放，修正 C# 双重缩放 bug。"""
    if full_stamp_px_w <= 0:
        return 0.0
    return 100.0 * size_mm * xzbl * 72.0 / (25.4 * full_stamp_px_w)


def scale_px(px: float, sfbl: float) -> float:
    return px * sfbl / 100.0


def seam_visual_rect(strip_w_pt: float, strip_h_pt: float,
                     page_w_pt: float, page_h_pt: float,
                     edge: Edge, wz: int) -> Rect:
    """骑缝章单条在显示空间的矩形（左上原点）。wz: 0-100。

    左右缘：贴边，顶边距页顶 wz%（wz=0 顶部,50 居中）；
    上下缘：贴边，左边距页左 wz%。
    """
    free_h = page_h_pt - strip_h_pt
    free_w = page_w_pt - strip_w_pt
    if edge == Edge.RIGHT:
        return (page_w_pt - strip_w_pt, free_h * wz / 100.0, page_w_pt, free_h * wz / 100.0 + strip_h_pt)
    if edge == Edge.LEFT:
        return (0.0, free_h * wz / 100.0, strip_w_pt, free_h * wz / 100.0 + strip_h_pt)
    if edge == Edge.BOTTOM:
        return (free_w * wz / 100.0, page_h_pt - strip_h_pt, free_w * wz / 100.0 + strip_w_pt, page_h_pt)
    # TOP
    return (free_w * wz / 100.0, 0.0, free_w * wz / 100.0 + strip_w_pt, strip_h_pt)


def normal_visual_rect(stamp_w_pt: float, stamp_h_pt: float,
                       page_w_pt: float, page_h_pt: float,
                       px: float, py: float) -> Rect:
    """普通章显示空间矩形。px/py 为自由区(页-章)分数，与 C# textPx/textPy 语义一致。"""
    free_w = page_w_pt - stamp_w_pt
    free_h = page_h_pt - stamp_h_pt
    return (free_w * px, free_h * py, free_w * px + stamp_w_pt, free_h * py + stamp_h_pt)


def rect_center(rect: Rect) -> tuple[float, float]:
    return ((rect[0] + rect[2]) / 2.0, (rect[1] + rect[3]) / 2.0)


def rect_with_size_centered(rect: Rect, new_w: float, new_h: float) -> Rect:
    """围绕中心换尺寸（用于像素层旋转导致外接框变化时保持章心不动）。"""
    cx, cy = rect_center(rect)
    return (cx - new_w / 2.0, cy - new_h / 2.0, cx + new_w / 2.0, cy + new_h / 2.0)


def visual_to_unrotated(rect: Rect, rotation: int,
                        unrot_w_pt: float, unrot_h_pt: float) -> Rect:
    """显示空间(左上) rect → 未旋转页面(左上) rect。rotation ∈ {0,90,180,270}(顺时针)。"""
    r = rotation % 360
    x0, y0, x1, y1 = rect
    if r == 0:
        return rect
    if r == 90:
        # 视觉宽 = 未旋转高；ux=vy, uy=vw-vx
        return (y0, unrot_h_pt - x1, y1, unrot_h_pt - x0)
    if r == 180:
        return (unrot_w_pt - x1, unrot_h_pt - y1, unrot_w_pt - x0, unrot_h_pt - y0)
    # 270: ux=vh... ux=unrot_w-vy, uy=vx
    return (unrot_w_pt - y1, x0, unrot_w_pt - y0, x1)


def unrotated_topleft_to_pdf_bottomleft(rect: Rect, unrot_h_pt: float) -> Rect:
    """未旋转左上原点 → PDF 左下原点（pyHanko 签名域坐标）。x 不变，y 翻转。"""
    x0, y0, x1, y1 = rect
    return (x0, unrot_h_pt - y1, x1, unrot_h_pt - y0)


def expand_rect(rect: Rect, delta_pt: float) -> Rect:
    return (rect[0] - delta_pt, rect[1] - delta_pt, rect[2] + delta_pt, rect[3] + delta_pt)
