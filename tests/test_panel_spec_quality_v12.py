"""Regression excerpts reconstructed from the user's 15 Nov 2026 LIVE preview.

These are *not* downloaded manufacturer datasheets or exact archived shop HTML.
All tests run offline; they protect against treating variant ranges as exact data.
"""
from __future__ import annotations

import pytest

from scraper.panel_detail_specs import (
    PARSER_VERSION, _normalize, parse_panel_details, sample_quality,
)
from scripts import panel_detail_pilot as pilot
from test_panel_live_hotfix import URL_1, URL_2, URL_3, install_fake

URL_505 = "https://sklepsoltech.pl/pl/p/Panel-fotowoltaiczny-TW-Solar-505-TWMNH-54HD505-BF/3516"


def rows_html(rows: list[tuple[str, str]]) -> str:
    import html
    body = "".join(f"<tr><td>{html.escape(a)}</td><td>{html.escape(b)}</td></tr>" for a, b in rows)
    return '<h1>Panel fotowoltaiczny TW Solar</h1><div id="projector_longdescription"><table>' + body + "</table></div>"


ROWS_505 = [
    ("Zakres mocy", "od 495 W do 515 W – elastyczne dopasowanie do konfiguracji systemu PV."),
    ("Sprawność modułu", "od 22,3% do 23,2% – bardzo wysoka efektywność energetyczna."),
    ("Technologia ogniw", "n-type half-cell, 108 ogniw (6×18) – zwiększona wydajność przy zacienieniu i niższa degradacja."),
    ("Bifacjalność", "do 80% – dodatkowy uzysk energii z tylnej strony (do +30%)."),
    ("Współczynniki temperaturowe", "Pmax -0,28%/°C, Voc -0,24%/°C, Isc +0,046%/°C – wysoka stabilność cieplna."),
    ("Maksymalne napięcie systemowe", "1500 V DC, maksymalny prąd bezpiecznika: 30 A."),
    ("Gwarancja", "30 lat liniowej gwarancji na moc (≤1% spadku w 1. roku, ≤0,4% rocznie w kolejnych latach)"),
]

ROWS_575 = [
    ("Producent", "TW Solar"), ("Model", "TWMND-72HD575"),
    ("Moc maksymalna Pmax", "575 Wp"),
    ("Napięcie obwodu otwartego Voc", "52,10 V"),
    ("Napięcie mocy maksymalnej Vmp", "43,76 V"),
    ("Prąd zwarciowy Isc", "13,80 A"),
    ("Prąd mocy maksymalnej Imp", "13,14 A"),
    ("Sprawność modułu", "22,3%"),
    ("Bifacjalność", "80% ±5%"),
    ("NMOT", "45°C ±2°C"),
    ("Gwarancja", "12 lat gwarancji materiałowej, 30 lat gwarancji mocy"),
]


def test_505_range_and_upper_bound_not_falsely_exact():
    values, issues = _normalize([{"label": a, "value": b} for a, b in ROWS_505])
    assert "rated_power_w" not in values  # catalog label is not an exact 505-W spec
    assert "efficiency_pct" not in values  # range 22.3..23.2, not 22.3 exact
    assert "bifaciality_pct" not in values  # up to 80, not 80 exact
    assert "range_not_exact_efficiency_pct" in issues
    assert "upper_bound_not_exact_bifaciality_pct" in issues
    assert values["cell_count"] == 108
    assert values["cell_technology"] == "n-type half-cell, 108 ogniw (6×18)"
    assert values["temp_coeff_pmax_pct_c"] == -0.28
    assert values["temp_coeff_voc_pct_c"] == -0.24
    assert values["temp_coeff_isc_pct_c"] == 0.046
    assert values["max_system_voltage_v"] == 1500
    assert values["performance_warranty_years"] == 30
    assert sample_quality(values, issues)["status"] == "INCOMPLETE"


def test_505_raw_range_stays_preserved():
    sample = parse_panel_details(rows_html(ROWS_505), URL_505)
    assert sample.parser_version == "panel-details-v1.2"
    assert sample.attributes_raw[1]["value"].startswith("od 22,3% do 23,2%")
    assert sample_quality(sample.values, sample.parse_issues)["missing_core_fields"] == [
        "imp_a", "isc_a", "rated_power_w", "vmp_v", "voc_v",
    ]


def test_575_exact_stc_and_combined_warranty():
    values, issues = _normalize([{"label": a, "value": b} for a, b in ROWS_575])
    assert values["rated_power_w"] == 575
    assert values["efficiency_pct"] == 22.3
    assert values["bifaciality_pct"] == 80.0  # tolerance is retained in raw text
    assert values["nmot_c"] == 45
    assert values["product_warranty_years"] == 12
    assert values["performance_warranty_years"] == 30
    assert issues == []
    assert sample_quality(values, issues)["status"] == "PASS"


def test_unqualified_ambiguous_warranty_still_warns():
    values, issues = _normalize([{"label": "Gwarancja", "value": "12 lat / 30 lat"}])
    assert "product_warranty_years" not in values
    assert "performance_warranty_years" not in values
    assert "combined_warranty_needs_review" in issues


def test_explicit_range_with_units_does_not_become_exact_power():
    values, issues = _normalize([{"label": "Moc maksymalna Pmax", "value": "od 495 W do 515 W"}])
    assert "rated_power_w" not in values
    assert "range_not_exact_rated_power_w" in issues


def test_same_raw_under_new_parser_version_gets_different_hash(monkeypatch):
    import scraper.panel_detail_specs as module
    text = rows_html(ROWS_575)
    hash_v12 = module.parse_panel_details(text, URL_505).spec_hash
    monkeypatch.setattr(module, "PARSER_VERSION", "panel-details-v1.1")
    hash_v11 = module.parse_panel_details(text, URL_505).spec_hash
    assert hash_v11 != hash_v12


def test_strict_write_refuses_incomplete_505_but_preview_still_works(monkeypatch):
    install_fake(monkeypatch, [URL_1, URL_2], {URL_2: {"html": rows_html(ROWS_505)}})
    preview = pilot.live_samples(2, 5, strict=False)
    assert len(preview) == 2
    assert sample_quality(preview[1].values, preview[1].parse_issues)["status"] == "INCOMPLETE"
    install_fake(monkeypatch, [URL_1, URL_2], {URL_2: {"html": rows_html(ROWS_505)}})
    with pytest.raises(RuntimeError, match="refusing --write"):
        pilot.live_samples(2, 5, strict=True)


def test_strict_write_allows_complete_independent_samples(monkeypatch):
    install_fake(monkeypatch, [URL_1, URL_2], {URL_2: {"html": rows_html(ROWS_575)}})
    assert len(pilot.live_samples(2, 5, strict=True)) == 2


@pytest.mark.parametrize("variant", ["22,3%–23,2%", "22,3% - 23,2%", "22,3~23,2%", "od 22,3% do 23,2%"])
def test_efficiency_ranges_are_never_exact(variant):
    values, issues = _normalize([{"label": "Sprawność modułu", "value": variant}])
    assert "efficiency_pct" not in values
    assert "range_not_exact_efficiency_pct" in issues


def test_polish_stroked_l_label_normalization():
    from scraper.panel_detail_specs import _key
    assert _key("Współczynniki temperaturowe") == "wspolczynniki temperaturowe"
    assert _key("Gwarancja materiałowa") == "gwarancja materialowa"
