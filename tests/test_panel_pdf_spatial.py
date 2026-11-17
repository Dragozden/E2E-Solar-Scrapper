"""Regression: graphic datasheet rows with STC title fragmented into PDF words.

No network, DB or OCR; exercises original PDF word coordinates with a
synthetic two-column sample. The user's Soltech PDF is not bundled here.
"""
from scraper.panel_pdf_stc import spatial_stc_candidate, spatial_stc_anchors


def sample_words(*, split_header=False):
    words = []
    def add(line, y, x=42, increment=26):
        for i, text in enumerate(line):
            # Each value is a separate PDF text object, not one wrapped line.
            pos = x + i * increment
            words.append({"text": text, "top": float(y), "bottom": float(y+10),
                          "x0": float(pos), "x1": float(pos+max(8, len(text)*3.8))})
    if split_header:
        add(["CHARAKTERYSTYKA", "ELEKTRYCZNA"], 90, 40, 94)
        add(["(STC)"], 101, 226)
    else:
        add(["CHARAKTERYSTYKA", "ELEKTRYCZNA", "(STC)"], 100, 40, 91)
    groups = [
        (125, ["Maksymalna", "moc:", "Pmax", "[W]"], ["495", "500", "505", "510", "515"]),
        (143, ["Napięcie", "obwodu", "otwartego:", "Voc", "[V]"], ["39.88", "40.06", "40.24", "40.42", "40.60"]),
        (161, ["Prąd", "zwarciowy:", "lsc", "[A]"], ["15.86", "15.89", "15.92", "15.95", "15.98"]),
        (179, ["Napięcie", "przy", "mocy", "maksymalnej:", "Vmp"], ["33.45", "33.70", "33.94", "34.19", "34.43"]),
        (197, ["Prąd", "przy", "mocy", "maksymalnej:", "lmp", "[A]"], ["14.80", "14.84", "14.88", "14.92", "14.96"]),
        (215, ["Wydajność", "modułu:", "η", "[%]"], ["22.3", "22.5", "22.7", "22.9", "23.2"]),
    ]
    for y, labels, nums in groups:
        add(labels, y, 40, 19)
        for i, number in enumerate(nums):
            x = 169 + i * 25
            words.append({"text": number, "top": float(y), "bottom": float(y+10),
                          "x0": float(x), "x1": float(x+19)})
    add(["CHARAKTERYSTYKA", "ELEKTRYCZNA", "(NMOT)"], 240, 40, 91)
    add(["Moc", "maksymalna:", "Pmax", "[W]", "374", "378", "381", "385", "389"], 263)
    # This right-side graph must never enter the STC columns.
    add(["Gwarancja", "99%", "95%"], 169, 375, 46)
    return words


def test_split_heading_still_detectable():
    anchors = spatial_stc_anchors(sample_words(split_header=True), page_width=595)
    assert len(anchors) == 1
    assert "STC" in anchors[0]["text"]


def test_spatial_tw505_exact_stc_col():
    found, reasons = spatial_stc_candidate(sample_words(), 505, page=2,
                                            page_width=595, model_family="TWMNH-54HD")
    assert len(found) == 1, reasons
    assert found[0].variant_column == 2
    assert found[0].values["rated_power_w"] == 505
    assert found[0].values["voc_v"] == 40.24
    assert found[0].values["isc_a"] == 15.92
    assert found[0].values["vmp_v"] == 33.94
    assert found[0].values["imp_a"] == 14.88
    assert found[0].values["efficiency_pct"] == 22.7
    assert "SPATIAL_STC_COLUMNS_VALIDATED" in reasons


def test_spatial_tw500_adjacent_variant():
    found, reasons = spatial_stc_candidate(sample_words(), 500, page=2,
                                            page_width=595)
    assert len(found) == 1, reasons
    assert found[0].variant_column == 1
    assert found[0].values["voc_v"] == 40.06


def test_spatial_split_heading_detects_505():
    found, reasons = spatial_stc_candidate(sample_words(split_header=True), 505,
                                            page=2, page_width=595)
    assert len(found) == 1, reasons
    assert found[0].values["rated_power_w"] == 505


def test_spatial_refuse_no_stc_heading():
    data = sample_words()
    data = [w for w in data if w["text"] not in ("(STC)",)]
    assert spatial_stc_candidate(data, 505, page=2, page_width=595)[0] == []


def test_spatial_reject_missing_voltage():
    data = sample_words()
    data = [w for w in data if not (w["top"] == 143 and w["x0"] > 150)]
    found, reasons = spatial_stc_candidate(data, 505, page=2, page_width=595)
    assert found == [] and "MISSING_SPATIAL_METRICS:voc_v" in reasons


def test_spatial_reject_misaligned_columns():
    data = sample_words()
    for w in data:
        if w["top"] == 161 and w["x0"] >= 169 and w["x0"] < 315:
            w["x0"] += 15
            w["x1"] += 15
    found, reasons = spatial_stc_candidate(data, 505, page=2, page_width=595)
    assert found == [] and "MISALIGNED_SPATIAL_COLUMNS" in reasons


def test_spatial_reject_current_inconsistent():
    data = sample_words()
    for w in data:
        if w["top"] == 197 and w["text"] == "14.88":
            w["text"] = "7.00"
    found, reasons = spatial_stc_candidate(data, 505, page=2, page_width=595)
    assert found == [] and "PHYSICS_OR_STC_VALIDATION_FAILED" in reasons


def test_spatial_refuse_nmot_381_as_stc():
    found, reasons = spatial_stc_candidate(sample_words(), 381, page=2, page_width=595)
    assert found == [] and "TARGET_POWER_NOT_UNIQUE" in reasons


def test_stc_token_in_footnote_is_not_heading():
    data = [
        {"text": t, "top": 100, "bottom": 110, "x0": x, "x1": x+18}
        for t, x in [("STC:", 40), ("1000W/m2", 100), ("25°C", 180)]
    ]
    assert spatial_stc_anchors(data, page_width=595) == []
