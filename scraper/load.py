import psycopg
from config import config

def get_connection():
    return psycopg.connect(
        host=config.host,
        port=config.port,
        dbname=config.database,
        user=config.user,
        password=config.password,
    )

def insert_raw_panel(panel: dict):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO bronze.panel_scrape_raw (
                    title,
                    price_text,
                    power_text,
                    efficiency_text,
                    bifaciality_text,
                    source_url
                )
                VALUES (%s,%s,%s,%s,%s,%s)
                """,
                (
                    panel["title"],
                    panel["price_text"],
                    panel["power_text"],
                    panel["efficiency_text"],
                    panel["bifaciality_text"],
                    panel["source_url"],
                ),
            )