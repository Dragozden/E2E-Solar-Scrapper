"""Offline, deterministic PV technical specification parsing tests."""
from pathlib import Path
import pytest

from scraper.panel_detail_specs import (
    is_allowed_detail_url, parse_panel_details, raw_attribute_rows,
    _field_for, _one_number, _normalize,
)

ROOT = Path(__file__).parent
URL = 'https://sklepsoltech.pl/pl/p/Panel-testowy/4226'


def fixture(name):
    return (ROOT / 'fixtures' / name).read_text(encoding='utf-8')


@pytest.mark.parametrize('u', [
    'http://sklepsoltech.pl/pl/p/Model/111',
    'https://attacker.test/pl/p/Model/111',
    'https://sklepsoltech.pl.evil.test/pl/p/Model/111',
    'https://sklepsoltech.pl/pl/c/Panele-fotowoltaiczne/13',
    'https://sklepsoltech.pl/pl/p/Model/111?next=evil',
    'https://user:pass@sklepsoltech.pl/pl/p/Model/111',
])
def test_reject_non_product_or_unsafe_urls(u):
    assert not is_allowed_detail_url(u)


def test_allow_valid_product_url():
    assert is_allowed_detail_url(URL)


def test_parse_full_table_with_raw_provenance():
    sample = parse_panel_details(fixture('panel_detail_ja_solar.html'), URL)
    assert sample.page_title.startswith('Panel fotowoltaiczny')
    assert len(sample.attributes_raw) >= 17
    assert sample.values['rated_power_w'] == 510
    assert sample.values['efficiency_pct'] == 23.0
    assert sample.values['voc_v'] == 44.25
    assert sample.values['vmp_v'] == 37.31
    assert sample.values['isc_a'] == 14.54
    assert sample.values['imp_a'] == 13.67
    assert sample.values['bifaciality_pct'] == 80.0
    assert sample.values['dimensions_mm'] == [1953, 1134, 30]
    assert sample.values['mass_kg'] == 27.3
    assert sample.values['temp_coeff_pmax_pct_c'] == -0.29
    assert sample.values['temp_coeff_voc_pct_c'] == -0.25
    assert sample.values['max_system_voltage_v'] == 1500
    assert sample.values['product_warranty_years'] == 12
    assert sample.values['performance_warranty_years'] == 30
    assert sample.values['manufacturer'] == 'JA Solar'
    assert sample.values['model'] == 'JAM60D40-510/LB BF'
    assert sample.parse_issues == []


def test_ignores_recommendations_outside_description():
    sample = parse_panel_details(fixture('panel_detail_ja_solar.html'), URL)
    assert sample.values['efficiency_pct'] == 23.0
    assert all(row['value'] != '17%' for row in sample.attributes_raw)


def test_pdf_is_link_only_not_downloaded():
    sample = parse_panel_details(fixture('panel_detail_ja_solar.html'), URL)
    assert sample.datasheet_urls == ['https://sklepsoltech.pl/uploaded/datasheet_JAM60D40.pdf']


def test_prose_and_heading_section():
    sample = parse_panel_details(fixture('panel_detail_aiko.html'), URL)
    assert sample.values['rated_power_w'] == 480
    assert sample.values['voc_v'] == 35.33
    assert sample.values['vmp_v'] == 31.05
    assert sample.values['isc_a'] == 16.63
    assert sample.values['imp_a'] == 15.46
    assert sample.values['efficiency_pct'] == 24.0
    assert sample.values['dimensions_mm'] == [1762, 1134, 30]
    assert sample.values['bifaciality_pct'] == 80.0
    assert sample.values['model'] == 'AIKO-A480-GRH48Dw'
    assert all(row['value'] != '99,9%' for row in sample.attributes_raw)


def test_same_content_hash_is_stable():
    a = parse_panel_details(fixture('panel_detail_ja_solar.html'), URL)
    b = parse_panel_details(fixture('panel_detail_ja_solar.html'), URL)
    assert a.spec_hash == b.spec_hash
    assert len(a.spec_hash) == 64


def test_hash_changes_after_spec_change():
    a = parse_panel_details(fixture('panel_detail_ja_solar.html'), URL)
    content = fixture('panel_detail_ja_solar.html').replace('44,25 V', '44,30 V')
    b = parse_panel_details(content, URL)
    assert a.spec_hash != b.spec_hash


def test_no_technical_section_not_fake_data():
    sample = parse_panel_details('<h1>Panel 500W</h1><p>Sprawność 99%</p>', URL)
    assert sample.attributes_raw == []
    assert sample.values == {}
    assert 'no_technical_rows' in sample.parse_issues


