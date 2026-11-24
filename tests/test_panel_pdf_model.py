"""Catalog model resolver regression cases from the real queue plan."""
from decimal import Decimal
from pathlib import Path
import pytest
from scraper.panel_pdf_model import resolve_model
from scripts.panel_pdf_queue import make_plan

@pytest.mark.parametrize('title,raw,watts,expected', [
 ('Panel fotowoltaiczny TW Solar TWMND-72HD590W','TWMND-72HD590W — N-Type TOPCon, bifacial, szkło–szkło, srebrna rama.',590,'TWMND-72HD590W'),
 ('Panel fotowoltaiczny Risen Energy RSM 96-11-450 BNDG 450W Bifacial BF',None,450,'RSM96-11-450BNDG'),
 ('Panel fotowoltaiczny Hyundai HiT-H460LE - 460 FB',None,460,'HIT-H460LE'),
 ('Panel fotowoltaiczny JA SOLAR 505 JAM60D40-505 LB Bifacial BF','JAM60D40-505/LB BF',505,'JAM60D40-505/LB'),
 ('Panel LONGi LR7-72HVH-650M SF','LR7-72HVH-650M',650,'LR7-72HVH-650M'),
 ('Panel JA Solar JAM72D40-605 MB','JAM72D40-605/MB',605,'JAM72D40-605/MB'),
])
def test_exact_resolution(title,raw,watts,expected):
    assert resolve_model(raw,title,watts)[0] == expected

@pytest.mark.parametrize('title,raw,watts', [
 ('Panel JINKO Solar 620 JKM620-66HL4M-BDV SF','JKM620N-66HL4M-BDV',620),
 ('Panel Trina Solar TSM-NEG9R.28 470W','TSM-470NEG9R.28',470),
 ('Panel AIKO A-MAH54Mw 440 W BF','AIKO-A440-MAH54Mw',440),
 ('Panel TW TWMND-72HD590W','TWMNH-72HD590W — opis',590),
 ('Panel JA JAM60D40-505 LB','JAM60D40-505/LR BF',505),
 ('Panel Hyundai HiT-H460LE - 460 FB',None,450),
 ('Panel Hyundai HiT-H460LE oraz HiT-H450LE',None,460),
 ('Panel Hyundai HiT-H460LE-X',None,460),
 ('Panel Risen RSM 96-11-450 BNDG-X',None,450),
 ('Panel Risen 450W',None,450),
])
def test_refuses_conflicts_and_unsupported_variants(title,raw,watts):
    assert resolve_model(raw,title,watts)[0] is None

def test_manual_map_does_not_silently_fallback():
    assert resolve_model('wrong','Panel Hyundai HiT-H460LE',460,explicit=True)[0] is None

def test_queue_preserves_raw_and_stable_folder(tmp_path):
    url='https://sklepsoltech.pl/pl/p/Panel-TWMND-72HD590W/3663'
    pdf='https://sklepsoltech.pl/pl/p/file/abc/card.pdf'
    row=(4,'Panel TWMND-72HD590W',url,Decimal('590'),'TWMND-72HD590W — opis','INCOMPLETE',[pdf],[])
    item,=make_plan([row],tmp_path)
    assert item['state']=='READY' and item['model']=='TWMND-72HD590W'
    assert item['model_input']==row[4] and item['model_resolution']=='NORMALIZED_CATALOG_TOKEN'
    Path(item['folder']).mkdir()
    assert make_plan([row],tmp_path)[0]['state']=='ALREADY_ATTEMPTED'
