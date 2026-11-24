import copy
import hashlib
import json
from pathlib import Path
import pytest
from scraper.panel_pdf_ocr_table import reconstruct, TableError
from scripts.reconstruct_panel_pdf_ocr import run

@pytest.fixture
def evidence():
    return json.loads((Path(__file__).parent/'fixtures/ocr_ja_stc_tokens.json').read_text(encoding='utf8'))

def test_real_tokens(evidence):
    r=reconstruct(evidence)
    assert r['status']=='OCR_TABLE_REVIEW_REQUIRED'
    assert r['variant_column_zero_based']==4
    assert r['proposed_values']==dict(rated_power_w=505,voc_v=44.05,vmp_v=37.11,isc_a=14.48,imp_a=13.61,efficiency_pct=22.8)
    assert r['database_write'] is False and 'candidates' not in r

def test_scale_and_shuffle(evidence):
    for w in evidence['ocr_words']:
        for k in ('left','top','width','height'): w[k]*=2
    evidence['image_width']*=2; evidence['image_height']*=2
    # use a smaller scale (1/2 of original) to respect pixel limit
    for w in evidence['ocr_words']:
        for k in ('left','top','width','height'): w[k]=max(1,w[k]//4)
    evidence['image_width']//=4; evidence['image_height']//=4
    evidence['ocr_words'].reverse()
    assert reconstruct(evidence)['proposed_values']['voc_v']==44.05

@pytest.mark.parametrize('kind', ['missing','duplicate','low_conf','shift','wrong_value','wrong_suffix','wrong_family','no_heading','wrong_power','missing_boundary','wrong_status','wrong_box'])
def test_reject(evidence,kind):
    words=evidence['ocr_words']
    w=next(w for w in words if w['text']=='13.61' and w['top']<1800)
    if kind=='missing': words.remove(w)
    elif kind=='duplicate': words.append(dict(w))
    elif kind=='low_conf': w['confidence']=70
    elif kind=='shift': w['left']+=55
    elif kind=='wrong_value': w['text']='14.99'
    elif kind=='wrong_suffix': next(w for w in words if w['text']=='-505/LB')['text']='-505/LR'
    elif kind=='wrong_family': evidence['model_requested']='JAM54D40-505/LB'
    elif kind=='no_heading': next(w for w in words if w['text']=='PARAMETERS')['text']='OTHER'
    elif kind=='wrong_power': next(w for w in words if w['text']=='505')['text']='506'
    elif kind=='missing_boundary': next(w for w in words if w['text']=='Tolerance')['text']='OTHER'
    elif kind=='wrong_status': evidence['status']='REVIEW_REQUIRED'
    elif kind=='wrong_box': w['left']=-1
    with pytest.raises(TableError): reconstruct(evidence)

def folder_fixture(tmp_path,evidence):
    pdf=b'%PDF-1.4\nfixture'; (tmp_path/'document.pdf').write_bytes(pdf)
    evidence['pdf_sha256']=hashlib.sha256(pdf).hexdigest()
    for name,obj in [('job.json',dict(model=evidence['model_requested'],power_w=505)),('review.json',dict(status='NO_UNAMBIGUOUS_STC_TABLE',database_write=False,candidates=[],model_requested=evidence['model_requested'],power_w_requested=505,pdf_sha256=evidence['pdf_sha256'])),('ocr_evidence_page2.json',evidence)]:
        (tmp_path/name).write_text(json.dumps(obj),encoding='utf8')
    return tmp_path

def test_cli_provenance_and_no_overwrite(tmp_path,evidence):
    folder_fixture(tmp_path,evidence)
    result=run(tmp_path,2)
    assert result['status']=='OCR_TABLE_REVIEW_REQUIRED'
    before=(tmp_path/'ocr_table_review_page2.json').read_bytes()
    with pytest.raises(TableError,match='REPORT_ALREADY_EXISTS'): run(tmp_path,2)
    assert (tmp_path/'ocr_table_review_page2.json').read_bytes()==before

def test_cli_wrong_hash(tmp_path,evidence):
    folder_fixture(tmp_path,evidence)
    (tmp_path/'document.pdf').write_bytes(b'%PDF-1.4\nchanged')
    with pytest.raises(TableError,match='PROVENANCE'): run(tmp_path,2)
    assert not (tmp_path/'ocr_table_review_page2.json').exists()
