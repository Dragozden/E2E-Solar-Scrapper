# Data Quality — E2E Solar Price Pipeline

> **Stan potwierdzony: 28.10.2026.** `pytest`: **8 passed**; log `dbt build`: **15 data tests** i **5 modeli**. Pełny DAG przeszedł po poprawce paginacji. Nie oznacza to pełnego pokrycia wszystkich scenariuszy awarii.

## Założenie

Kontrole jakości zabezpieczają przejście **Bronze → Silver → Gold**. Status scrapera `SUCCESS` oznacza, że proces pobrania/zapisu zakończył się, lecz **nie dowodzi**, że zapisany zbiór jest kompletny i unikalny. Dlatego dbt waliduje dane niezależnie.

## Kontrole działające obecnie

| Etap | Kontrola | Reakcja |
|---|---|---|
| Extractor | Jednoznaczna sekcja „Lista produktów” | Wyjątek przy niezgodności DOM |
| Extractor | Przejście po linkach „Następne produkty”; brak zapętleń | Zakończenie na końcu katalogu / wyjątek przy pętli |
| Extractor | Puste strony, błędne HTTP, brak URL produktu | Wyjątek, zamiast cichego pominięcia błędu |
| Extractor | Duplikaty `source_url` w jednym runie | Pomijane z logowaniem liczby duplikatów |
| Extractor | `MAX_PAGES=50` | Bezpiecznik przed niekończącą się paginacją |
| Python/pytest | Zachowanie parsera (np. moc, URL, selekcja paneli) | Błąd testu przy regresji objętej testami |
| dbt | `assert_latest_run_integrity` dla ostatniego `SUCCESS` | `FAIL`, gdy błędny licznik, URL albo duplikaty |
| dbt Silver | `not_null` i `unique` na kluczowych kolumnach | Fail testu dbt |
| dbt / SQL | Poprawność dodatniej ceny i mocy (`assert_valid_price_and_power`) | Fail testu dbt |
| dbt Gold | Testy `not_null` dla historii i metryk dziennych oraz `unique` dnia | Fail testu dbt |

**Ostrożność:** wynik `8 passed` nie potwierdza sam w sobie, że istnieje test każdej gałęzi nowej paginacji — wymaga to przeglądu plików testowych.

## Jak działa `assert_latest_run_integrity`

Test jest w `dbt/solar_dbt/tests/assert_latest_run_integrity.sql`. Pobiera **ostatni run `SUCCESS`** z `bronze.scrape_runs` według `finished_at DESC`, dołącza jego wiersze z `bronze.panel_scrape_raw` i zwraca wiersz wtedy, gdy zachodzi przynajmniej jeden warunek:

| Warunek | Znaczenie |
|---|---|
| `actual_count = 0` | Brak zapisanych produktów |
| `expected_count IS NULL` | Brak zadeklarowanej liczby produktów |
| `actual_count <> expected_count` | Niezgodność deklaracji z rzeczywistym zapisem |
| `missing_urls > 0` | Co najmniej jeden `source_url` jest NULL lub pusty |
| `non_unique_urls > 0` | Liczba wierszy przekracza liczbę różnych, niepustych URL |

W testach dbt **zero wierszy = PASS**; jeden zwrócony wiersz oznacza naruszenie co najmniej jednego warunku. Komunikat `FAIL 1` **nie oznacza jednego uszkodzonego produktu**. Porażka testu sprawia, że zależne modele Silver/Gold mogą zostać oznaczone `SKIP`, a `dbt build` zwraca niezerowy kod zakończenia.

## Incydent 28.10.2026 — wykryta regresja paginacji

| Parametr | Wynik uszkodzonego runu |
|---|---:|
| `expected_count` | 126 |
| `actual_count` | 126 |
| `missing_urls` | 0 |
| Liczba unikalnych URL | 78 |
| `non_unique_urls` | **48** |

Powód: historyczna pętla `TOTAL_PAGES=12` odwiedzała również strony poza aktualnym końcem katalogu. Sześć produktów pojawiło się **po dziewięć razy każde** (8 nadmiarowych wystąpień × 6 = 48). To blokowało `assert_latest_run_integrity`, mimo że liczba zapisów zgadzała się z `products_count`.

**Naprawa:** dynamiczne przejście po istniejących linkach paginacji, deduplikacja według URL i jawne błędy na nieprawidłowej nawigacji. Potwierdzony lokalny wynik po naprawie: 4 strony, **78 produktów**, **0 duplikatów**. Następnie wszystkie etapy Airflow/dbt wykonały się pomyślnie.

