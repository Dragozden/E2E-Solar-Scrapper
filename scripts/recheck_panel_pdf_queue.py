"""Reanalyse downloaded evidence only; no DB, downloads, or approvals."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))
from scripts.panel_pdf_preview import extract_stc_lines
from scraper.panel_pdf_approval import validate_stc, ApprovalError
from scraper.panel_detail_specs import is_allowed_detail_url


def recheck(folder, extract=extract_stc_lines):
    output=folder/'review_v2.json'
    if output.exists():
        return {'folder':folder.name,'status':'ALREADY_RECHECKED'}
    for name in ('job.json','review.json','document.pdf'):
        if not (folder/name).is_file() or (folder/name).is_symlink():
            raise ValueError('Missing or unsafe evidence file')
    job=json.loads((folder/'job.json').read_text(encoding='utf-8-sig'))
    old=json.loads((folder/'review.json').read_text(encoding='utf-8-sig'))
    pdf=folder/'document.pdf'
    if pdf.stat().st_size>20*1024*1024:
        raise ValueError('PDF too large')
    raw=pdf.read_bytes(); digest=hashlib.sha256(raw).hexdigest()
    model=job['model']; power=job['power_w']
    if (not raw.startswith(b'%PDF-') or digest!=old.get('pdf_sha256') or
        old.get('model_requested')!=model or old.get('power_w_requested')!=power or
        old.get('database_write') is not False or not is_allowed_detail_url(job['source_url']) or
        not isinstance(power,int) or isinstance(power,bool) or not 100<=power<=900 or
        not isinstance(model,str) or not re.search(rf'(?<!\d){power}(?!\d)',model)):
        raise ValueError('Evidence mismatch')
    candidates,diag=extract(pdf,model=model,power=power)
    valid=len(candidates)==1
    if valid:
        try: validate_stc(candidates[0].values,power)
        except ApprovalError as exc:
            valid=False; diag.append({'warning':'APPROVAL_VALIDATION_FAILED','reason':str(exc)})
    report=dict(status='REVIEW_REQUIRED' if valid else 'NO_UNAMBIGUOUS_STC_TABLE',
                model_requested=model,power_w_requested=power,pdf_sha256=digest,
                candidates=[c.as_dict() for c in candidates],diagnostics=diag,database_write=False)
    with output.open('x',encoding='utf-8') as fp:
        json.dump(report,fp,indent=2,ensure_ascii=False)
    return dict(folder=folder.name,model=model,status=report['status'],report=str(output))


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--directory',type=Path,default=Path.home()/'Downloads'/'SolarSpecs'/'queue')
    a=p.parse_args(argv); root=a.directory.resolve()
    if not root.is_dir() or root==ROOT or ROOT in root.parents:
        p.error('Use an existing evidence directory outside repository')
    import pdfplumber
    results=[]
    for folder in sorted(root.iterdir()):
        if folder.is_symlink() or not folder.is_dir() or not re.fullmatch(r'[a-f0-9]{24}',folder.name): continue
        try: results.append(recheck(folder))
        except Exception as exc: results.append(dict(folder=folder.name,status='RECHECK_ERROR',error=type(exc).__name__))
    print(json.dumps(results,indent=2,ensure_ascii=False))
    return int(any(r['status']=='RECHECK_ERROR' for r in results))

if __name__=='__main__': raise SystemExit(main())
