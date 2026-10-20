import math

import pytest

from pdfqfz.core import geometry as G
from pdfqfz.model.spec import Edge


def approx(t):
    return [pytest.approx(v, abs=1e-9) for v in t]


def test_mm_to_pt():
    assert G.mm_to_pt(40) == pytest.approx(40 * 72 / 25.4)


def test_sfbl_single_scaling():
    # size=40mm, xzbl=1, W=600px → sfbl=100*40*72/(25.4*600)
    s = G.sfbl_percent(40, 1.0, 600)
    assert s == pytest.approx(100 * 40 * 72 / (25.4 * 600))
    # 单条宽度之和(pt) == size mm（单重缩放的核心断言）
    widths_pt = [G.scale_px(w, s) for w in (200, 200, 200)]
    assert sum(widths_pt) == pytest.approx(40 * 72 / 25.4)


def test_seam_rect_right_edge_wz50():
    r = G.seam_visual_rect(20, 100, 595, 842, Edge.RIGHT, 50)
    assert list(r) == approx((575, (842 - 100) * 0.5, 595, (842 - 100) * 0.5 + 100))


def test_seam_rect_matches_csharp_formula():
    # C# 右缘: xPos=pW-imgW; yPos_bl=(pH-imgH)*(100-wz)/100 → 视觉 top = pH - (yPos+imgH) = (pH-imgH)*wz/100
    for wz in (0, 30, 50, 100):
        r = G.seam_visual_rect(30, 120, 612, 792, Edge.RIGHT, wz)
        assert r[1] == pytest.approx((792 - 120) * wz / 100)
        assert r[0] == pytest.approx(612 - 30)
    # 下缘: x=(pW-imgW)*wz/100, 视觉 top = pH - imgH
    r = G.seam_visual_rect(300, 40, 612, 792, Edge.BOTTOM, 25)
    assert r[0] == pytest.approx((612 - 300) * 0.25)
    assert r[1] == pytest.approx(792 - 40)
    # 上缘: top=0, 左=同下缘
    r = G.seam_visual_rect(300, 40, 612, 792, Edge.TOP, 25)
    assert r[1] == pytest.approx(0)
    # 左缘: x=0
    r = G.seam_visual_rect(30, 120, 612, 792, Edge.LEFT, 40)
    assert r[0] == pytest.approx(0)
    assert r[1] == pytest.approx((792 - 120) * 0.4)


def test_normal_rect_click_equals_position():
    # pyH=40mm 章 200x140pt 于 595x842 页, px/py 分数
    r = G.normal_visual_rect(200, 140, 595, 842, 0.77, 0.88)
    assert r[0] == pytest.approx((595 - 200) * 0.77)
    assert r[1] == pytest.approx((842 - 140) * 0.88)


def test_rect_center_helpers():
    r = G.rect_with_size_centered((10, 10, 30, 50), 40, 20)
    c = G.rect_center(r)
    assert c == pytest.approx((20.0, 30.0))
    assert r == pytest.approx((0.0, 20.0, 40.0, 40.0))


def test_expand_rect():
    assert G.expand_rect((10, 10, 30, 50), 2) == (8, 8, 32, 52)


# --- 空间换算：纯函数 vs PyMuPDF derotation_matrix 交叉验证 ---

@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_visual_to_unrotated_matches_fitz(rotation):
    pymupdf = pytest.importorskip("pymupdf")
    uw, uh = 595, 842
    doc = pymupdf.open()
    page = doc.new_page(width=uw, height=uh)
    page.set_rotation(rotation)
    # 任一视觉空间矩形
    vrect = pymupdf.Rect(100, 150, 260, 400)
    expected = vrect * page.derotation_matrix
    got = G.visual_to_unrotated(tuple(vrect), rotation, uw, uh)
    # 变换后是轴对齐矩形，bbox 一致即可
    assert max(abs(expected.x0 - got[0]), abs(expected.y0 - got[1]),
               abs(expected.x1 - got[2]), abs(expected.y1 - got[3])) < 1e-6
    doc.close()


def test_unrotated_to_pdf_bottomleft():
    # 未旋转左上 (0,0,W,H) → PDF 左下 (0,0,W,H)
    assert G.unrotated_topleft_to_pdf_bottomleft((0, 0, 100, 200), 200) == (0, 0, 100, 200)
    # 顶部条 y∈[0,10] → PDF 底部 y∈[H-10,H]
    assert G.unrotated_topleft_to_pdf_bottomleft((5, 0, 55, 10), 200) == (5, 190, 55, 200)
