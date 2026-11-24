"""Manual, bounded, restartable PV product specification enrichment (Step 11.4).

Read-only plan:  python scripts/panel_spec_batch.py plan --limit 5
Live preview:    python scripts/panel_spec_batch.py run --limit 3
Save per item:   python scripts/panel_spec_batch.py run --limit 3 --write
Retry partials: python scripts/panel_spec_batch.py plan --retry-incomplete --cooldown-days 30

This module does not register an Airflow DAG, alter price-history tables, or
fetch manufacturer PDFs. The existing pilot remains unchanged. Each product
is committed separately, so a later network failure does not undo progress.
Only use with permission and a request rate allowed by the source website.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
import time
from typing import Callable, Iterator

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scraper.panel_detail_specs import (
    PanelSpecSample, is_allowed_detail_url, parse_panel_details, sample_quality,
)
from scripts.panel_detail_pilot import _document_snapshot, _same_product_document

RUNNER_VERSION = "panel-spec-batch-v1"
MAX_ITEMS = 10
MIN_DELAY = 8.0
MIN_COOLDOWN_DAYS = 7
STOPPED_OUTCOMES = frozenset({"STOPPED"})
OUTCOMES = frozenset({
    "PASS", "INCOMPLETE", "REVIEW", "POWER_MISMATCH", "SKIPPED", "STOPPED"
})
LOCKFILE = ROOT / "runtime" / "locks" / ".panel_spec_batch.lock"


@dataclass(frozen=True)
class Candidate:
    source_url: str
    title: str
    overall_rank: int
    catalog_power_w: int
    last_spec_id: int | None = None
    saved_values: dict | None = None
    saved_issues: list[str] | None = None
    saved_at: datetime | None = None
    attempted_at: datetime | None = None
    last_outcome: str | None = None


@dataclass(frozen=True)
class FetchResult:
    sample: PanelSpecSample | None
    reason: str = ""  # Sanitized category only, never URLs or page content.


class StopBatch(RuntimeError):
    """Stop all further HTTP requests (HTTP error, timeout, browser failure)."""


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def as_aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        raise ValueError("Enrichment timestamps must have a timezone")
    return value.astimezone(timezone.utc)


def load_candidates() -> list[Candidate]:
    """Use live Bronze snapshots, not a stale cached Gold enrichment status.

    LATERAL subqueries select the newest saved spec and the newest logged
    attempt. This guarantees resume works immediately after each INSERT,
    even if the user has not manually executed another dbt build.
    """
    from scraper.load import get_connection
    query = """
        SELECT r.source_url, r.title, r.overall_rank, r.power_w,
               s.spec_id, s.normalized_values, s.parse_issues, s.fetched_at,
               a.attempted_at, a.outcome
        FROM gold.current_panel_ranking r
        LEFT JOIN LATERAL (
            SELECT spec_id, normalized_values, parse_issues, fetched_at
            FROM bronze.panel_spec_snapshots
            WHERE source_url = r.source_url
            ORDER BY fetched_at DESC, spec_id DESC
            LIMIT 1
        ) s ON TRUE
        LEFT JOIN LATERAL (
            SELECT attempted_at, outcome
            FROM bronze.panel_spec_attempts
            WHERE source_url = r.source_url
            ORDER BY attempted_at DESC, attempt_id DESC
            LIMIT 1
        ) a ON TRUE
        WHERE r.is_available IS TRUE AND r.source_url IS NOT NULL
        ORDER BY r.overall_rank, r.source_url
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query)
            data = cur.fetchall()
    return [Candidate(*r) for r in data]


def saved_status(item: Candidate) -> str | None:
    if item.last_spec_id is None:
        return None
    if not isinstance(item.saved_values, dict) or not isinstance(item.saved_issues, list):
        return "REVIEW"
    return assess_values(item.saved_values, item.saved_issues, item.catalog_power_w)


