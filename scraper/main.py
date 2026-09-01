from scraper.extractor import scrape_panels
from scraper.load import insert_raw_panel


def main():
    panels = scrape_panels()

    print(f"\nZnaleziono paneli: {len(panels)}")

    for panel in panels:
        insert_raw_panel(panel)

    print("Dane zapisane do PostgreSQL.")


if __name__ == "__main__":
    main()