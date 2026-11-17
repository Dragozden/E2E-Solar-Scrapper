"""Offline pure-parser regression: STC variant column only; no PDF/network/DB."""
from __future__ import annotations

import pytest

from scraper.panel_pdf_stc import find_stc_candidates, family_token

STC_TW = [
    "ELECTRICAL CHARACTERISTICS (STC)",
    "Module Type: TWMNH-54HDXXX",
    "Maximum Power: Pmax [W] 495 500 505 510 515",
    "Open Circuit Voltage: Voc [V] 39.88 40.06 40.24 40.42 40.60",
    "Short Circuit Current: Isc [A] 15.86 15.89 15.92 15.95 15.98",
    "Voltage at Maximum Power: Vmp [V] 33.45 33.70 33.94 34.19 34.43",
    "Current at Maximum Power: Imp [A] 14.80 14.84 14.88 14.92 14.96",
    "Module Efficiency: η [%] 22.3 22.5 22.7 22.9 23.2",
    "ELECTRICAL CHARACTERISTICS (NMOT)",
    "Maximum Power: Pmax [W] 374 378 381 385 389",
    "Open Circuit Voltage: Voc [V] 37.97 38.14 38.31 38.48 38.65",
    "Short Circuit Current: Isc [A] 12.80 12.83 12.85 12.88 12.90",
    "Voltage at Maximum Power: Vmp [V] 31.30 31.56 31.73 31.96 32.21",
    "Current at Maximum Power: Imp [A] 11.95 11.98 12.01 12.05 12.08",
]
STC_RISEN = [
    "DANE ELEKTRYCZNE (STC)",
    "Moc znamionowa w watach-Pmax (Wp) 605 610 615 620 625 630",
    "Napięcie obwodu otwartego-Voc(V) 48,49 48,69 48,89 49,08 49,27 49,46",
    "Prąd zwarcia-Isc(A) 15,86 15,92 15,98 16,04 16,10 16,16",
    "Napięcie mocy maksymalnej-Vmpp(V) 40,28 40,46 40,64 40,81 40,98 41,17",
    "Prąd mocy maksymalnej-Impp(A) 15,02 15,08 15,14 15,20 15,26 15,31",
    "Sprawność modułu (%) 22,4 22,6 22,8 23,0 23,1 23,3",
    "DANE ELEKTRYCZNE (NMOT)",
]


def test_tw_505_stc_correct_column_and_not_nmot():
    candidates = find_stc_candidates(STC_TW, 505, page=2, model_family="TWMNH-54HD")
    assert len(candidates) == 1
    a = candidates[0]
    assert a.variant_column == 2 and a.page == 2
    assert a.values == dict(rated_power_w=505, voc_v=40.24, isc_a=15.92,
                            vmp_v=33.94, imp_a=14.88, efficiency_pct=22.7)


def test_tw_500_is_adjacent_but_not_505():
    [a] = find_stc_candidates(STC_TW, 500, page=2)
    assert a.variant_column == 1 and a.values['voc_v'] == 40.06


def test_risen_620_correct_column_and_polish_labels():
    [a] = find_stc_candidates(STC_RISEN, 620, page=2)
    assert a.variant_column == 3
    assert a.values['voc_v'] == 49.08 and a.values['imp_a'] == 15.20
    assert a.values['efficiency_pct'] == 23.0


def test_no_match_for_unlisted_wattage():
    assert find_stc_candidates(STC_TW, 530, page=1) == []


def test_reject_mismatched_number_of_columns():
    bad = STC_TW.copy()
    bad[3] = 'Open Circuit Voltage: Voc [V] 39.88 40.06 40.24'
    assert find_stc_candidates(bad, 505, page=2) == []


def test_reject_duplicate_power_columns():
    bad = STC_TW.copy()
    bad[2] = 'Maximum Power: Pmax [W] 495 505 505 510 515'
    assert find_stc_candidates(bad, 505, page=2) == []


def test_reject_missing_stc_heading():
    assert find_stc_candidates(STC_TW[1:], 505, page=2) == []


def test_reject_only_nmot():
    assert find_stc_candidates(STC_TW[8:], 505, page=2) == []


def test_reject_power_current_inconsistency():
    bad = STC_TW.copy()
    bad[6] = 'Current at Maximum Power: Imp [A] 14.80 14.84 9.00 14.92 14.96'
    assert find_stc_candidates(bad, 505, page=2) == []


def test_reject_electrical_inconsistency():
    bad = STC_TW.copy()
    bad[3] = 'Open Circuit Voltage: Voc [V] 39.88 40.06 20.24 40.42 40.60'
    assert find_stc_candidates(bad, 505, page=2) == []


def test_no_values_in_label_only_without_units():
    bad = STC_TW.copy()
    bad[2] = 'Maximum Power 495 500 505 510 515'
    assert find_stc_candidates(bad, 505, page=2) == []


def test_two_stc_tables_ambiguous():
    assert find_stc_candidates(STC_TW + STC_TW, 505, page=2) == []


def test_tolerance_of_commas_and_punctuation():
    assert find_stc_candidates(STC_RISEN, 620, page=2)[0].values['isc_a'] == 16.04


def test_model_families():
    assert family_token('TWMNH-54HD505') == 'TWMNH-54HD'
    assert family_token('TWMND-72HD590W') == 'TWMND-72HD'
    assert family_token('RSM132-11-620BNDG') == 'RSM132-11'


@pytest.mark.parametrize('power', [0, -10, 99, 901, 3000])
def test_reject_invalid_power(power):
    with pytest.raises(ValueError, match='100..900'):
        find_stc_candidates(STC_TW, power, page=2)


def test_tw_590_selection_from_580_to_600_series():
    lines = [
        'ELECTRICAL CHARACTERISTICS (STC)',
        'Maximum Power: Pmax [W] 580 585 590 595 600',
        'Open Circuit Voltage: Voc [V] 52.30 52.50 52.70 53.20 53.40',
        'Short Circuit Current: Isc [A] 13.85 13.90 13.95 14.15 14.20',
        'Voltage at Maximum Power: Vmp [V] 43.93 44.10 44.27 44.41 44.55',
        'Current at Maximum Power: Imp [A] 13.21 13.27 13.33 13.40 13.47',
        'Module Efficiency: η [%] 22.5 22.6 22.8 23.0 23.2',
        'ELECTRICAL CHARACTERISTICS (NMOT)',
        'Maximum Power: Pmax [W] 436.2 439.9 443.7 447.4 451.2',
    ]
    [candidate] = find_stc_candidates(lines, 590, page=2)
    assert candidate.variant_column == 2
    assert candidate.values['voc_v'] == 52.70
    assert candidate.values['imp_a'] == 13.33


def test_no_rear_gain_values_are_substituted_for_stc():
    lines = STC_TW + [
        'Electrical characteristics with different rear side power gain',
        'Maximum Power: Pmax [W] 519 525 530 535 540',
        'Current at Maximum Power: Imp [A] 16 16 16 16 16',
    ]
    [a] = find_stc_candidates(lines, 505, page=2)
    assert a.values['rated_power_w'] == 505
    assert a.values['imp_a'] == 14.88
