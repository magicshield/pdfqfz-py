from pathlib import Path

from pdfqfz.config import inistore, stamplib
from pdfqfz.model.spec import CertMode, Edge, SeamType, StampSpec, StampType


def test_roundtrip(tmp_path: Path, seal_png):
    spec = StampSpec(stamp_image=seal_png, seam=SeamType.ODD, edge=Edge.LEFT,
                     size_mm=35, rotation=-45, opacity=80, tolerance=12,
                     normal=StampType.CUSTOM, random_jitter=True, fix_str="盖章版",
                     white_to_alpha=False)
    p = tmp_path / "config.ini"
    inistore.save_spec(spec, p)
    ov = inistore.load_overrides(p)
    assert ov["seam"] == SeamType.ODD
    assert ov["edge"] == Edge.LEFT
    assert ov["size_mm"] == 35
    assert ov["rotation"] == -45
    assert ov["tolerance"] == 12          # 修正点: 容差持久化
    assert ov["white_to_alpha"] is False
    assert ov["random_jitter"] is True
    assert ov["fix_str"] == "盖章版"
    assert ov["stamp_image"] == seal_png


def test_no_passwords_persisted(tmp_path: Path, seal_png):
    spec = StampSpec(stamp_image=seal_png, encrypt_password="SECRETENC",
                     pdf_password="SECRETPW", pfx_password="SECRETPFX")
    p = tmp_path / "config.ini"
    inistore.save_spec(spec, p)
    text = p.read_text(encoding="utf-8")
    for secret in ("SECRETENC", "SECRETPW", "SECRETPFX"):
        assert secret not in text


def test_missing_file(tmp_path: Path):
    assert inistore.load_overrides(tmp_path / "none.ini") == {}


def test_custom_pfx_without_path_downgrades(tmp_path: Path, seal_png):
    spec = StampSpec(stamp_image=seal_png, cert_mode=CertMode.CUSTOM_PFX, pfx_path=None)
    p = tmp_path / "c.ini"
    inistore.save_spec(spec, p)
    ov = inistore.load_overrides(p)
    assert ov["cert_mode"] == CertMode.NONE


def test_migrate_legacy(tmp_path: Path):
    legacy = tmp_path / "old"
    legacy.mkdir()
    (legacy / "config.ini").write_text("[config]\nsize=50\n", encoding="utf-8")
    target = tmp_path / "new" / "config.ini"
    assert inistore.migrate_legacy(legacy, target) is True
    assert inistore.load_overrides(target)["size_mm"] == 50
    assert (tmp_path / "new" / "config.ini.bak").exists()
    assert inistore.migrate_legacy(legacy, target) is False  # 已存在不覆盖


def test_stamplib(tmp_path: Path, seal_png):
    p = tmp_path / "yz.log"
    assert stamplib.load(p) == []
    items = stamplib.append(p, seal_png)
    assert items == [seal_png.resolve()]
    stamplib.append(p, seal_png)  # 去重
    assert len(stamplib.load(p)) == 1
    stamplib.remove(p, seal_png)
    assert stamplib.load(p) == []
