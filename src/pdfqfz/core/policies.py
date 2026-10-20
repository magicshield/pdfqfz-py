"""纯函数策略层：逐条移植 C# PDFQFZ Library/* 与 Form1.cs 的决策逻辑。

不 import fitz/PIL/Qt —— 全部可单测，数值即行为基准。
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Sequence

from pdfqfz.model.spec import SeamType, StampType, Edge

# ---------- SeamStampPolicy.cs ----------

def should_skip_seam_single_page(page_count: int, seam: SeamType) -> bool:
    """单页文件凡是要盖骑缝(ALL/ODD/EVEN/CUSTOM)一律跳过；NONE 不跳过(本来就不盖)。"""
    return page_count == 1 and seam != SeamType.NONE


# ---------- StampRenderPolicy.cs ----------

def should_render_normal_stamp(stamp: StampType) -> bool:
    return stamp != StampType.NONE


# ---------- StampPlacementPolicy.cs ----------

def should_draw_normal_on_page(page: int, excluded_page: int,
                               sig_page: int, sig_on: bool) -> bool:
    if excluded_page != 0 and page == excluded_page:
        return False
    if sig_on and page == sig_page:
        return False
    return True


# ---------- 页选择 (Form1.cs:928-969) ----------

def seam_target_pages(page_count: int, seam: SeamType,
                      custom_pages: Sequence[int] = ()) -> list[int]:
    """返回 1-based 页码列表；单页跳过规则在此生效（返回空表即不盖）。"""
    if should_skip_seam_single_page(page_count, seam):
        return []
    if seam == SeamType.ALL:
        return list(range(1, page_count + 1))
    if seam == SeamType.ODD:
        return list(range(1, page_count + 1, 2))
    if seam == SeamType.EVEN:
        return list(range(2, page_count + 1, 2))
    if seam == SeamType.CUSTOM:
        return sorted(set(custom_pages))
    return []  # NONE


def normal_page_plan(pages: int, stamp: StampType,
                     custom_pages: Sequence[int] = ()) -> tuple[int, int, list[int]]:
    """返回 (excluded_page, sig_page, 要盖的页列表)。

    excluded=0 表示无排除页；sig_page 为数字签名代表页。
    对应 Form1.cs:1070-1106。CUSTOM 且无记录时 sig_page=1(C# 初值)。
    """
    if stamp == StampType.NO_FIRST:
        excluded = 1 if pages > 1 else 0
        sig = pages
        seq = [p for p in range(1, pages + 1) if p != excluded]
    elif stamp == StampType.NO_LAST:
        excluded = pages if pages > 1 else 0
        sig = 1
        seq = [p for p in range(1, pages + 1) if p != excluded]
    elif stamp == StampType.ALL:
        excluded = 0
        sig = pages
        seq = list(range(1, pages + 1))
    elif stamp == StampType.CUSTOM:
        excluded = 0
        cps = sorted(set(custom_pages))
        sig = cps[-1] if cps else 1
        seq = cps
    else:  # NONE
        excluded = 0
        sig = pages
        seq = []
    return excluded, sig, seq


# ---------- 切条与分组 (Form1.cs:864-896, 975-990) ----------

def strip_widths(total_px: int, n: int) -> list[int]:
    """把宽 total_px 的印章切成 n 个竖条的像素宽度，和恰为 total_px。

    第 1 条 = W//3；中间条 = (W - W//3) // n；最后一条吸收余数。
    n==1 时整图不切。与 C# subImages 逐像素等价。
    """
    if n <= 1:
        return [total_px]
    w1 = total_px // 3
    w = (total_px - w1) // n
    widths = [w1] + [w] * (n - 2)
    widths.append(total_px - sum(widths))
    return widths


def seam_groups(n_pages: int, max_strips: int) -> list[int]:
    """页数超过 max_strips 时整章循环再盖的分组：组数 ceil(n/max)，尽量平均。

    修正 C# 整数除法 bug（40页/20 原得 14+13+13 三组，现得 20+20）。
    """
    if n_pages <= 0:
        return []
    max_strips = max(1, max_strips)
    ss = -(-n_pages // max_strips)  # ceil
    base, extra = divmod(n_pages, ss)
    return [base + 1] * extra + [base] * (ss - extra)


# ---------- WhiteTransparencyHelper.cs:55 ----------

def clamp_tolerance(t: int) -> int:
    return max(0, min(50, t))


# ---------- PreviewValueSanitizer.cs ----------

def keep_digits_only(text: str) -> str:
    return "".join(c for c in text or "" if c.isdigit())


def keep_signed_integer(text: str) -> str:
    out: list[str] = []
    for c in text or "":
        if c.isdigit():
            out.append(c)
        elif c == "-" and not out:
            out.append(c)
    return "".join(out)


def clamp_int(text: str, fallback: int, lo: int, hi: int) -> int:
    try:
        value = int(text)
    except (TypeError, ValueError):
        return fallback
    return max(lo, min(hi, value))


# ---------- PreviewStampLayout.cs ----------

def overlay_size(size_mm: float, img_px_w: int, img_px_h: int,
                 preview_w: float, pdf_w: float,
                 fallback: int = 72) -> tuple[int, int]:
    if size_mm <= 0 or img_px_w <= 0 or img_px_h <= 0 or preview_w <= 0 or pdf_w <= 0:
        return (fallback, fallback)
    stamp_w_pt = size_mm * 72 / 25.4
    scale = preview_w / pdf_w
    w = max(1, int(stamp_w_pt * scale))
    h = max(1, int(w * img_px_h / img_px_w))
    return (w, h)


# ---------- PreviewPanelLayout.cs（改进：骑缝章也显示预览） ----------

def should_show_preview(stamp: StampType, seam: SeamType) -> bool:
    return stamp != StampType.NONE or seam != SeamType.NONE


def collapsed_client_width(preview_left: int, margin: int) -> int:
    return max(1, preview_left - margin)


# ---------- 预览显隐与点击定位 (Form1.cs:2447-2482, 1786-1827) ----------

def overlay_visible_for_page(stamp: StampType, seam: SeamType, page: int,
                             pages: int, has_position: bool) -> bool:
    if stamp == StampType.CUSTOM or seam == SeamType.CUSTOM:
        return has_position
    if stamp == StampType.NO_FIRST and page == 1 and pages > 1:
        return False
    if stamp == StampType.NO_LAST and page == pages and pages > 1:
        return False
    return stamp != StampType.NONE or seam != SeamType.NONE


def click_to_position(click: tuple[float, float], view: tuple[float, float],
                      overlay: tuple[int, int]) -> tuple[float, float]:
    """以点击点为章中心反推 (px, py)，4 位小数、钳 [0,1]。自由区分数(非页面分数)。"""
    free_w = max(view[0] - overlay[0], 1.0)
    free_h = max(view[1] - overlay[1], 1.0)
    px = min(max(round((click[0] - overlay[0] / 2) / free_w, 4), 0.0), 1.0)
    py = min(max(round((click[1] - overlay[1] / 2) / free_h, 4), 0.0), 1.0)
    return px, py


# ---------- 随机参数 (Form1.cs:1132-1165) ----------

JITTER_MIN = -2
JITTER_MAX = 2  # random.Next(-2, 3) → 整数 -2..2


def jitter_position(value: float, delta_int: int) -> float:
    """±delta 个百分点，结果须在 (0,1) 开区间，否则不偏移。"""
    candidate = value + 0.01 * delta_int
    if 0.0 < candidate < 1.0:
        return candidate
    return value


def jitter_angle(page: int, sig_page: int, enabled: bool, rng_draw: int) -> int:
    if page == sig_page or not enabled:
        return 0
    return rng_draw


# ---------- 签名/校验小工具 ----------

def signature_rep_page(pages: int, stamp: StampType,
                       custom_pages: Sequence[int] = ()) -> int:
    return normal_page_plan(pages, stamp, custom_pages)[1]


# ---------- CommandLineFileLoader.cs ----------

def collect_existing_pdfs(args: Iterable[str],
                          base_dir: Path | None = None) -> list[Path]:
    out: list[Path] = []
    for arg in args or []:
        if not arg or not arg.strip():
            continue
        p = Path(arg)
        if not p.is_absolute() and base_dir is not None:
            p = base_dir / p
        p = p.resolve()
        if p.is_file() and p.suffix.lower() == ".pdf":
            out.append(p)
    return out
