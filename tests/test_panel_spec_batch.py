"""Offline regression for bounded, restartable enrichment. No HTTP/Postgres."""
from __future__ import annotations
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import sys
from types import ModuleType, SimpleNamespace

import pytest

from scripts import panel_spec_batch as batch
from scraper.panel_detail_specs import parse_panel_details

URL_A = "https://sklepsoltech.pl/pl/p/Panel-fotowoltaiczny-Longi-A/101"
URL_B = "https://sklepsoltech.pl/pl/p/Panel-fotowoltaiczny-TW-B/102"
URL_C = "https://sklepsoltech.pl/pl/p/Panel-fotowoltaiczny-TW-C/103"
NOW = datetime(2026, 11, 16, tzinfo=timezone.utc)
HTML = '''<h1>Panel fotowoltaiczny LONGi A</h1>
<div id="projector_longdescription"><table>
<tr><th>Model</th><td>LONGi A</td></tr>
<tr><th>Moc maksymalna Pmax</th><td>615 W</td></tr>
<tr><th>Napięcie obwodu otwartego Voc</th><td>48,58 V</td></tr>
<tr><th>Napięcie mocy maksymalnej Vmp</th><td>40,71 V</td></tr>
<tr><th>Prąd zwarciowy Isc</th><td>16,00 A</td></tr>
<tr><th>Prąd mocy maksymalnej Imp</th><td>15,11 A</td></tr>
</table></div>'''
PARTIAL_HTML = '''<h1>Panel fotowoltaiczny TW C</h1>
<div id="projector_longdescription"><table><tr><th>Sprawność modułu</th>
<td>od 22,3% do 23,2%</td></tr><tr><th>Technologia ogniw</th>
<td>n-type, 108 ogniw</td></tr></table></div>'''


def item(url=URL_A, rank=1, watts=615, **kwargs):
    return batch.Candidate(url, "Panel fotowoltaiczny Test", rank, watts, **kwargs)


def sample(url=URL_A, content=HTML):
    return parse_panel_details(content, url)


def test_no_prior_data_is_eligible():
    selected, tally = batch.choose_batch([item()], limit=5, at=NOW)
    assert len(selected) == 1 and tally == {"eligible": 1}


def test_selection_bounded_and_ranked():
    items = [item(URL_A, 1), item(URL_B, 2), item(URL_C, 3)]
    selected, tally = batch.choose_batch(items, limit=2, at=NOW)
    assert [i.overall_rank for i in selected] == [1, 2]
    assert tally == {"eligible": 3}


def test_already_complete_never_re_scraped():
    p = sample()
    existing = item(last_spec_id=9, saved_values=p.values,
                    saved_issues=p.parse_issues, saved_at=NOW - timedelta(days=100))
    selected, counts = batch.choose_batch([existing], limit=5, at=NOW,
                                           include_incomplete=True)
    assert not selected and counts["already_complete"] == 1


def test_saved_partial_is_not_retried_by_default():
    p = sample(URL_C, PARTIAL_HTML)
    previous = item(URL_C, 3, 505, last_spec_id=3, saved_values=p.values,
                    saved_issues=p.parse_issues, saved_at=NOW - timedelta(days=90))
    assert batch.choose_batch([previous], limit=3, at=NOW)[1] == {"already_saved_partial": 1}


def test_saved_partial_is_retryable_after_cooldown():
    p = sample(URL_C, PARTIAL_HTML)
    previous = item(URL_C, 3, 505, last_spec_id=3, saved_values=p.values,
                    saved_issues=p.parse_issues, saved_at=NOW - timedelta(days=31))
    selected, _ = batch.choose_batch([previous], limit=5, at=NOW,
                                      include_incomplete=True, cooldown_days=30)
    assert selected == [previous]


def test_saved_partial_not_retryable_while_cooling_down():
    p = sample(URL_C, PARTIAL_HTML)
    previous = item(URL_C, 3, 505, last_spec_id=3, saved_values=p.values,
                    saved_issues=p.parse_issues, saved_at=NOW - timedelta(days=31),
                    attempted_at=NOW - timedelta(days=2), last_outcome="INCOMPLETE")
    assert batch.choose_batch([previous], limit=5, at=NOW, include_incomplete=True)[1] == {"cooldown": 1}


