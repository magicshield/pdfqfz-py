import pymupdf

from pdfqfz.core import pipeline
from pdfqfz.model.spec import Blend, Mode, SeamType, StampSpec, StampType


def test_merge_rasterizes_pages(tmp_path, make_pdf, seal_png):
    src = make_pdf(pages=2)
    spec = StampSpec(stamp_image=seal_png, mode=Mode.FILES, sources=(src,),
                     out_dir=tmp_path / "out", normal=StampType.ALL,
                     seam=SeamType.NONE, opacity=100, blend=Blend.MERGE)
    res = pipeline.run(spec)
    assert res[0].ok
    doc = pymupdf.open(str(res[0].output))
    assert doc.page_count == 2
    pg = doc[0]
    # 300dpi 光栅化重建：页尺寸(pt) = 像素×72/300 ≈ 原尺寸
    assert abs(pg.rect.width - 595) < 3
    # 文字层被压扁
    assert pg.get_text().strip() == ""
    # 整页就是一张图
    assert len(pg.get_image_info()) == 1
    doc.close()


def test_merge_then_no_seam_loss(tmp_path, make_pdf, seal_png):
    src = make_pdf(pages=2)
    spec = StampSpec(stamp_image=seal_png, mode=Mode.FILES, sources=(src,),
                     out_dir=tmp_path / "out", seam=SeamType.ALL,
                     opacity=100, white_to_alpha=False, blend=Blend.MERGE,
                     merge_dpi=150)
    res = pipeline.run(spec)
    assert res[0].ok and res[0].seam_pages == 2
    doc = pymupdf.open(str(res[0].output))
    pix = doc[0].get_pixmap(dpi=72)
    # 右缘中部应仍含章色(光栅化后成为页面像素的一部分)
    x = int(pix.width - 5)
    y = pix.height // 2
    r, g, b = pix.pixel(x, y)[:3]
    assert r > 120 and g < 120
    doc.close()
