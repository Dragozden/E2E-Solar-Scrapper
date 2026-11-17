"""Offline checks for manual PDF approval and product identity. No DB calls."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

import pytest

from scraper.panel_pdf_approval import (
    ApprovalError, approved_document_url, check_catalog_match,
    validate_review, validate_stc,
)
from scripts import approve_panel_pdf as cli

URL_500 = "https://sklepsoltech.pl/pl/p/Panel-fotowoltaiczny-TW-Solar-500-TWMNH-54HD500-BF/3515"
URL_505 = "https://sklepsoltech.pl/pl/p/Panel-fotowoltaiczny-TW-Solar-505-TWMNH-54HD505-BF/3516"
PDF_URL = "https://sklepsoltech.pl/pl/p/file/c92c05030efd938483a50e1fe334ef73/Karta-katalogowa-TW-Solar-TWMNH-54HD-495-515-W-PL.pdf"
FIELDS = {"rated_power_w": 500.0, "voc_v": 40.06, "isc_a": 15.89,
          "vmp_v": 33.7, "imp_a": 14.84, "efficiency_pct": 22.5}


def create_evidence(tmp_path):
    pdf = tmp_path / "TW_500.pdf"
    pdf.write_bytes(b"%PDF-1.7\nunit test only\n")
    report = tmp_path / "review.json"
    data = {
        "status": "REVIEW_REQUIRED", "database_write": False,
        "model_requested": "TWMNH-54HD500", "power_w_requested": 500,
        "pdf_sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
        "candidates": [{"page": 2, "power_w": 500, "variant_column_zero_based": 1,
                        "model_family": "TWMNH-54HD", "values": FIELDS}],
        "diagnostics": [],
    }
    report.write_text(json.dumps(data), encoding="utf-8")
    return pdf, report, data


def verify(pdf, report, *, source_url=URL_500, model="TWMNH-54HD500"):
    return validate_review(pdf, report, source_url=source_url, confirm_model=model)


def test_realistic_500w_approval(tmp_path):
    pdf, report, _ = create_evidence(tmp_path)
    result = verify(pdf, report)
    assert result.pdf_page == 2 and result.variant_column == 1
    assert result.values_stc["imp_a"] == 14.84
    check_catalog_match(result, title="Panel fotowoltaiczny TW Solar 500 TWMNH-54HD500 BF",
                        catalog_power=500)


def test_reject_report_for_different_pdf(tmp_path):
    pdf, report, _ = create_evidence(tmp_path)
    pdf.write_bytes(b"%PDF-1.7\ntampered content")
    with pytest.raises(ApprovalError, match="SHA-256 mismatch"):
        verify(pdf, report)


def test_reject_same_pdf_but_wrong_variant(tmp_path):
    pdf, report, _ = create_evidence(tmp_path)
    with pytest.raises(ApprovalError, match="confirmation"):
        verify(pdf, report, model="TWMNH-54HD505")


def test_reject_same_pdf_wrong_source_catalog(tmp_path):
    pdf, report, _ = create_evidence(tmp_path)
    candidate = verify(pdf, report, source_url=URL_505)
    with pytest.raises(ApprovalError, match="power"):
        check_catalog_match(candidate, title="Panel TWMNH-54HD505", catalog_power=505)


def test_reject_different_title(tmp_path):
    pdf, report, _ = create_evidence(tmp_path)
    with pytest.raises(ApprovalError, match="model token"):
        check_catalog_match(verify(pdf, report), title="Risen 500W", catalog_power=500)


def test_reject_off_host_url(tmp_path):
    pdf, report, _ = create_evidence(tmp_path)
    with pytest.raises(ApprovalError, match="trusted"):
        verify(pdf, report, source_url=URL_500.replace("sklepsoltech.pl", "malicious.tld"))


@pytest.mark.parametrize("url", [
    "https://evil.tld/x.pdf", "http://sklepsoltech.pl/file.pdf",
    "https://sklepsoltech.pl.evil.tld/file.pdf", "https://sklepsoltech.pl/x.png",
    "https://person@sklepsoltech.pl/x.pdf", "https://sklepsoltech.pl:444/x.pdf",
    "https://sklepsoltech.pl/x.pdf?token=1",
])
def test_reject_untrusted_document_url(url):
    with pytest.raises(ApprovalError, match="No trusted"):
        approved_document_url([url])


def test_selects_safe_url_from_retained_shop_link():
    assert approved_document_url(["https://evil.tld/x.pdf", PDF_URL]) == PDF_URL


@pytest.mark.parametrize("changes", [
    {"rated_power_w": 505}, {"voc_v": 20}, {"imp_a": 40},
    {"isc_a": 10}, {"efficiency_pct": 40}, {"vmp_v": 20},
    {"imp_a": True}, {"imp_a": "14.84"}, {"imp_a": float("nan")},
    {"bad_field": 1},
])
def test_stc_invalid(changes):
    with pytest.raises(ApprovalError):
        validate_stc({**FIELDS, **changes}, 500)


def test_reject_non_review_status(tmp_path):
    pdf, report, data = create_evidence(tmp_path)
    data["status"] = "PASS"
    report.write_text(json.dumps(data))
    with pytest.raises(ApprovalError, match="REVIEW_REQUIRED"):
        verify(pdf, report)


def test_reject_multiple_candidates(tmp_path):
    pdf, report, data = create_evidence(tmp_path)
    data["candidates"] = data["candidates"] * 2
    report.write_text(json.dumps(data))
    with pytest.raises(ApprovalError, match="Exactly one"):
        verify(pdf, report)


def test_reject_duplicate_json_keys(tmp_path):
    pdf, report, data = create_evidence(tmp_path)
    report.write_text(json.dumps(data)[:-1] + ', "status":"REVIEW_REQUIRED"}')
    with pytest.raises(ApprovalError, match="duplicate"):
        verify(pdf, report)


def test_reject_wrong_family(tmp_path):
    pdf, report, data = create_evidence(tmp_path)
    data["candidates"][0]["model_family"] = "WRONG"
    report.write_text(json.dumps(data))
    with pytest.raises(ApprovalError, match="family"):
        verify(pdf, report)


def test_preview_never_writes(tmp_path, monkeypatch, capsys):
    pdf, report, _ = create_evidence(tmp_path)
    from scraper import panel_pdf_approval as validate
    monkeypatch.setattr(cli, "execute", lambda item, approve: ("PREVIEW_ONLY", None, PDF_URL))
    rc = cli.main(["--pdf", str(pdf), "--review-json", str(report),
                   "--source-url", URL_500, "--confirm-model", "TWMNH-54HD500"])
    assert rc == 0
    output = json.loads(capsys.readouterr().out)
    assert output["database_write"] is False and output["status"] == "PREVIEW_ONLY"


def test_explicit_approve_argument(tmp_path, monkeypatch, capsys):
    pdf, report, _ = create_evidence(tmp_path)
    calls = []
    def fake_execute(item, *, approve):
        calls.append(approve)
        return "APPROVED_NEW", 7, PDF_URL
    monkeypatch.setattr(cli, "execute", fake_execute)
    rc = cli.main(["--pdf", str(pdf), "--review-json", str(report),
                   "--source-url", URL_500, "--confirm-model", "TWMNH-54HD500", "--approve"])
    assert rc == 0 and calls == [True]
    assert json.loads(capsys.readouterr().out)["approval_id"] == 7


def test_conflict_is_refused_without_modification(tmp_path):
    pdf, report, _ = create_evidence(tmp_path)
    c = verify(pdf, report)
    class Cursor:
        def __init__(self): self.step = 0
        def execute(self, sql, args): self.step += 1
        def fetchone(self):
            if self.step == 1: return None
            return (4, c.model, PDF_URL, c.review_sha256, {**FIELDS, "voc_v": 41.0})
    with pytest.raises(ApprovalError, match="Conflicting"):
        cli.write_approval(Cursor(), c, PDF_URL)


def test_idempotent_existing_approval(tmp_path):
    pdf, report, _ = create_evidence(tmp_path)
    c = verify(pdf, report)
    class Cursor:
        def __init__(self): self.step = 0
        def execute(self, sql, args): self.step += 1
        def fetchone(self):
            if self.step == 1: return None
            return (11, c.model, PDF_URL, c.review_sha256, FIELDS)
    assert cli.write_approval(Cursor(), c, PDF_URL) == (11, False)


def test_gold_pdf_contract_and_isolation():
    root = Path(__file__).resolve().parents[1]
    model = (root / "dbt/solar_dbt/models/marts/panel_technical_comparison.sql").read_text()
    staging = (root / "dbt/solar_dbt/models/staging/stg_panel_pdf_approvals.sql").read_text()
    migration = (root / "docker/postgres/init/008_panel_pdf_approvals.sql").read_text()
    assert "{{ ref('stg_panel_pdf_approvals') }}" in model
    assert "p.pdf_quality" in model and "PDF_APPROVED" in model
    assert "html_spec_quality" in model and "spec_power_matches_catalog" in model
    assert "rated_power_w = power_w" in staging and "pdf_quality" in staging
    assert "CREATE TABLE IF NOT EXISTS bronze.panel_pdf_approvals" in migration
    assert "DELETE FROM" not in migration and "DROP TABLE" not in migration


def test_html_fallback_is_preserved_for_no_pdf():
    root = Path(__file__).resolve().parents[1]
    text = (root / "dbt/solar_dbt/models/marts/panel_technical_comparison.sql").read_text()
    assert "COALESCE(p.voc_v, s.voc_v)" in text
    assert "LEFT JOIN latest_pdf p" in text
    assert "WHEN s.spec_id IS NOT NULL THEN 'HTML'" in text


def test_legacy_gold_columns_precede_new_provenance_columns():
    """Postgres CREATE OR REPLACE VIEW may only append, not reorder columns."""
    model = (Path(__file__).resolve().parents[1] /
             "dbt/solar_dbt/models/marts/panel_technical_comparison.sql").read_text()
    tail = model.rsplit("\nSELECT\n", 1)[1]
    legacy = (
        "overall_rank", "scrape_id", "scrape_run_id", "title", "source_url",
        "price_pln", "catalog_power_w", "pln_per_watt", "watt_per_pln",
        "price_category", "is_available", "scraped_at", "spec_id",
        "spec_fetched_at", "parser_version", "spec_hash", "spec_page_title",
        "spec_quality", "parse_issue_count", "parse_issues", "datasheet_urls",
        "manufacturer", "model", "cell_technology", "technical_power_w",
        "efficiency_pct", "voc_v", "vmp_v", "isc_a", "imp_a", "bifaciality_pct",
        "cell_count", "area_m2", "power_density_w_m2", "mass_kg",
        "max_system_voltage_v", "max_series_fuse_a", "temp_coeff_pmax_pct_c",
        "temp_coeff_voc_pct_c", "temp_coeff_isc_pct_c", "nmot_c",
        "product_warranty_years", "performance_warranty_years",
        "has_specification", "spec_power_matches_catalog",
    )
    prefix = "".join(f"    {x},\n" for x in legacy)
    assert tail.startswith(prefix)
    assert tail.index("AS technical_status") < tail.index("AS is_technical_comparable")
    assert tail.index("AS is_technical_comparable") < tail.index("    technical_source,")
