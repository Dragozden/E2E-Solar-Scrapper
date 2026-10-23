"""Fail the Airflow task when the latest successful ingestion is inconsistent."""
from scraper.load import get_connection


def main() -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    r.scrape_run_id,
                    r.products_count,
                    COUNT(p.scrape_id) AS actual_count,
                    COUNT(p.scrape_id) FILTER (
                        WHERE p.source_url IS NULL OR TRIM(p.source_url) = ''
                    ) AS missing_urls,
                    COUNT(DISTINCT p.source_url) AS unique_urls
                FROM (
                    SELECT scrape_run_id, products_count
                    FROM bronze.scrape_runs
                    WHERE status = 'SUCCESS'
                    ORDER BY finished_at DESC NULLS LAST
                    LIMIT 1
                ) r
                LEFT JOIN bronze.panel_scrape_raw p
                    ON p.scrape_run_id = r.scrape_run_id
                GROUP BY r.scrape_run_id, r.products_count
            """)
            row = cur.fetchone()
            if row is None:
                raise RuntimeError("No successful scrape run found")
            run_id, expected, actual, missing, unique = row
            if expected is None or actual == 0 or expected != actual:
                raise RuntimeError(
                    f"Inconsistent run {run_id}: expected={expected}, actual={actual}"
                )
            if missing > 0 or unique != actual:
                raise RuntimeError(
                    f"Bad URLs in {run_id}: missing={missing}, unique={unique}, actual={actual}"
                )

            cur.execute("SELECT COUNT(*) FROM gold.current_panel_ranking")
            gold_count = cur.fetchone()[0]
            if gold_count == 0:
                raise RuntimeError("Gold current_panel_ranking is empty")

    print(f"Validated scrape run {run_id}: {actual} products, Gold={gold_count}")


if __name__ == "__main__":
    main()
