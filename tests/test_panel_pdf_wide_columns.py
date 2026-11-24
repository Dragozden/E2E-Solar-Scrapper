"""Regression for right-side wide STC tables, as observed on Risen 620 PDF.
Synthetic coordinates; no proprietary PDF, OCR, database or internet required.
"""
from scraper.panel_pdf_stc import spatial_stc_candidate
from scripts.panel_pdf_preview import extract_stc_lines
from types import SimpleNamespace
import sys


def wide_words():
    words = []
    def line(y, pairs):
        for x, text in pairs:
            words.append(dict(text=text, top=float(y), bottom=float(y+6),
                              x0=float(x), x1=float(x+len(text)*3)))
    line(41, [(75, 'Dimensions'), (115, 'of'), (130, 'Module'),
              (225, 'ELECTRICAL'), (279, 'DATA'), (303, '(STC)')])
    for y, label, values in [
        (66, 'Rated Power Pmax(Wp)', [605,610,615,620,625,630]),
        (77, 'Open Circuit Voc(V)', [48.49,48.69,48.89,49.08,49.27,49.46]),
        (88, 'Short Circuit Isc(A)', [15.86,15.92,15.98,16.04,16.10,16.16]),
        (98, 'Maximum Power Vmpp(V)', [40.28,40.46,40.64,40.81,40.98,41.17]),
        (109, 'Maximum Power Impp(A)', [15.02,15.08,15.14,15.20,15.26,15.31]),
        (120, 'Module Efficiency (%)', [22.4,22.6,22.8,23.0,23.1,23.3]),
    ]:
        line(y, [(105, '1134'),(225,label)] + [(338+37*i,str(v)) for i,v in enumerate(values)])
    line(133, [(225,'STC:'),(245,'Irradiance'),(275,'1000')])
    line(145, [(225,'Module Efficiency (%)'),(400,'25')])
    line(160, [(225,'Electrical characteristics with 10% rear side power gain')])
    line(173, [(225,'Pmax(Wp)')] + [(338+37*i,str(v)) for i,v in enumerate([666,671,677,682,688,693])])
    return words


def test_wide_right_table_exact_variant():
    [a], reasons = spatial_stc_candidate(wide_words(),620,page=2,page_width=581)
    assert a.variant_column == 3
    assert a.values == dict(rated_power_w=620.,voc_v=49.08,isc_a=16.04,vmp_v=40.81,imp_a=15.2,efficiency_pct=23.)
    assert reasons == ['SPATIAL_STC_COLUMNS_VALIDATED']


def test_wide_right_table_adjacent_power():
    [a], _ = spatial_stc_candidate(wide_words(),625,page=2,page_width=581)
    assert a.variant_column == 4 and a.values['voc_v'] == 49.27


def test_rear_gain_not_used_as_nominal_power():
    candidates, reasons = spatial_stc_candidate(wide_words(),682,page=2,page_width=581)
    assert not candidates and 'TARGET_POWER_NOT_UNIQUE' in reasons


def test_wide_table_missing_metric_rejected():
    words = [w for w in wide_words() if w['top'] != 88]
    candidates, reasons = spatial_stc_candidate(words,620,page=2,page_width=581)
    assert not candidates and 'MISSING_SPATIAL_METRICS:isc_a' in reasons


def test_missing_family_and_limited_text_layer_still_refused(monkeypatch,tmp_path):
    class Pdf:
        pages = [SimpleNamespace(extract_text=lambda: 'STC: 1000 W/m2')]
        def __enter__(self): return self
        def __exit__(self,*args): return False
    monkeypatch.setitem(sys.modules,'pdfplumber',SimpleNamespace(open=lambda _: Pdf()))
    candidates, diagnostic = extract_stc_lines(tmp_path/'sample.pdf',model='TWMND-72HD590W',power=590)
    assert not candidates
    assert diagnostic[0]['warning'] == 'EXPECTED_MODEL_FAMILY_NOT_PRESENT_IN_PDF'
    assert diagnostic[0]['text_layer_hint'] == 'LIMITED_TEXT_LAYER_MANUAL_REVIEW'
