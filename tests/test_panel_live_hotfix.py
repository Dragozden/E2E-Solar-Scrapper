"""Offline regression for client-side redirects and real LONGi-like prose.

All network/browser actions are replaced; these tests never contact Soltech.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

from scripts import panel_detail_pilot as pilot
from scraper.panel_detail_specs import parse_panel_details

URL_1 = "https://sklepsoltech.pl/pl/p/Panel-615W/4149"
URL_2 = "https://sklepsoltech.pl/pl/p/Panel-610W/4150"
URL_3 = "https://sklepsoltech.pl/pl/p/Panel-600W/4151"
DESCRIPTION = """<h1>Panel fotowoltaiczny Longi 615 W</h1>
<div id="projector_longdescription">
  <table><tr><th>Model</th><td>LR8-66HGD-615M SF</td></tr>
  <tr><th>Moc maksymalna (Pmax)</th><td>615 W</td></tr>
  <tr><th>Napięcie obwodu otwartego (Voc)</th><td>48,58 V</td></tr>
  <tr><th>Napięcie mocy maksymalnej (Vmp)</th><td>40,71 V</td></tr>
  <tr><th>Prąd zwarciowy (Isc)</th><td>16,00 A</td></tr>
  <tr><th>Prąd w punkcie mocy maksymalnej (Imp)</th><td>15,11 A</td></tr>
  <tr><th>Wymiary</th><td>2382 × 1134 × 30 mm</td></tr></table>
  <p><strong>Moc znamionowa 615 W</strong> — wysoka gęstość mocy dla projektów</p>
  <li><strong>Sprawność modułu 22,8%</strong> — wykorzystanie powierzchni</li>
  <p><strong>Uwaga</strong>: podane parametry mają charakter orientacyjny i mogą ulec zmianie.</p>
  <p><strong>Klasa ochrony</strong>: IP68</p>
  <p>Kolor ramy: Silver</p>
</div>"""


class FakePage:
    def __init__(self, behavior=None):
        self.url = 'about:blank'
        self.behavior = behavior or {}
        self.selected = None

    def goto(self, url, *, wait_until, timeout):
        assert wait_until == 'domcontentloaded' and timeout == 30000
        self.selected = url
        self.url = url
        return SimpleNamespace(status=self.behavior.get(url, {}).get('status', 200))

    def wait_for_timeout(self, ms):
        assert ms == 600
        moved = self.behavior.get(self.selected, {}).get('redirect_on_wait')
        if moved:
            self.url = moved

    def evaluate(self, expression):
        assert "window.location.href" in expression
        assert "document.documentElement.outerHTML" in expression
        behavior = self.behavior.get(self.selected, {})
        moved = behavior.get('redirect_on_content')
        if moved:
            self.url = moved
        html = behavior.get('html', DESCRIPTION)
        return {'href': self.url, 'html': html}


class FakeBrowser:
    def __init__(self, behavior=None):
        self.page_obj = FakePage(behavior)
        self.closed = False

    def new_page(self):
        return self.page_obj

    def close(self):
        self.closed = True


class FakePlaywright:
    def __init__(self, browser):
        self.chromium = SimpleNamespace(launch=lambda headless: browser)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def install_fake(monkeypatch, urls, behavior=None):
    import playwright.sync_api
    browser = FakeBrowser(behavior)
    monkeypatch.setattr(playwright.sync_api, 'sync_playwright', lambda: FakePlaywright(browser))
    monkeypatch.setattr(pilot, 'select_product_urls', lambda limit: urls[:limit])
    monkeypatch.setattr(pilot.time, 'sleep', lambda seconds: None)
    return browser


def test_normal_preview_for_one_product(monkeypatch, capsys):
    browser = install_fake(monkeypatch, [URL_1])
    samples = pilot.live_samples(1, 5)
    assert browser.closed
    assert len(samples) == 1
    assert samples[0].values['rated_power_w'] == 615
    assert 'LIVE SUMMARY: 1/1' in capsys.readouterr().out


def test_redirect_to_category_skipped_without_crashing_remaining_products(monkeypatch, capsys):
    redirect = 'https://sklepsoltech.pl/pl/c/Panele-fotowoltaiczne/13'
    install_fake(monkeypatch, [URL_1, URL_2, URL_3],
                 {URL_2: {'redirect_on_wait': redirect}})
    samples = pilot.live_samples(3, 5)
    assert len(samples) == 2
    assert [s.source_url for s in samples] == [URL_1, URL_3]
    out = capsys.readouterr()
    assert 'LIVE SUMMARY: 2/3' in out.out
    assert 'left the intended HTTPS product path' in out.err


def test_write_mode_refuses_partial_live_run(monkeypatch):
    install_fake(monkeypatch, [URL_1, URL_2],
                 {URL_2: {'redirect_on_wait': 'https://sklepsoltech.pl/'}})
    with pytest.raises(RuntimeError, match='refusing --write'):
        pilot.live_samples(2, 5, strict=True)


def test_redirect_during_content_read_skips_page(monkeypatch):
    install_fake(monkeypatch, [URL_1, URL_2],
                 {URL_2: {'redirect_on_content': 'https://sklepsoltech.pl/'}})
    assert len(pilot.live_samples(2, 5)) == 1


def test_redirect_to_different_product_skipped(monkeypatch):
    install_fake(monkeypatch, [URL_1, URL_2],
                 {URL_2: {'redirect_on_wait': URL_3}})
    assert len(pilot.live_samples(2, 5)) == 1


def test_429_stops_all_without_bypass(monkeypatch):
    install_fake(monkeypatch, [URL_1], {URL_1: {'status': 429}})
    with pytest.raises(RuntimeError, match='HTTP response 429'):
        pilot.live_samples(1, 5)


def test_no_valid_pages_fails_explicitly(monkeypatch):
    install_fake(monkeypatch, [URL_1],
                 {URL_1: {'redirect_on_wait': 'https://sklepsoltech.pl/'}})
    with pytest.raises(RuntimeError, match='No valid product pages'):
        pilot.live_samples(1, 5)


def test_unknown_structured_attributes_survive_but_marketing_does_not():
    sample = parse_panel_details(DESCRIPTION, URL_1)
    labels = [row['label'] for row in sample.attributes_raw]
    assert 'Model' in labels and 'Klasa ochrony' in labels and 'Kolor ramy' in labels
    assert 'Uwaga' not in labels
    assert not any(label.startswith('Moc znamionowa 615 W') for label in labels)
    assert not any(label.startswith('Sprawność modułu 22,8%') for label in labels)
    assert sample.values['vmp_v'] == 40.71
    assert sample.values['imp_a'] == 15.11
    assert sample.parse_issues == []
