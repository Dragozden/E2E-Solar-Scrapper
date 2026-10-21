# Data Dictionary

## bronze.scrape_runs — jedno wykonanie
| Kolumna | Typ | Definicja |
|---|---|---|
| `scrape_run_id` | UUID PK | Identyfikator jednego uruchomienia, generowany w `main.py`. |
| `started_at` | TIMESTAMP | Rozpoczęcie wykonania. |
| `finished_at` | TIMESTAMP NULL | Zakończenie wykonania; brak np. przy niedokończonym runie. |
| `status` | TEXT | `RUNNING`, `SUCCESS`, `FAILED` w obecnym modelu. |
| `products_count` | INTEGER NULL | Liczba produktów zadeklarowana przez pipeline po powodzeniu. |

## bronze.panel_scrape_raw — jedna oferta w jednym wykonaniu
| Kolumna | Typ | Definicja |
|---|---|---|
| `scrape_id` | BIGSERIAL PK | Identyfikator obserwacji. |
| `scrape_run_id` | UUID NULL (historycznie) | Powiązanie obserwacji z wykonaniem; w nowych rekordach oczekiwane. |
| `title` | TEXT | Nazwa odczytana z atrybutu `name` kafelka. |
| `price_text` | TEXT | Cena z atrybutu `price`, zachowana jako tekst. |
| `power_text` | TEXT | Moc ustalona regexem z nazwy, sformatowana np. `575 W`. Nie jest dosłownie surowym polem strony. |
| `efficiency_text` | TEXT | Zarezerwowane na sprawność; obecnie najczęściej pusty tekst. |
| `bifaciality_text` | TEXT | Zarezerwowane na bifaciality; obecnie najczęściej pusty tekst. |
| `source_url` | TEXT NULL | Absolutny URL strony produktu; `NULL` oznacza brak odczytu. |
| `is_available` | BOOLEAN NULL (historycznie) | Dostępność wyznaczona po obecności `availability-notifier-btn`. |
| `scraped_at` | TIMESTAMP | Czas inserta/obserwacji. |

## silver.stg_panels — obserwacje poprawnych runów
- Klucz wiersza: `scrape_id`.
- `price_pln`: `NUMERIC`, wyprowadzony z `price_text`, przy niepoprawnym zapisie `NULL`.
- `power_w`: `INTEGER`, wyprowadzony z `power_text`, przy niepoprawnym zapisie `NULL`.
- `title`, `source_url`, `is_available`, `scraped_at`, `scrape_run_id`: zachowane.
- Wiersze pochodzą wyłącznie z runów `SUCCESS` w `bronze.scrape_runs`.
- Historia tego samego produktu z kolejnych runów jest zachowana.

## gold.current_panel_ranking — ostatni poprawny snapshot
- Jedna oferta na `source_url` w ostatnim runie `SUCCESS` (przy duplikatach wewnątrz runu preferowana najnowsza obserwacja; duplikat powinien jednocześnie uruchomić alarm jakości).
- `price_pln`, `power_w`, `pln_per_watt`, `watt_per_pln`, `price_category`, `overall_rank`, `is_available`, `title`, `source_url`, identyfikatory i czas.
- Ranking jest oparty o dostępność i rosnącą cenę za wat, a nie wyłącznie o najniższą cenę.

## Plany nowych modeli Gold
- `product_price_history`: jeden wiersz na (`scrape_run_id`, `source_url`), cena oraz zmiana od poprzedniego pomiaru.
- `daily_market_prices`: dzienny snapshot najnowszego pomiaru produktu w danym dniu, agregowany do metryk rynku.
