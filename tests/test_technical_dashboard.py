"""Offline data-quality and UI contract tests for Stage 11.3.

No network, database, Docker, or Streamlit process required.
"""
from pathlib import Path

import pandas as pd
import pytest
import yaml

from dashboard.technical import (
    filter_technical, technical_comparison, technical_coverage,
    safe_datasheet_url,
)

ROOT = Path(__file__).resolve().parents[1]


def catalog():
    base = [
        {"overall_rank": 1, "source_url": "https://sklepsoltech.pl/pl/p/Longi/4149",
         "title": "Longi 615", "manufacturer": "Longi", "model": "A", "is_available": True,
         "technical_status": "PASS", "has_specification": True,
         "is_technical_comparable": True,
         "efficiency_pct": 22.8, "voc_v": 48.58, "vmp_v": 40.71, "isc_a": 16.0, "imp_a": 15.11},
        {"overall_rank": 2, "source_url": "https://sklepsoltech.pl/pl/p/TW/4229",
         "title": "TW Solar 575", "manufacturer": "TW Solar", "model": "B", "is_available": True,
         "technical_status": "PASS", "has_specification": True,
         "is_technical_comparable": True,
         "efficiency_pct": 22.3, "voc_v": 52.1, "vmp_v": 43.76, "isc_a": 13.8, "imp_a": 13.14},
        {"overall_rank": 3, "source_url": "https://sklepsoltech.pl/pl/p/TW505/3516",
         "title": "TW 505", "manufacturer": "TW Solar", "model": "C", "is_available": True,
         "technical_status": "INCOMPLETE", "has_specification": True,
         "is_technical_comparable": False,
         "efficiency_pct": None, "voc_v": None, "vmp_v": None, "isc_a": None, "imp_a": None},
        {"overall_rank": 4, "source_url": "https://sklepsoltech.pl/pl/p/Other/4444",
         "title": "Other", "manufacturer": None, "model": None, "is_available": True,
         "technical_status": "NOT_ENRICHED", "has_specification": False,
         "is_technical_comparable": False,
         "efficiency_pct": None, "voc_v": None, "vmp_v": None, "isc_a": None, "imp_a": None},
        {"overall_rank": 5, "source_url": "https://sklepsoltech.pl/pl/p/Mismatch/5555",
         "title": "Different power", "manufacturer": "Vendor", "model": "D", "is_available": False,
         "technical_status": "POWER_MISMATCH", "has_specification": True,
         "is_technical_comparable": False,
         "efficiency_pct": 22.0, "voc_v": 49.9, "vmp_v": 42.1, "isc_a": 13.0, "imp_a": 12.0},
    ]
    return pd.DataFrame(base)


def test_coverage_counts_all_five_statuses():
    coverage = technical_coverage(catalog())
    assert coverage['total'] == 5
    assert coverage['enriched'] == 4
    assert coverage['comparable'] == 2
    assert coverage['coverage_pct'] == 40.0
    assert coverage['NOT_ENRICHED'] == 1
    assert coverage['INCOMPLETE'] == 1
    assert coverage['POWER_MISMATCH'] == 1


def test_coverage_on_empty_catalog_is_safe():
    empty = catalog().iloc[:0]
    assert technical_coverage(empty)['coverage_pct'] == 0.0


def test_default_filters_only_qualified_available():
    assert filter_technical(catalog())['title'].tolist() == ['Longi 615', 'TW Solar 575']


def test_all_offers_preserved_including_missing_specs():
    assert len(filter_technical(catalog(), mode='Wszystkie oferty', available_only=False)) == 5


def test_only_needing_enrichment_keeps_missing_and_incomplete():
    titles = filter_technical(catalog(), mode='Do uzupełnienia')['title'].tolist()
    assert titles == ['TW 505', 'Other']


def test_unavailable_only_excluded_when_requested():
    assert len(filter_technical(catalog(), mode='Do uzupełnienia', available_only=False)) == 3


