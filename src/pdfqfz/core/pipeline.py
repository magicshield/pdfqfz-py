"""批量盖章编排：输入解析 → 盖章 → 合并 → (签名) → 加密。顺序对应设计文档 §2.5。"""

from __future__ import annotations

import random
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from pdfqfz.core import names, pdfio, scanner
from pdfqfz.core.imageops import StampAssets, build_assets
from pdfqfz.model.spec import Blend, CertMode, StampSpec


def _resolve_signer(spec: StampSpec):
    from pdfqfz.config import paths
    from pdfqfz.core import signing
    if spec.cert_mode == CertMode.SELF_SIGNED:
        store = spec.cert_store_path or paths.default_cert_path()
        pw = spec.pfx_password or signing.DEFAULT_SELF_PASSWORD
        signing.ensure_self_signed_pfx(store, spec.signer_name, pw)
        return signing.load_signer(store.read_bytes(), pw)
    if spec.pfx_path is None:
        raise ValueError("自定义证书模式需要 pfx 文件")
    return signing.load_signer(Path(spec.pfx_path).read_bytes(), spec.pfx_password)


class Cancelled(Exception):
    pass


@dataclass
class FileResult:
    source: Path
    output: Path | None
    ok: bool
    seam_pages: int = 0
    normal_pages: int = 0
    encrypted: bool = False
    message: str = ""


def process_one(src: Path, spec: StampSpec, assets: StampAssets,
                rng: random.Random, dry: bool = False) -> FileResult:
    out = names.resolve_output(src, spec)
    file_key = str(src)
    positions = spec.positions

    in_path = src
    tmp: Path | None = None
    if spec.multi_pass and out.exists():
        tmp = Path(tempfile.mkstemp(suffix=".pdf", dir=str(out.parent))[1])
        shutil.copy2(out, tmp)
        in_path = tmp

    try:
        doc = pdfio.open_doc(in_path, spec.pdf_password)
        try:
            plan = pdfio.build_plan(doc, spec, assets, file_key, positions, rng)
            if dry:
                rows = [f"seam p{p}: ({r[0]:.2f},{r[1]:.2f},{r[2]:.2f},{r[3]:.2f})"
                        for p, r in plan.seam] + \
                       [f"normal p{p} a{a}: ({r[0]:.2f},{r[1]:.2f},{r[2]:.2f},{r[3]:.2f})"
                        for p, r, a in plan.normal]
                msg = "; ".join(rows) if rows else "无盖章动作"
                if plan.skipped_seam_reason:
                    msg += f" [{plan.skipped_seam_reason}]"
                return FileResult(src, out, True, len(plan.seam), len(plan.normal),
                                  False, msg)
            out.parent.mkdir(parents=True, exist_ok=True)
            pdfio.apply_plan(doc, spec, assets, plan)
            pdfio.save_doc(doc, out, spec)
        finally:
            doc.close()

        if spec.blend == Blend.MERGE:
            pdfio.rasterize_merge(out, spec.merge_dpi, spec)

        if spec.cert_mode != CertMode.NONE:
            if spec.encrypt_password:
                return FileResult(src, out, False,
                                  message="数字签名与加密输出不能同时使用（加密会使签名失效）")
            from pdfqfz.core import signing
            signer = _resolve_signer(spec)
            signing.sign_pdf_file(
                out, signer,
                page_index=plan.sig_page_index,
                box_bottomleft=plan.sig_box_bl,
                seal_png=assets.full_png if plan.sig_box_bl else None,
                ccw_rotation=plan.sig_ccw,
                vendor=spec.meta_producer or "PDFQFZ")

        encrypted = False
        final = out
        if spec.encrypt_password:
            enc = names.encrypted_path(out, spec, src)
            pdfio.encrypt_copy(out, enc, spec.encrypt_password)
            out.unlink()
            final, encrypted = enc, True

        return FileResult(src, final, True, len(plan.seam), len(plan.normal), encrypted)
    except pdfio.DocPasswordError as e:
        return FileResult(src, None, False, message=str(e))
    except Exception as e:  # noqa: BLE001 — 批量场景逐文件兜底
        return FileResult(src, None, False, message=f"{type(e).__name__}: {e}")
    finally:
        if tmp is not None and tmp.exists():
            tmp.unlink()


def run(spec: StampSpec, assets: StampAssets | None = None, *,
        dry: bool = False,
        on_progress: Callable[[int, int, FileResult], None] | None = None,
        cancel: Callable[[], bool] | None = None) -> list[FileResult]:
    files = scanner.collect_sources(spec)
    if not files:
        return []
    assets = assets or build_assets(spec)
    seed = spec.jitter_seed if spec.jitter_seed is not None else random.randrange(2**32)
    rng = random.Random(seed)
    results: list[FileResult] = []
    total = len(files)
    for i, src in enumerate(files, 1):
        if cancel and cancel():
            raise Cancelled()
        res = process_one(src, spec, assets, rng, dry=dry)
        results.append(res)
        if on_progress:
            on_progress(i, total, res)
    return results
