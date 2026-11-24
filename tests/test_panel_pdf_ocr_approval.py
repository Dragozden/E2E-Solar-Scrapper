import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import pytest
from scripts import approve_panel_pdf_ocr as cli
from scripts.reconstruct_panel_pdf_ocr import run
from scraper.panel_pdf_approval import ApprovalError, validate_review

URL='https://sklepsoltech.pl/pl/p/Panel-fotowoltaiczny-JA-SOLAR-505-JAM60D40-505-LB-Bifacial-BF/4312'
LINK='https://sklepsoltech.pl/pl/p/file/test/card.pdf'
MODEL='JAM60D40-505/LB'

@pytest.fixture
def folder(tmp_path):
    evidence=json.loads((Path(__file__).parent/'fixtures/ocr_ja_stc_tokens.json').read_text(encoding='utf8'))
    pdf=b'%PDF-1.4\nfixture'; (tmp_path/'document.pdf').write_bytes(pdf)
    evidence['pdf_sha256']=hashlib.sha256(pdf).hexdigest()
    for name,obj in [('job.json',dict(model=MODEL,power_w=505,source_url=URL,pdf_url=LINK)),
        ('review.json',dict(status='NO_UNAMBIGUOUS_STC_TABLE',database_write=False,candidates=[],model_requested=MODEL,power_w_requested=505,pdf_sha256=evidence['pdf_sha256'])),
        ('ocr_evidence_page2.json',evidence)]:
        (tmp_path/name).write_text(json.dumps(obj),encoding='utf8')
    run(tmp_path,2)
    return tmp_path


def test_replay(folder):
    item=cli.validate_folder(folder,2,MODEL)
    assert item.candidate.values_stc['voc_v']==44.05
    assert item.pdf_url==LINK and item.candidate.variant_column==4
    assert item.evidence_sha256==hashlib.sha256((folder/'ocr_evidence_page2.json').read_bytes()).hexdigest()

@pytest.mark.parametrize('file,key,value',[
    ('ocr_table_review_page2.json','proposed_values',{'rated_power_w':505}),
    ('ocr_table_review_page2.json','source_pdf_url','https://sklepsoltech.pl/other.pdf'),
    ('ocr_table_review_page2.json','ocr_evidence_sha256','0'*64),
    ('ocr_table_review_page2.json','variant_column_zero_based',3),
    ('ocr_evidence_page2.json','page',3),
    ('job.json','source_url','https://evil.example/x'),
    ('job.json','pdf_url','https://evil.example/x.pdf'),
    ('review.json','status','REVIEW_REQUIRED'),
])
def test_tamper(folder,file,key,value):
    path=folder/file; obj=json.loads(path.read_text()); obj[key]=value; path.write_text(json.dumps(obj))
    with pytest.raises(ValueError): cli.validate_folder(folder,2,MODEL)


def test_changed_pdf(folder):
    (folder/'document.pdf').write_bytes(b'%PDF-1.4\nchanged')
    with pytest.raises(ValueError): cli.validate_folder(folder,2,MODEL)


def test_wrong_model(folder):
    with pytest.raises(ValueError): cli.validate_folder(folder,2,'JAM60D40-500/LB')


def test_old_importer_still_refuses_ocr(folder):
    with pytest.raises(ApprovalError): validate_review(folder/'document.pdf',folder/'ocr_table_review_page2.json',source_url=URL,confirm_model=MODEL)


class Cursor:
    def __init__(self, rows): self.rows=iter(rows); self.calls=[]
    def execute(self,sql,args): self.calls.append((sql,args))
    def fetchone(self): return next(self.rows)
    def __enter__(self): return self
    def __exit__(self,*args): pass


