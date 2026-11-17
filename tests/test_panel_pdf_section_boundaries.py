"""Regression for Polish Soltech PDF page 2 diagnostics, 17 Nov 2026.

The original PDF was NOT uploaded; these are synthetic coordinates that
reproduce the failure mode: the subsequent NMOT heading appears as 'N MOT'
and the original extractor counted its electrical rows as duplicate STC rows.
No network, database writes, or OCR.
"""
from test_panel_pdf_spatial import sample_words
from scraper.panel_pdf_stc import spatial_stc_candidate, _is_following_section_heading


def add_row(words, label, y, values):
    for i, text in enumerate(label.split()):
        x = 40 + 19 * i
        words.append({"text": text, "top": float(y), "bottom": float(y + 10),
                      "x0": float(x), "x1": float(x + max(8, len(text) * 3))})
    for i, value in enumerate(values):
        x = 169 + i * 25
        words.append({"text": str(value), "top": float(y), "bottom": float(y + 10),
                      "x0": float(x), "x1": float(x + 19)})


def nmot_following(words):
    words = [w.copy() for w in words if w["top"] < 240]
    for i, word in enumerate(("CHARAKTERYSTYKA", "ELEKTRYCZNA", "(N", "MOT)")):
        x = (40, 134, 229, 251)[i]
        words.append({"text": word, "top": 228., "bottom": 238.,
                      "x0": float(x), "x1": float(x + 15)})
    add_row(words, "Maksymalna moc: Pmax [W]", 245, [374, 378, 381, 385, 389])
    add_row(words, "Napięcie obwodu otwartego: Voc [V]", 258, [37.97,38.14,38.31,38.48,38.65])
    add_row(words, "Prąd zwarciowy: Isc [A]", 271, [12.80,12.83,12.85,12.88,12.90])
    add_row(words, "Napięcie przy mocy maksymalnej: Vmp [V]", 284, [31.30,31.56,31.73,31.96,32.21])
    add_row(words, "Prąd przy mocy maksymalnej: Imp [A]", 297, [11.95,11.98,12.01,12.05,12.08])
    return words


def test_real_diagnostic_n_mot_stops_before_duplicate_metric_rows():
    candidates, reasons = spatial_stc_candidate(nmot_following(sample_words()), 505,
                                                 page=2, page_width=595)
    assert len(candidates) == 1, reasons
    assert candidates[0].values["rated_power_w"] == 505
    assert candidates[0].values["voc_v"] == 40.24
    assert candidates[0].values["imp_a"] == 14.88
    assert candidates[0].values["efficiency_pct"] == 22.7
    assert "SPATIAL_STC_COLUMNS_VALIDATED" in reasons


def test_rear_side_heading_is_an_explicit_boundary():
    words = [w.copy() for w in sample_words() if w["top"] < 240]
    for i, word in enumerate(("CHARAKTERYSTYKA", "ELEKTRYCZNA", "TYLNA", "STRONA", "MODUŁU")):
        x = 40 + i * 42
        words.append({"text": word, "top": 226., "bottom": 236.,
                      "x0": float(x), "x1": float(x+35)})
    add_row(words, "Maksymalna moc: Pmax [W]", 240, [519,525,530,535,540])
    add_row(words, "Prąd zwarciowy: Isc [A]", 250, [18,18,18,18,18])
    candidates, reasons = spatial_stc_candidate(words, 505, page=2, page_width=595)
    assert len(candidates) == 1, reasons
    assert candidates[0].values["imp_a"] == 14.88
    absent, why = spatial_stc_candidate(words, 535, page=2, page_width=595)
    assert absent == [] and "TARGET_POWER_NOT_UNIQUE" in why


def test_real_duplicate_within_stc_still_fail_closed():
    words = [w.copy() for w in sample_words()]
    add_row(words, "Prąd zwarciowy: Isc [A]", 208, [15.86,15.89,15.92,15.95,15.98])
    candidates, reasons = spatial_stc_candidate(words, 505, page=2, page_width=595)
    assert candidates == []
    assert any("DUPLICATE_METRIC_ROWS" in r for r in reasons)


def test_polish_section_markers():
    assert _is_following_section_heading("CHARAKTERYSTYKA ELEKTRYCZNA (N MOT)")
    assert _is_following_section_heading("CHARAKTERYSTYKA ELEKTRYCZNA (NMOT)")
    assert _is_following_section_heading("CHARAKTERYSTYKA ELEKTRYCZNA TYLNA STRONA MODUŁU")
    assert not _is_following_section_heading("STC: Promieniowanie 1000 W/m2")
    assert not _is_following_section_heading("Bifacjalność 80%")


def test_n_mot_split_over_two_visual_rows_is_boundary():
    words = [w.copy() for w in sample_words() if w["top"] < 240]
    for i, token in enumerate(("CHARAKTERYSTYKA", "ELEKTRYCZNA", "(N")):
        words.append({"text": token, "top": 227., "bottom": 237.,
                      "x0": float(40 + i * 75), "x1": float(73 + i * 75)})
    words.append({"text": "MOT)", "top": 242., "bottom": 252., "x0": 42., "x1": 63.})
    add_row(words, "Maksymalna moc: Pmax [W]", 259, [374,378,381,385,389])
    found, reasons = spatial_stc_candidate(words, 505, page=2, page_width=595)
    assert len(found) == 1, reasons
    assert found[0].values["rated_power_w"] == 505


def test_text_parser_stops_at_n_mot_boundary():
    from scraper.panel_pdf_stc import find_stc_candidates
    lines = [
        'CHARAKTERYSTYKA ELEKTRYCZNA (STC)',
        'Moc maksymalna Pmax [W] 495 500 505 510 515',
        'Napięcie obwodu otwartego Voc [V] 39.88 40.06 40.24 40.42 40.60',
        'Prąd zwarciowy Isc [A] 15.86 15.89 15.92 15.95 15.98',
        'Napięcie mocy maksymalnej Vmp [V] 33.45 33.70 33.94 34.19 34.43',
        'Prąd mocy maksymalnej Imp [A] 14.80 14.84 14.88 14.92 14.96',
        'Sprawność modułu (%) 22.3 22.5 22.7 22.9 23.2',
        'CHARAKTERYSTYKA ELEKTRYCZNA (N MOT)',
        'Moc maksymalna Pmax [W] 374 378 381 385 389',
        'Napięcie obwodu otwartego Voc [V] 37.97 38.14 38.31 38.48 38.65',
    ]
    found = find_stc_candidates(lines,505,page=2,model_family='TWMNH-54HD')
    assert len(found) == 1
    assert found[0].values['voc_v'] == 40.24
