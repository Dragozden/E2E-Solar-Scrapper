"""Strict offline PDF/STC approval validation, with no database imports at module load.

A review JSON is untrusted until its source PDF hash, exact variant, manual
confirmation and current catalog row are all checked.  No user-supplied raw
SQL or automatic inferred manufacturer identification.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from scraper.panel_detail_specs import is_allowed_detail_url
from scraper.panel_pdf_stc import family_token

REQUIRED_STC = ("rated_power_w", "voc_v", "vmp_v", "isc_a", "imp_a", "efficiency_pct")
HEX_SHA256 = re.compile(r"^[a-f0-9]{64}$")


class ApprovalError(ValueError):
    """Rejected, incomplete or unverified import request."""


def _unique_object(pairs):
    value = {}
    for k, v in pairs:
        if k in value:
            raise ApprovalError("Review JSON contains duplicate object keys")
        value[k] = v
    return value


def _number(value, field: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApprovalError(f"STC {field}: expected a JSON number")
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise ApprovalError(f"STC {field}: invalid number") from None
    if not number.is_finite() or len(number.as_tuple().digits) > 8 or number.as_tuple().exponent < -4:
        raise ApprovalError(f"STC {field}: unsafe precision or nonfinite value")
    return number


def validate_stc(data: dict, power: int) -> dict[str, float]:
    """Reject extra fields and physically inconsistent/model-agnostic values."""
    if not isinstance(data, dict) or set(data) != set(REQUIRED_STC):
        raise ApprovalError("Review must contain exactly six STC fields")
    checked = {key: _number(data[key], key) for key in REQUIRED_STC}
    p, voc, vmp, isc, imp, eff = (checked[k] for k in REQUIRED_STC)
    if (p != power or not 100 <= p <= 900 or not 0 < vmp < voc <= 100
            or not 0 < imp <= isc <= 50 or not 10 <= eff <= 30):
        raise ApprovalError("STC data violates model power or physical bounds")
    if abs((vmp * imp) - p) > p * Decimal("0.02"):
        raise ApprovalError("STC Pmax inconsistent with Vmp * Imp")
    return {key: float(value) for key, value in checked.items()}


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _pdf_bytes(pdf: Path) -> bytes:
    if not pdf.is_file() or pdf.suffix.lower() != ".pdf":
        raise ApprovalError("Provide an existing local PDF file")
    if pdf.stat().st_size > 20 * 1024 * 1024:
        raise ApprovalError("PDF exceeds 20 MiB limit")
    raw = pdf.read_bytes()
    if not raw.startswith(b"%PDF-"):
        raise ApprovalError("Input does not have PDF magic bytes")
    return raw


@dataclass(frozen=True)
class ApprovedCandidate:
    source_url: str
    model: str
    power_w: int
    pdf_sha256: str
    review_sha256: str
    pdf_page: int
    variant_column: int
    values_stc: dict[str, float]


def validate_review(pdf: Path, review_json: Path, *, source_url: str,
                    confirm_model: str) -> ApprovedCandidate:
    """Only local evidence is inspected. The source URL is checked, never visited."""
    if not is_allowed_detail_url(source_url):
        raise ApprovalError("Source URL must be a trusted Soltech product URL")
    if not review_json.is_file() or review_json.stat().st_size > 128 * 1024:
        raise ApprovalError("Provide a local review JSON at most 128 KiB")
    raw_review = review_json.read_bytes()
    try:
        report = json.loads(raw_review.decode("utf-8-sig"), object_pairs_hook=_unique_object)
    except (UnicodeError, json.JSONDecodeError):
        raise ApprovalError("Review JSON unreadable") from None
    if not isinstance(report, dict) or report.get("status") != "REVIEW_REQUIRED" \
            or report.get("database_write") is not False:
        raise ApprovalError("Expected an unmodified REVIEW_REQUIRED report")
    model = report.get("model_requested")
    power = report.get("power_w_requested")
    digest = report.get("pdf_sha256")
    if (not isinstance(model, str) or not model or model != confirm_model
            or isinstance(power, bool) or not isinstance(power, int)
            or not 100 <= power <= 900 or not isinstance(digest, str)
            or not HEX_SHA256.fullmatch(digest)):
        raise ApprovalError("Model/power/hash invalid or manual model confirmation missing")
    if not re.search(rf"(?<!\d){power}(?!\d)", model):
        raise ApprovalError("Model name must contain the exact variant wattage")
    if _sha256(_pdf_bytes(pdf)) != digest:
        raise ApprovalError("PDF SHA-256 mismatch: report belongs to another document")
    candidates = report.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != 1:
        raise ApprovalError("Exactly one validated STC candidate is required")
    candidate = candidates[0]
    if not isinstance(candidate, dict) or candidate.get("power_w") != power \
            or isinstance(candidate.get("power_w"), bool) \
            or candidate.get("model_family") != family_token(model):
        raise ApprovalError("Candidate family or power differs from approved model")
    page = candidate.get("page")
    variant = candidate.get("variant_column_zero_based")
    if (isinstance(page, bool) or not isinstance(page, int) or not 1 <= page <= 20
            or isinstance(variant, bool) or not isinstance(variant, int)
            or not 0 <= variant <= 20):
        raise ApprovalError("Invalid page or variant column")
    fields = validate_stc(candidate.get("values"), power)
    return ApprovedCandidate(
        source_url=source_url, model=model, power_w=power, pdf_sha256=digest,
        review_sha256=_sha256(raw_review), pdf_page=page,
        variant_column=variant, values_stc=fields,
    )


def approved_document_url(value) -> str:
    """Only a retailer-hosted HTTPS PDF attached to the exact product."""
    if not isinstance(value, list) or not value:
        raise ApprovalError("Catalog product has no linked PDF evidence")
    for link in value:
        if not isinstance(link, str):
            continue
        try:
            p = urlsplit(link)
            if (p.scheme == "https" and p.hostname == "sklepsoltech.pl"
                    and p.username is None and p.password is None
                    and p.port in (None, 443) and p.path.lower().endswith(".pdf")
                    and not p.query and not p.fragment):
                return link
        except ValueError:
            continue
    raise ApprovalError("No trusted HTTPS PDF link attached to catalog product")


def check_catalog_match(approval: ApprovedCandidate, *, title: str, catalog_power: int) -> None:
    if isinstance(catalog_power, bool) or catalog_power != approval.power_w:
        raise ApprovalError("Current catalog power is not the approved PDF variant")
    normal = lambda s: re.sub(r"[^a-z0-9]", "", s.casefold())
    if normal(approval.model) not in normal(title):
        raise ApprovalError("Exact approved model token absent from current catalog title")
