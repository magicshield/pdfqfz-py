"""跨平台配置/数据目录（platformdirs），支持从旧 C# 版 config.ini 迁移。"""

from __future__ import annotations

from pathlib import Path

from platformdirs import user_config_dir, user_data_dir

APP = "pdfqfz"


def config_dir() -> Path:
    p = Path(user_config_dir(APP))
    p.mkdir(parents=True, exist_ok=True)
    return p


def data_dir() -> Path:
    p = Path(user_data_dir(APP))
    p.mkdir(parents=True, exist_ok=True)
    return p


def config_path() -> Path:
    return config_dir() / "config.ini"


def stamplib_path() -> Path:
    return data_dir() / "yz.log"


def default_cert_path() -> Path:
    return data_dir() / "pdfqfz.pfx"