def assess_values(values: dict, issues: list[str], catalog_power: int) -> str:
    """Align with Silver/Gold (including the current offer's power variant)."""
    quality = sample_quality(values, issues)
    if quality["missing_core_fields"]:
        return "INCOMPLETE"
    if quality["blocking_issues"] or issues:
        return "REVIEW"
    technical_power = values.get("rated_power_w")
    if not isinstance(technical_power, (int, float)) or isinstance(technical_power, bool):
        return "INCOMPLETE"
    if abs(technical_power - catalog_power) > 1:
        return "POWER_MISMATCH"
    return "PASS"


def candidate_reason(item: Candidate, *, include_incomplete: bool,
                     cooldown_days: int, at: datetime) -> str:
    """Return 'eligible' or a safe reason to skip without any HTTP requests."""
    if not is_allowed_detail_url(item.source_url):
        return "untrusted_url"
    prior_quality = saved_status(item)
    if prior_quality == "PASS":
        return "already_complete"
    if prior_quality is not None and not include_incomplete:
        return "already_saved_partial"
    previous = max((as_aware_utc(d) for d in (item.saved_at, item.attempted_at)
                    if d is not None), default=None)
    if previous is not None and previous > at - timedelta(days=cooldown_days):
        return "cooldown"
    return "eligible"


def choose_batch(items: list[Candidate], *, limit: int,
                 include_incomplete: bool = False, cooldown_days: int = 30,
                 at: datetime | None = None) -> tuple[list[Candidate], dict[str, int]]:
    if not 1 <= limit <= MAX_ITEMS:
        raise ValueError(f"limit must be in 1..{MAX_ITEMS}")
    if cooldown_days < MIN_COOLDOWN_DAYS:
        raise ValueError(f"cooldown_days must be >= {MIN_COOLDOWN_DAYS}")
    current = as_aware_utc(at or now_utc())
    selected: list[Candidate] = []
    counts: dict[str, int] = {}
    for item in items:
        reason = candidate_reason(item, include_incomplete=include_incomplete,
                                  cooldown_days=cooldown_days, at=current)
        counts[reason] = counts.get(reason, 0) + 1
        if reason == "eligible" and len(selected) < limit:
            selected.append(item)
    return selected, counts


def fetch_product(page, item: Candidate) -> FetchResult:
    """One product = one HTTP navigation; no retry, no off-host navigation.

    Reuses the pilot's same-product checks and atomic (URL + DOM) snapshot.
    Final stored key is always the canonical URL from current Gold.
    """
    if not is_allowed_detail_url(item.source_url):
        raise ValueError("Refusing noncanonical Soltech detail URL")
    try:
        response = page.goto(item.source_url, wait_until="domcontentloaded", timeout=30000)
    except Exception as exc:
        raise StopBatch(f"navigation_{type(exc).__name__}") from None
    if response is None:
        raise StopBatch("missing_http_response")
    if response.status >= 400:
        # Stop immediately, especially for 403/429. No retries or bypasses.
        raise StopBatch(f"http_{response.status}")
    try:
        page.wait_for_timeout(600)
        observed = page.url
    except Exception as exc:
        raise StopBatch(f"browser_{type(exc).__name__}") from None
    if not _same_product_document(item.source_url, observed):
        return FetchResult(None, "unexpected_redirect")
    try:
        page_url, html = _document_snapshot(page)
    except Exception:
        return FetchResult(None, "snapshot_unavailable")
    if not _same_product_document(item.source_url, page_url):
        return FetchResult(None, "unexpected_snapshot_url")
    try:
        sample = parse_panel_details(html, item.source_url)
    except Exception as exc:
        return FetchResult(None, "parse_" + type(exc).__name__)
    if (not sample.attributes_raw or not sample.values
            or "panel fotowoltaiczny" not in sample.page_title.casefold()):
        return FetchResult(None, "missing_product_specs")
    return FetchResult(sample)


