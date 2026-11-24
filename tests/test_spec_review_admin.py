import hashlib
import json
from pathlib import Path
from dataclasses import replace
import pytest
from dashboard import spec_review_admin as a
from scripts.reconstruct_panel_pdf_ocr import run
from scraper.panel_pdf_stc import family_token

KEY='a'*24
URL='https://sklepsoltech.pl/pl/p/Panel-fotowoltaiczny-JA-SOLAR-505-JAM60D40-505-LB-Bifacial-BF/4312'
LINK='https://sklepsoltech.pl/pl/p/file/test/card.pdf'
MODEL='JAM60D40-505/LB'
NAME='ocr_table_review_page2.json'

@pytest.fixture
def local(tmp_path):
    root=tmp_path/'queue'; folder=root/KEY; folder.mkdir(parents=True)
    evidence=json.loads((Path(__file__).parent/'fixtures/ocr_ja_stc_tokens.json').read_text(encoding='utf8'))
    pdf=b'%PDF-1.4\nfixture'; (folder/'document.pdf').write_bytes(pdf)
    evidence['pdf_sha256']=hashlib.sha256(pdf).hexdigest()
    old=dict(status='NO_UNAMBIGUOUS_STC_TABLE',database_write=False,candidates=[],model_requested=MODEL,power_w_requested=505,pdf_sha256=evidence['pdf_sha256'])
    for name,obj in [('job.json',dict(model=MODEL,power_w=505,source_url=URL,pdf_url=LINK)),('review.json',old),('ocr_evidence_page2.json',evidence)]:
        (folder/name).write_text(json.dumps(obj),encoding='utf8')
    run(folder,2)
    return root,folder

@pytest.fixture
def candidate(local):
    return a.load_review(local[0],KEY,NAME)

@pytest.fixture
def row(candidate):
    return dict(source_url=URL,title='JA SOLAR JAM60D40-505 LB',power=505,links=[LINK],issues=['conflicting_bifaciality_pct'],approval_id=None,status='REVIEW',method=None,pdf_stc_quality=None,spec_hash='v1')


def test_list(local):
    (local[0]/'not-a-job').mkdir()
    assert a.list_jobs(local[0])==[dict(key=KEY,model=MODEL,source_url=URL,reports=[NAME,'review.json'])]

@pytest.mark.parametrize('key',['../other','a'*23,'A'*24])
def test_bad_path(local,key):
    with pytest.raises(ValueError): a.folder_for(local[0],key)

@pytest.mark.parametrize('name',['../review.json','job.json','ocr_evidence_page2.json'])
def test_bad_report(local,name):
    with pytest.raises(ValueError): a.load_review(local[0],KEY,name)


def test_symlink(local):
    link=local[0]/('b'*24)
    try: link.symlink_to(local[1],target_is_directory=True)
    except OSError: pytest.skip('symlink unavailable')
    with pytest.raises(ValueError): a.folder_for(local[0],link.name)


def test_real_reconstruction_fixture(candidate):
    assert candidate.method==a.METHOD and candidate.candidate.values_stc['voc_v']==44.05


def test_text(local,candidate):
    c=candidate.candidate
    report=dict(status='REVIEW_REQUIRED',database_write=False,model_requested=MODEL,power_w_requested=505,pdf_sha256=c.pdf_sha256,candidates=[dict(power_w=505,model_family=family_token(MODEL),page=2,variant_column_zero_based=4,values=c.values_stc)])
    (local[1]/'review_v2.json').write_text(json.dumps(report))
    assert a.load_review(local[0],KEY,'review_v2.json').ocr is None


def test_tamper_pdf(local):
    (local[1]/'document.pdf').write_bytes(b'%PDF-1.4\nchanged')
    with pytest.raises(ValueError): a.load_review(local[0],KEY,NAME)


def test_tamper_report(local):
    p=local[1]/NAME; report=json.loads(p.read_text()); report['proposed_values']['voc_v']=44.06; p.write_text(json.dumps(report))
    with pytest.raises(ValueError): a.load_review(local[0],KEY,NAME)


def test_blockers(candidate,row):
    assert a.blocker(candidate,row) is None
    assert a.blocker(replace(candidate,ocr=None),row)
    assert a.blocker(candidate,dict(row,approval_id=7))
    assert a.blocker(candidate,dict(row,status='PASS'))
    with pytest.raises(ValueError): a.blocker(candidate,dict(row,links=[]))
    with pytest.raises(ValueError): a.blocker(candidate,dict(row,power=500))
    with pytest.raises(ValueError): a.blocker(candidate,dict(row,source_url='other'))


class Fake:
    def __init__(self): self.statements=[]; self.error=None
    def __enter__(self): return self
    def __exit__(self,typ,*args): self.error=typ
    def cursor(self): return self
    def execute(self,sql,*args): self.statements.append(sql)


