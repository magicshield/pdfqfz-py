from pathlib import Path

import pymupdf
import pytest
from PIL import Image


def _make_pdf(path: Path, pages: int = 3, size=(595, 842),
              rotations: list[int] | None = None,
              sizes: list[tuple[int, int]] | None = None,
              password: str | None = None) -> Path:
    doc = pymupdf.open()
    for i in range(pages):
        w, h = (sizes[i] if sizes else size)
        pg = doc.new_page(width=w, height=h)
        pg.insert_text((50, 80), f"PAGE {i + 1}", fontsize=28)
        if rotations:
            pg.set_rotation(rotations[i])
    kw = {}
    if password:
        kw = dict(encryption=pymupdf.PDF_ENCRYPT_AES_256,
                  owner_pw=password, user_pw=password)
    doc.save(str(path), **kw)
    doc.close()
    return path


@pytest.fixture
def make_pdf(tmp_path):
    def factory(name="in.pdf", **kw):
        p = tmp_path / name
        return _make_pdf(p, **kw)
    return factory


@pytest.fixture
def seal_png(tmp_path):
    """90x30 红色印章(白底)，用于白转透明与位置断言。"""
    p = tmp_path / "seal.png"
    img = Image.new("RGBA", (90, 30), (255, 255, 255, 255))
    for x in range(2, 88):
        for y in range(2, 28):
            img.putpixel((x, y), (200, 30, 30, 255))
    img.save(p)
    return p