## Diagnostyka w pgAdmin

```sql
WITH latest_run AS (
    SELECT scrape_run_id, started_at, finished_at, products_count
    FROM bronze.scrape_runs
    WHERE status = 'SUCCESS'
    ORDER BY finished_at DESC NULLS LAST
    LIMIT 1
)
SELECT
    r.scrape_run_id,
    r.started_at,
    r.finished_at,
    r.products_count AS expected_count,
    COUNT(p.scrape_id) AS actual_count,
    COUNT(p.scrape_id) FILTER (
        WHERE p.source_url IS NULL OR TRIM(p.source_url) = ''
    ) AS missing_urls,
    COUNT(p.scrape_id)
      - COUNT(DISTINCT NULLIF(TRIM(p.source_url), '')) AS non_unique_urls
FROM latest_run r
LEFT JOIN bronze.panel_scrape_raw p ON p.scrape_run_id = r.scrape_run_id
GROUP BY r.scrape_run_id, r.started_at, r.finished_at, r.products_count;
```

Aby zobaczyć **konkretne powtarzane URL** ostatniego udanego runu:

```sql
WITH latest_run AS (
    SELECT scrape_run_id
    FROM bronze.scrape_runs
    WHERE status = 'SUCCESS'
    ORDER BY finished_at DESC NULLS LAST
    LIMIT 1
)
SELECT TRIM(p.source_url) AS source_url, COUNT(*) AS occurrences, MIN(p.title) AS example_title
FROM bronze.panel_scrape_raw p
JOIN latest_run r ON r.scrape_run_id = p.scrape_run_id
WHERE p.source_url IS NOT NULL AND TRIM(p.source_url) <> ''
GROUP BY TRIM(p.source_url)
HAVING COUNT(*) > 1
ORDER BY occurrences DESC, source_url;
```

Jeśli liczba unikalnych ofert nagle spadnie, porównaj kilka ostatnich runów zamiast uznawać od razu, że produkty zostały usunięte ze sklepu. Dane z 27.10.2026 pokazywały 288 unikalnych produktów, a 28.10.2026 — 78. Nie ustalaj `288` ani `78` jako sztywnego oczekiwanego limitu.

## Backlog testów i kontroli (jeszcze niewdrożony / niepotwierdzony)

| Priorytet | Kontrola | Proponowany scenariusz / działanie |
|---|---|---|
| Wysoki | Regresyjne testy paginacji | Mock: 4 strony i brak „Następne produkty” na ostatniej; pętla, duplikaty, błędny `href`, pusta lista |
| Wysoki | Spadek liczby ofert | Ostrzegaj przy dużej zmianie względem mediany kilku poprzednich poprawnych runów; nie zakładaj stałej liczby |
| Wysoki | Rollback podczas batch insertu | Wymuś błąd **po rozpoczęciu zapisu**; sprawdź brak wierszy nowego UUID i status `FAILED` |
| Średni | Niespójność `SUCCESS` / dbt FAIL | Zapisz osobny status walidacji (np. `QUALITY_FAILED`) bez nadpisywania historii wykonania scrapera |
| Średni | Alerty i trwałe raporty | Raport per `scrape_run_id`: liczności, brakujące URL, duplikaty, czas wykonania, rezultat dbt |
| Średni | Identyfikacja produktu | Weryfikacja stabilności `source_url`, ewentualnie identyfikator sklepu |
| Średni | Integralność referencyjna | Po migracji historycznych danych rozważyć FK `scrape_run_id` |
| Niższy | Ujednolicenie czasu | Migracja do UTC i `TIMESTAMPTZ` po określeniu znaczenia danych historycznych |
| Niższy | Retry sieciowe | Kontrolowane ponawianie błędów chwilowych HTTP/Playwright, bez powielania runów |

## Wskazówki operacyjne

- Log zadania Airflow: interfejs Airflow lub `/opt/airflow/logs/`.
- Log dbt: `/opt/airflow/solar/dbt/logs/dbt.log`.
- Skompilowany SQL i `run_results.json`: `/opt/airflow/solar/dbt/target/` — artefakty mogą zostać nadpisane przez kolejny przebieg.
- `dbt build` obejmuje modele i testy; przy niepowodzeniu testu upstream modele zależne nie muszą w ogóle wystartować.
- Nie usuwaj podejrzanych wierszy historycznych na ślepo. Najpierw diagnozuj je po `scrape_run_id` i odróżniaj błąd techniczny od faktycznej zmiany oferty.

Powiązane pliki: [Architecture](architecture.md), [Data dictionary](data_dictionary.md), [Development](development.md).