def test_exact_catalog_link(folder):
    item=cli.validate_folder(folder,2,MODEL)
    cursor=Cursor([('JA JAM60D40-505 LB',505,['https://sklepsoltech.pl/other.pdf',LINK],['conflicting_bifaciality_pct'],None)])
    assert cli.fetch_catalog(cursor,item)==['conflicting_bifaciality_pct']
    with pytest.raises(ApprovalError,match='Exact OCR PDF URL'):
        cli.fetch_catalog(Cursor([('JA JAM60D40-505 LB',505,['https://sklepsoltech.pl/other.pdf'],[],None)]),item)


def test_insert(folder):
    item=cli.validate_folder(folder,2,MODEL); cur=Cursor([(6,)])
    assert cli.write_approval(cur,item)==(6,True)
    assert cur.calls[0][1][-2:]==(cli.METHOD,item.evidence_sha256)


def test_idempotence(folder):
    item=cli.validate_folder(folder,2,MODEL); c=item.candidate
    row=(6,c.model,LINK,c.review_sha256,c.values_stc,cli.METHOD,item.evidence_sha256)
    assert cli.write_approval(Cursor([None,row]),item)==(6,False)
    with pytest.raises(ApprovalError,match='Conflicting'):
        cli.write_approval(Cursor([None,(*row[:-1],'0'*64)]),item)


def test_approve_requires_visual(folder):
    with pytest.raises(SystemExit): cli.main(['--folder',str(folder),'--confirm-model',MODEL,'--approve'])


def test_preview_read_only(folder,monkeypatch,capsys):
    monkeypatch.setattr(cli,'execute',lambda item,approve: ('PREVIEW_ONLY',None,['conflicting_bifaciality_pct'],None) if not approve else pytest.fail('unexpected write'))
    assert cli.main(['--folder',str(folder),'--confirm-model',MODEL])==0
    assert json.loads(capsys.readouterr().out)['database_write'] is False

@pytest.mark.parametrize('issues,expected', [([],False),(['conflicting_imp_a'],False),(['conflicting_bifaciality_pct'],True),(['conflicting_product_warranty_years'],True),(None,True),(['unknown'],True)])
def test_quality_policy(issues,expected):
    assert cli.has_unresolved_issues(issues) is expected


@pytest.mark.parametrize('status,accepted',[('REVIEW',True),('PASS',False)])
def test_gold_rollback_guard(folder,monkeypatch,status,accepted):
    item=cli.validate_folder(folder,2,MODEL)
    cursor=Cursor([('JA JAM60D40-505 LB',505,[LINK],['conflicting_bifaciality_pct'],None),(6,), (6,cli.METHOD,status,item.evidence_sha256)])
    class Conn:
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def cursor(self): return cursor
    monkeypatch.setitem(sys.modules,'scraper.load',SimpleNamespace(get_connection=lambda:Conn()))
    if accepted: assert cli.execute(item,approve=True)==('APPROVED_NEW',6,['conflicting_bifaciality_pct'],'REVIEW')
    else:
        with pytest.raises(ApprovalError,match='concealed'): cli.execute(item,approve=True)


def test_sql_contract():
    root=Path(__file__).resolve().parents[1]
    migration=(root/'docker/postgres/init/009_panel_pdf_ocr_approvals.sql').read_text()
    silver=(root/'dbt/solar_dbt/models/staging/stg_panel_pdf_approvals.sql').read_text()
    gold=(root/'dbt/solar_dbt/models/marts/panel_technical_comparison.sql').read_text()
    assert 'local_pdf_manual_v1' in migration and 'local_pdf_ocr_manual_v1' in migration
    assert 'ocr_evidence_sha256 IS NOT NULL' in migration and 'DELETE FROM' not in migration
    assert 'END AS pdf_quality,\n    ocr_evidence_sha256' in silver
    assert 'pdf_approved_at,\n    pdf_approval_method,\n    pdf_ocr_evidence_sha256,\n    pdf_stc_quality' in gold
    assert 'conflicting_bifaciality_pct' not in gold and "THEN 'REVIEW'" in gold
