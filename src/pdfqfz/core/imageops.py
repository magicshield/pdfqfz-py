"""像素管线（Pillow）：白转透明 → 不透明度 → 旋转 → 切条 → PNG。

语义对齐 C#（Form1.cs:668-896, WhiteTransparencyHelper.cs）：
- 白转透明: R,G,B 全部 > (255-tol) 时 alpha=0，仅改 alpha 不改颜色。
- 不透明度: 非零 alpha 直接置为 opacity*255//100（覆盖，非相乘）。
- 旋转: 正角 = 顺时针（GDI+ 视觉语义；PIL 正角为逆时针，内部取反）。
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field

from PIL import Image, ImageChops

from pdfqfz.core.policies import clamp_tolerance
from pdfqfz.model.spec import RotCrop, StampSpec

_CROP = RotCrop.CROP


def load_rgba(path) -> Image.Image:
    img = Image.open(path)
    img.load()
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    return img


def white_to_transparent(img: Image.Image, tolerance: int) -> Image.Image:
    t = 255 - clamp_tolerance(tolerance)
    r, g, b, a = img.split()
    darkest = ImageChops.darker(ImageChops.darker(r, g), b)
    mask = darkest.point(lambda v: 0 if v > t else 255)
    new_a = ImageChops.darker(a, mask)
    return Image.merge("RGBA", (r, g, b, new_a))


def apply_opacity(img: Image.Image, opacity: int) -> Image.Image:
    opacity = max(0, min(100, opacity))
    target = opacity * 255 // 100
    out = img.copy()
    r, g, b, a = out.split()
    new_a = a.point(lambda x: 0 if x == 0 else target)
    out.putalpha(new_a)
    return out


def _bbox_after_rotate(w: int, h: int, angle_cw: int) -> tuple[int, int]:
    from math import ceil, cos, radians, sin
    a = radians(angle_cw % 360)
    nw = ceil(w * abs(cos(a)) + h * abs(sin(a)))
    nh = ceil(w * abs(sin(a)) + h * abs(cos(a)))
    return nw, nh


def rotate(img: Image.Image, angle_cw: int, crop: RotCrop = _CROP
           ) -> tuple[Image.Image, float]:
    """返回 (旋转后图, xzbl=外接框宽/原宽)。

    CROP(切边): 旋转后中心裁剪回原画布尺寸（真正裁角，内容物理尺寸不变）；
    EXPAND: 返回完整外接框画布（内容物理尺寸同样不变，画布变大）。
    印章物理尺寸换算以旋转前的 base_px_w 为准（见 geometry.sfbl_percent）。
    """
    angle = angle_cw % 360
    if angle == 0:
        return img, 1.0
    w, h = img.size
    if angle in (90, 180, 270):  # 无损转置
        mode = {90: Image.ROTATE_270, 180: Image.ROTATE_180, 270: Image.ROTATE_90}[angle]
        out = img.transpose(mode)
    else:
        out = img.rotate(-angle, expand=True, resample=Image.BILINEAR,
                         fillcolor=(0, 0, 0, 0))
    bw, bh = out.size
    if crop == _CROP and not (angle in (90, 270) and w != h):
        # 90/270 且非方形时裁剪会裁掉印章主体，退化为完整外接框
        cx, cy = bw / 2, bh / 2
        out = out.crop((int(cx - w / 2), int(cy - h / 2),
                        int(cx + w / 2), int(cy + h / 2)))
    return out, bw / w


def slice_strips(img: Image.Image, widths: list[int]) -> list[Image.Image]:
    """左→右按像素宽切竖条（与 policies.strip_widths 配套）。"""
    strips = []
    x = 0
    W, H = img.size
    for w in widths:
        strips.append(img.crop((x, 0, min(x + w, W), H)))
        x += w
    return strips


def to_png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def rotate_strip_90_cw(img: Image.Image) -> Image.Image:
    """骑缝上/下缘用：单条顺时针转 90°，完整外接框（= C# RotateImg(x,90,false)）。"""
    return img.transpose(Image.ROTATE_270)


@dataclass
class StampAssets:
    full: Image.Image                      # 处理后整章(像素)
    xzbl: float                            # 外接框宽/基准宽（仅信息用）
    base_px_w: int                         # 旋转前印章像素宽（物理尺寸基准）
    full_png: bytes
    _strips: dict = field(default_factory=dict)   # key -> list[Image]

    @property
    def size_px(self) -> tuple[int, int]:
        return self.full.size

    def _strip_images(self, widths: tuple[int, ...], edge) -> list[Image.Image]:
        key = (widths, edge)
        if key not in self._strips:
            strips = slice_strips(self.full, list(widths))
            from pdfqfz.model.spec import Edge
            if edge in (Edge.TOP, Edge.BOTTOM):
                strips = [rotate_strip_90_cw(s) for s in strips]
            self._strips[key] = strips
        return self._strips[key]

    def strip_images(self, widths: tuple[int, ...], edge=None) -> list[Image.Image]:
        return self._strip_images(widths, edge)

    def strip_pngs(self, widths: tuple[int, ...], edge=None) -> list[bytes]:
        return [to_png(s) for s in self._strip_images(widths, edge)]

    def strip_sizes(self, widths: tuple[int, ...], edge=None) -> list[tuple[int, int]]:
        return [s.size for s in self._strip_images(widths, edge)]


def build_assets(spec: StampSpec) -> StampAssets:
    img = load_rgba(spec.stamp_image)
    base_px_w = img.width
    if spec.white_to_alpha:
        img = white_to_transparent(img, spec.tolerance)
    if spec.opacity < 100:
        img = apply_opacity(img, spec.opacity)
    if spec.rotation % 360 != 0:
        img, xzbl = rotate(img, spec.rotation, spec.crop)
    else:
        xzbl = 1.0
    return StampAssets(full=img, xzbl=xzbl, base_px_w=base_px_w, full_png=to_png(img))