def test_failed_attempt_cools_unsaved_page():
    failed = item(attempted_at=NOW - timedelta(days=1), last_outcome="STOPPED")
    selected, tally = batch.choose_batch([failed], limit=5, at=NOW)
    assert not selected and tally["cooldown"] == 1


def test_failed_attempt_after_cooldown_is_eligible():
    failed = item(attempted_at=NOW - timedelta(days=31), last_outcome="SKIPPED")
    selected, _ = batch.choose_batch([failed], limit=5, at=NOW)
    assert selected == [failed]


def test_untrusted_url_never_selected():
    bad = item("https://example.test/pl/p/fake/15")
    selected, tally = batch.choose_batch([bad], limit=5, at=NOW)
    assert not selected and tally["untrusted_url"] == 1


def test_reject_unrealistic_limits_or_cooldowns():
    for limit in (0, 11):
        with pytest.raises(ValueError, match="limit"):
            batch.choose_batch([], limit=limit)
    with pytest.raises(ValueError, match="cooldown"):
        batch.choose_batch([], limit=3, cooldown_days=0)


def test_missing_electrical_values_is_incomplete_not_guessed():
    p = sample(URL_C, PARTIAL_HTML)
    assert batch.assess_values(p.values, p.parse_issues, 505) == "INCOMPLETE"
    assert "efficiency_pct" not in p.values


def test_electrical_disagreement_causes_power_mismatch():
    p = sample()
    assert batch.assess_values(p.values, p.parse_issues, 505) == "POWER_MISMATCH"


def test_physical_or_parser_issue_requires_review():
    p = sample()
    assert batch.assess_values(p.values, ["combined_warranty_needs_review"], 615) == "REVIEW"


def test_consistent_spec_passes():
    p = sample()
    assert batch.assess_values(p.values, [], 615) == "PASS"


class Page:
    def __init__(self, *, status=200, actual_url=URL_A, html=HTML,
                 broken_dom=False, navigation_error=False):
        self.status = status
        self.url = actual_url
        self.html = html
        self.broken_dom = broken_dom
        self.navigation_error = navigation_error
        self.goto_count = 0

    def goto(self, url, *, wait_until, timeout):
        self.goto_count += 1
        assert timeout == 30000 and wait_until == "domcontentloaded"
        if self.navigation_error:
            raise TimeoutError("slow request")
        return SimpleNamespace(status=self.status)

    def wait_for_timeout(self, duration):
        assert duration == 600

    def evaluate(self, js):
        if self.broken_dom:
            raise ValueError("execution context destroyed")
        return {"href": self.url, "html": self.html}


def test_product_snapshot_accepts_fragment_same_url_and_preserves_canonical():
    page = Page(actual_url=URL_A + "#tabs")
    res = batch.fetch_product(page, item())
    assert res.sample.source_url == URL_A
    assert res.sample.values["rated_power_w"] == 615
    assert page.goto_count == 1


def test_product_snapshot_rejects_escaped_domain():
    res = batch.fetch_product(Page(actual_url="https://evil.test/pl/p/x/1"), item())
    assert res.sample is None and res.reason == "unexpected_redirect"


def test_product_snapshot_rejects_other_product_path():
    res = batch.fetch_product(Page(actual_url=URL_B), item())
    assert res.sample is None and res.reason == "unexpected_redirect"


def test_product_snapshot_rejects_dom_switch():
    res = batch.fetch_product(Page(broken_dom=True), item())
    assert res.sample is None and res.reason == "snapshot_unavailable"


@pytest.mark.parametrize("http_status", [403, 404, 429, 500])
def test_any_http_error_stops_without_retry(http_status):
    page = Page(status=http_status)
    with pytest.raises(batch.StopBatch, match=f"http_{http_status}"):
        batch.fetch_product(page, item())
    assert page.goto_count == 1


def test_timeout_stops_without_retry():
    page = Page(navigation_error=True)
    with pytest.raises(batch.StopBatch, match="navigation_TimeoutError"):
        batch.fetch_product(page, item())
    assert page.goto_count == 1


