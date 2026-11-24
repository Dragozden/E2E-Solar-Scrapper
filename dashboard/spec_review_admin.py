"""Local review service; no network fetch or changes to the public dashboard."""
from __future__ import annotations
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from scraper.panel_pdf_approval import ApprovalError, approved_document_url, check_catalog_match, validate_review
from scripts.approve_panel_pdf_ocr import validate_folder, has_unresolved_issues, write_approval as write_ocr, METHOD
from scripts.approve_panel_pdf import write_approval as write_text
from scripts.reconstruct_panel_pdf_ocr import read, decode, require

ROOT = Path(__file__).resolve().parents[1]
QUEUE = Path.home() / 'Downloads' / 'SolarSpecs' / 'queue'
FIELDS = ('rated_power_w','voc_v','vmp_v','isc_a','imp_a','efficiency_pct')
REPORT = re.compile(r'review(?:_v[2-9][0-9]*)?\.json|ocr_table_review_page(?:[1-9]|1[0-9]|20)\.json')
JOB_ID = re.compile(r'[a-f0-9]{24}')
SQL = '''SELECT overall_rank, title, source_url, catalog_power_w, model,
    technical_status, technical_source, parse_issues, datasheet_urls,
    pdf_approval_id, pdf_approval_method, pdf_stc_quality, spec_hash,
    technical_power_w, voc_v, vmp_v, isc_a, imp_a, efficiency_pct
    FROM gold.panel_technical_comparison'''
KEYS = ('rank','title','source_url','power','model','status','source','issues','links',
        'approval_id','method','pdf_stc_quality','spec_hash',*FIELDS)


def _unsafe(path):
    return path.is_symlink() or getattr(path,'is_junction',lambda:False)()


def checked_root(root=QUEUE):
    root=Path(root).absolute()
    require(not any(_unsafe(p) for p in (root,*root.parents)), 'UNSAFE_QUEUE_ROOT')
    root=root.resolve()
    require(root != ROOT and ROOT not in root.parents, 'QUEUE_MUST_BE_OUTSIDE_REPOSITORY')
    return root


def folder_for(root, key):
    root=checked_root(root)
    require(isinstance(key,str) and JOB_ID.fullmatch(key), 'INVALID_JOB_ID')
    folder=root/key
    require(folder.is_dir() and not _unsafe(folder) and folder.resolve().parent==root, 'UNSAFE_JOB_FOLDER')
    return folder


def report_names(folder):
    return sorted(p.name for p in folder.iterdir() if REPORT.fullmatch(p.name) and p.is_file() and not _unsafe(p))


def list_jobs(root=QUEUE):
    root=checked_root(root)
    if not root.exists(): return []
    result=[]
    for folder in sorted(root.iterdir()):
        if not JOB_ID.fullmatch(folder.name) or not folder.is_dir() or _unsafe(folder): continue
        try:
            folder=folder_for(root,folder.name)
            job=decode(read(folder/'job.json',1024*1024))
            source=job.get('source_url')
            require(isinstance(source,str), 'INVALID_SOURCE_URL')
            result.append(dict(key=folder.name, model=str(job.get('model','?')), source_url=source, reports=report_names(folder)))
        except (ValueError,OSError,TypeError):
            result.append(dict(key=folder.name, model='INVALID_JOB',source_url=None,reports=[]))
    return result


CANDIDATE_STATUSES = ('REVIEW_REQUIRED', 'OCR_TABLE_REVIEW_REQUIRED')


def report_summary(root, key, name):
    """Metadata only: a report claiming candidate status is not validated."""
    folder = folder_for(root, key)
    require(isinstance(name, str) and REPORT.fullmatch(name) and name in report_names(folder), 'INVALID_REPORT_NAME')
    report = decode(read(folder/name, 1024*1024))
    status = report.get('status')
    if not isinstance(status, str) or not re.fullmatch(r'[A-Z_]{1,80}', status):
        status = 'UNKNOWN'
    reasons = []
    diagnostics = report.get('diagnostics')
    if isinstance(diagnostics, list):
        for page in diagnostics[:20]:
            if not isinstance(page, dict): continue
            entries = page.get('inspections', [])
            if not isinstance(entries, list): continue
            for entry in [page, *entries[:30]]:
                if not isinstance(entry, dict): continue
                items = entry.get('reasons', [])
                if not isinstance(items, list): items = []
                for reason in [*items[:30], entry.get('reason'), entry.get('warning')]:
                    if isinstance(reason, str) and re.fullmatch(r'[A-Z_]{1,100}', reason) and reason not in reasons:
                        reasons.append(reason)
    return {'status': status, 'reasons': reasons[:30]}


def preferred_report(names, summaries):
    """Prefer a reported candidate over a failed newer report, then OCR/version."""
    def order(name):
        number = re.search(r'\d+', name)
        return (summaries.get(name, {}).get('status') in CANDIDATE_STATUSES,
                name.startswith('ocr_'), int(number[0]) if number else 1, name)
    return max(names, key=order) if names else None


def filter_catalog(rows, statuses, query):
    q = query.strip().casefold()
    return [row for row in rows if row['status'] in statuses and
            (not q or any(q in str(row.get(k) or '').casefold() for k in ('title','model','source_url')))]


