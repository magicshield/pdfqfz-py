import pytest

from pdfqfz.core import pipeline, signing
from pdfqfz.model.spec import (CertMode, Mode, SeamType, StampSpec, StampType)


@pytest.fixture(scope="module")
def pfx(tmp_path_factory):
    p = tmp_path_factory.mktemp("cert") / "t.pfx"
    signing.ensure_self_signed_pfx(p, "测试签名人", "pw123")
    return p


def test_ensure_pfx_idempotent(tmp_path):
    p = tmp_path / "idem.pfx"
    signing.ensure_self_signed_pfx(p, "同名", "pw")
    before = p.read_bytes()
    signing.ensure_self_signed_pfx(p, "同名", "pw")
    assert p.read_bytes() == before


def test_load_signer(pfx):
    signer = signing.load_signer(pfx.read_bytes(), "pw123")
    assert signer.signing_cert is not None


def _sign_spec(src, out_dir, pfx, **kw):
    d = dict(stamp_image=kw.pop("seal"), mode=Mode.FILES, sources=(src,),
             out_dir=out_dir, opacity=100,
             cert_mode=CertMode.CUSTOM_PFX, pfx_path=pfx, pfx_password="pw123")
    d.update(kw)
    return StampSpec(**d)


def test_sign_with_appearance(tmp_path, make_pdf, seal_png, pfx):
    src = make_pdf(pages=2)
    spec = _sign_spec(src, tmp_path / "out", pfx, seal=seal_png,
                      normal=StampType.ALL)
    res = pipeline.run(spec)
    assert res[0].ok, res[0].message
    sigs = signing.verify_pdf(res[0].output)
    assert len(sigs) == 1
    assert sigs[0]["integrity_ok"] and sigs[0]["digest_ok"]
    assert "测试签名人" in sigs[0]["signer"]


def test_invisible_sign(tmp_path, make_pdf, seal_png, pfx):
    src = make_pdf(pages=1)
    spec = _sign_spec(src, tmp_path / "out", pfx, seal=seal_png,
                      normal=StampType.NONE, seam=SeamType.NONE)
    res = pipeline.run(spec)
    assert res[0].ok, res[0].message
    sigs = signing.verify_pdf(res[0].output)
    assert len(sigs) == 1 and sigs[0]["integrity_ok"]


def test_multi_pass_keeps_first_signature(tmp_path, make_pdf, seal_png, pfx):
    src = make_pdf(pages=1)
    spec = _sign_spec(src, tmp_path / "out", pfx, seal=seal_png,
                      normal=StampType.ALL, multi_pass=False)
    r1 = pipeline.run(spec)
    assert r1[0].ok
    # 第二次直接对已签名文件全量重写会破坏签名（与 C# 非签名 stamper 行为一致），
    # 因此多章连盖+签名场景应重新签名：两枚签名需两次增量。
    spec2 = _sign_spec(src, tmp_path / "out", pfx, seal=seal_png,
                       normal=StampType.NO_LAST, multi_pass=True)
    r2 = pipeline.run(spec2)
    assert r2[0].ok, r2[0].message
    sigs = signing.verify_pdf(r2[0].output)
    assert len(sigs) >= 1


def test_tamper_detected(tmp_path, make_pdf, seal_png, pfx):
    src = make_pdf(pages=1)
    spec = _sign_spec(src, tmp_path / "out", pfx, seal=seal_png,
                      normal=StampType.ALL)
    res = pipeline.run(spec)
    data = bytearray(res[0].output.read_bytes())
    data[100] ^= 0xFF  # 头部之后的已签名覆盖区，破坏摘要但不毁文件结构
    tampered = tmp_path / "tampered.pdf"
    tampered.write_bytes(bytes(data))
    sigs = signing.verify_pdf(tampered)
    assert len(sigs) == 1
    assert not (sigs[0]["integrity_ok"] and sigs[0]["digest_ok"])


