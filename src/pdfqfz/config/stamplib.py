"""印章图片库 yz.log：每行一个绝对路径，追加去重。"""

from __future__ import annotations

from pathlib import Path


def load(path: Path) -> list[Path]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(Path(line))
    return out


def append(path: Path, image: Path) -> list[Path]:
    items = load(path)
    image = Path(image).resolve()
    if image not in items:
        items.append(image)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(str(i) for i in items) + "\n", encoding="utf-8")
    return items


def remove(path: Path, image: Path) -> list[Path]:
    items = [i for i in load(path) if i != Path(image).resolve()]
    path.write_text("".join(f"{i}\n" for i in items), encoding="utf-8")
    return items
