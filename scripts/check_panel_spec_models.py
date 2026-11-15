"""Read-only local smoke test for dbt technical models (Step 11.2).

Run from repository root with `uv run --frozen python scripts/check_panel_spec_models.py`.
No writes, schema changes, or scraping. Prints aggregate coverage only.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import sys

# Direct script execution puts scripts/ (not the repo root) on sys.path.
# Match the import strategy of scripts/panel_detail_pilot.py without relying
# on editable package installation or PYTHONPATH set by the caller.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@dataclass(frozen=True)
class ComparisonCounts:
    ranking: int
    comparison: int
    passed: int
    incomplete: int
    review: int
    missing: int
    power_mismatch: int


def validate_counts(counts: ComparisonCounts, min_complete: int = 0) -> None:
    if min_complete < 0:
        raise ValueError("min_complete cannot be negative")
    if counts.ranking != counts.comparison:
        raise RuntimeError("Technical Gold row count differs from current ranking")
    categories = (counts.passed, counts.incomplete, counts.review,
                  counts.missing, counts.power_mismatch)
    if any(x < 0 for x in categories) or sum(categories) != counts.comparison:
        raise RuntimeError("Technical status categories are inconsistent")
    if counts.passed < min_complete:
        raise RuntimeError(f"Only {counts.passed} complete specifications; need {min_complete}")


def fetch_counts():
    from scraper.load import get_connection
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM gold.current_panel_ranking")
            ranking = cur.fetchone()[0]
            cur.execute("""
                SELECT COUNT(*),
                       COUNT(*) FILTER (WHERE technical_status = 'PASS'),
                       COUNT(*) FILTER (WHERE technical_status = 'INCOMPLETE'),
                       COUNT(*) FILTER (WHERE technical_status = 'REVIEW'),
                       COUNT(*) FILTER (WHERE technical_status = 'NOT_ENRICHED'),
                       COUNT(*) FILTER (WHERE technical_status = 'POWER_MISMATCH')
                FROM gold.panel_technical_comparison
            """)
            comparison, passed, incomplete, review, missing, mismatch = cur.fetchone()
            return ComparisonCounts(ranking, comparison, passed, incomplete, review,
                                    missing, mismatch)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Read-only panel spec dbt coverage check")
    parser.add_argument("--min-complete", type=int, default=0)
    args = parser.parse_args(argv)
    try:
        counts = fetch_counts()
        validate_counts(counts, args.min_complete)
    except Exception as exc:
        print(f"SPEC DBT CHECK FAIL: {type(exc).__name__}: {exc}")
        return 1
    print(f"SPEC DBT PASS: {counts.comparison} current offers, "
          f"{counts.passed} complete technical comparisons; "
          f"{counts.incomplete} incomplete, {counts.review} review, "
          f"{counts.missing} not enriched, {counts.power_mismatch} power mismatch")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