def test_search_is_literal_not_regex():
    assert filter_technical(catalog(), mode='Wszystkie oferty', search='.*').empty
    assert len(filter_technical(catalog(), mode='Wszystkie oferty', search='tw')) == 2


def test_numeric_range_filters_exclude_missing_values():
    out = filter_technical(catalog(), mode='Wszystkie oferty',
                           ranges={'voc_v': (50, 54)})
    assert out['title'].tolist() == ['TW Solar 575']


def test_numeric_filter_works_for_imp_and_efficiency():
    out = filter_technical(catalog(), ranges={'imp_a': (15, 16),
                                              'efficiency_pct': (22.7, 23.5)})
    assert out['title'].tolist() == ['Longi 615']


@pytest.mark.parametrize('field', ('__bad__', 'price_pln', 'spec_hash'))
def test_unapproved_numeric_filter_rejected(field):
    with pytest.raises(ValueError, match='Unsupported'):
        filter_technical(catalog(), ranges={field: (0, 100)})


def test_reversed_range_rejected():
    with pytest.raises(ValueError, match='Reversed'):
        filter_technical(catalog(), ranges={'voc_v': (55, 40)})


def test_unknown_mode_rejected():
    with pytest.raises(ValueError, match='Unknown'):
        filter_technical(catalog(), mode='ignore-validation')


def test_comparison_preserves_selection_order():
    frame = catalog()
    chosen = [frame.iloc[1]['source_url'], frame.iloc[0]['source_url']]
    assert technical_comparison(frame, chosen)['title'].tolist() == ['TW Solar 575', 'Longi 615']


def test_incomplete_product_cannot_be_compared():
    frame = catalog()
    with pytest.raises(ValueError, match='lacks a qualified spec'):
        technical_comparison(frame, [frame.iloc[0]['source_url'], frame.iloc[2]['source_url']])


def test_single_or_duplicate_comparison_is_rejected():
    frame = catalog()
    a = frame.iloc[0]['source_url']
    with pytest.raises(ValueError):
        technical_comparison(frame, [a])
    with pytest.raises(ValueError):
        technical_comparison(frame, [a, a])


@pytest.mark.parametrize('url', [
    'https://evil.test/sheet.pdf',
    'http://sklepsoltech.pl/file.pdf',
    'https://sklepsoltech.pl.evil.test/file.pdf',
    'https://user:secret@sklepsoltech.pl/file.pdf',
    'https://sklepsoltech.pl/file.jpg',
    'https://sklepsoltech.pl:444/file.pdf',
    '', None,
])
def test_unsafe_datasheet_urls_rejected(url):
    assert safe_datasheet_url(url) is None


def test_valid_datasheet_url_accepted():
    url = 'https://sklepsoltech.pl/pl/p/file/123/Datasheet-575.pdf'
    assert safe_datasheet_url(url) == url


def test_view_query_only_reads_gold_and_never_writes():
    source = (ROOT / 'dashboard/technical_db.py').read_text()
    assert 'FROM gold.panel_technical_comparison' in source
    assert 'default_transaction_read_only' in source
    assert not any(x in source.upper() for x in ('INSERT INTO', 'UPDATE GOLD.', 'DELETE FROM'))


def test_accepted_values_migrated_to_arguments_property():
    for path in (ROOT / 'dbt/solar_dbt/models/staging/stg_panel_specs.yml',
                 ROOT / 'dbt/solar_dbt/models/marts/panel_technical_comparison.yml'):
        content = yaml.safe_load(path.read_text(encoding='utf-8'))
        col = next(c for c in content['models'][0]['columns'] if
                   c['name'] in ('technical_status', 'spec_quality'))
        av = next(test['accepted_values'] for test in col['data_tests']
                  if isinstance(test, dict) and 'accepted_values' in test)
        assert isinstance(av['arguments']['values'], list)
        assert 'values' not in av
