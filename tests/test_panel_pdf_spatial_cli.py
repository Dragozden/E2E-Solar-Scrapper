"""PDF extractor fallback when the STC title is not a single extract_text_line."""
import sys
from types import SimpleNamespace

from scripts.panel_pdf_preview import extract_stc_lines
from test_panel_pdf_spatial import sample_words


class FakePDF:
    def __init__(self, words):
        self.pages = [FakePage(words)]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakePage:
    width = 595
    height = 842

    def __init__(self, words):
        self.words = words

    def extract_text(self):
        return 'TWMNH-54HDXXX technical catalog'  # Family present in source

    def extract_text_lines(self, **kwargs):
        return []  # Real PDF may fragment the heading into non-line objects

    def extract_words(self, **kwargs):
        return self.words


def test_pdf_extraction_works_without_text_headings(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, 'pdfplumber', SimpleNamespace(open=lambda _: FakePDF(sample_words(split_header=True))))
    matches, diagnostics = extract_stc_lines(tmp_path / 'fake.pdf', model='TWMNH-54HD505', power=505)
    assert len(matches) == 1
    assert matches[0].values['rated_power_w'] == 505
    assert diagnostics[0]['text_headings'] == 0
    assert diagnostics[0]['inspections'][0]['reasons'] == ['SPATIAL_STC_COLUMNS_VALIDATED']


def test_no_header_results_in_actionable_diagnostic(monkeypatch, tmp_path):
    words = [w for w in sample_words() if w['text'] != '(STC)']
    monkeypatch.setitem(sys.modules, 'pdfplumber', SimpleNamespace(open=lambda _: FakePDF(words)))
    matches, diagnostics = extract_stc_lines(tmp_path / 'fake.pdf', model='TWMNH-54HD505', power=505)
    assert matches == []
    assert diagnostics[0]['inspections'][0]['reasons'] == ['NO_SPATIAL_STC_HEADING']
    assert diagnostics[0]['inspections'][1]['warning'] == 'NO_READABLE_STC_HEADER_OR_ALIGNED_COLUMNS'
