from __future__ import annotations

import os
import sys

if sys.stdout is None:   # PyInstaller --windowed 无控制台
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    from pdfqfz.cli.main import build_parser, cmd_cert, cmd_stamp, cmd_verify

    argv = sys.argv[1:] if argv is None else argv
    commands = ("gui", "stamp", "verify", "cert")
    if not argv or argv[0] not in commands:
        # 无参数或以文件开头（右键"打开方式"）→ 启动 GUI 并预载
        from pdfqfz.gui.app import run_gui
        return run_gui([a for a in argv if not a.startswith("-")])
    parser = build_parser()
    a = parser.parse_args(argv)
    if a.cmd == "stamp":
        return cmd_stamp(a)
    if a.cmd == "verify":
        return cmd_verify(a)
    if a.cmd == "cert":
        return cmd_cert(a)
    if a.cmd == "gui":
        from pdfqfz.gui.app import run_gui
        return run_gui([])
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
