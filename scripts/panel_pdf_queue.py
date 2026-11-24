"""Bounded, resumable PDF preview queue. No database writes or approvals."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlsplit
from urllib.request import build_opener, HTTPRedirectHandler, Request
from urllib.robotparser import RobotFileParser

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scraper.panel_detail_specs import is_allowed_detail_url
from scraper.panel_pdf_approval import approved_document_url, validate_stc, ApprovalError
from scraper.panel_pdf_stc import family_token
from scripts.panel_pdf_preview import extract_stc_lines

HOST = 'sklepsoltech.pl'
AGENT = 'SolarSpecReview/1.0'
MAX_BYTES = 20 * 1024 * 1024

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def read_url(url, limit):
    """Only the catalog host, no redirects, no retries, bounded response."""
    p = urlsplit(url)
    if (p.scheme != 'https' or p.hostname != HOST or p.username is not None
            or p.password is not None or p.port not in (None, 443)
            or p.query or p.fragment or not (p.path == '/robots.txt' or
                re.fullmatch(r'/pl/p/file/[^/]+/[^/]+\.pdf', p.path, re.I))):
        raise ValueError('Untrusted download URL')
    with build_opener(NoRedirect()).open(Request(url, headers={'User-Agent': AGENT}), timeout=30) as response:
        data = response.read(limit + 1)
    if not data or len(data) > limit:
        raise ValueError('Empty or oversized HTTP response')
    return data


def load_rows():
    from scraper.load import get_connection
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('SET TRANSACTION READ ONLY')
            cur.execute('''SELECT overall_rank, title, source_url, catalog_power_w,
                                  model, technical_status, datasheet_urls, parse_issues
                           FROM gold.panel_technical_comparison
                           WHERE technical_status IN ('INCOMPLETE', 'REVIEW')
                           ORDER BY CASE WHEN technical_status='INCOMPLETE' THEN 0 ELSE 1 END,
                                    overall_rank''')
            return cur.fetchall()


def make_plan(rows, root, overrides=None):
    overrides = overrides or {}
    items = []
    for rank, title, url, watts, model, status, links, issues in rows:
        item = dict(rank=rank, title=title, source_url=url, status=status,
                    parse_issues=issues, model=overrides.get(url, model), state='READY')
        items.append(item)
        try:
            item['pdf_url'] = approved_document_url(links)
        except ApprovalError:
            item['state'] = 'NO_TRUSTED_PDF'; continue
        if not is_allowed_detail_url(url):
            item['state'] = 'UNTRUSTED_PRODUCT'; continue
        if not re.fullmatch(r'/pl/p/file/[^/]+/[^/]+\.pdf', urlsplit(item['pdf_url']).path, re.I):
            item['state'] = 'UNSUPPORTED_PDF_PATH'; continue
        if watts is None or not 100 <= watts <= 900 or int(watts) != watts:
            item['state'] = 'INVALID_POWER'; continue
        power = int(watts)
        item['power_w'] = power
        m = item['model']
        normal = lambda s: re.sub(r'[^a-z0-9]', '', s.casefold())
        if (not isinstance(m, str) or not m.strip() or len(m) > 100 or
            not re.search(rf'(?<!\d){power}(?!\d)', m) or not family_token(m) or
            normal(m) not in normal(title)):
            item['state'] = 'MODEL_CONFIRMATION_NEEDED'; continue
        key = hashlib.sha256(json.dumps([url, item['pdf_url'], m, power], ensure_ascii=False).encode()).hexdigest()[:24]
        item['folder'] = str(root / key)
        if (root / key).exists():
            item['state'] = 'ALREADY_ATTEMPTED'
    return items


def run_queue(items, root, limit, delay, *, fetch=read_url, extract=extract_stc_lines, sleep=time.sleep):
    """Stop on HTTP/robots errors. Keep all evidence. No approval invocation."""
    selected = [i for i in items if i['state'] == 'READY'][:limit]
    if not selected:
        return []
    root.mkdir(parents=True, exist_ok=True)
    lock = root / '.queue.lock'
    with lock.open('x', encoding='utf-8') as fp:
        fp.write('PDF preview queue active\n')
    results = []
    try:
        robots = RobotFileParser()
        robots.parse(fetch(f'https://{HOST}/robots.txt', 512 * 1024).decode('utf-8', errors='strict').splitlines())
        delay = max(delay, robots.crawl_delay(AGENT) or 0, robots.crawl_delay('*') or 0)
        rate = robots.request_rate(AGENT) or robots.request_rate('*')
        if rate and rate.requests > 0:
            delay = max(delay, rate.seconds / rate.requests)
        for item in selected:
            if not robots.can_fetch(AGENT, item['pdf_url']):
                results.append({'source_url': item['source_url'], 'status': 'ROBOTS_DISALLOWED'})
                continue
            sleep(delay)
            folder = Path(item['folder'])
            folder.mkdir(exist_ok=False)
            (folder / 'job.json').write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding='utf-8')
            try:
                raw = fetch(item['pdf_url'], MAX_BYTES)
                if not raw.startswith(b'%PDF-') or len(raw) > MAX_BYTES:
                    raise ValueError('Invalid PDF response')
            except Exception as exc:
                result = {'source_url': item['source_url'], 'status': 'DOWNLOAD_STOPPED', 'error': type(exc).__name__}
                (folder / 'failure.json').write_text(json.dumps(result), encoding='utf-8')
                results.append(result)
                break
            pdf = folder / 'document.pdf'
            pdf.write_bytes(raw)
            try:
                candidates, diagnostics = extract(pdf, model=item['model'], power=item['power_w'])
                valid = len(candidates) == 1
                if valid:
                    try:
                        validate_stc(candidates[0].values, item['power_w'])
                    except ApprovalError as exc:
                        valid = False
                        diagnostics.append({'warning': 'APPROVAL_VALIDATION_FAILED', 'reason': str(exc)})
                report = dict(status='REVIEW_REQUIRED' if valid else 'NO_UNAMBIGUOUS_STC_TABLE',
                              model_requested=item['model'], power_w_requested=item['power_w'],
                              pdf_sha256=hashlib.sha256(raw).hexdigest(),
                              candidates=[c.as_dict() for c in candidates], diagnostics=diagnostics,
                              database_write=False)
            except Exception as exc:
                report = dict(status='PDF_READ_FAIL', model_requested=item['model'],
                              power_w_requested=item['power_w'], pdf_sha256=hashlib.sha256(raw).hexdigest(),
                              candidates=[], diagnostics=[{'warning': type(exc).__name__}], database_write=False)
            with (folder / 'review.json').open('x', encoding='utf-8') as fp:
                json.dump(report, fp, indent=2, ensure_ascii=False)
            results.append({'source_url': item['source_url'], 'status': report['status'], 'folder': str(folder)})
        return results
    finally:
        lock.unlink(missing_ok=True)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=['plan', 'run'])
    p.add_argument('--limit', type=int, default=5)
    p.add_argument('--delay-seconds', type=float, default=10)
    p.add_argument('--directory', type=Path, default=Path.home()/'Downloads'/'SolarSpecs'/'queue')
    p.add_argument('--model-map', type=Path, help='Optional JSON mapping exact current product URLs to manually inspected model tokens')
    p.add_argument('--download', action='store_true', help='Explicit opt-in to permitted HTTP requests; run only')
    a = p.parse_args(argv)
    if not 1 <= a.limit <= 10 or not 10 <= a.delay_seconds <= 120:
        p.error('limit 1..10; delay 10..120 seconds')
    if a.command == 'run' and not a.download:
        p.error('run requires --download; use plan for read-only preview')
    try:
        overrides = json.loads(a.model_map.read_text(encoding='utf-8-sig')) if a.model_map else {}
        if not isinstance(overrides, dict) or not all(isinstance(k,str) and isinstance(v,str) for k,v in overrides.items()):
            raise ValueError('Invalid model map')
        root = a.directory.resolve()
        if root == ROOT or ROOT in root.parents:
            raise ValueError('Evidence directory must be outside the Git repository')
        items = make_plan(load_rows(), root, overrides)
        ready = [i for i in items if i['state'] == 'READY']
        print(json.dumps({'items': items, 'ready': len(ready),
                          'selected': [i['source_url'] for i in ready[:a.limit]],
                          'database_write': False}, ensure_ascii=False, indent=2, default=str))
        if a.command == 'run':
            import pdfplumber  # fail before network if missing
            results = run_queue(items, root, a.limit, a.delay_seconds)
            print('RESULTS: ' + json.dumps(results, ensure_ascii=False, indent=2))
            return int(any(r['status']=='DOWNLOAD_STOPPED' for r in results))
        return 0
    except Exception as exc:
        print(f'QUEUE ERROR: {type(exc).__name__}; check DB, directory, robots and configuration', file=sys.stderr)
        return 1

if __name__ == '__main__':
    raise SystemExit(main())