def store_attempt(item: Candidate, outcome: str, *, sample: PanelSpecSample | None = None,
                  note: str = "") -> bool:
    """One atomic commit per visited product. Return new spec version flag.

    Partial specs are intentionally retained in Bronze; Gold excludes them
    from comparable technical metrics. Never overwrites previous versions.
    """
    if outcome not in OUTCOMES:
        raise ValueError("Unknown attempt outcome")
    if sample is not None and (sample.source_url != item.source_url or
                               not is_allowed_detail_url(sample.source_url)):
        raise ValueError("Sample URL differs from canonical Gold product")
    if (sample is None) != (outcome in ("SKIPPED", "STOPPED")):
        raise ValueError("Only a parsed product may have a quality outcome")
    if not note.isascii() or len(note) > 80 or any(c in note for c in ("/", "\\", "?", "=")):
        raise ValueError("Only short, sanitized notes may be logged")
    from psycopg.types.json import Jsonb
    from scraper.load import get_connection
    created = False
    with get_connection() as conn:
        with conn.cursor() as cur:
            spec_id = None
            if sample is not None:
                cur.execute("""
                    INSERT INTO bronze.panel_spec_snapshots
                    (source_url, page_title, attributes_raw, normalized_values,
                     datasheet_urls, parse_issues, spec_hash, parser_version)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (source_url, spec_hash) DO NOTHING
                    RETURNING spec_id
                """, (sample.source_url, sample.page_title,
                      Jsonb(sample.attributes_raw), Jsonb(sample.values),
                      Jsonb(sample.datasheet_urls), Jsonb(sample.parse_issues),
                      sample.spec_hash, sample.parser_version))
                row = cur.fetchone()
                if row is not None:
                    spec_id, created = row[0], True
                else:
                    cur.execute("""
                        SELECT spec_id FROM bronze.panel_spec_snapshots
                        WHERE source_url = %s AND spec_hash = %s
                    """, (sample.source_url, sample.spec_hash))
                    row = cur.fetchone()
                    if not row:
                        raise RuntimeError("Snapshot conflict but matching spec missing")
                    spec_id = row[0]
            cur.execute("""
                INSERT INTO bronze.panel_spec_attempts
                (source_url, outcome, spec_id, inserted_new_version, note, runner_version)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (item.source_url, outcome, spec_id, created, note, RUNNER_VERSION))
    return created


def run_items(items: list[Candidate], *, fetch: Callable[[Candidate], FetchResult],
              write: bool = False, save: Callable = store_attempt,
              delay_seconds: float = 10.0, sleep: Callable = time.sleep) -> dict:
    if not MIN_DELAY <= delay_seconds <= 120:
        raise ValueError(f"delay_seconds must be in {MIN_DELAY:g}..120")
    totals = {outcome: 0 for outcome in sorted(OUTCOMES)}
    created = 0
    stopped = False
    for i, item in enumerate(items):
        if i:
            sleep(delay_seconds)
        print(f"PRODUCT {i+1}/{len(items)} rank={item.overall_rank} {item.source_url}", flush=True)
        try:
            result = fetch(item)
        except StopBatch as exc:
            note = str(exc)
            totals["STOPPED"] += 1
            if write:
                save(item, "STOPPED", note=note)
            print(f"STOP: {note}; no further requests", flush=True)
            stopped = True
            break
        except Exception as exc:
            # Unknown browser/parser error: don't keep browsing after failure.
            note = "internal_" + type(exc).__name__
            totals["STOPPED"] += 1
            if write:
                save(item, "STOPPED", note=note)
            print(f"STOP: {note}; no further requests", flush=True)
            stopped = True
            break
        if result.sample is None:
            totals["SKIPPED"] += 1
            if write:
                save(item, "SKIPPED", note=result.reason)
            print(f"SKIP: {result.reason}; no technical data saved", flush=True)
            continue
        outcome = assess_values(result.sample.values, result.sample.parse_issues,
                                item.catalog_power_w)
        totals[outcome] += 1
        if write:
            created += int(save(item, outcome, sample=result.sample))
        print(f"{outcome}: {len(result.sample.attributes_raw)} raw attributes, "
              f"{len(result.sample.values)} normalized fields, "
              f"issues={len(result.sample.parse_issues)}"
              + (" [saved]" if write else " [preview]"), flush=True)
    report = {"planned": len(items), "visited": sum(totals.values()),
              "new_spec_versions": created, "outcomes": totals, "stopped": stopped,
              "writes_enabled": write}
    print("SUMMARY: " + json.dumps(report, ensure_ascii=False), flush=True)
    return report


def load_progress() -> dict:
    """Read-only coverage and historical attempt counters for operations."""
    from scraper.load import get_connection
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT technical_status, COUNT(*)
                FROM gold.panel_technical_comparison
                GROUP BY technical_status
            """)
            current = dict(cur.fetchall())
            cur.execute("""
                SELECT outcome, COUNT(*)
                FROM bronze.panel_spec_attempts
                GROUP BY outcome
            """)
            attempts = dict(cur.fetchall())
    return {"current_offers": sum(current.values()), "technical_statuses": current,
            "total_logged_attempts": sum(attempts.values()), "attempts_by_outcome": attempts}


