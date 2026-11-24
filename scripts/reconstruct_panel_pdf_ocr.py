"""Reconstruct local OCR evidence, with provenance checks; never write to PostgreSQL."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scraper.panel_pdf_ocr_table import reconstruct, require, TableError


def read(path, limit):
    require(not path.is_symlink() and path.is_file() and path.stat().st_size <= limit, 'MISSING_OR_UNSAFE_FILE: '+path.name)
    return path.read_bytes()


def unique(pairs):
    result = {}
    for k,v in pairs:
        require(k not in result, 'DUPLICATE_JSON_KEY')
        result[k] = v
    return result


def decode(raw):
    obj = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=unique)
    require(isinstance(obj,dict), 'INVALID_JSON_OBJECT')
    return obj


def run(folder, page):
    require(folder.is_dir() and not folder.is_symlink() and type(page) is int and 1 <= page <= 20, 'INVALID_FOLDER_OR_PAGE')
    out = folder/f'ocr_table_review_page{page}.json'
    require(not out.exists() and not out.is_symlink(), 'REPORT_ALREADY_EXISTS')
    pdf = read(folder/'document.pdf', 20*1024*1024)
    require(pdf.startswith(b'%PDF-'), 'NOT_PDF')
    digest = hashlib.sha256(pdf).hexdigest()
    job = decode(read(folder/'job.json', 1024*1024))
    old = decode(read(folder/'review.json', 1024*1024))
    raw = read(folder/f'ocr_evidence_page{page}.json', 8*1024*1024)
    evidence = decode(raw)
    require(old.get('status') == 'NO_UNAMBIGUOUS_STC_TABLE' and old.get('database_write') is False
            and old.get('candidates') == [] and old.get('pdf_sha256') == digest == evidence.get('pdf_sha256')
            and old.get('model_requested') == job.get('model') == evidence.get('model_requested')
            and old.get('power_w_requested') == job.get('power_w') == evidence.get('power_w_requested')
            and evidence.get('page') == page, 'EVIDENCE_PROVENANCE_MISMATCH')
    report = reconstruct(evidence)
    report['ocr_evidence_sha256'] = hashlib.sha256(raw).hexdigest()
    report['source_url'] = job.get('source_url')
    report['source_pdf_url'] = job.get('pdf_url')
    with out.open('x',encoding='utf-8') as f:
        json.dump(report,f,ensure_ascii=False,indent=2,allow_nan=False)
    return dict(status=report['status'], report=str(out), proposed_values=report['proposed_values'], database_write=False)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--folder',type=Path,required=True)
    p.add_argument('--page',type=int,default=2)
    a=p.parse_args(argv)
    folder=a.folder.absolute()
    if folder.resolve()==ROOT or ROOT in folder.resolve().parents:
        p.error('Use evidence directory outside repository')
    try:
        print(json.dumps(run(folder,a.page),indent=2)); return 0
    except (ValueError, OSError, TypeError, KeyError) as exc:
        print(f'OCR TABLE REVIEW ERROR: {exc}',file=sys.stderr); return 1

if __name__=='__main__': raise SystemExit(main())
