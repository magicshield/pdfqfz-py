"""config.ini 读写（沿用 C# 键名，可迁移旧文件）。

修正 C# 行为：持久化 tolerance/whiteAlpha/jitter；不持久化任何密码。
"""

from __future__ import annotations

import configparser
import shutil
from pathlib import Path

from pdfqfz.model.spec import StampSpec

# ini 键 -> (spec 字段, 类型)
_INT = {
    "wjType": ("mode", int), "qfzType": ("seam", int), "yzType": ("normal", int),
    "djType": ("blend", int), "qmType": ("cert_mode", int), "wzType": ("edge", int),
    "qbflag": ("crop", int), "size": ("size_mm", int), "rotation": ("rotation", int),
    "opacity": ("opacity", int), "wz": ("wz", int), "maxfgs": ("max_strips", int),
    "fixType": ("fix_type", int), "tolerance": ("tolerance", int),
    "mergeDpi": ("merge_dpi", int),
}
_BOOL = {
    "whiteAlpha": "white_to_alpha", "inSource": "save_in_source",
    "multiPass": "multi_pass", "jitter": "random_jitter",
}
_FLOAT = {"px": "px", "py": "py"}
_STR = {"fixStr": "fix_str", "fixStr2": "fix_str2", "signText": "signer_name",
        "producer": "meta_producer", "creator": "meta_creator"}
_PATH = {"imagePath": "stamp_image", "outDir": "out_dir", "srcDir": "src_dir",
         "pfxPath": "pfx_path"}
SECTION = "config"


def load_overrides(path: Path) -> dict:
    if not path.exists():
        return {}
    cp = configparser.ConfigParser()
    cp.optionxform = str
    cp.read(path, encoding="utf-8")
    if not cp.has_section(SECTION):
        return {}
    raw = dict(cp[SECTION])
    out: dict = {}
    for key, (field, _t) in _INT.items():
        if key in raw:
            try:
                out[field] = int(raw[key])
            except ValueError:
                pass
    for key, field in _BOOL.items():
        if key in raw:
            out[field] = raw[key] in ("1", "true", "True")
    for key, field in _FLOAT.items():
        if key in raw:
            try:
                out[field] = float(raw[key])
            except ValueError:
                pass
    for key, field in _STR.items():
        if key in raw:
            out[field] = raw[key]
    for key, field in _PATH.items():
        if key in raw and raw[key]:
            out[field] = Path(raw[key])
    # 枚举字段转换
    from pdfqfz.model.spec import (Blend, CertMode, Edge, Mode, RotCrop,
                                   SeamType, StampType)
    conv = {"mode": Mode, "seam": SeamType, "normal": StampType, "blend": Blend,
            "cert_mode": CertMode, "edge": Edge, "crop": RotCrop}
    for key, enum in conv.items():
        if key in out:
            out[key] = enum(out[key])
    if "cert_mode" in out and out["cert_mode"] == CertMode.CUSTOM_PFX and "pfx_path" not in out:
        out["cert_mode"] = CertMode.NONE
    return out


def save_spec(spec: StampSpec, path: Path) -> None:
    cp = configparser.ConfigParser()
    cp.optionxform = str
    cp[SECTION] = {}
    for key, (field, _t) in _INT.items():
        cp[SECTION][key] = str(int(getattr(spec, field)))
    for key, field in _BOOL.items():
        cp[SECTION][key] = "1" if getattr(spec, field) else "0"
    for key, field in _FLOAT.items():
        cp[SECTION][key] = f"{getattr(spec, field):.4f}"
    for key, field in _STR.items():
        cp[SECTION][key] = str(getattr(spec, field) or "")
    for key, field in _PATH.items():
        v = getattr(spec, field, None)
        cp[SECTION][key] = str(v) if v else ""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        cp.write(f)


def migrate_legacy(legacy_dir: Path, target: Path) -> bool:
    """旧 C# 版 config.ini 一次性迁移（保留 .bak 备份）。"""
    src = Path(legacy_dir) / "config.ini"
    if not src.exists() or target.exists():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, target.with_suffix(".ini.bak"))
    shutil.copy2(src, target)
    return True
