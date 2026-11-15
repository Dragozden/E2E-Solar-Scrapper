# Scraper regression tests (offline)

## Why this exists

On 2026-10-28, the retailer's catalog shrank from 12 expected pages to four.
The old fixed-page scraper fetched repeated product cards and wrote 126 rows
containing only 78 unique URLs. dbt correctly stopped on its integrity check.

`tests/test_extractor_regression.py` guards against this class of error without
making requests to the retailer. The tests use a real Playwright Chromium browser for parsing and DOM queries.
A small `OfflinePage` adapter replaces only `goto()` with `set_content()` from
local fixtures. It refuses non-loopback navigations and returns a synthetic HTTP
status (including 404 for unexpected paths). **There are zero outgoing
requests to the store.**

## Fixtures

The HTML files in `tests/fixtures/` are **minimal, synthetic contract samples**
based on the selectors used in the scraper (`Lista produktów`, `product-tile`,
`name`, `price`, `availability-notifier-btn`, and `Następne produkty`). They are
**not captured copies of the current shop's HTML**. They check our assumptions;
if the retailer changes its real DOM, a periodic live smoke-check or a new,
sanitized and reviewed snapshot is still needed.

| Fixture | Purpose |
| --- | --- |
| `catalog_page_1.html` | Category heading; valid/invalid products; availability; next link; decoy tile outside section |
| `catalog_page_2.html` | Last page; overlap with page 1; two new unique offers |
| `catalog_repeated.html` | All URLs were already encountered; fail closed |
| `catalog_missing_section.html` | Changed category heading/DOM |
| `catalog_missing_url.html` | Valid product without source href |
| `catalog_missing_next_href.html` | Visible next-page control without `href` |

## Running

From the repository root:

```powershell
uv sync --frozen
uv run --frozen python -m playwright install chromium
uv run --frozen python -m pytest tests/test_extractor_regression.py -q
uv run --frozen python -m pytest -q
```

On Windows, if Chromium has not been installed yet, install it using the same
Python environment as Playwright. In GitHub Actions, the Python job installs
Chromium and the required Linux dependencies (`playwright install --with-deps chromium`).
These browser-backed tests add some execution time to CI. The current CI is
configured for Ubuntu 24.04 to make Playwright installation predictable.

## What is covered

- Correct navigation from the first category page to a discovered last page.
- Deduplication of overlapping product URLs across pages and preservation of a
  single `scrape_run_id`.
- Category scoping: a product tile outside the `Lista produktów` section is ignored.
- Availability marker, relative URL normalization and rejection of non-panels.
- Fail-closed behavior for repeated pages, missing sections, invalid product
  URLs, malformed pagination, HTTP failures, loops and `MAX_PAGES`.
- Parser behavior on **real HTML DOM locators**, not just Python mocks.

## Deployment safety

No production SQL schema changes. `scrape_panels(scrape_run_id)` keeps its
public API. `_scrape_catalog(page, scrape_run_id)` contains the prior scraping
loop so regression tests can provide their own offline Playwright page.

A passing test suite does **not** prove that the current live Soltech DOM still
matches these fixtures. Continue monitoring Airflow and Bronze run counts.
