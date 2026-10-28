# Data Dictionary — E2E Solar Price Pipeline

> **Stan: 28.10.2026.** Słownik obejmuje potwierdzone warstwy Bronze, Silver i Gold. Typy kolumn Bronze pochodzą z dotychczasowego kontraktu projektu; w przypadku modeli dbt zestaw kolumn należy sprawdzać również w SQL i YAML danego modelu.

## Konwencje

- `scrape_run_id`: UUID wspólny dla jednego wykonania scrapera.
- `scrape_id`: techniczny klucz pojedynczej obserwacji w Bronze.
- `source_url`: absolutny, znormalizowany URL produktu — identyfikator produktu na etapie MVP.
- `scraped_at` / `observed_at`: czas zarejestrowania obserwacji; **nie** czas rzeczywistej zmiany ceny w sklepie.
- `SUCCESS`: wykonanie uznane przez scraper/loader za udane; **nie zastępuje** niezależnych testów jakości w dbt.

## `bronze.scrape_runs` — metadane wykonania

**Grain:** jeden wiersz na uruchomienie scrapera.

| Kolumna | Typ | Definicja |
|---|---|---|
| `scrape_run_id` | `UUID PRIMARY KEY` | UUID generowany w `scraper.main` i przekazywany do pozostałych modułów |
| `started_at` | `TIMESTAMP` | Czas rozpoczęcia runu |
| `finished_at` | `TIMESTAMP NULL` | Czas zakończenia; może być pusty dla runu niezakończonego |
| `status` | `TEXT` | Stany `RUNNING`, `SUCCESS`, `FAILED` |
| `products_count` | `INTEGER NULL` | Zadeklarowana liczba produktów po zakończeniu scrapingu; porównywana z rzeczywistą liczbą wierszy Bronze |

**Uwaga:** `products_count = COUNT(*)` nie wystarcza do uznania runu za poprawny. Przykład z 28.10: **126 zapisanych / 126 zadeklarowanych, ale tylko 78 unikalnych URL**.

## `bronze.panel_scrape_raw` — obserwacje ofert

**Grain:** jeden zapis produktu w określonym runie. Nowe runy zachowują historię, a nie aktualizują wcześniejszych rekordów.

| Kolumna | Typ | Definicja |
|---|---|---|
| `scrape_id` | `BIGSERIAL PRIMARY KEY` | Techniczny identyfikator obserwacji |
| `scrape_run_id` | `UUID NULL` (historycznie) | Identyfikator runu; w nowych danych wymagany logicznie |
| `title` | `TEXT` | Nazwa produktu z kafelka |
| `price_text` | `TEXT` | Cena odczytana z atrybutu `price`, bez utraty oryginalnej postaci tekstowej |
| `power_text` | `TEXT` | Wartość mocy, np. `575 W`, uzyskana regexem z nazwy |
| `efficiency_text` | `TEXT` | Pole rezerwowe; brak obecnie zweryfikowanej ekstrakcji sprawności |
| `bifaciality_text` | `TEXT` | Pole rezerwowe; brak obecnie zweryfikowanej ekstrakcji bifaciality |
| `source_url` | `TEXT NULL` | Bezwzględny adres oferty; w poprawnym nowym runie nie może być pusty |
| `is_available` | `BOOLEAN NULL` (historycznie) | Odczyt dostępności z kafelka, wg logiki m.in. `availability-notifier-btn` |
| `scraped_at` | `TIMESTAMP` | Czas zapisanej obserwacji |

**Ograniczenie:** brak pewnego potwierdzenia, że `price_text` jest kwotą brutto/netto. `power_text` nie jest niezależnym parametrem technicznym produktu.

## `silver.stg_panels` — typowanie i normalizacja

**Grain:** `scrape_id` (pojedyncza historyczna obserwacja).

| Pole / grupa pól | Znaczenie |
|---|---|
| `scrape_id` | Klucz rekordu; testy `unique` i `not_null` |
| `scrape_run_id` | Powiązanie z runem `SUCCESS`; test `not_null` |
| `title`, `source_url`, `is_available` | Identyfikacja produktu i dostępność |
| `scraped_at` | Czas obserwacji |
| `price_pln` | Liczbowa wartość ceny, typ `NUMERIC`; przy niepoprawnym parsowaniu może być `NULL` |
| `power_w` | Moc w watach, typ `INTEGER`; przy niepoprawnym parsowaniu może być `NULL` |

