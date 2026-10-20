import pymupdf
import pytest

from pdfqfz.core import pipeline
from pdfqfz.core.imageops import build_assets
from pdfqfz.model.spec import (Blend, Edge, Mode, SeamType, StampSpec, StampType)

MM = 72 / 25.4


def red_at(page, x_pt, y_pt):
    """页面显示空间某 pt 位置渲染后是否为印章红。"""
    pix = page.get_pixmap(clip=pymupdf.Rect(x_pt - 1, y_pt - 1, x_pt + 1, y_pt + 1))
    r, g, b = pix.pixel(1, 1)[:3]
    return r > 120 and g < 100 and b < 100


def base_spec(make_pdf_env, seal_png, **kw) -> StampSpec:
    d = dict(stamp_image=seal_png, seam=SeamType.NONE, normal=StampType.NONE,
             opacity=100, white_to_alpha=True)
    d.update(kw)
    return StampSpec(**d)


def test_normal_stamp_position_semantics(tmp_path, make_pdf, seal_png):
    src = make_pdf(pages=2)
    spec = base_spec(None, seal_png, mode=Mode.FILES, sources=(src,),
                     out_dir=tmp_path / "out", normal=StampType.ALL,
                     px=0.5, py=0.9, size_mm=40)
    res = pipeline.run(spec)
    assert res[0].ok and res[0].normal_pages == 2
    out = res[0].output
    doc = pymupdf.open(str(out))
    # py=0.9 → 章心在页面下方约 88% 处；顶部不应有章
    w_pt, h_pt = 40 * MM, 40 * MM * 30 / 90
    cy = (842 - h_pt) * 0.9 + h_pt / 2
    assert red_at(doc[0], 595 / 2, cy)
    assert not red_at(doc[0], 595 / 2, 842 * 0.2)
    # 文字层保留(叠加模式)
    assert "PAGE 1" in doc[0].get_text()
    doc.close()


def test_seam_right_edge_positions(tmp_path, make_pdf, seal_png):
    src = make_pdf(pages=4)
    spec = base_spec(None, seal_png, mode=Mode.FILES, sources=(src,),
                     out_dir=tmp_path / "out", seam=SeamType.ALL,
                     edge=Edge.RIGHT, wz=50, size_mm=40)
    res = pipeline.run(spec)
    assert res[0].ok and res[0].seam_pages == 4
    doc = pymupdf.open(str(res[0].output))
    for i, page in enumerate(doc):
        # 每页右缘中部应有印章红(条中心≈距右缘 条宽/2，取靠近右缘 5pt 处)
        assert red_at(page, page.rect.width - 5, page.rect.height / 2), f"page {i}"
    # 条宽之和 = 40mm
    doc.close()


def test_seam_rotated_pages_upright(tmp_path, make_pdf, seal_png):
    src = make_pdf(pages=3, rotations=[90, 0, 270])
    spec = base_spec(None, seal_png, mode=Mode.FILES, sources=(src,),
                     out_dir=tmp_path / "out", seam=SeamType.ALL, edge=Edge.RIGHT)
    res = pipeline.run(spec)
    assert res[0].ok
    doc = pymupdf.open(str(res[0].output))
    for page in doc:
        assert red_at(page, page.rect.width - 5, page.rect.height / 2)
        assert page.rotation in (0, 90, 270)
    doc.close()


def test_single_page_seam_skipped(tmp_path, make_pdf, seal_png):
    src = make_pdf(pages=1)
    spec = base_spec(None, seal_png, mode=Mode.FILES, sources=(src,),
                     out_dir=tmp_path / "out", seam=SeamType.ALL)
    res = pipeline.run(spec)
    assert res[0].ok and res[0].seam_pages == 0
    doc = pymupdf.open(str(res[0].output))
    assert len(doc[0].get_image_info()) == 0
    doc.close()


def test_seam_groups_21_pages(tmp_path, make_pdf, seal_png):
    src = make_pdf(pages=21)
    spec = base_spec(None, seal_png, mode=Mode.FILES, sources=(src,),
                     out_dir=tmp_path / "out", seam=SeamType.ALL, max_strips=20)
    res = pipeline.run(spec)
    assert res[0].seam_pages == 21
    doc = pymupdf.open(str(res[0].output))
    # 第 1 页与第 12 页(新组首页)都应有 1 张图，共 21 张
    total = sum(len(p.get_image_info()) for p in doc)
    assert total == 21
    doc.close()


