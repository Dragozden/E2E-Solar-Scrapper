import hashlib
import json
import pytest
from scripts.panel_pdf_ocr import run,parse_words
from scraper.panel_pdf_layouts import item_unit_stc
from scraper.panel_pdf_approval import validate_review,ApprovalError


def table():
    lines=[['Electrical Characteristics (STC*)'],['HiT-HxxxLE-FB'],['Item Unit','455','460'],
           ['Nominal Output (Pmax)','W','455','460'],['Open Circuit Voltage (Voc)','V','36.82','36.92'],
           ['Short Circuit Current (Isc)','A','15.64','15.75'],['Voltage at Pmax (Vmpp)','V','30.94','31.05'],
           ['Current at Pmax (Impp)','A','14.71','14.82'],['Module Efficiency','%','22.8','23.0']]
    out=[]
    for i,line in enumerate(lines):
        for j,v in enumerate(line):
            x=20 if j==0 else (180 if len(line)==4 and j==1 else 250+70*(j-(2 if len(line)==4 else 1)))
            out.append(dict(text=v,x0=x-2,x1=x+2,top=i*12,bottom=i*12+5))
    return out


def test_hyundai_full_width():
    [c]=item_unit_stc(table(),'HIT-H460LE',460,2,'HIT-H460LE','HiT-H460LE-FB')
    assert c.values['voc_v']==36.92 and c.values['efficiency_pct']==23 and c.variant_column==1

@pytest.mark.parametrize('change',['cover','series','header','misalign','unit','stc'])
def test_hyundai_rejects(change):
    w=table(); cover='HiT-H460LE-FB'
    if change=='cover': cover='HiT-H455LE-FB'
    elif change=='series': w[1]['text']='HiT-HxxxLE-X'
    elif change=='header': w[4]['text']='455'
    elif change=='misalign': w[-1]['x0']+=20;w[-1]['x1']+=20
    elif change=='unit': w[-3]['text']='A'
    elif change=='stc': w[0]['text']='Electrical Characteristics (NMOT)'
    assert not item_unit_stc(w,'HIT-H460LE',460,2,'HIT-H460LE',cover)

TSV='level\tleft\ttop\twidth\theight\tconf\ttext\n5\t12\t13\t30\t9\t95.1\tSTC\n4\t0\t0\t0\t0\t-1\t\n'

def evidence(p):
    b=b'%PDF-1.7 mock'; (p/'document.pdf').write_bytes(b)
    (p/'job.json').write_text(json.dumps(dict(model='JAM60D40-505/LB',power_w=505)))
    (p/'review.json').write_text(json.dumps(dict(status='NO_UNAMBIGUOUS_STC_TABLE',model_requested='JAM60D40-505/LB',power_w_requested=505,pdf_sha256=hashlib.sha256(b).hexdigest(),database_write=False)))


def test_ocr_is_not_approval(tmp_path):
    evidence(tmp_path)
    result=run(tmp_path,2,'fake',render=lambda *a:(b'png',(100,200),0),ocr=lambda *a:TSV)
    report=tmp_path/'ocr_evidence_page2.json'
    data=json.loads(report.read_text())
    assert result['status']=='OCR_EVIDENCE_ONLY' and data['candidates']==[] and data['database_write'] is False
    assert data['ocr_words'][0]['confidence']==95.1
    with pytest.raises(ApprovalError): validate_review(tmp_path/'document.pdf',report,source_url='https://sklepsoltech.pl/pl/p/Panel-fotowoltaiczny-JA/4312',confirm_model='JAM60D40-505/LB')
    assert run(tmp_path,2,'fake')['status']=='ALREADY_OCR_ANALYZED'


def test_ocr_hash_mismatch(tmp_path):
    evidence(tmp_path); (tmp_path/'document.pdf').write_bytes(b'%PDF-1.7 changed')
    with pytest.raises(ValueError,match='Evidence mismatch'): run(tmp_path,2,'fake')


def test_ocr_text_recovered(tmp_path):
    evidence(tmp_path); old=json.loads((tmp_path/'review.json').read_text());old['status']='REVIEW_REQUIRED'
    (tmp_path/'review_v2.json').write_text(json.dumps(old))
    with pytest.raises(ValueError,match='already recovered'): run(tmp_path,2,'fake')
