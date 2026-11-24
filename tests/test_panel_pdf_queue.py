"""Offline queue tests; HTTP, database and parser are mocked unless stated."""
import json
from pathlib import Path
from decimal import Decimal
import pytest
from scripts import panel_pdf_queue as q
from scraper.panel_pdf_stc import StcCandidate

URL = 'https://sklepsoltech.pl/pl/p/Panel-TWMNH-54HD500/3515'
PDF = 'https://sklepsoltech.pl/pl/p/file/abc/card.pdf'
VALUES = dict(rated_power_w=500., voc_v=40.06, isc_a=15.89, vmp_v=33.70, imp_a=14.84, efficiency_pct=22.5)

def row(**changes):
    fields=dict(rank=1,title='Panel TW Solar TWMNH-54HD500 BF',url=URL,watts=Decimal('500'),model='TWMNH-54HD500',status='INCOMPLETE',links=[PDF],issues=[])
    fields.update(changes)
    return tuple(fields.values())

def test_plan_ready(tmp_path):
    item, = q.make_plan([row()], tmp_path)
    assert item['state']=='READY' and item['power_w']==500 and item['pdf_url']==PDF
    assert not Path(item['folder']).exists()

@pytest.mark.parametrize('changes,state', [
    ({'links':[]},'NO_TRUSTED_PDF'),
    ({'links':['https://example.org/x.pdf']},'NO_TRUSTED_PDF'),
    ({'links':['https://sklepsoltech.pl/x.pdf']},'UNSUPPORTED_PDF_PATH'),
    ({'url':'https://example.org/p/1'},'UNTRUSTED_PRODUCT'),
    ({'model':None},'MODEL_CONFIRMATION_NEEDED'),
    ({'model':'TWMNH-54HD505'},'MODEL_CONFIRMATION_NEEDED'),
    ({'model':'OTHER500'},'MODEL_CONFIRMATION_NEEDED'),
    ({'watts':Decimal('500.5')},'INVALID_POWER'),
])
def test_blocks_unsafe_jobs(tmp_path,changes,state):
    assert q.make_plan([row(**changes)],tmp_path)[0]['state']==state

def test_manual_mapping(tmp_path):
    assert q.make_plan([row(model=None)],tmp_path,{URL:'TWMNH-54HD500'})[0]['state']=='READY'

def test_resume(tmp_path):
    item=q.make_plan([row()],tmp_path)[0]
    Path(item['folder']).mkdir()
    assert q.make_plan([row()],tmp_path)[0]['state']=='ALREADY_ATTEMPTED'

def test_run_local_review(tmp_path):
    calls=[]; delays=[]
    def fetch(url,limit):
        calls.append(url)
        return b'User-agent: *\nAllow: /\n' if url.endswith('robots.txt') else b'%PDF-1.7\nmock'
    def extract(pdf,**kw):
        return [StcCandidate(page=2,power_w=500,variant_column=1,model_family='TWMNH-54HD',values=VALUES,warning='manual')],[]
    items=q.make_plan([row()],tmp_path)
    result,=q.run_queue(items,tmp_path,5,10,fetch=fetch,extract=extract,sleep=delays.append)
    assert result['status']=='REVIEW_REQUIRED'
    report=json.loads((Path(result['folder'])/'review.json').read_text())
    assert report['database_write'] is False and len(report['candidates'])==1
    assert (Path(result['folder'])/'document.pdf').exists()
    assert len(calls)==2 and delays==[10] and not (tmp_path/'.queue.lock').exists()
    assert q.make_plan([row()],tmp_path)[0]['state']=='ALREADY_ATTEMPTED'

def test_robots_blocks_pdf(tmp_path):
    calls=[]
    def fetch(url,limit):
        calls.append(url); return b'User-agent: *\nDisallow: /pl/p/file/\n'
    result,=q.run_queue(q.make_plan([row()],tmp_path),tmp_path,5,10,fetch=fetch,sleep=lambda _:None)
    assert result['status']=='ROBOTS_DISALLOWED' and len(calls)==1

def test_download_error_stops_batch(tmp_path):
    calls=[]
    def fetch(url,limit):
        calls.append(url)
        if url.endswith('robots.txt'):return b'User-agent: *\nAllow: /\n'
        raise OSError('blocked')
    items=q.make_plan([row(),row(url=URL+'0')],tmp_path)
    results=q.run_queue(items,tmp_path,5,10,fetch=fetch,sleep=lambda _:None)
    assert len(results)==1 and results[0]['status']=='DOWNLOAD_STOPPED' and len(calls)==2
    assert (Path(items[0]['folder'])/'failure.json').exists()

def test_bad_pdf_never_parsed(tmp_path):
    def fetch(url,limit):return b'User-agent: *\nAllow: /\n' if url.endswith('robots.txt') else b'<html>'
    results=q.run_queue(q.make_plan([row()],tmp_path),tmp_path,1,10,fetch=fetch,extract=lambda *a,**k: pytest.fail('parsed HTML'),sleep=lambda _:None)
    assert results[0]['status']=='DOWNLOAD_STOPPED'

def test_approval_validation_still_required(tmp_path):
    def fetch(url,limit):return b'User-agent: *\nAllow: /\n' if url.endswith('robots.txt') else b'%PDF-1.7\nmock'
    bad=dict(VALUES);bad.pop('efficiency_pct')
    def extract(pdf,**kw):return [StcCandidate(2,500,1,'TWMNH-54HD',bad,'manual')],[]
    result,=q.run_queue(q.make_plan([row()],tmp_path),tmp_path,1,10,fetch=fetch,extract=extract,sleep=lambda _:None)
    assert result['status']=='NO_UNAMBIGUOUS_STC_TABLE'

def test_run_requires_explicit_network():
    with pytest.raises(SystemExit):q.main(['run'])

def test_plan_no_network_or_disk(tmp_path, monkeypatch):
    monkeypatch.setattr(q,'load_rows',lambda:[row()])
    monkeypatch.setattr(q,'run_queue',lambda *a,**k: pytest.fail('network attempted'))
    assert q.main(['plan','--directory',str(tmp_path/'out')])==0
    assert not (tmp_path/'out').exists()
