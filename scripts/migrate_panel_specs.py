"""Idempotent DDL migration for the enrichment pilot. No historical table edits."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scraper.load import get_connection
MIGRATION = ROOT / 'docker/postgres/init/006_panel_spec_snapshots.sql'


def main():
    statement = MIGRATION.read_text(encoding='utf-8-sig')
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(statement)
    print('MIGRATION PASS — bronze.panel_spec_snapshots is ready (existing tables unchanged)')


if __name__ == '__main__':
    main()
