"""参数真源：所有表单/命令行参数汇聚为 StampSpec。枚举值与 C# 版 combo 索引一一对应。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path


class Mode(IntEnum):
    DIRECTORY = 0   # comboType: 目录模式
    FILES = 1       # 文件模式


class SeamType(IntEnum):
    ALL = 0         # comboQfz: 加盖骑缝章(全页)
    NONE = 1        # 不加骑缝章
    ODD = 2         # 奇数页
    EVEN = 3        # 偶数页
    CUSTOM = 4      # 随意骑缝章(点击选页)


class StampType(IntEnum):
    NONE = 0        # comboYz: 全都不加印章
    NO_FIRST = 1    # 首页不加
    NO_LAST = 2     # 尾页不加
    ALL = 3         # 所有页
    CUSTOM = 4      # 自定义(点击定位)


class Edge(IntEnum):
    TOP = 0         # comboBoxWZ
    BOTTOM = 1
    LEFT = 2
    RIGHT = 3


class Blend(IntEnum):
    OVERLAY = 0     # comboDJ: 叠加(保留文字层)
    MERGE = 1       # 合并(光栅化压扁)


class CertMode(IntEnum):
    NONE = 0        # comboQmtype
    SELF_SIGNED = 1
    CUSTOM_PFX = 2


class RotCrop(IntEnum):
    CROP = 0        # comboBoxQB: 旋转切边(保持原宽)
    EXPAND = 1      # 不切边(完整外接框)


@dataclass(frozen=True)
class StampSpec:
    mode: Mode = Mode.FILES
    sources: tuple[Path, ...] = ()
    src_dir: Path | None = None
    out_dir: Path | None = None
    stamp_image: Path | None = None

    size_mm: int = 40
    rotation: int = 0
    opacity: int = 60
    tolerance: int = 20
    white_to_alpha: bool = True
    crop: RotCrop = RotCrop.CROP

    seam: SeamType = SeamType.ALL
    edge: Edge = Edge.RIGHT
    wz: int = 50
    max_strips: int = 20

    normal: StampType = StampType.NONE
    px: float = 0.77
    py: float = 0.88
    random_jitter: bool = False
    jitter_seed: int | None = None

    save_in_source: bool = False
    fix_type: int = 0          # 0=后缀 1=前缀
    fix_str: str = "已盖章"
    fix_str2: str = "加密"
    multi_pass: bool = False
    blend: Blend = Blend.OVERLAY
    merge_dpi: int = 300

    pdf_password: str | None = None
    encrypt_password: str | None = None

    cert_mode: CertMode = CertMode.NONE
    signer_name: str = ""
    pfx_path: Path | None = None
    pfx_password: str | None = None
    cert_store_path: Path | None = None   # 自签证书存放位置(默认 pdfqfz.pfx)

    # (源绝对路径str, 1-based页) -> (px, py)，点击定位记录；同时驱动 SeamType.CUSTOM 与 StampType.CUSTOM
    positions: dict[tuple[str, int], tuple[float, float]] = field(default_factory=dict)

    def jitter_rng_seed(self) -> int | None:
        return self.jitter_seed
