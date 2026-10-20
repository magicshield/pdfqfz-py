"""输出命名与多章连盖输入选择（对应 C# Form1.cs:518-629 的命名逻辑，修正 fixStr2 bug）。"""

from __future__ import annotations

from pathlib import Path

from pdfqfz.model.spec import Mode, StampSpec


def _fixed_name(name: str, spec: StampSpec) -> str:
    stem = Path(name).stem
    if spec.fix_type == 1:
        return f"{spec.fix_str}_{stem}.pdf"
    return f"{stem}_{spec.fix_str}.pdf"


def resolve_output(src: Path, spec: StampSpec) -> Path:
    """目录模式镜像相对子路径（修正 C# 同名覆盖 bug）；同目录/源目录时改用前后缀命名。"""
    if spec.mode == Mode.DIRECTORY and spec.src_dir is not None:
        rel = src.resolve().relative_to(spec.src_dir.resolve())
    else:
        rel = Path(src.name)

    out_dir = spec.out_dir
    if spec.save_in_source or out_dir is None:
        return src.parent / _fixed_name(rel.name, spec)

    target = out_dir / rel
    if target.parent.resolve() == src.parent.resolve():
        # 输出目录恰为源文件目录 → C# 行为：就地改名
        return src.parent / _fixed_name(rel.name, spec)
    return target


def encrypted_path(out: Path, spec: StampSpec, src: Path | None = None) -> Path:
    """C# 文件模式：加密终稿名 = 原名_已盖章_加密.pdf（盖章中间稿随后删除）。"""
    stem = (src or out).stem
    mark = f"{spec.fix_str}_" if spec.fix_str else ""
    if spec.fix_type == 1:
        name = f"{spec.fix_str2}_{mark}{stem}.pdf"
    else:
        name = f"{stem}_{mark}{spec.fix_str2}.pdf"
    return out.parent / name
