"""Manually approve one local STC/PDF report for an exact current product.

Preview is the default. Opt-in --approve is an append-only PostgreSQL INSERT.
Reads no remote URLs, never alters prior HTML snapshots or pricing history.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scraper.panel_pdf_approval import (
    ApprovalError, ApprovedCandidate, approved_document_url,
    check_catalog_match, validate_review,
)


def fetch_catalog(cursor, item: ApprovedCandidate) -> str:
    """Match source URL, model string and power against the current Gold row."""
    cursor.execute("""
        SELECT title, catalog_power_w, datasheet_urls
        FROM gold.panel_technical_comparison
        WHERE source_url = %s
    """, (item.source_url,))
    record = cursor.fetchone()
    if record is None:
        raise ApprovalError("Product URL not present in the current Gold catalog")
    title, watts, links = record
    check_catalog_match(item, title=title, catalog_power=watts)
    return approved_document_url(links)


def write_approval(cursor, item: ApprovedCandidate, pdf_url: str) -> tuple[int, bool]:
    """Insert or verify an identical existing approval (never overwrite evidence)."""
    cursor.execute("""
        INSERT INTO bronze.panel_pdf_approvals (
            source_url, model, power_w, pdf_url,
            pdf_sha256, review_sha256, pdf_page, variant_column, values_stc
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
        ON CONFLICT (source_url, pdf_sha256, power_w, pdf_page, variant_column)
        DO NOTHING RETURNING approval_id
    """, (item.source_url, item.model, item.power_w, pdf_url,
          item.pdf_sha256, item.review_sha256, item.pdf_page,
          item.variant_column, json.dumps(item.values_stc, ensure_ascii=False)))
    row = cursor.fetchone()
    if row is not None:
        return int(row[0]), True
    cursor.execute("""
        SELECT approval_id, model, pdf_url, review_sha256, values_stc
        FROM bronze.panel_pdf_approvals
        WHERE source_url=%s AND pdf_sha256=%s AND power_w=%s
          AND pdf_page=%s AND variant_column=%s
    """, (item.source_url, item.pdf_sha256, item.power_w,
          item.pdf_page, item.variant_column))
    existing = cursor.fetchone()
    if existing is None:
        raise ApprovalError("Approval conflict without a matching row")
    approval_id, old_model, old_url, old_review, old_values = existing
    if (old_model != item.model or old_url != pdf_url or old_review != item.review_sha256
            or old_values != item.values_stc):
        raise ApprovalError("Conflicting approval exists for same PDF/variant; review manually")
    return int(approval_id), False


def execute(item: ApprovedCandidate, *, approve: bool = False) -> tuple[str, int | None, str]:
    """Safe DB transaction. Preview fetches only and does not write."""
    from scraper.load import get_connection
    with get_connection() as conn:
        with conn.cursor() as cursor:
            pdf_url = fetch_catalog(cursor, item)
            if not approve:
                return "PREVIEW_ONLY", None, pdf_url
            approval_id, created = write_approval(cursor, item, pdf_url)
            return ("APPROVED_NEW" if created else "APPROVED_ALREADY_EXISTS"), approval_id, pdf_url


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Approve exact model-specific PDF STC data")
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--review-json", type=Path, required=True)
    parser.add_argument("--source-url", required=True, help="Canonical product URL in current Gold")
    parser.add_argument("--confirm-model", required=True,
                        help="Exact inspected model variant, e.g. TWMNH-54HD500")
    parser.add_argument("--approve", action="store_true", help="Explicit opt-in append-only DB INSERT")
    args = parser.parse_args(argv)
    try:
        item = validate_review(args.pdf, args.review_json,
                               source_url=args.source_url, confirm_model=args.confirm_model)
        status, approval_id, source_pdf_url = execute(item, approve=args.approve)
    except (ApprovalError, OSError, ValueError) as exc:
        print(f"PDF APPROVAL REJECTED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        # Never expose psycopg connection details or credentials in user logs.
        print(f"PDF APPROVAL ERROR: {type(exc).__name__}; check DB migration and connections", file=sys.stderr)
        return 2
    output = {
        "status": status, "source_url": item.source_url,
        "model": item.model, "power_w": item.power_w,
        "pdf_sha256": item.pdf_sha256, "review_sha256": item.review_sha256,
        "source_pdf_url": source_pdf_url,
        "page": item.pdf_page, "variant_column_zero_based": item.variant_column,
        "stc": item.values_stc, "approval_id": approval_id,
        "database_write": status == "APPROVED_NEW",
        "write_requested": bool(args.approve),
    }
    print(json.dumps(output, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