def report_message(summary):
    if summary.get('status') == 'NO_UNAMBIGUOUS_STC_TABLE':
        if 'INSTALLATION_MANUAL_NOT_DATASHEET' in summary.get('reasons', []):
            return 'Installation manual detected, not a datasheet. Obtain the correct manufacturer datasheet.'
        return 'No unambiguous STC table found. Check the document or extract new evidence. Approval disabled.'
    if summary.get('status') in CANDIDATE_STATUSES:
        return 'The report claims a candidate, but validation failed. Approval disabled.'
    return 'No validated candidate for this report. Approval disabled.'


@dataclass(frozen=True)
class Review:
    candidate: object
    pdf_url: str
    method: str
    ocr: object | None = None


def load_review(root,key,name):
    folder=folder_for(root,key)
    require(isinstance(name,str) and REPORT.fullmatch(name) and name in report_names(folder),'INVALID_REPORT_NAME')
    job=decode(read(folder/'job.json',1024*1024))
    require(isinstance(job.get('model'),str),'INVALID_JOB_MODEL')
    link=approved_document_url([job.get('pdf_url')])
    pdf=read(folder/'document.pdf',20*1024*1024)
    old=decode(read(folder/'review.json',1024*1024))
    require(old.get('pdf_sha256')==hashlib.sha256(pdf).hexdigest()
        and old.get('model_requested')==job['model'] and old.get('power_w_requested')==job.get('power_w'), 'JOB_PROVENANCE_MISMATCH')
    if name.startswith('ocr_'):
        page=int(re.search(r'page(\d+)\.json$',name)[1])
        item=validate_folder(folder,page,job['model'])
        require(item.pdf_url==link and item.candidate.source_url==job.get('source_url'),'JOB_SOURCE_MISMATCH')
        return Review(item.candidate,link,METHOD,item)
    c=validate_review(folder/'document.pdf',folder/name,source_url=job.get('source_url'),confirm_model=job['model'])
    require(c.power_w==job.get('power_w'),'JOB_POWER_MISMATCH')
    return Review(c,link,'local_pdf_manual_v1')


def catalog(cursor, url=None):
    if url is None:
        cursor.execute(SQL+' ORDER BY overall_rank')
        return [dict(zip(KEYS,row)) for row in cursor.fetchall()]
    cursor.execute(SQL+' WHERE source_url=%s',(url,))
    row=cursor.fetchone()
    if row is None: raise ApprovalError('Product not in current Gold catalog')
    return dict(zip(KEYS,row))


def get_connection():
    from scraper.load import get_connection as connect
    return connect()


def load_catalog():
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute('SET TRANSACTION READ ONLY')
        return catalog(cur)


def check_current(review,row):
    c=review.candidate
    require(row['source_url']==c.source_url,'CATALOG_SOURCE_MISMATCH')
    check_catalog_match(c,title=row['title'],catalog_power=row['power'])
    require(isinstance(row['links'],list) and review.pdf_url in row['links'],'PDF_URL_NOT_IN_CURRENT_CATALOG')
    if review.ocr is None:
        require(approved_document_url(row['links'])==review.pdf_url,'PDF_URL_NOT_FIRST_TRUSTED_LINK')


def blocker(review,row):
    check_current(review,row)
    if row['approval_id'] is not None: return 'An effective approval already exists; replacement disabled.'
    if row['status'] not in ('INCOMPLETE','REVIEW'): return 'Current catalog does not require review.'
    if review.ocr is None and has_unresolved_issues(row['issues']):
        return 'Text PDF has unresolved non-STC issues; approval disabled.'
    return None


def fingerprint(review,row):
    c=review.candidate
    body=[c.source_url,c.model,c.pdf_sha256,c.review_sha256,review.method,review.pdf_url,row]
    return hashlib.sha256(json.dumps(body,sort_keys=True,default=str).encode()).hexdigest()


def approve(root,key,name,*,expected,confirm_model,confirm_visual,write_enabled=False):
    require(write_enabled is True and confirm_visual is True,'WRITE_OR_VISUAL_CONFIRMATION_MISSING')
    review=load_review(root,key,name)
    c=review.candidate
    require(confirm_model==c.model,'EXACT_MODEL_CONFIRMATION_REQUIRED')
    # Serialize approvals via a transaction lock on the approval table. No external requests.
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute('SET LOCAL lock_timeout = \'3s\'')
        cur.execute('LOCK TABLE bronze.panel_pdf_approvals IN SHARE ROW EXCLUSIVE MODE')
        current=catalog(cur,c.source_url)
        require(fingerprint(review,current)==expected,'STALE_PREVIEW_REFRESH_REQUIRED')
        reason=blocker(review,current)
        require(reason is None,reason or '')
        if review.ocr is None: aid,created=write_text(cur,c,review.pdf_url)
        else: aid,created=write_ocr(cur,review.ocr)
        result=catalog(cur,c.source_url)
        require(created and result['approval_id']==aid and result['method']==review.method
            and result['pdf_stc_quality']=='PASS','APPROVAL_NOT_EFFECTIVE_ROLLBACK')
        require(all(float(result[k])==c.values_stc[k] for k in FIELDS),'GOLD_STC_MISMATCH_ROLLBACK')
        if has_unresolved_issues(current['issues']):
            require(result['status']=='REVIEW','UNRESOLVED_ISSUE_CONCEALED_ROLLBACK')
        return dict(approval_id=aid,status=result['status'],database_write=True)
