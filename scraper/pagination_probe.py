"""Inspect live Soltech pagination without writing anything to PostgreSQL.

Run in Airflow (scraper/ is bind-mounted there):
    docker compose exec airflow /opt/airflow/solar-venv/bin/python -m scraper.pagination_probe
"""
from playwright.sync_api import sync_playwright

from scraper.extractor import BASE_URL
from scraper.pagination import next_catalog_url


def main():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            response = page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30000)
            if response is None or response.status >= 400:
                raise RuntimeError("Cannot inspect Soltech: HTTP error")
            links = page.get_by_role("link", name="Następne produkty", exact=True)
            print(f"Strona: {page.url}")
            print(f"Elementy 'Następne produkty': {links.count()}")
            for i in range(links.count()):
                print(f"  [{i + 1}] href={links.nth(i).get_attribute('href')!r}")
            print(f"Wybrany adres: {next_catalog_url(page, 1)}")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
