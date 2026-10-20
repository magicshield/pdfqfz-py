"""输入收集：目录递归扫描（跳过输出目录内文件）与文件模式列表。"""

from __future__ import annotations

from pathlib import Path

from pdfqfz.model.spec import StampSpec


def collect_sources(spec: StampSpec) -> list[Path]:
    if spec.mode.value == 0 and spec.src_dir is not None:
        out_dir = spec.out_dir.resolve() if spec.out_dir else None
        files: list[Path] = []
        for p in sorted(spec.src_dir.rglob("*.pdf")):
            if not p.is_file():
                continue
            if out_dir is not None:
                try:
                    p.resolve().relative_to(out_dir)
                    continue  # 位于输出目录内，跳过自吞
                except ValueError:
                    pass
            files.append(p.resolve())
        return files
    return [Path(s).resolve() for s in spec.sources]