def test_read_only(monkeypatch):
    conn=Fake(); monkeypatch.setattr(a,'get_connection',lambda:conn); monkeypatch.setattr(a,'catalog',lambda cur:[])
    assert a.load_catalog()==[] and conn.statements==['SET TRANSACTION READ ONLY']


@pytest.mark.parametrize('write,visual,model',[(False,True,MODEL),(True,False,MODEL),(True,True,'wrong')])
def test_confirmation(local,candidate,row,monkeypatch,write,visual,model):
    monkeypatch.setattr(a,'get_connection',lambda:pytest.fail('DB must not be called'))
    with pytest.raises(ValueError): a.approve(local[0],KEY,NAME,expected=a.fingerprint(candidate,row),confirm_model=model,confirm_visual=visual,write_enabled=write)


@pytest.mark.parametrize('mode',['success','stale','already','concealed','mismatch','wrong_method'])
def test_transaction(local,candidate,row,monkeypatch,mode):
    conn=Fake(); monkeypatch.setattr(a,'get_connection',lambda:conn)
    current=dict(row)
    if mode=='stale': current['spec_hash']='v2'
    if mode=='already': current['approval_id']=7; row['approval_id']=7
    result=dict(current,approval_id=8,method=a.METHOD,pdf_stc_quality='PASS',**candidate.candidate.values_stc)
    if mode=='concealed': result['status']='PASS'
    if mode=='mismatch': result['voc_v']=99
    if mode=='wrong_method': result['method']='other'
    records=iter([current,result]); monkeypatch.setattr(a,'catalog',lambda *args:next(records))
    calls=[]
    def insert(*args): calls.append(1); return 8,True
    monkeypatch.setattr(a,'write_ocr',insert)
    kwargs=dict(expected=a.fingerprint(candidate,row),confirm_model=MODEL,confirm_visual=True,write_enabled=True)
    if mode=='success':
        assert a.approve(local[0],KEY,NAME,**kwargs)==dict(approval_id=8,status='REVIEW',database_write=True)
        assert conn.error is None
    else:
        with pytest.raises(ValueError): a.approve(local[0],KEY,NAME,**kwargs)
        assert conn.error is not None
    assert len(calls)==(0 if mode in ('stale','already') else 1)
    assert any('LOCK TABLE' in x for x in conn.statements)


def test_manual_diagnostic(local):
    report={'status':'NO_UNAMBIGUOUS_STC_TABLE','diagnostics':[{'warning':'INSTALLATION_MANUAL_NOT_DATASHEET'}]}
    (local[1]/'review_v2.json').write_text(json.dumps(report))
    summary=a.report_summary(local[0],KEY,'review_v2.json')
    assert summary=={'status':'NO_UNAMBIGUOUS_STC_TABLE','reasons':['INSTALLATION_MANUAL_NOT_DATASHEET']}
    assert 'Installation manual' in a.report_message(summary)


def test_nested_diagnostics(local):
    report={'status':'NO_UNAMBIGUOUS_STC_TABLE','diagnostics':[{'inspections':[{'reasons':['TARGET_POWER_NOT_UNIQUE','bad arbitrary text']},{'warning':'NO_SPATIAL_STC_HEADING'}]}]}
    (local[1]/'review_v2.json').write_text(json.dumps(report))
    summary=a.report_summary(local[0],KEY,'review_v2.json')
    assert summary['reasons']==['TARGET_POWER_NOT_UNIQUE','NO_SPATIAL_STC_HEADING']
    assert 'No unambiguous' in a.report_message(summary)


def test_preferred_report():
    names=['review.json','review_v2.json','review_v10.json',NAME]
    info={n:{'status':'REVIEW_REQUIRED'} for n in names}
    info[NAME]['status']='UNKNOWN'
    assert a.preferred_report(names,info)=='review_v10.json'
    info[NAME]['status']='OCR_TABLE_REVIEW_REQUIRED'
    assert a.preferred_report(names,info)==NAME
    assert a.preferred_report([],{}) is None


def test_filter_catalog():
    rows=[dict(title='JA Solar 505',model='JAM60D40',status='REVIEW'),dict(title='LONGi',model=None,status='PASS')]
    assert a.filter_catalog(rows,['REVIEW'],' ja SOLAR ')==rows[:1]
    assert a.filter_catalog(rows,['PASS'],'JAM60D40')==[]
    assert a.filter_catalog(rows,['PASS'],'')==rows[1:]
    assert a.filter_catalog(rows,[],'')==[]


def test_metadata_not_authorization(local):
    report={'status':'REVIEW_REQUIRED','diagnostics':[]}
    (local[1]/'review_v2.json').write_text(json.dumps(report))
    summary=a.report_summary(local[0],KEY,'review_v2.json')
    assert 'validation failed' in a.report_message(summary)
    with pytest.raises(ValueError): a.load_review(local[0],KEY,'review_v2.json')
