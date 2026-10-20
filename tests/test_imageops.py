from PIL import Image

from pdfqfz.core import imageops as I
from pdfqfz.core.geometry import scale_px, sfbl_percent
from pdfqfz.model.spec import Edge, RotCrop, StampSpec
from pathlib import Path


def px(img, x, y):
    return img.getpixel((x, y))


def test_white_to_transparent_threshold():
    img = Image.new("RGBA", (3, 1), (0, 0, 0, 0))
    data = [(250, 250, 250, 255), (200, 240, 240, 255), (236, 250, 250, 255)]
    img.putdata(data)
    out = I.white_to_transparent(img, 20)  # threshold=235
    assert px(out, 0, 0)[3] == 0      # 全>235 → 透明
    assert px(out, 1, 0)[3] == 255    # 200 不大于 235 → 保留
    assert px(out, 2, 0)[3] == 0      # 236>235 全满足
    assert px(out, 0, 0)[:3] == (250, 250, 250)  # 不改颜色


def test_white_to_transparent_respects_existing_alpha():
    img = Image.new("RGBA", (1, 1), (250, 250, 250, 128))
    out = I.white_to_transparent(img, 20)
    assert px(out, 0, 0)[3] == 0


def test_apply_opacity_override_semantics():
    img = Image.new("RGBA", (2, 1))
    img.putdata([(10, 20, 30, 200), (10, 20, 30, 0)])
    out = I.apply_opacity(img, 60)
    assert px(out, 0, 0)[3] == 60 * 255 // 100 == 153
    assert px(out, 1, 0)[3] == 0  # 原透明保持


def test_rotate_90_cw_transpose():
    img = Image.new("RGBA", (10, 4), (255, 0, 0, 255))
    out, xzbl = I.rotate(img, 90, RotCrop.EXPAND)
    assert out.size == (4, 10)
    assert xzbl == 4 / 10


def test_rotate_direction_matches_gdi_plus_semantics():
    # 左上角放标记，顺时针 90° 后应到右上角
    img = Image.new("RGBA", (10, 6), (0, 0, 0, 0))
    img.putpixel((0, 0), (255, 0, 0, 255))
    out, _ = I.rotate(img, 90, RotCrop.EXPAND)
    assert px(out, out.width - 1, 0)[:3] == (255, 0, 0)
    out2, _ = I.rotate(img, -90, RotCrop.EXPAND)
    assert px(out2, 0, out2.height - 1)[:3] == (255, 0, 0)


def test_rotate_crop_keeps_width_xzbl_1():
    img = Image.new("RGBA", (20, 10), (0, 0, 0, 255))
    out, xzbl = I.rotate(img, 45, RotCrop.CROP)
    assert out.width == 20
    assert xzbl == 1.0
    out2, xzbl2 = I.rotate(img, 45, RotCrop.EXPAND)
    assert out2.width > 20 and xzbl2 == out2.width / 20


def test_slice_strips_cover_full_width():
    img = Image.new("RGBA", (23, 5), (0, 0, 0, 0))
    strips = I.slice_strips(img, [7, 7, 9])
    assert [s.width for s in strips] == [7, 7, 9]
    # 第 1 条(左)像素与第 3 条(右)不重叠且拼满
    assert sum(s.width for s in strips) == 23


def test_strip_rotation_for_top_edge():
    img = Image.new("RGBA", (9, 3), (0, 0, 0, 0))
    img.putpixel((0, 0), (255, 0, 0, 255))
    strip = I.rotate_strip_90_cw(img)
    assert strip.size == (3, 9)
    assert px(strip, 2, 0)[:3] == (255, 0, 0)  # 顺时针 90°: 左上→右上


def test_build_assets_pipeline_order(tmp_path: Path):
    img = Image.new("RGBA", (60, 30), (250, 250, 250, 255))
    img.putpixel((5, 5), (200, 0, 0, 255))  # 红章一点(不被白转透明)
    p = tmp_path / "seal.png"
    img.save(p)
    spec = StampSpec(stamp_image=p, opacity=50, tolerance=20, rotation=0)
    assets = I.build_assets(spec)
    assert assets.size_px == (60, 30)
    assert assets.xzbl == 1.0
    a_counts = assets.full.tobytes()[3::4]      # alpha 通道
    assert set(a_counts) <= {0, 127}            # 白底→0，红点→覆盖为 127
    assert a_counts.count(127) == 1


def test_strip_sizes_and_cache(tmp_path: Path):
    img = Image.new("RGBA", (30, 10), (10, 20, 30, 255))
    p = tmp_path / "s.png"
    img.save(p)
    assets = I.build_assets(StampSpec(stamp_image=p, opacity=100,
                                     white_to_alpha=False))
    sizes_r = assets.strip_sizes((10, 10, 10), Edge.RIGHT)
    assert sizes_r == [(10, 10), (10, 10), (10, 10)]
    sizes_t = assets.strip_sizes((10, 10, 10), Edge.TOP)
    assert sizes_t == [(10, 10)] * 3  # 正方形条旋转 90 后尺寸不变
    # 缩放一致性：全部条宽(pt)之和 == size mm
    widths = tuple(s[0] for s in assets.strip_sizes((12, 9, 9), Edge.RIGHT))
    s = sfbl_percent(40, assets.xzbl, 30)
    total_pt = sum(scale_px(w, s) for w in widths)
    assert abs(total_pt - 40 * 72 / 25.4) < 1e-6
