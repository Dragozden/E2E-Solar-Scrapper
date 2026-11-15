# Etap 11.2 — modele techniczne Silver / Gold (lokalnie)

## Co zostaje bez zmian

- Historyczne oferty `bronze.panel_scrape_raw`, trzy dotychczasowe modele Gold i działający Streamlit pozostają nietknięte.
- `bronze.panel_spec_snapshots` jest niezależną historią specyfikacji; zapis jest ręczny (`panel_detail_pilot.py --write`). Ten etap **nie** uruchamia automatycznego crawl produktu dla każdego rekordu.
- Dane techniczne są jeszcze **ofertowe** (opis strony sklepu), nie potwierdzone niezależnie przez producenta.
- Karty PDF są jedynie zapisanymi linkami; parametry nie pochodzą jeszcze z treści dokumentów PDF.

## Nowe relacje

| Relacja | Grain | Znaczenie |
|---|---|---|
| `silver.stg_panel_specs` | `spec_id` | Wszystkie historyczne wersje specyfikacji; typowanie JSONB, status jakości |
| `gold.panel_technical_comparison` | `source_url` z `gold.current_panel_ranking` | Oferta z ostatniego katalogu z najnowszą zaobserwowaną specyfikacją (lub bez niej) |

Konwersja liczb z JSONB jest celowo ograniczona do rozsądnej liczby cyfr; niepoprawny format i bardzo duże wartości nie powodują błędu `dbt build`, lecz zwracają `NULL`.

Silver: `PASS` wymaga `Pmax`, `Voc`, `Vmp`, `Isc`, `Imp` jako liczb dodatnich, zgodności `Voc > Vmp`, `Isc >= Imp`, zgodności Pmax z Vmp×Imp w granicy 12% oraz braku błędów parsera. Brak danych = `INCOMPLETE`; konflikt wartości lub błąd parsera przy kompletnych polach = `REVIEW`.

Gold: `NOT_ENRICHED` — nie znaleziono specyfikacji; `INCOMPLETE`/`REVIEW` — najnowsza wersja wymaga sprawdzenia; `POWER_MISMATCH` — ważna specyfikacja, ale `Pmax` różni się od mocy ofertowej o ponad 1 W; `PASS` — specyfikacja kompletna i zgodna z mocą oferty. Tylko `PASS` ma `is_technical_comparable=TRUE`.

Specyfikacje są łączone po dokładnym URL produktu, nie po podobieństwie nazwy. Późniejsze przebudowanie widoku nie zmienia historii cen. Data ostatniej specyfikacji może być starsza od daty oferty, dlatego dostępne są oba znaczniki czasu.

## Weryfikacja przed użyciem

1. Najpierw uruchom istniejący pilot **z dwoma** poprawnymi produktami i `--write`. Sprawdź liczbę nowych rekordów w `bronze.panel_spec_snapshots`. Nie uruchamiaj `--limit 3 --write` gdy trzeci produkt pozostaje `INCOMPLETE`.
2. Wgraj pliki paczki do repo. `source.yml` rozszerza istniejącą deklarację tabel Bronze, a nie usuwa starych.
3. Uruchom `pytest` i `dbt build` (najwygodniej wewnątrz kontenera Airflow).
4. Uruchom `scripts/check_panel_spec_models.py --min-complete 2`, a następnie `scripts/grant_panel_comparison_reader.py` i `--check` dla konta Streamlit. Przy zmianie oferty lub rankingu oba zapisane produkty mogą wypaść z aktualnego katalogu; wtedy test progowy wyświetli liczbę dostępnych aktualnie kompletnych porównań.
5. Zweryfikuj SQL w pgAdmin i działanie wcześniejszego dashboardu/DoD. Nadanie SELECT na nowym widoku jest wymagane, jeśli dashboard ma go później wyświetlać.

## Sprawdzenie SQL

```sql
SELECT technical_status, COUNT(*) AS n
FROM gold.panel_technical_comparison
GROUP BY technical_status ORDER BY technical_status;

SELECT title, price_pln, catalog_power_w, technical_power_w,
       voc_v, vmp_v, isc_a, imp_a, efficiency_pct,
       spec_fetched_at, technical_status
FROM gold.panel_technical_comparison
WHERE has_specification IS TRUE
ORDER BY overall_rank;

SELECT COUNT(*) FROM gold.current_panel_ranking;
SELECT COUNT(*) FROM gold.panel_technical_comparison;
```

Liczby dwóch ostatnich zapytań **muszą** być jednakowe. Dane niekompletne przechowujemy w Bronze/Silver, ale nie traktujemy ich jako kompletnych danych technicznych w Gold.

## CI

GitHub Actions tworzy osobną bazę PostgreSQL 17, wywołuje istniejący `scripts/ci_dbt_integration.py seed` i nowy `scripts/ci_panel_specs.py seed`, następnie `dbt build` i obie asercje. Dane CI są syntetyczne i odizolowane od komputera użytkownika. Nowy fixture obejmuje dwie wersje jednego URL, jedną niekompletną specyfikację, produkt z historią niewystępujący w bieżącym rankingu i produkt bez szczegółów.

## Przyszłe prace

- Etap 11.3: opcjonalna zakładka Streamlit z pokryciem, filtrami elektrycznymi, porównaniami i oznaczaniem jakości.
- Etap 11.4: pozyskiwanie parametrów konkretnego modelu z kart katalogowych PDF; wyraźnie oddzielić źródło producenta od źródła sklepu.
- Dopiero potem kontrolowane powiększanie skali zbierania danych i kolejne kategorie produktów.
