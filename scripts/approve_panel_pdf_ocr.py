"""Manually approve an OCR reconstruction, retaining its separate provenance.
Preview is read-only. OCR evidence is replayed before any database access.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scraper.panel_detail_specs import is_allowed_detail_url
from scraper.panel_pdf_approval import (ApprovalError, ApprovedCandidate,
    approved_document_url, check_catalog_match, validate_stc)
from scraper.panel_pdf_ocr_table import reconstruct
from scripts.reconstruct_panel_pdf_ocr import read, decode, require

METHOD = 'local_pdf_ocr_manual_v1'
RESOLVED_ISSUES = frozenset('conflicting_'+field for field in (
    'rated_power_w','voc_v','vmp_v','isc_a','imp_a','efficiency_pct'))


def has_unresolved_issues(issues):
    return not isinstance(issues,list) or any(
        not isinstance(issue,str) or issue not in RESOLVED_ISSUES for issue in issues)



@dataclass(frozen=True)
class OCRApproval:
    candidate: ApprovedCandidate
    pdf_url: str
    evidence_sha256: str


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def validate_folder(folder: Path, page: int, confirm_model: str) -> OCRApproval:
    require(folder.is_dir() and not folder.is_symlink() and type(page) is int
            and 1 <= page <= 20, 'INVALID_FOLDER_OR_PAGE')
    pdf = read(folder/'document.pdf', 20*1024*1024)
    require(pdf.startswith(b'%PDF-'), 'NOT_PDF')
    digest = sha(pdf)
    job = decode(read(folder/'job.json', 1024*1024))
    old = decode(read(folder/'review.json', 1024*1024))
    raw = read(folder/f'ocr_evidence_page{page}.json', 8*1024*1024)
    evidence = decode(raw)
    raw_table = read(folder/f'ocr_table_review_page{page}.json', 128*1024)
    table = decode(raw_table)
    require(old.get('status') == 'NO_UNAMBIGUOUS_STC_TABLE'
            and old.get('database_write') is False and old.get('candidates') == []
            and old.get('pdf_sha256') == digest == evidence.get('pdf_sha256')
            and old.get('model_requested') == job.get('model') == evidence.get('model_requested') == confirm_model
            and old.get('power_w_requested') == job.get('power_w') == evidence.get('power_w_requested')
            and type(evidence.get('page')) is int and evidence['page'] == page,
            'EVIDENCE_PROVENANCE_MISMATCH')
    source = job.get('source_url'); link = job.get('pdf_url')
    require(isinstance(source, str) and is_allowed_detail_url(source), 'UNTRUSTED_PRODUCT_URL')
    approved_document_url([link])
    rebuilt = reconstruct(evidence)
    rebuilt.update(ocr_evidence_sha256=sha(raw), source_url=source, source_pdf_url=link)
    # Compare the entire report, not just the proposed values; no manual edits accepted.
    require(json.dumps(rebuilt, sort_keys=True, allow_nan=False) ==
            json.dumps(table, sort_keys=True, allow_nan=False), 'OCR_RECONSTRUCTION_MISMATCH')
    power = rebuilt['power_w_requested']
    values = validate_stc(rebuilt['proposed_values'], power)
    return OCRApproval(ApprovedCandidate(source, confirm_model, power, digest,
        sha(raw_table), page, rebuilt['variant_column_zero_based'], values), link, sha(raw))


def fetch_catalog(cursor, item: OCRApproval):
    c = item.candidate
    cursor.execute('''SELECT title, catalog_power_w, datasheet_urls, parse_issues,
                       pdf_approval_method FROM gold.panel_technical_comparison
                       WHERE source_url = %s''', (c.source_url,))
    row = cursor.fetchone()
    if row is None:
        raise ApprovalError('Product URL not present in current Gold catalog')
    title, watts, links, issues, _ = row
    check_catalog_match(c, title=title, catalog_power=watts)
    if not isinstance(links, list) or item.pdf_url not in links:
        raise ApprovalError('Exact OCR PDF URL not attached to current catalog product')
    return issues


def write_approval(cursor, item: OCRApproval):
    c = item.candidate
    cursor.execute('''INSERT INTO bronze.panel_pdf_approvals
        (source_url, model, power_w, pdf_url, pdf_sha256, review_sha256,
         pdf_page, variant_column, values_stc, approval_method, ocr_evidence_sha256)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s)
        ON CONFLICT (source_url, pdf_sha256, power_w, pdf_page, variant_column)
        DO NOTHING RETURNING approval_id''', (c.source_url,c.model,c.power_w,item.pdf_url,
            c.pdf_sha256,c.review_sha256,c.pdf_page,c.variant_column,
            json.dumps(c.values_stc), METHOD,item.evidence_sha256))
    row = cursor.fetchone()
    if row is not None:
        return int(row[0]), True
    cursor.execute('''SELECT approval_id, model, pdf_url, review_sha256, values_stc,
        approval_method, ocr_evidence_sha256 FROM bronze.panel_pdf_approvals
        WHERE source_url=%s AND pdf_sha256=%s AND power_w=%s
        AND pdf_page=%s AND variant_column=%s''', (c.source_url,c.pdf_sha256,c.power_w,c.pdf_page,c.variant_column))
    row = cursor.fetchone()
    if row is None or tuple(row[1:]) != (c.model,item.pdf_url,c.review_sha256,c.values_stc,METHOD,item.evidence_sha256):
        raise ApprovalError('Conflicting approval exists for this PDF variant')
    return int(row[0]), False


def execute(item: OCRApproval, *, approve=False):
    from scraper.load import get_connection
    with get_connection() as conn:
        with conn.cursor() as cursor:
            issues = fetch_catalog(cursor,item)  # Requires upgraded Gold, even for preview.
            if not approve:
                return 'PREVIEW_ONLY', None, issues, None
            aid, created = write_approval(cursor,item)
            cursor.execute('''SELECT pdf_approval_id, pdf_approval_method, technical_status,
                pdf_ocr_evidence_sha256 FROM gold.panel_technical_comparison
                WHERE source_url=%s''', (item.candidate.source_url,))
            row = cursor.fetchone()
            # Fail closed on an outdated/stale view or another effective approval.
            if row is None or row[0] != aid or row[1] != METHOD or row[3] != item.evidence_sha256:
                raise ApprovalError('Gold does not expose the expected OCR approval; transaction rolled back')
            if has_unresolved_issues(issues) and row[2] != 'REVIEW':
                raise ApprovalError('Gold concealed an unresolved issue; transaction rolled back')
            return ('APPROVED_NEW' if created else 'APPROVED_ALREADY_EXISTS'), aid, issues, row[2]


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--folder',type=Path,required=True)
    p.add_argument('--page',type=int,default=2)
    p.add_argument('--confirm-model',required=True)
    p.add_argument('--approve',action='store_true')
    p.add_argument('--confirm-visual',action='store_true',help='Confirm original PDF page, exact model, STC column and all six values visually')
    a=p.parse_args(argv)
    if a.approve and not a.confirm_visual:
        p.error('--approve requires --confirm-visual')
    try:
        item=validate_folder(a.folder,a.page,a.confirm_model)
        status, aid, issues, quality=execute(item,approve=a.approve)
    except (ValueError,OSError,TypeError,KeyError) as exc:
        print(f'OCR APPROVAL REJECTED: {exc}',file=sys.stderr); return 1
    except Exception as exc:
        print(f'OCR APPROVAL ERROR: {type(exc).__name__}; check migration 009, dbt and connection',file=sys.stderr); return 2
    c=item.candidate
    print(json.dumps(dict(status=status,source_url=c.source_url,source_pdf_url=item.pdf_url,
        model=c.model,power_w=c.power_w,pdf_sha256=c.pdf_sha256,review_sha256=c.review_sha256,
        ocr_evidence_sha256=item.evidence_sha256,approval_method=METHOD,page=c.pdf_page,
        variant_column_zero_based=c.variant_column,stc=c.values_stc,html_parse_issues=issues,
        technical_status=quality,approval_id=aid,database_write=status=='APPROVED_NEW',
        write_requested=a.approve),indent=2,ensure_ascii=False,default=str))
    return 0

if __name__=='__main__': raise SystemExit(main())
