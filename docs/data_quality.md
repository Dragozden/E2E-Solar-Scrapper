# Data Quality

## Reguły już częściowo pokryte
- Python/pytest: regex mocy; filtr `is_panel`; brak URL / href oraz normalizacja ścieżki.
- dbt staging: `scrape_id` ma być `unique`, `not_null`; `scrape_run_id`, `title`, `scraped_at` nie mogą być NULL w Silver.
- dbt SQL: dodatnia cena i moc; spójność liczby produktów w ostatnim `SUCCESS`; brak URL-i i duplikatów URL-i w tym runie.

## Kontrole docelowe (do rozwinięcia)
| Kontrola | Warunek | Postępowanie |
|---|---|---|
| Spójność runu | `COUNT(panel rows) = scrape_runs.products_count` | Fail dla nowego SUCCESS |
| Link produktu | URL nie-NULL i niepusty | Fail / kwarantanna źle sparsowanych |
| Duplikat w runie | Unikalność `(scrape_run_id, source_url)` | Fail; zbadać DOM i paginację |
| Typ produktu | tylko właściwe produkty z „Lista produktów” | Test parsera + monitoring zmian DOM |
| Cena i moc | `price_pln > 0`, `power_w > 0` | Fail w Silver; zachować błędny raw rekord w Bronze, o ile ekstrakcja go przyjmie |
| Status runu | `RUNNING`, `SUCCESS`, `FAILED` | Check constraint przy późniejszej migracji |
| Stare osierocone runy | `SUCCESS` bez dzieci / `RUNNING` z dawną datą | Oznaczyć jako historyczne/testowe; nie imputować losowych UUID |
| Liczność katalogu | porównać ze sklepem i trendem liczby ofert | Alert przy anomalii; **nie** ustawiać stałego 286 lub 288 |

## Znany przypadek
- Działający test: 288 rekordów, 288 unikalnych URL-i i nazw, 0 braków URL.
- Wcześniejsze źródło raportowało 286; nie ma dowodu, czy to zmiana katalogu czy efekt paginacji.
- Różne ceny dla tego samego panelu w różnych runach są poprawną historią.

## Brakujący ważny test
- **Rollback wewnątrz batcha:** wymusić wyjątek po rozpoczęciu transakcyjnego ładowania; sprawdzić `FAILED` i zero nowych paneli tego UUID. Test przed insertem nie dowodzi poprawności rollbacku.
- **Foreign key:** po porządkowaniu danych historycznych rozważyć `FOREIGN KEY (scrape_run_id) REFERENCES bronze.scrape_runs`.
