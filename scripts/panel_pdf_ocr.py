"""Local OCR evidence pilot. Never generates an importable approval report."""
from __future__ import annotations
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def recognize(image_bytes, executable):
    result = subprocess.run([executable, 'stdin', 'stdout', '-l', 'eng', '--psm', '11', 'tsv'],
                            input=image_bytes, capture_output=True, timeout=60, check=True)
    return result.stdout.decode('utf-8')


def parse_words(tsv):
    words = []
    for row in csv.DictReader(io.StringIO(tsv), delimiter='\t'):
        if row.get('level') != '5' or not row.get('text','').strip():
            continue
        words.append(dict(text=row['text'], confidence=float(row['conf']),
                          left=int(row['left']), top=int(row['top']),
                          width=int(row['width']), height=int(row['height'])))
    return words


def page_image(pdf, page_number):
    import pdfplumber
    with pdfplumber.open(pdf) as doc:
        if len(doc.pages)>20 or not 1<=page_number<=len(doc.pages):
            raise ValueError('Page outside supported range')
        page = doc.pages[page_number-1]
        chars = len((page.extract_text() or '').strip())
        if chars >= 250:
            raise ValueError('Readable text layer; use normal parser, not OCR')
        if page.width*page.height*(250/72)**2 > 20_000_000:
            raise ValueError('Rendered page exceeds pixel limit')
        image = page.to_image(resolution=250).original
        buf = io.BytesIO(); image.save(buf, format='PNG')
        return buf.getvalue(), image.size, chars


def run(folder, page, executable, *, render=page_image, ocr=recognize):
    if folder.is_symlink() or not folder.is_dir():
        raise ValueError('Missing or unsafe evidence directory')
    if not 1<=page<=20:
        raise ValueError('Invalid page')
    output=folder/f'ocr_evidence_page{page}.json'
    if output.exists() or output.is_symlink():
        return {'status':'ALREADY_OCR_ANALYZED','report':str(output)}
    for name in ('job.json','review.json','document.pdf'):
        p=folder/name
        if p.is_symlink() or not p.is_file():
            raise ValueError('Missing or unsafe evidence file')
    job=json.loads((folder/'job.json').read_text(encoding='utf-8-sig'))
    old=json.loads((folder/'review.json').read_text(encoding='utf-8-sig'))
    pdf=folder/'document.pdf'
    if pdf.stat().st_size>20*1024*1024:
        raise ValueError('PDF too large')
    raw=pdf.read_bytes(); digest=hashlib.sha256(raw).hexdigest()
    if (not raw.startswith(b'%PDF-') or old.get('pdf_sha256')!=digest
        or old.get('model_requested')!=job.get('model')
        or old.get('power_w_requested')!=job.get('power_w')
        or old.get('database_write') is not False
        or old.get('status')!='NO_UNAMBIGUOUS_STC_TABLE'):
        raise ValueError('Evidence mismatch or original report not failed')
    # Do not re-OCR a document already recovered by the text parser.
    for report in folder.glob('review_v*.json'):
        if report.is_symlink():
            raise ValueError('Unsafe evidence report')
        newer=json.loads(report.read_text(encoding='utf-8-sig'))
        if newer.get('pdf_sha256')!=digest:
            raise ValueError('Evidence mismatch')
        if newer.get('status')=='REVIEW_REQUIRED':
            raise ValueError('Text parser already recovered this document')
    png, size, chars=render(pdf,page)
    words=parse_words(ocr(png,executable))
    report=dict(status='OCR_EVIDENCE_ONLY',model_requested=job['model'],
                power_w_requested=job['power_w'],pdf_sha256=digest,page=page,
                resolution_dpi=250,image_width=size[0],image_height=size[1],
                text_layer_characters=chars,ocr_language='eng',ocr_words=words,
                candidates=[],database_write=False,
                warning='Unverified OCR tokens. Never import or infer STC values from this report.')
    with output.open('x',encoding='utf-8') as fp:
        json.dump(report,fp,indent=2,ensure_ascii=False)
    return dict(status=report['status'],report=str(output),words=len(words))


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--folder',type=Path,required=True)
    p.add_argument('--page',type=int,default=2)
    p.add_argument('--tesseract',default='tesseract',help='Executable name or absolute path')
    a=p.parse_args(argv); folder=a.folder.resolve()
    if folder==ROOT or ROOT in folder.parents:
        p.error('Use evidence directory outside repository')
    exe=shutil.which(a.tesseract)
    if not exe:
        p.error('Tesseract executable not found; install Tesseract and add it to PATH or pass --tesseract')
    try:
        print(json.dumps(run(folder,a.page,exe),indent=2,ensure_ascii=False)); return 0
    except (ValueError,OSError,subprocess.SubprocessError) as exc:
        print(f'OCR EVIDENCE ERROR: {type(exc).__name__}: {exc}',file=sys.stderr); return 1

if __name__=='__main__': raise SystemExit(main())
