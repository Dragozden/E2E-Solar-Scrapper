from uuid import uuid4

from scraper.extractor import scrape_panels
from scraper.load import (
    create_scrape_run,
    finish_scrape_run,
    insert_raw_panel,
)


def main():
    scrape_run_id = uuid4()

    create_scrape_run(scrape_run_id)

    panels = scrape_panels(scrape_run_id)

    for panel in panels:
        insert_raw_panel(panel)

    finish_scrape_run(
        scrape_run_id,
        len(panels),
    )

    print(
        f"Scrape zakończony. "
        f"Produktów: {len(panels)}"
    )


if __name__ == "__main__":
    main()