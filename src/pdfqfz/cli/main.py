"""argparse 命令行入口：参数与 StampSpec 字段 1:1。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pdfqfz.core.policies import collect_existing_pdfs
from pdfqfz.model.spec import (Blend, CertMode, Edge, Mode, RotCrop, SeamType,
                               StampSpec, StampType)

SEAM = {"all": SeamType.ALL, "none": SeamType.NONE, "odd": SeamType.ODD,
        "even": SeamType.EVEN, "custom": SeamType.CUSTOM}
STAMP = {"none": StampType.NONE, "no-first": StampType.NO_FIRST,
         "no-last": StampType.NO_LAST, "all": StampType.ALL, "custom": StampType.CUSTOM}
EDGE = {"top": Edge.TOP, "bottom": Edge.BOTTOM, "left": Edge.LEFT, "right": Edge.RIGHT}
BLEND = {"overlay": Blend.OVERLAY, "merge": Blend.MERGE}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pdfqfz", description="PDF 骑缝章/印章工具")
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("stamp", help="批量盖章")
    src = s.add_mutually_exclusive_group(required=True)
    src.add_argument("--dir", type=Path, help="目录模式：递归处理 *.pdf")
    src.add_argument("--files", nargs="+", type=str, help="文件模式：一个或多个 PDF")
    s.add_argument("--out", type=Path, default=None, help="输出目录(默认源目录+前后缀命名)")
    s.add_argument("--in-source", action="store_true", help="保存在源文件夹(前后缀命名)")
    s.add_argument("--image", type=Path, required=True, help="印章图片")
    s.add_argument("--size", type=int, default=40, help="印章宽 mm(默认40)")
    s.add_argument("--rotate", type=int, default=0, help="旋转角度,正角顺时针(默认0)")
    s.add_argument("--opacity", type=int, default=60, help="不透明度0-100(默认60)")
    s.add_argument("--tolerance", type=int, default=20, help="白转透明容差0-50(默认20)")
    s.add_argument("--no-white-alpha", action="store_true", help="不启用白转透明")
    s.add_argument("--crop-mode", choices=["crop", "expand"], default="crop")
    s.add_argument("--seam", choices=list(SEAM), default="all")
    s.add_argument("--seam-pages", type=str, default="", help="随意骑缝页,逗号分隔(配合 --seam custom)")
    s.add_argument("--edge", choices=list(EDGE), default="right")
    s.add_argument("--wz", type=int, default=50, help="骑缝位置百分比0-100(默认50)")
    s.add_argument("--max-strips", type=int, default=20, help="每组最大分割数(默认20)")
    s.add_argument("--stamp", choices=list(STAMP), default="none")
    s.add_argument("--px", type=float, default=0.77)
    s.add_argument("--py", type=float, default=0.88)
    s.add_argument("--positions", type=Path, default=None,
                   help='点击定位 JSON: [["file.pdf", 页码, px, py], ...]')
    s.add_argument("--jitter", action="store_true", help="普通章随机参数(±2%/±2°)")
    s.add_argument("--jitter-seed", type=int, default=None)
    s.add_argument("--blend", choices=["overlay", "merge"], default="overlay")
    s.add_argument("--merge-dpi", type=int, default=300)
    s.add_argument("--multi-pass", action="store_true", help="输出已存在时在其上再盖一次")
    s.add_argument("--read-password", type=str, default=None)
    s.add_argument("--encrypt-password", type=str, default=None)
    s.add_argument("--fix-str", type=str, default="已盖章")
    s.add_argument("--fix-mode", choices=["suffix", "prefix"], default="suffix")
    s.add_argument("--sign", choices=["self", "pfx"], default=None,
                   help="数字签名: self=自动生成自签证书, pfx=使用 --pfx")
    s.add_argument("--pfx", type=Path, default=None)
    s.add_argument("--pfx-password", type=str, default=None)
    s.add_argument("--cn", type=str, default="", help="签名人名称(自签证书 CN)")
    s.add_argument("--dry-run", action="store_true", help="只打印计划不写盘")
    s.add_argument("-v", "--verbose", action="store_true")

    v = sub.add_parser("verify", help="校验 PDF 数字签名")
    v.add_argument("file", type=Path)

    c = sub.add_parser("cert", help="证书管理")
    cs = c.add_subparsers(dest="cert_cmd")
    cn_ = cs.add_parser("new", help="生成自签 pfx 证书")
    cn_.add_argument("--cn", required=True)
    cn_.add_argument("--out", type=Path, default=None)
    cn_.add_argument("--password", type=str, default=None)

    sub.add_parser("gui", help="启动图形界面(默认)")
    return p


def spec_from_args(a: argparse.Namespace) -> StampSpec:
    positions: dict[tuple[str, int], tuple[float, float]] = {}
    if a.positions:
        for row in json.loads(Path(a.positions).read_text(encoding="utf-8")):
            f, page, px, py = row
            positions[(str(Path(f).resolve()), int(page))] = (float(px), float(py))
    if a.seam == "custom":
        if not a.files:
            raise SystemExit("--seam custom --seam-pages 仅用于文件模式，请改用 --positions")
        f = str(Path(a.files[0]).resolve())
        for part in filter(None, a.seam_pages.split(",")):
            positions.setdefault((f, int(part)), (a.px, a.py))
    mode = Mode.DIRECTORY if a.dir else Mode.FILES
    sources = tuple(Path(f).resolve() for f in a.files) if a.files else ()
    fix_str2 = "加密"
    return StampSpec(
        mode=mode, sources=sources, src_dir=a.dir, out_dir=a.out,
        stamp_image=a.image.resolve(),
        size_mm=a.size, rotation=a.rotate, opacity=a.opacity,
        tolerance=a.tolerance, white_to_alpha=not a.no_white_alpha,
        crop=RotCrop.CROP if a.crop_mode == "crop" else RotCrop.EXPAND,
        seam=SEAM[a.seam], edge=EDGE[a.edge], wz=a.wz, max_strips=a.max_strips,
        normal=STAMP[a.stamp], px=a.px, py=a.py,
        random_jitter=a.jitter, jitter_seed=a.jitter_seed,
        save_in_source=a.in_source, fix_type=1 if a.fix_mode == "prefix" else 0,
        fix_str=a.fix_str, fix_str2=fix_str2,
        multi_pass=a.multi_pass, blend=BLEND[a.blend], merge_dpi=a.merge_dpi,
        pdf_password=a.read_password, encrypt_password=a.encrypt_password,
        cert_mode=CertMode.NONE if not a.sign else (
            CertMode.SELF_SIGNED if a.sign == "self" else CertMode.CUSTOM_PFX),
        signer_name=a.cn, pfx_path=a.pfx, pfx_password=a.pfx_password,
        positions=positions,
    )


def cmd_stamp(a: argparse.Namespace) -> int:
    from pdfqfz.core import pipeline
    from pdfqfz.core.imageops import build_assets

    spec = spec_from_args(a)
    try:
        assets = build_assets(spec)
    except Exception as e:  # noqa: BLE001
        print(f"印章图片加载失败: {e}", file=sys.stderr)
        return 2

    def progress(i: int, total: int, res) -> None:
        if a.dry_run:
            print(f"[{i}/{total}] {res.source}\n    {res.message}")
        elif res.ok:
            enc = " (+加密)" if res.encrypted else ""
            print(f"[{i}/{total}] {res.source.name} -> {res.output}"
                  f" 骑缝{res.seam_pages}页 章{res.normal_pages}页{enc}")
        else:
            print(f"[{i}/{total}] {res.source.name} 失败: {res.message}", file=sys.stderr)

    try:
        results = pipeline.run(spec, assets, dry=a.dry_run, on_progress=progress)
    except pipeline.Cancelled:
        print("已取消", file=sys.stderr)
        return 130
    if not results:
        print("没有找到可处理的 PDF", file=sys.stderr)
        return 2
    return 0 if all(r.ok for r in results) else 1


def cmd_verify(a: argparse.Namespace) -> int:
    from pdfqfz.core import signing
    sigs = signing.verify_pdf(a.file)
    if not sigs:
        print("该 PDF 没有数字签名")
        return 1
    for s in sigs:
        print(f"签名域 {s['field']}: 完整性={'通过' if s['integrity_ok'] else '失败'}"
              f" 摘要={'通过' if s['digest_ok'] else '失败'}"
              f" 签名人={s['signer']} 证书到期={s['not_after'][:10]}")
    return 0 if all(s["integrity_ok"] and s["digest_ok"] for s in sigs) else 1


def cmd_cert(a: argparse.Namespace) -> int:
    from pdfqfz.config import paths
    from pdfqfz.core import signing
    if a.cert_cmd == "new":
        out = a.out or (paths.data_dir() / "pdfqfz.pfx")
        pw = a.password or signing.DEFAULT_SELF_PASSWORD
        if out.exists():
            print(f"证书已存在: {out}")
            return 1
        signing.ensure_self_signed_pfx(out, a.cn, pw)
        print(f"已生成自签证书: {out}")
        return 0
    print("用法: pdfqfz cert new --cn 名字 [--out 文件] [--password 密码]")
    return 2
