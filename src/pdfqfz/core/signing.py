"""数字签名（pyHanko + cryptography）。

- 自签证书：RSA4096 / SHA256 / 5 年 / CN=签名人（对齐 C# Form1.cs:447-452）。
- 签名 = 增量更新（天然保留既有签名，等价 iText preservingSignature）。
- 外观：StaticStampStyle + PdfImage 背景 = iText RenderingMode.GRAPHIC；
  签名域 = 章 rect 外扩 2pt；无普通章时不可见域。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import (BestAvailableEncryption,
                                                          pkcs12)
from cryptography.x509.oid import NameOID
from PIL import Image
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.pdf_utils.images import PdfImage
from pyhanko.pdf_utils.reader import PdfFileReader
from pyhanko.sign import PdfSignatureMetadata, PdfSigner, signers, validation
from pyhanko.sign.fields import SigFieldSpec, enumerate_sig_fields as pyhanko_enum_sig_fields
from pyhanko.stamp import StaticStampStyle

DEFAULT_SELF_PASSWORD = "pdfqfz"


def ensure_self_signed_pfx(path: Path, cn: str, password: str = DEFAULT_SELF_PASSWORD,
                           years: int = 5) -> Path:
    if path.exists():
        return path
    key = rsa.generate_private_key(public_exponent=65537, key_size=4096)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn or "PDFQFZ")])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(name).issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=365 * years))
            .sign(key, hashes.SHA256()))
    p12 = pkcs12.serialize_key_and_certificates(
        (cn or "PDFQFZ").encode(), key, cert, None,
        BestAvailableEncryption(password.encode()))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(p12)
    return path


def load_signer(pfx_bytes: bytes, password: str | None) -> signers.SimpleSigner:
    return signers.SimpleSigner.load_pkcs12_data(
        pfx_bytes, other_certs=[],
        passphrase=password.encode() if password else None)


def sign_pdf_file(path: Path, signer, *, page_index: int,
                  box_bottomleft: tuple[float, float, float, float] | None = None,
                  seal_png: bytes | None = None,
                  ccw_rotation: int = 0,
                  field_name: str | None = None) -> None:
    """box_bottomleft: 未旋转页面 PDF 左下原点坐标；None 则不可见签名。"""
    from datetime import datetime
    if field_name is None:
        field_name = "PDFQFZ 签名 " + datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    with open(path, "r+b") as f:
        writer = IncrementalPdfFileWriter(f)
        spec = SigFieldSpec(sig_field_name=field_name, on_page=page_index,
                           box=None if box_bottomleft is None else tuple(box_bottomleft))
        style = None
        if box_bottomleft is not None and seal_png is not None:
            img = Image.open(BytesIO(seal_png)).convert("RGB")
            if ccw_rotation:
                from pdfqfz.core.pdfio import CCW
                img = img.transpose(CCW[ccw_rotation])
            style = StaticStampStyle(border_width=0, background=PdfImage(img, writer=writer),
                                     background_opacity=1.0)
        meta = PdfSignatureMetadata(field_name=field_name, md_algorithm="sha256")
        psign = PdfSigner(meta, signer, stamp_style=style, new_field_spec=spec)
        psign.sign_pdf(writer, in_place=True)


def verify_pdf(path: Path) -> list[dict]:
    from pyhanko_certvalidator import ValidationContext
    rdr = PdfFileReader(BytesIO(Path(path).read_bytes()))
    out: list[dict] = []
    for fq_name, _sig_ref, field_ref in pyhanko_enum_sig_fields(rdr, filled_status=True):
        cert = None
        integ = dig = False
        try:
            es = validation.EmbeddedPdfSignature(rdr, field_ref.get_object(), str(fq_name))
            cert = es.signer_cert
            vc = ValidationContext(trust_roots=[cert]) if cert else None
            st = validation.validate_pdf_signature(es, signer_validation_context=vc,
                                                   ts_validation_context=vc, skip_diff=True)
            integ, dig = bool(st.intact), bool(st.valid)
        except Exception:  # noqa: BLE001 — 篡改导致解析失败也算校验不通过
            pass
        out.append({
            "field": str(fq_name),
            "integrity_ok": integ,
            "digest_ok": dig,
            "signer": cert.subject.human_friendly if cert else "",
            "not_after": str(getattr(cert, "not_valid_after_utc", None)
                             or cert.not_valid_after) if cert else "",
        })
    return out
