"""Apply only the additive Step 11.4 attempts table to an existing database."""
from __future__ import annotations
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
MIGRATION = ROOT / "docker/postgres/init/007_panel_spec_attempts.sql"


def main():
    from scraper.load import get_connection
    ddl = MIGRATION.read_text(encoding="utf-8-sig")
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(ddl)
    print("MIGRATION PASS — bronze.panel_spec_attempts ready; pricing history untouched")


if __name__ == "__main__":
    main()