def test_wrong_units_not_silently_parsed():
    rows = [{'label': 'Voc', 'value': '44,25 A'}, {'label': 'Masa', 'value': '25 g'}]
    values, _ = _normalize(rows)
    assert 'voc_v' not in values
    assert 'mass_kg' not in values


def test_voltage_current_anomaly_detected():
    rows = [{'label': 'Voc', 'value': '32 V'}, {'label': 'Vmp', 'value': '34 V'},
            {'label': 'Isc', 'value': '12 A'}, {'label': 'Imp', 'value': '13 A'}]
    _, warnings = _normalize(rows)
    assert 'voc_not_above_vmp' in warnings
    assert 'isc_below_imp' in warnings


def test_power_electrical_consistency_warning():
    rows = [{'label': 'Pmax', 'value': '500 W'}, {'label': 'Vmp', 'value': '40 V'}, {'label': 'Imp', 'value': '5 A'}]
    _, warnings = _normalize(rows)
    assert 'pmax_vs_vmp_imp_mismatch' in warnings


def test_out_of_range_efficiency_is_removed():
    result, issues = _normalize([{'label': 'Sprawność modułu', 'value': '77,7%'}])
    assert 'efficiency_pct' not in result
    assert 'out_of_range_efficiency_pct' in issues


def test_missing_dimensions_unit_does_not_guess():
    result, _ = _normalize([{'label': 'Wymiary', 'value': '1953 x 1134 x 30'}])
    assert 'dimensions_mm' not in result


def test_conflicting_duplicate_label_flagged():
    result, issues = _normalize([{'label': 'Voc', 'value': '44 V'}, {'label': 'Voc', 'value': '45 V'}])
    assert result['voc_v'] == 44
    assert 'conflicting_voc_v' in issues


def test_combined_warranty_requires_review():
    result, issues = _normalize([{'label': 'Gwarancja', 'value': '12 lat produktu, 30 lat mocy'}])
    assert 'product_warranty_years' not in result
    assert 'combined_warranty_needs_review' in issues


def test_data_sheet_external_host_is_skipped():
    html = '<div class="product__description"><p>Model | X12</p></div><a href="https://evil.test/datasheet.pdf">Karta katalogowa</a>'
    assert parse_panel_details(html, URL).datasheet_urls == []


def test_dedup_exact_raw_rows():
    html = '''<div id="projector_longdescription"><table><tr><td>Voc</td><td>44 V</td></tr>
    <tr><td>Voc</td><td>44 V</td></tr></table></div>'''
    assert len(raw_attribute_rows(html)) == 1


@pytest.mark.parametrize('label, expected', [
    ('Napięcie obwodu otwartego Voc', 'voc_v'),
    ('Napięcie w punkcie MPP Vmp', 'vmp_v'),
    ('Prąd zwarciowy Isc', 'isc_a'),
    ('Prąd mocy maksymalnej Imp', 'imp_a'),
    ('Sprawność modułu', 'efficiency_pct'),
    ('Współczynnik temperaturowy Pmax', 'temp_coeff_pmax_pct_c'),
    ('Współczynnik bifacjalności', 'bifaciality_pct'),
    ('Maksymalne napięcie systemu', 'max_system_voltage_v'),
])
def test_realistic_polish_labels(label, expected):
    assert _field_for(label) == expected


def test_other_technical_fields():
    raw = [
        {'label': 'Liczba ogniw', 'value': '120 ogniw, układ 6 × 20'},
        {'label': 'Maksymalny bezpiecznik szeregowy', 'value': '30 A'},
        {'label': 'NOCT', 'value': '45°C ±2°C'},
        {'label': 'Współczynnik temperaturowy Isc', 'value': '+0,045%/°C'},
    ]
    values, issues = _normalize(raw)
    assert values['cell_count'] == 120
    assert values['max_series_fuse_a'] == 30
    assert values['noct_c'] == 45
    assert values['temp_coeff_isc_pct_c'] == 0.045
    assert issues == []


def test_area_and_power_density_derived_from_proven_dimensions():
    sample = parse_panel_details(fixture('panel_detail_ja_solar.html'), URL)
    assert sample.values['area_m2'] == round(1953 * 1134 / 1_000_000, 4)
    assert sample.values['power_density_w_m2'] == round(510 / (1953 * 1134 / 1_000_000), 2)


def test_report_impossible_efficiency_vs_area():
    rows = [{'label': 'Moc maksymalna Pmax', 'value': '500 Wp'},
            {'label': 'Wymiary', 'value': '2000 x 1000 x 30 mm'},
            {'label': 'Sprawność modułu', 'value': '12,0%'}]
    _, issues = _normalize(rows)
    assert 'efficiency_vs_area_power_mismatch' in issues
