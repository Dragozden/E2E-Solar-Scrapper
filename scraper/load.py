import psycopg
from datetime import datetime
from uuid import UUID

from scraper.config import config
from scraper.models import RawPanel


def get_connection():
    return psycopg.connect(
        host=config.host,
        port=config.port,
        dbname=config.database,
        user=config.user,
        password=config.password,
    )

def create_scrape_run(scrape_run_id: UUID):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO bronze.scrape_runs (
                    scrape_run_id,
                    started_at,
                    status
                )
                VALUES (%s, %s, %s)
                """,
                (
                    scrape_run_id,
                    datetime.now(),
                    "RUNNING",
                ),
            )

def finish_scrape_run(
    scrape_run_id: UUID,
    products_count: int,
):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE bronze.scrape_runs
                SET
                    finished_at = %s,
                    status = %s,
                    products_count = %s
                WHERE scrape_run_id = %s
                """,
                (
                    datetime.now(),
                    "SUCCESS",
                    products_count,
                    scrape_run_id,
                ),
            )

def insert_raw_panel(panel: RawPanel):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO bronze.panel_scrape_raw (
                    scrape_run_id,
                    title,
                    price_text,
                    power_text,
                    efficiency_text,
                    bifaciality_text,
                    source_url,
                    is_available
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    panel.scrape_run_id,
                    panel.title,
                    panel.price_text,
                    panel.power_text,
                    panel.efficiency_text,
                    panel.bifaciality_text,
                    panel.source_url,
                    panel.is_available,
                ),
            )