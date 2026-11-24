from scraper.panel_pdf_layouts import paired_conditions, jinko_range
from scripts.recheck_panel_pdf_queue import recheck
import hashlib,json
import pytest


def words(bad=False):
    rows=[['Electrical Characteristics STC NOCT'],['Module Type LR7-72HVH-630M LR7-72HVH-635M'],
          ['Testing Condition','STC','NOCT','STC','NOCT'],
          ['Maximum Power (Pmax/W)','630','480','635','483'],
          ['Open Circuit Voltage (Voc/V)','53.5','50.84','53.6','50.94'],
          ['Short Circuit Current (Isc/A)','14.97','12.02','15.05','12.09'],
          ['Voltage at Maximum Power (Vmp/V)','44.16','41.96','44.26','42.06'],
          ['Current at Maximum Power (Imp/A)','14.27','11.44','14.35','11.50'],
          ['Module Efficiency (%)','23.3','23.5']]
    if bad: rows[2][3]='NOCT'
    out=[]
    for i,row in enumerate(rows):
        for j,t in enumerate(row):
            x=20 if j==0 else (170+(j-1)*60+15 if i==8 else 170+(j-1)*30)
            out.append(dict(text=t,x0=x-2,x1=x+2,top=i*12,bottom=i*12+5))
    return out


def test_paired_stc_only():
    [c]=paired_conditions(words(),'LR7-72HVH-635M',635,2,'LR7-72HVH-635M')
    assert c.values['voc_v']==53.6 and c.values['imp_a']==14.35 and c.variant_column==1
    assert c.values['efficiency_pct']==23.5


def test_bad_conditions():
    assert not paired_conditions(words(True),'LR7-72HVH-635M',635,2,'f')


def test_wrong_model():
    assert not paired_conditions(words(),'LR7-72HVD-635M',635,2,'f')


def test_misaligned():
    w=words(); w[-1]['x0']+=12; w[-1]['x1']+=12
    assert not paired_conditions(w,'LR7-72HVH-635M',635,2,'f')

@pytest.mark.parametrize('text,model,power,expected',[
    ('JKM420-440N-54HL4-B-F2C1-US','JKM435N-54HL4-B',435,(420,440)),
    ('JKM420-440N-54HL4-B','JKM445N-54HL4-B',445,None),
    ('JKM420-440N-54HL4-C','JKM435N-54HL4-B',435,None),
    ('54HL4-B 420-440 Watt','JKM435N-54HL4-B',435,None)])
def test_range(text,model,power,expected):
    assert jinko_range(text,model,power)==expected


def test_local_recheck_preserves_old(tmp_path):
    raw=b'%PDF-1.7 test'; (tmp_path/'document.pdf').write_bytes(raw)
    job=dict(model='JKM435N-54HL4-B',power_w=435,source_url='https://sklepsoltech.pl/pl/p/Panel-fotowoltaiczny-Jinko/2101')
    (tmp_path/'job.json').write_text(json.dumps(job))
    old=json.dumps(dict(model_requested=job['model'],power_w_requested=435,pdf_sha256=hashlib.sha256(raw).hexdigest(),database_write=False))
    (tmp_path/'review.json').write_text(old)
    result=recheck(tmp_path,extract=lambda *a,**kw:([],[]))
    assert result['status']=='NO_UNAMBIGUOUS_STC_TABLE'
    assert (tmp_path/'review.json').read_text()==old
    assert recheck(tmp_path)['status']=='ALREADY_RECHECKED'
    (tmp_path/'review_v2.json').unlink(); (tmp_path/'document.pdf').write_bytes(raw+b'changed')
    with pytest.raises(ValueError,match='Evidence mismatch'): recheck(tmp_path)