Silver obejmuje obserwacje z poprawnie powiązanych runów oznaczonych `SUCCESS`; zachowuje historyczne dane o tym samym produkcie. Dodatnia cena i moc są dalej weryfikowane przez testy SQL.

## `gold.current_panel_ranking` — aktualny ranking

**Grain:** maksymalnie jeden `source_url` z najnowszego runu `SUCCESS`.

| Pole | Znaczenie |
|---|---|
| `source_url`, `title` | Identyfikacja oferty |
| `price_pln`, `power_w` | Dane wejściowe do wskaźników |
| `pln_per_watt` | Cena / moc znamionowa |
| `watt_per_pln` | Moc / cena |
| `price_category` | Przedział cenowy produktu |
| `overall_rank` | Pozycja oferty w rankingu |
| `is_available` | Dostępność wg ekstrakcji |
| Identyfikatory i czas obserwacji | Powiązanie rankingu z runem i źródłem; dokładne nazwy w SQL modelu |

Ranking bierze pod uwagę dostępność, a następnie rosnący koszt PLN/W. Nie jest rankingiem sprawności ani ilości wyprodukowanej energii.

## `gold.product_price_history` — historia cen produktu

**Kontrakt grain:** jeden wiersz na (`scrape_run_id`, `source_url`). Model został wdrożony i uruchomiony w pełnym przebiegu dbt.

| Pole | Znaczenie |
|---|---|
| `source_url` | Identyfikator porównywanego produktu |
| `scrape_run_id` | Run, z którego pochodzi obserwacja |
| `observed_at` | Czas obserwacji wykorzystywany do sortowania historii |
| `price_pln` | Zaobserwowana cena |
| `previous_price_pln` | Cena z poprzedniej dostępnej obserwacji tego produktu |
| `price_change_pln` | Różnica między obecną i poprzednią ceną |
| `power_w` | Moc znamionowa; pole potwierdzone testem nie-NULL |

Te pola są znane z dokumentacji i logów testów; pozostałe pola, ewentualne procentowe zmiany i dokładną definicję poprzedniej obserwacji należy odczytywać z aktualnego SQL `models/marts/product_price_history.sql`.

## `gold.daily_market_prices` — dzienne statystyki rynku

**Grain:** jeden wiersz na `observation_date`. Model jest wdrożony i objęty testami not-null/unique.

| Pole | Znaczenie |
|---|---|
| `observation_date` | Dzień, za który liczony jest agregat; testy `not_null`, `unique` |
| `available_panels` | Liczba paneli dostępnych w agregacie; test `not_null` |
| Pozostałe miary agregowane | Miary cenowe i PLN/W — szczegółowe nazwy i formuły w `models/marts/daily_market_prices.sql` |

Według przyjętej logiki biznesowej wielokrotnie obserwowany produkt nie powinien być liczony kilka razy w jednej dobie; do przekroju dziennego wykorzystuje się jego ostatnią obserwację z tego dnia.

## Dodatkowy obiekt techniczny

W logach dbt występuje również **`silver.assert_history_unique_per_run`** jako model (relacja) zależny od wcześniejszych węzłów. Należy go traktować jako element techniczny wspierający kontrolę spójności, a nie jako dodatkowy produkt biznesowy Gold. Szczegóły semantyki i kolumn opisuje źródłowy SQL tego modelu.

## Źródła prawdy i dalsze decyzje

- Definicje SQL: `dbt/solar_dbt/models/staging/` oraz `dbt/solar_dbt/models/marts/`.
- Testy i opisy kolumn: odpowiadające pliki `.yml` oraz `dbt/solar_dbt/tests/`.
- Warto uzupełnić YAML o precyzyjne definicje wszystkich miar Gold oraz jednostki.
- Docelowa migracja `TIMESTAMP` → `TIMESTAMPTZ` wymaga ustalenia strefy wcześniejszych zapisów.
- Możliwe późniejsze wzmocnienie integralności: klucz obcy `panel_scrape_raw.scrape_run_id` → `scrape_runs.scrape_run_id` po uporządkowaniu starszych danych.
