"""Bounded, manual-only PV panel detail enrichment pilot.

Offline: uv run python scripts/panel_detail_pilot.py --html tests/fixtures/panel_detail_ja_solar.html --url https://sklepsoltech.pl/pl/p/test/1234
Live preview: uv run python scripts/panel_detail_pilot.py --live --limit 3
Persist after inspecting preview: uv run python scripts/migrate_panel_specs.py
                                uv run python scripts/panel_detail_pilot.py --live --limit 3 --write

No Airflow integration. Never changes Bronze price history or existing Gold views.
Before live runs review site terms/robots, use low frequency, honor rate limits.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scraper.panel_detail_specs import is_allowed_detail_url, parse_panel_details, sample_quality


def select_product_urls(limit: int) -> list[str]:
    from scraper.load import get_connection
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT source_url FROM gold.current_panel_ranking
                WHERE is_available IS TRUE AND source_url IS NOT NULL
                ORDER BY overall_rank LIMIT %s
            """, (limit,))
            urls = [row[0] for row in cur.fetchall()]
    # Refuse off-host or unexpected URLs even when returned by local DB.
    checked = [u for u in urls if is_allowed_detail_url(u)]
    if not checked:
        raise RuntimeError('No allowed product URLs found in latest Gold ranking')
    return checked


def persist_samples(samples) -> int:
    """Append only new spec versions; a repeat pilot is idempotent by (URL, hash)."""
    from scraper.load import get_connection
    count = 0
    with get_connection() as conn:
        with conn.cursor() as cur:
            for sample in samples:
                cur.execute("""
                    INSERT INTO bronze.panel_spec_snapshots
                    (source_url, page_title, attributes_raw, normalized_values,
                     datasheet_urls, parse_issues, spec_hash, parser_version)
                    VALUES (%s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s)
                    ON CONFLICT (source_url, spec_hash) DO NOTHING
                    RETURNING spec_id
                """, (
                    sample.source_url, sample.page_title,
                    json.dumps(sample.attributes_raw, ensure_ascii=False),
                    json.dumps(sample.values, ensure_ascii=False),
                    json.dumps(sample.datasheet_urls, ensure_ascii=False),
                    json.dumps(sample.parse_issues, ensure_ascii=False),
                    sample.spec_hash, sample.parser_version,
                ))
                if cur.fetchone() is not None:
                    count += 1
    return count


def _readable_url(url: str) -> str:
    """Only display scheme/host/path in logs, not queries or credentials."""
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.hostname or '?'}{parts.path}"


def _same_product_path(expected: str, actual: str) -> bool:
    """Identity is the store product path, never tracking query/fragment."""
    a, b = urlsplit(expected), urlsplit(actual)
    return a.hostname == b.hostname and a.path.rstrip("/") == b.path.rstrip("/")


def _same_product_document(expected: str, actual: str) -> bool:
    """Accept only HTTPS on the exact trusted host and same product path.

    Shops can append a harmless query string or fragment with history.replaceState.
    The canonical Gold URL remains the DB key. Never permit a new origin,
    credentials, non-HTTPS URL, other port, or different product path.
    """
    if not is_allowed_detail_url(expected):
        return False
    try:
        observed = urlsplit(actual)
        return (observed.scheme == "https"
                and observed.hostname == "sklepsoltech.pl"
                and observed.username is None and observed.password is None
                and observed.port in (None, 443)
                and _same_product_path(expected, actual))
    except ValueError:  # malformed port or malformed URL
        return False


def _document_snapshot(page) -> tuple[str, str]:
    """Capture document URL and DOM in one browser execution.

    Reading `page.url` and `page.content()` separately can produce mismatched
    values when the retailer updates the address using client-side navigation.
    """
    data = page.evaluate("""() => ({
        href: window.location.href,
        html: document.documentElement ? document.documentElement.outerHTML : ''
    })""")
    if not isinstance(data, dict) or not isinstance(data.get("href"), str) \
            or not isinstance(data.get("html"), str):
        raise ValueError("Unable to capture page URL and HTML atomically")
    return data["href"], data["html"]