@contextmanager
def exclusive_batch(path: Path = LOCKFILE) -> Iterator[None]:
    """Cross-process local guard; stale lock requires manual process inspection."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise RuntimeError("Enrichment batch already running or stale lock; check processes") from None
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            file.write(f"pid={os.getpid()} utc={now_utc().isoformat()}\n")
        yield
    finally:
        path.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Safe manual PV specification batch enrichment")
    subs = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "run"):
        sub = subs.add_parser(name)
        sub.add_argument("--limit", type=int, default=5)
        sub.add_argument("--retry-incomplete", action="store_true",
                         help="Recheck previously saved non-PASS specs only after cooldown")
        sub.add_argument("--cooldown-days", type=int, default=30)
        if name == "run":
            sub.add_argument("--delay-seconds", type=float, default=10.0)
            sub.add_argument("--write", action="store_true",
                             help="Persist validated and incomplete data plus attempt outcomes")
    subs.add_parser("status", help="Show read-only technical coverage and attempt history")
    args = parser.parse_args(argv)
    if args.command == "status":
        try:
            print(json.dumps(load_progress(), ensure_ascii=False, indent=2))
            return 0
        except Exception as exc:
            print(f"STATUS ERROR: {type(exc).__name__}; check database and Step 11.4 migration",
                  file=sys.stderr)
            return 1
    if not 1 <= args.limit <= MAX_ITEMS:
        parser.error(f"--limit must be 1..{MAX_ITEMS}")
    if args.cooldown_days < MIN_COOLDOWN_DAYS:
        parser.error(f"--cooldown-days must be >= {MIN_COOLDOWN_DAYS}")
    if args.command == "run" and not MIN_DELAY <= args.delay_seconds <= 120:
        parser.error(f"--delay-seconds must be {MIN_DELAY:g}..120")
    try:
        candidates = load_candidates()
        selected, counts = choose_batch(
            candidates, limit=args.limit, include_incomplete=args.retry_incomplete,
            cooldown_days=args.cooldown_days)
        print(f"PLAN: available={len(candidates)} eligible={counts.get('eligible', 0)} "
              f"selected={len(selected)}; skipped={{{', '.join(f'{k}: {v}' for k,v in counts.items() if k != 'eligible')}}}")
        for item in selected:
            print(f"  #{item.overall_rank} {item.title} | {item.source_url}")
        if args.command == "plan" or not selected:
            return 0
        print("MANUAL RUN: respect retailer robots/terms, do not run concurrently with other detail scrapers")
        with exclusive_batch():
            from playwright.sync_api import sync_playwright
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                try:
                    page = browser.new_page()
                    report = run_items(selected, fetch=lambda item: fetch_product(page, item),
                                       write=args.write, delay_seconds=args.delay_seconds)
                finally:
                    browser.close()
        return 1 if report["stopped"] else 0
    except Exception as exc:
        # Never echo DB DSNs, query strings, or other potential credentials.
        print(f"BATCH ERROR: {type(exc).__name__}. "
              "Check PostgreSQL connectivity and apply "
              "scripts/migrate_panel_spec_batch.py before running.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
