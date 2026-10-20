from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    from pdfqfz.cli.main import build_parser, cmd_stamp

    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("gui",):
        from pdfqfz.gui.app import run_gui
        return run_gui(argv[1:] if argv and argv[0] == "gui" else [])
    parser = build_parser()
    a = parser.parse_args(argv)
    if a.cmd == "stamp":
        return cmd_stamp(a)
    if a.cmd == "gui":
        from pdfqfz.gui.app import run_gui
        return run_gui([])
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