def live_samples(limit: int, delay: float, *, explicit_url: str | None = None,
                 strict: bool = False):
    """Bounded preview; never trust a URL that changes during page loading.

    Redirects to home/category/challenge pages are skipped in preview and fail
    the whole batch with strict=True (--write), so no partial batch is saved.
    HTTP errors (especially 429) stop immediately; no retries or bypasses.
    """
    from playwright.sync_api import sync_playwright
    if explicit_url is not None and not is_allowed_detail_url(explicit_url):
        raise ValueError("--live-url must be an HTTPS Soltech product URL")
    urls = [explicit_url] if explicit_url else select_product_urls(limit)
    samples = []
    skipped = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            for i, url in enumerate(urls):
                if i:
                    time.sleep(delay)
                print(f"PRODUCT {i+1}/{len(urls)}: {_readable_url(url)}", flush=True)
                response = page.goto(url, wait_until="domcontentloaded", timeout=30000)
                if response is None or response.status >= 400:
                    status = "none" if response is None else str(response.status)
                    raise RuntimeError(f"Product #{i + 1}: HTTP response {status}; stopped")
                page.wait_for_timeout(600)
                actual_url = page.url
                if not _same_product_document(url, actual_url):
                    reason = (f"Product #{i + 1}: left the intended HTTPS product path; "
                              f"observed {_readable_url(actual_url)} "
                              f"(query={bool(urlsplit(actual_url).query)}, "
                              f"fragment={bool(urlsplit(actual_url).fragment)})")
                    print(f"SKIP: {reason}", file=sys.stderr, flush=True)
                    skipped.append(reason)
                    continue
                try:
                    snapshot_url, content = _document_snapshot(page)
                except Exception as exc:
                    # An in-flight navigation can invalidate Playwright's execution
                    # context. Skip safely, without reloading or retrying the site.
                    reason = (f"Product #{i + 1}: document snapshot failed "
                              f"({type(exc).__name__}); no retry")
                    print(f"SKIP: {reason}", file=sys.stderr, flush=True)
                    skipped.append(reason)
                    continue
                if not _same_product_document(url, snapshot_url):
                    reason = (f"Product #{i + 1}: snapshot belongs to a different "
                              f"page {_readable_url(snapshot_url)}")
                    print(f"SKIP: {reason}", file=sys.stderr, flush=True)
                    skipped.append(reason)
                    continue
                if snapshot_url != url:
                    # The path is still the same, so this is not a new product.
                    # Do not log query values: they can contain session tokens.
                    print(f"INFO: Product #{i + 1}: same-product URL variation "
                          f"(query={bool(urlsplit(snapshot_url).query)}, "
                          f"fragment={bool(urlsplit(snapshot_url).fragment)}); "
                          "using canonical Gold URL", flush=True)
                # Persist the stable URL from Gold, never temporary query state.
                sample = parse_panel_details(content, url)
                if not sample.attributes_raw or not sample.values:
                    reason = (f"Product #{i + 1}: no usable technical parameters; "
                              "possible empty or unrelated page")
                    print(f"SKIP: {reason}", file=sys.stderr, flush=True)
                    skipped.append(reason)
                    continue
                samples.append(sample)
                quality = sample_quality(sample.values, sample.parse_issues)
                print(f"OK: {len(sample.attributes_raw)} attributes, "
                      f"{len(sample.values)} normalized fields, "
                      f"{len(sample.parse_issues)} issues; "
                      f"quality={quality['status']}", flush=True)
                if quality['missing_core_fields']:
                    print(f"  MISSING CORE: {', '.join(quality['missing_core_fields'])}", flush=True)
                if quality['review_issues']:
                    print(f"  TO REVIEW: {', '.join(quality['review_issues'])}", flush=True)
        finally:
            browser.close()
    print(f"LIVE SUMMARY: {len(samples)}/{len(urls)} valid product pages, "
          f"{len(skipped)} skipped", flush=True)
    if strict and skipped:
        raise RuntimeError("Incomplete live batch: refusing --write after skipped product pages")
    if strict:
        inadequate = [s.source_url for s in samples
                      if sample_quality(s.values, s.parse_issues)['status'] != 'PASS']
        if inadequate:
            raise RuntimeError(
                f"Incomplete technical data in {len(inadequate)} product(s): "
                "refusing --write; review --live output and select only approved products"
            )
    if not samples:
        raise RuntimeError("No valid product pages; nothing to preview or write")
    return samples


def main() -> int:
    parser = argparse.ArgumentParser(description='Manual-only PV specs pilot; preview default')
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--html', type=Path, help='Offline local HTML input; no DB/network')
    source.add_argument('--live', action='store_true', help='Visit a bounded list of URLs from current Gold')
    source.add_argument('--live-url', type=str, help='Visit one explicitly selected Soltech product page')
    parser.add_argument('--url', type=str, help='Canonical detail URL with --html')
    parser.add_argument('--limit', type=int, default=3, help='Maximum 1..5, live only')
    parser.add_argument('--delay-seconds', type=float, default=5.0)
    parser.add_argument('--write', action='store_true', help='Opt-in database INSERT of parsed metadata')
    args = parser.parse_args()
    if not 1 <= args.limit <= 5:
        parser.error('--limit must be within 1..5')
    if not 3 <= args.delay_seconds <= 120:
        parser.error('--delay-seconds must be within 3..120')
    if args.html:
        if not args.url:
            parser.error('--url is required with --html')
        if args.write:
            parser.error('Offline mode is strictly read-only')
        samples = [parse_panel_details(args.html.read_text(encoding='utf-8'), args.url)]
    else:
        if args.url:
            parser.error('--url only applies to offline --html')
        print('LIVE PILOT: limit <=5; review site rules first; stop on 429/HTTP error')
        samples = live_samples(args.limit, args.delay_seconds, explicit_url=args.live_url,
                               strict=args.write)
    for sample in samples:
        print(json.dumps(sample.as_dict(), ensure_ascii=False, indent=2))
    if args.write:
        if any(not s.attributes_raw for s in samples):
            raise RuntimeError('Empty technical description; refusing DB write')
        print(f'INSERTED {persist_samples(samples)} new spec snapshots; duplicates skipped')
    else:
        print('PREVIEW ONLY — no database writes (use --write after review)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