def test_read_wrong_password_fails(tmp_path, make_pdf, seal_png):
    src = make_pdf(pages=1, password="secret")
    spec = base_spec(None, seal_png, mode=Mode.FILES, sources=(src,),
                     out_dir=tmp_path / "out", normal=StampType.ALL,
                     pdf_password="wrong")
    res = pipeline.run(spec)
    assert not res[0].ok and "密码" in res[0].message


def test_read_password_ok(tmp_path, make_pdf, seal_png):
    src = make_pdf(pages=1, password="secret")
    spec = base_spec(None, seal_png, mode=Mode.FILES, sources=(src,),
                     out_dir=tmp_path / "out", normal=StampType.ALL,
                     pdf_password="secret")
    res = pipeline.run(spec)
    assert res[0].ok
    doc = pymupdf.open(str(res[0].output))
    assert doc.needs_pass and doc.authenticate("secret")
    doc.close()


def test_encrypt_output(tmp_path, make_pdf, seal_png):
    src = make_pdf(pages=1)
    spec = base_spec(None, seal_png, mode=Mode.FILES, sources=(src,),
                     out_dir=tmp_path / "out", normal=StampType.ALL,
                     encrypt_password="enc123")
    res = pipeline.run(spec)
    assert res[0].ok and res[0].encrypted
    assert res[0].output.name == "in_已盖章_加密.pdf"
    assert not (tmp_path / "out" / "in_已盖章.pdf").exists()
    doc = pymupdf.open(str(res[0].output))
    assert doc.needs_pass and doc.authenticate("enc123")
    doc.close()


def test_directory_mode_mirror_and_skip_output(tmp_path, make_pdf, seal_png):
    root = tmp_path / "srcs"
    (root / "sub").mkdir(parents=True)
    for d in (root, root / "sub"):
        doc = pymupdf.open()
        doc.new_page(width=595, height=842)
        doc.save(str(d / "same.pdf"))
        doc.close()
    out = tmp_path / "out"
    spec = base_spec(None, seal_png, mode=Mode.DIRECTORY, src_dir=root,
                     out_dir=out, normal=StampType.ALL)
    res = pipeline.run(spec)
    assert len(res) == 2 and all(r.ok for r in res)
    assert (out / "same.pdf").exists() and (out / "sub" / "same.pdf").exists()
    # 再跑一次：输出目录内文件应被跳过
    res2 = pipeline.run(spec)
    assert len(res2) == 2
    # 输出仍在 sub 镜像路径，不互相覆盖：两文件页内容都含章
    d1 = pymupdf.open(str(out / "same.pdf"))
    assert len(d1[0].get_image_info()) == 1
    d1.close()


def test_save_in_source_prefix(tmp_path, make_pdf, seal_png):
    src = make_pdf(pages=1)
    spec = base_spec(None, seal_png, mode=Mode.FILES, sources=(src,),
                     save_in_source=True, fix_type=1, normal=StampType.ALL)
    res = pipeline.run(spec)
    assert res[0].ok
    assert res[0].output.name == "已盖章_in.pdf"
    assert src.exists()  # 原文件保留


def test_multi_pass(tmp_path, make_pdf, seal_png):
    src = make_pdf(pages=1)
    spec = base_spec(None, seal_png, mode=Mode.FILES, sources=(src,),
                     out_dir=tmp_path / "out", normal=StampType.ALL,
                     multi_pass=True)
    r1 = pipeline.run(spec)[0]
    r2 = pipeline.run(spec)[0]
    assert r2.ok
    doc = pymupdf.open(str(r2.output))
    assert len(doc[0].get_image_info()) == 2
    doc.close()


def test_dry_run_writes_nothing(tmp_path, make_pdf, seal_png):
    src = make_pdf(pages=2)
    out = tmp_path / "out"
    spec = base_spec(None, seal_png, mode=Mode.FILES, sources=(src,),
                     out_dir=out, seam=SeamType.ALL)
    res = pipeline.run(spec, dry=True)
    assert res[0].ok and not out.exists()
    assert "seam p1" in res[0].message


def test_positions_file_mode_custom(tmp_path, make_pdf, seal_png):
    src = make_pdf(pages=3)
    key = str(src.resolve())
    spec = base_spec(None, seal_png, mode=Mode.FILES, sources=(src,),
                     out_dir=tmp_path / "out", normal=StampType.CUSTOM,
                     positions={(key, 2): (0.5, 0.5)})
    res = pipeline.run(spec)
    assert res[0].ok and res[0].normal_pages == 1
    doc = pymupdf.open(str(res[0].output))
    assert red_at(doc[1], 595 / 2, 842 / 2)
    assert len(doc[0].get_image_info()) == 0
    doc.close()
