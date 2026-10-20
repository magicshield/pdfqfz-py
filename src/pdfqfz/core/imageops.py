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
    """返回 (旋转后图, xzbl=旋转后宽/旋转前宽)。

    CROP(切边): 输出保持原宽，高度按外接框比例压缩（等价 C# original=true）；
    EXPAND: 输出完整外接框（等价 C# original=false，骑缝上下缘内部条带用）。
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
    if crop == _CROP:
        new_h = max(1, round(bh * w / bw))
        out = out.resize((w, new_h), Image.BILINEAR)
        return out, 1.0
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
    xzbl: float
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
    if spec.white_to_alpha:
        img = white_to_transparent(img, spec.tolerance)
    if spec.opacity < 100:
        img = apply_opacity(img, spec.opacity)
    if spec.rotation % 360 != 0:
        img, xzbl = rotate(img, spec.rotation, spec.crop)
    else:
        xzbl = 1.0
    return StampAssets(full=img, xzbl=xzbl, full_png=to_png(img))
