"""Safe enrichment pilot tests: offline CLI, SQL, bounded operation."""
from pathlib import Path
import subprocess
import sys
from types import ModuleType
import pytest

from scripts import panel_detail_pilot as pilot
from scraper.panel_detail_specs import parse_panel_details

ROOT = Path(__file__).resolve().parents[1]
URL = 'https://sklepsoltech.pl/pl/p/Panel-testowy/4226'


def test_offline_cli_never_calls_database_or_store():
    command = [sys.executable, str(ROOT / 'scripts/panel_detail_pilot.py'),
               '--html', str(ROOT / 'tests/fixtures/panel_detail_ja_solar.html'),
               '--url', URL]
    res = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=12)
    assert res.returncode == 0, res.stderr
    assert 'PREVIEW ONLY' in res.stdout
    assert '"rated_power_w": 510.0' in res.stdout


def test_offline_write_is_rejected():
    command = [sys.executable, str(ROOT / 'scripts/panel_detail_pilot.py'),
               '--html', str(ROOT / 'tests/fixtures/panel_detail_ja_solar.html'),
               '--url', URL, '--write']
    res = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=12)
    assert res.returncode != 0
    assert 'read-only' in res.stderr


def test_hard_limit_of_5():
    command = [sys.executable, str(ROOT / 'scripts/panel_detail_pilot.py'), '--live', '--limit', '6']
    res = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=12)
    assert res.returncode != 0
    assert '1..5' in res.stderr


def test_requires_respectful_delay():
    command = [sys.executable, str(ROOT / 'scripts/panel_detail_pilot.py'), '--live', '--delay-seconds', '0']
    res = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=12)
    assert res.returncode != 0
    assert '3..120' in res.stderr


def test_select_urls_rejects_untrusted_rows(monkeypatch):
    class Cursor:
        def execute(self, *args, **kwargs): pass
        def fetchall(self):
            return [('https://evil.test/pl/p/Bad/10',), (URL,)]
        def __enter__(self): return self
        def __exit__(self, *args): pass
    class Conn:
        def cursor(self): return Cursor()
        def __enter__(self): return self
        def __exit__(self, *args): pass
    fake = ModuleType('scraper.load')
    fake.get_connection = lambda: Conn()
    monkeypatch.setitem(sys.modules, 'scraper.load', fake)
    assert pilot.select_product_urls(3) == [URL]


def test_insert_uses_parameterized_sql_and_skips_duplicates(monkeypatch):
    sql_calls = []
    class Cursor:
        def execute(self, sql, params): sql_calls.append((sql, params))
        def fetchone(self): return (1,) if len(sql_calls) == 1 else None
        def __enter__(self): return self
        def __exit__(self, *args): pass
    class Conn:
        def cursor(self): return Cursor()
        def __enter__(self): return self
        def __exit__(self, *args): pass
    fake = ModuleType('scraper.load')
    fake.get_connection = lambda: Conn()
    monkeypatch.setitem(sys.modules, 'scraper.load', fake)
    sample = parse_panel_details((ROOT / 'tests/fixtures/panel_detail_ja_solar.html').read_text(), URL)
    assert pilot.persist_samples([sample, sample]) == 1
    assert all('ON CONFLICT (source_url, spec_hash) DO NOTHING' in call[0] for call in sql_calls)
    assert sql_calls[0][1][0] == URL


def test_migration_does_not_modify_existing_tables():
    sql = (ROOT / 'docker/postgres/init/006_panel_spec_snapshots.sql').read_text()
    assert 'CREATE TABLE IF NOT EXISTS bronze.panel_spec_snapshots' in sql
    assert 'UNIQUE (source_url, spec_hash)' in sql
    assert 'DROP TABLE' not in sql.upper()
    assert 'TRUNCATE' not in sql.upper()
    assert 'DELETE FROM' not in sql.upper()
    assert 'panel_scrape_raw' not in sql


def test_explicit_url_rejected_without_network():
    with pytest.raises(ValueError, match='Soltech'):
        pilot.live_samples(1, 5, explicit_url='https://evil.test/pl/p/XXX/1')
