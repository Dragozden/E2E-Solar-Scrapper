"""Extend approval provenance with OCR evidence. Never modifies price/history data."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
MIGRATION = ROOT / "docker/postgres/init/009_panel_pdf_ocr_approvals.sql"


def main():
    from scraper.load import get_connection
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(MIGRATION.read_text(encoding="utf-8-sig"))
    print("OCR APPROVAL MIGRATION PASS — existing records preserved")


if __name__ == "__main__":
    main()