def test_missing_or_invalid_dom_skipped_not_saved():
    res = batch.fetch_product(Page(html="<h1>Restricted</h1>"), item())
    assert res.sample is None and res.reason == "missing_product_specs"


def test_run_commits_each_product_in_order_and_retains_partials():
    items = [item(URL_A, 1), item(URL_B, 2, 505)]
    actions = []
    sleeps = []
    def fetch(c):
        return batch.FetchResult(sample(c.source_url, HTML if c.source_url == URL_A else PARTIAL_HTML))
    def save(c, outcome, *, sample=None, note=""):
        actions.append((c.source_url, outcome, sample is not None))
        return True
    report = batch.run_items(items, fetch=fetch, write=True, save=save,
                             sleep=sleeps.append, delay_seconds=9)
    assert actions == [(URL_A, "PASS", True), (URL_B, "INCOMPLETE", True)]
    assert sleeps == [9]
    assert report["new_spec_versions"] == 2
    assert report["outcomes"]["INCOMPLETE"] == 1


def test_preview_mode_never_writes_database():
    report = batch.run_items([item()], fetch=lambda _: batch.FetchResult(sample()),
                             save=lambda *args, **kwargs: pytest.fail("unexpected write"))
    assert report["writes_enabled"] is False and report["new_spec_versions"] == 0


def test_failure_stops_subsequent_requests_but_keeps_previous_commit():
    items = [item(URL_A, 1), item(URL_B, 2), item(URL_C, 3)]
    visited, saved = [], []
    def fetch(c):
        visited.append(c.source_url)
        if c.source_url == URL_B:
            raise batch.StopBatch("http_429")
        return batch.FetchResult(sample(c.source_url))
    def save(c, outcome, *, sample=None, note=""):
        saved.append((c.source_url, outcome))
        return sample is not None
    report = batch.run_items(items, fetch=fetch, write=True, save=save, sleep=lambda _: None)
    assert visited == [URL_A, URL_B]
    assert saved == [(URL_A, "PASS"), (URL_B, "STOPPED")]
    assert report["stopped"] is True and report["new_spec_versions"] == 1


def test_invalid_content_is_logged_as_skip_and_batch_continues():
    items = [item(URL_A, 1), item(URL_B, 2)]
    seen = []
    def fetch(c):
        return batch.FetchResult(None, "unexpected_redirect") if c.source_url == URL_A else batch.FetchResult(sample(URL_B))
    def save(c, outcome, *, sample=None, note=""):
        seen.append(outcome)
        return sample is not None
    result = batch.run_items(items, fetch=fetch, write=True, save=save, sleep=lambda _: None)
    assert seen == ["SKIPPED", "PASS"]
    assert result["outcomes"]["SKIPPED"] == 1


def test_singleton_lock_fails_on_second_acquire_and_recovers(tmp_path):
    lock = tmp_path / "lock"
    with batch.exclusive_batch(lock):
        with pytest.raises(RuntimeError, match="already running"):
            with batch.exclusive_batch(lock):
                pass
    assert not lock.exists()


def test_cli_plan_does_not_launch_browser(monkeypatch, capsys):
    monkeypatch.setattr(batch, "load_candidates", lambda: [item()])
    assert batch.main(["plan", "--limit", "3"]) == 0
    assert "selected=1" in capsys.readouterr().out


def test_cli_no_candidates_skips_browser(monkeypatch):
    p = sample()
    already = item(last_spec_id=8, saved_values=p.values, saved_issues=[], saved_at=NOW)
    monkeypatch.setattr(batch, "load_candidates", lambda: [already])
    assert batch.main(["run", "--limit", "5"]) == 0


