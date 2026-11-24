"""Offline regression: same-product URL state and an atomic DOM snapshot.

No remote requests, no database writes, no browser launch. 429 remains fatal.
"""
from __future__ import annotations

from scripts import panel_detail_pilot as pilot
from test_panel_live_hotfix import URL_1, URL_2, URL_3, DESCRIPTION, install_fake
import pytest


def test_same_product_query_and_fragment_allowed():
    assert pilot._same_product_document(URL_1, URL_1 + '?region=pl#description')
    assert pilot._same_product_document(URL_1, URL_1 + '/')


@pytest.mark.parametrize('destination', [
    'http://sklepsoltech.pl/pl/p/Panel-615W/4149',
    'https://evil.example/pl/p/Panel-615W/4149',
    'https://sklepsoltech.pl:8443/pl/p/Panel-615W/4149',
    'https://user:password@sklepsoltech.pl/pl/p/Panel-615W/4149',
    'https://sklepsoltech.pl/pl/p/Panel-610W/4150',
    'https://sklepsoltech.pl/pl/c/Panele-fotowoltaiczne/13',
])
def test_other_document_never_accepted(destination):
    assert not pilot._same_product_document(URL_1, destination)


def test_query_tracking_update_during_wait_succeeds(monkeypatch, capsys):
    install_fake(monkeypatch, [URL_1, URL_2, URL_3], {
        URL_2: {'redirect_on_wait': URL_2 + '?ref=track&lang=pl'},
        URL_3: {'redirect_on_wait': URL_3 + '#details'},
    })
    samples = pilot.live_samples(3, 5)
    assert len(samples) == 3
    assert [s.source_url for s in samples] == [URL_1, URL_2, URL_3]
    output = capsys.readouterr()
    assert 'LIVE SUMMARY: 3/3' in output.out
    assert 'same-product URL variation' in output.out
    assert 'ref=track' not in output.out  # don't print query values


def test_query_update_during_html_snapshot_succeeds(monkeypatch):
    install_fake(monkeypatch, [URL_1, URL_2], {
        URL_2: {'redirect_on_content': URL_2 + '?session=hidden'},
    })
    samples = pilot.live_samples(2, 5, strict=True)
    assert len(samples) == 2
    assert samples[1].source_url == URL_2


def test_no_attributes_is_skipped(monkeypatch, capsys):
    install_fake(monkeypatch, [URL_1, URL_2], {
        URL_2: {'html': '<html><h1>Unavailable</h1></html>'},
    })
    samples = pilot.live_samples(2, 5)
    assert len(samples) == 1
    assert 'no usable technical parameters' in capsys.readouterr().err


def test_missing_attributes_prevents_write(monkeypatch):
    install_fake(monkeypatch, [URL_1, URL_2], {
        URL_2: {'html': '<html><h1>Unavailable</h1></html>'},
    })
    with pytest.raises(RuntimeError, match='refusing --write'):
        pilot.live_samples(2, 5, strict=True)


def test_https_downgrade_is_blocked_even_with_same_path(monkeypatch):
    install_fake(monkeypatch, [URL_1, URL_2], {
        URL_2: {'redirect_on_wait': URL_2.replace('https://', 'http://')},
    })
    assert len(pilot.live_samples(2, 5)) == 1


def test_changed_product_in_atomic_snapshot_is_blocked(monkeypatch):
    install_fake(monkeypatch, [URL_1, URL_2], {
        URL_2: {'redirect_on_content': URL_3},
    })
    assert len(pilot.live_samples(2, 5)) == 1


def test_snapshot_html_and_url_are_returned_from_one_evaluation():
    class Page:
        def __init__(self): self.calls = []
        def evaluate(self, expression):
            self.calls.append(expression)
            return {'href': URL_1 + '?t=1', 'html': DESCRIPTION}
        @property
        def url(self): raise AssertionError('Do not read URL outside snapshot')
        def content(self): raise AssertionError('Do not read HTML separately')
    page = Page()
    address, html = pilot._document_snapshot(page)
    assert address == URL_1 + '?t=1'
    assert html == DESCRIPTION
    assert len(page.calls) == 1