def test_ensure_pfx_regen_on_cn_change(tmp_path):
    p = tmp_path / "c.pfx"
    signing.ensure_self_signed_pfx(p, "甲", "pw")
    b1 = p.read_bytes()
    signing.ensure_self_signed_pfx(p, "甲", "pw")
    assert p.read_bytes() == b1                      # 同名复用
    signing.ensure_self_signed_pfx(p, "乙", "pw")
    assert p.read_bytes() != b1                      # 换签名人重签
    signer = signing.load_signer(p.read_bytes(), "pw")
    assert "乙" in signer.signing_cert.subject.human_friendly


def test_metadata_customization(tmp_path, make_pdf, seal_png):
    src = make_pdf(pages=1)
    spec = StampSpec(stamp_image=seal_png, mode=Mode.FILES, sources=(src,),
                     out_dir=tmp_path / "out", opacity=100,
                     meta_producer="我的单位 OA", meta_creator="合同系统")
    res = pipeline.run(spec)
    assert res[0].ok
    import pymupdf
    doc = pymupdf.open(str(res[0].output))
    assert doc.metadata["producer"] == "我的单位 OA"
    assert doc.metadata["creator"] == "合同系统"
    doc.close()


def test_sign_replaces_pyhanko_vendor(tmp_path, make_pdf, seal_png, pfx):
    src = make_pdf(pages=1)
    spec = _sign_spec(src, tmp_path / "out", pfx, seal=seal_png,
                      normal=StampType.ALL, meta_producer="ACME 印章")
    res = pipeline.run(spec)
    assert res[0].ok, res[0].message
    import pymupdf
    doc = pymupdf.open(str(res[0].output))
    assert "pyHanko" not in (doc.metadata["producer"] or "")
    assert "ACME 印章" in doc.metadata["producer"]
    doc.close()


def test_signature_appearance_transparent(tmp_path, make_pdf, pfx):
    """签名页外观必须保留 alpha。回归：旧代码 convert(RGB) 丢弃 alpha，
    而真实透明底印章 PNG 的隐藏像素常为黑色 → 黑底。"""
    from PIL import Image
    seal = tmp_path / "blackhidden.png"
    img = Image.new("RGBA", (90, 30), (0, 0, 0, 0))   # 透明区 RGB=黑（常见导出形态）
    for x in range(2, 88):
        for y in range(2, 28):
            img.putpixel((x, y), (200, 30, 30, 255))
    img.save(seal)
    src = make_pdf(pages=2)
    spec = _sign_spec(src, tmp_path / "out", pfx, seal=seal,
                      normal=StampType.ALL, white_to_alpha=False)
    res = pipeline.run(spec)
    assert res[0].ok, res[0].message
    import pymupdf
    doc = pymupdf.open(str(res[0].output))
    page = doc[doc.page_count - 1]          # StampType.ALL → 签名代表页=末页
    pix = page.get_pixmap(dpi=72)
    data = pix.samples
    # 只检测印章区域(默认 px/py 0.77/0.88, 40mm 章)，避开页面示例文字
    x0, x1 = int(595 * 0.7), int(595 * 0.95)
    y0, y1 = int(842 * 0.78), int(842 * 0.95)
    black = red = 0
    for yy in range(y0, y1):
        for xx in range(x0, x1):
            i = (yy * pix.width + xx) * 3
            if data[i] < 40 and data[i + 1] < 40 and data[i + 2] < 40:
                black += 1
            elif data[i] > 120 and data[i + 1] < 100 and data[i + 2] < 100:
                red += 1
    assert black == 0 and red > 500
    doc.close()


def test_sign_encrypt_conflict(tmp_path, make_pdf, seal_png, pfx):
    src = make_pdf(pages=1)
    spec = _sign_spec(src, tmp_path / "out", pfx, seal=seal_png,
                      normal=StampType.ALL, encrypt_password="x")
    res = pipeline.run(spec)
    assert not res[0].ok and "加密" in res[0].message