def test_sql_migration_only_adds_append_only_attempts():
    ddl = (Path(batch.ROOT) / "docker/postgres/init/007_panel_spec_attempts.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS bronze.panel_spec_attempts" in ddl
    assert "REFERENCES bronze.panel_spec_snapshots" in ddl
    for forbidden in ("DROP TABLE", "TRUNCATE", "DELETE FROM", "panel_scrape_raw"):
        assert forbidden not in ddl.upper()


def test_batch_sql_selects_current_ranking_and_actual_latest_spec():
    import inspect
    src = inspect.getsource(batch.load_candidates)
    assert "gold.current_panel_ranking" in src
    assert "bronze.panel_spec_snapshots" in src
    assert "bronze.panel_spec_attempts" in src
    assert "ORDER BY fetched_at DESC, spec_id DESC" in src


def test_per_item_save_uses_conflict_safe_transaction(monkeypatch):
    class FakeCursor:
        def __init__(self):
            self.calls = []
        def execute(self, sql, params):
            self.calls.append((sql, params))
        def fetchone(self):
            return (77,)
        def __enter__(self): return self
        def __exit__(self, *args): pass
    class FakeConn:
        def __init__(self): self.cur = FakeCursor()
        def cursor(self): return self.cur
        def __enter__(self): return self
        def __exit__(self, *args): pass
    conn = FakeConn()
    fake_scraper_load = ModuleType("scraper.load")
    fake_scraper_load.get_connection = lambda: conn
    monkeypatch.setitem(sys.modules, "scraper.load", fake_scraper_load)
    fake_json = ModuleType("psycopg.types.json")
    fake_json.Jsonb = lambda x: x
    monkeypatch.setitem(sys.modules, "psycopg", ModuleType("psycopg"))
    monkeypatch.setitem(sys.modules, "psycopg.types", ModuleType("psycopg.types"))
    monkeypatch.setitem(sys.modules, "psycopg.types.json", fake_json)
    assert batch.store_attempt(item(), "PASS", sample=sample()) is True
    assert "ON CONFLICT (source_url, spec_hash) DO NOTHING" in conn.cur.calls[0][0]
    assert "INSERT INTO bronze.panel_spec_attempts" in conn.cur.calls[1][0]
    assert conn.cur.calls[1][1][2] == 77


def test_only_canonical_url_can_be_written(monkeypatch):
    with pytest.raises(ValueError, match="differs"):
        batch.store_attempt(item(), "PASS", sample=sample(URL_B))


def test_attempt_rejects_secrets_in_note():
    with pytest.raises(ValueError, match="sanitized"):
        batch.store_attempt(item(), "STOPPED", note="https://private/?token=1")


def test_attempt_outcome_requires_valid_sample():
    with pytest.raises(ValueError):
        batch.store_attempt(item(), "PASS")
    with pytest.raises(ValueError):
        batch.store_attempt(item(), "SKIPPED", sample=sample())


def test_naive_timestamp_rejected():
    with pytest.raises(ValueError, match="timezone"):
        batch.as_aware_utc(datetime(2026, 11, 16))


def test_status_aggregates_without_network(monkeypatch, capsys):
    monkeypatch.setattr(batch, "load_progress", lambda: {
        "current_offers": 72, "technical_statuses": {"PASS": 2, "NOT_ENRICHED": 70},
        "total_logged_attempts": 0, "attempts_by_outcome": {},
    })
    assert batch.main(["status"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["current_offers"] == 72
    assert result["total_logged_attempts"] == 0


def test_status_sql_is_read_only_and_counts_all_attempts(monkeypatch):
    class FakeCursor:
        def __init__(self): self.queries = []
        def execute(self, sql): self.queries.append(sql)
        def fetchall(self):
            return [("PASS", 2), ("NOT_ENRICHED", 70)] if len(self.queries) == 1 else [("PASS", 2), ("INCOMPLETE", 1)]
        def __enter__(self): return self
        def __exit__(self, *args): pass
    class FakeConn:
        def __init__(self): self.cur = FakeCursor()
        def cursor(self): return self.cur
        def __enter__(self): return self
        def __exit__(self, *args): pass
    conn = FakeConn()
    fake = ModuleType("scraper.load")
    fake.get_connection = lambda: conn
    monkeypatch.setitem(sys.modules, "scraper.load", fake)
    result = batch.load_progress()
    assert result["current_offers"] == 72
    assert result["total_logged_attempts"] == 3
    assert len(conn.cur.queries) == 2
    assert all(q.lstrip().startswith("SELECT") for q in conn.cur.queries)
