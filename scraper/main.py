from uuid import uuid4

from scraper.extractor import scrape_panels
from scraper.load import (
    create_scrape_run,
    finish_scrape_run,
    insert_raw_panels,
)


def main():
    scrape_run_id = uuid4()

    print(f"Rozpoczynam scrape run: {scrape_run_id}")

    create_scrape_run(scrape_run_id)

    try:
        panels = scrape_panels(scrape_run_id)

        print(
            f"Scraper zakończył ekstrakcję. "
            f"Znaleziono: {len(panels)} produktów."
        )

        insert_raw_panels(panels)

        finish_scrape_run(
            scrape_run_id=scrape_run_id,
            status="SUCCESS",
            products_count=len(panels),
        )

        print(
            f"Scrape zakończony sukcesem. "
            f"Run: {scrape_run_id}"
        )

    except KeyboardInterrupt:
        print("\nScraper został przerwany przez użytkownika.")

        finish_scrape_run(
            scrape_run_id=scrape_run_id,
            status="FAILED",
        )

        raise

    except Exception as exc:
        print(f"\nBłąd podczas wykonywania scrape run: {exc}")

        finish_scrape_run(
            scrape_run_id=scrape_run_id,
            status="FAILED",
        )

        raise


if __name__ == "__main__":
    main()