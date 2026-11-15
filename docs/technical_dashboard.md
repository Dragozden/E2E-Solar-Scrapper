# Etap 11.3 — Dashboard parametrów technicznych PV

## Cel i zakres

Do istniejącego Streamlit v3 dodajemy **ósmą zakładkę „Parametry techniczne”**. Ceny pochodzą z bieżącego `gold.current_panel_ranking`, dane techniczne z najnowszego zapisanego snapshotu danego URL. Łączy je przygotowany w etapie 11.2 model `gold.panel_technical_comparison`.

Cały pipeline cen, Airflow, Bronze, Silver i poprzednie zakładki działają bez zmian. Nowa zakładka jest opcjonalna: jeśli widok Gold nie istnieje lub brakuje `SELECT`, pokazuje ostrzeżenie **tylko w tej zakładce**, a nie wyłącza całego dashboardu.

## Zasady jakości

- Status `PASS` i `is_technical_comparable=true` oznaczają, że specyfikacja ma wymagane parametry oraz potwierdzoną zgodność mocy z bieżącym katalogiem. **Tylko takie wiersze** są domyślnie pokazywane i mogą trafić do porównania technicznego.
- `NOT_ENRICHED`: katalogowa oferta nie ma jeszcze zapisanej specyfikacji; cały katalog jest nadal dostępny w trybie „Wszystkie oferty”.
- `INCOMPLETE`: istnieje snapshot, ale nie ma kompletu danych wymaganych do porównania.
- `REVIEW` i `POWER_MISMATCH`: dane wymagają ręcznej kontroli. Nie służą do automatycznych porównań.
- `coverage_pct = 100 * liczba porównywalnych / liczba ofert z najnowszego katalogu`, **nie** procent liczby pobranych podstron ani liczba technicznych rekordów historycznych.
- Pola liczbowe pozbawione dokładnych wartości są `NULL`; nie stosujemy zer, średnich zakresów ani interpolacji.
- `Voc`, `Vmp`, `Isc`, `Imp` są parametrami katalogowymi w STC, nie wystarczają do projektowania stringów bez analizy temperatury, MPPT, bezpieczeństwa elektrycznego i danych falownika.
- Linki do PDF są prezentowane tylko jeśli wskazują na HTTPS sklepsoltech.pl i kończą się `.pdf`. Skrypt nie pobiera ani nie przetwarza PDF-ów.

## Implementacja

- `dashboard/technical_db.py`: jedno zapytanie SELECT do `gold.panel_technical_comparison`, z typowaniem liczbowym i zachowaniem `default_transaction_read_only=on`.
- `dashboard/technical.py`: czyste funkcje `technical_coverage`, `filter_technical`, `technical_comparison`, `safe_datasheet_url` — bez Streamlit i PostgreSQL.
- `dashboard/technical_ui.py`: KPI, pasek pokrycia, filtr jakości/dostępności/wyszukiwania, opcjonalne 5 zakresów liczbowych, tabela, eksport CSV i porównanie 2–5 wyłącznie zweryfikowanych paneli.
- `scripts/apply_technical_dashboard.py`: jednorazowa, idempotentna integracja z `dashboard/app.py`. Nie kopiuje całego pliku źródłowego i nie nadpisuje indywidualnych modyfikacji UI. Jeśli nie odnajdzie dokładnych punktów zaczepienia, odmówi zapisu.
- `scripts/check_panel_spec_models.py`: poprawiona ścieżka importowania pakietu `scraper` przy bezpośrednim uruchomieniu skryptu.
- `stg_panel_specs.yml`, `panel_technical_comparison.yml`: składnia `accepted_values.arguments.values` zgodna z aktualnym dbt; eliminuje dwa ostrzeżenia `MissingArgumentsPropertyInGenericTestDeprecation`.

## Instrukcja uruchomienia

Przejdź do katalogu repozytorium:

```powershell
uv run --frozen python scripts/apply_technical_dashboard.py --apply
uv run --frozen python scripts/apply_technical_dashboard.py --check
uv run --frozen python -m pytest -q
uv run --frozen python scripts/check_panel_spec_models.py --min-complete 2
```

W osobnym oknie sprawdź, czy Airflow nie wykonuje właśnie `build_dbt_models`, następnie uruchom test nowych definicji dbt (pliki są montowane do kontenera Airflow):

```powershell
cd docker
docker compose exec airflow /opt/airflow/solar-venv/bin/dbt build --project-dir /opt/airflow/solar/dbt --profiles-dir /opt/airflow/solar/dbt
cd ..
uv run --frozen python scripts/grant_panel_comparison_reader.py
uv run --frozen python scripts/grant_panel_comparison_reader.py --check
```

Przebuduj **tylko dashboard**, bez tworzenia nowej bazy:

```powershell
cd docker
docker compose up -d --build --no-deps dashboard
docker compose ps
docker compose logs --tail 40 dashboard
cd ..
```

Otwórz http://localhost:8501 i wybierz zakładkę **Parametry techniczne**.

## Spodziewane dane pilota

Na bazie testu 15.11.2026, przy nadal aktualnym katalogu 72 ofert i dwóch zapisanych specyfikacjach `v1.2`, początkowe pokrycie powinno wynosić około **2/72 = 2,8%**, oba modele ze statusem `PASS`. Jeśli katalog zmieni się w międzyczasie, liczby mogą się różnić.

## Weryfikacja

1. Dotychczasowe 7 zakładek działają jak wcześniej.
2. Ósma zakładka wyświetla 72 oferty w trybie „Wszystkie oferty”, nie 2; domyślnie pokazuje tylko poprawne specyfikacje.
3. LONGi 615 W i TW Solar 575 W mają techniczne napięcia/prądy z Gold; TW Solar 505 W **nie może** zostać porównany automatycznie.
4. `Do uzupełnienia` pokazuje produkty bez poprawnych specyfikacji.
5. Eksport CSV dotyczy tylko widocznego, przefiltrowanego zestawu; CSV zawiera NULL dla brakujących parametrów.
6. Przebudowa kontenera dashboardu nie zmienia wolumenu PostgreSQL, runów Airflow ani kopii na F:\\.

## Znane ograniczenia i dalszy etap

- Póki co specyfikacje pobieramy ręcznie małymi partiami. Nie ma cyklicznego pobierania PDF-ów ani danych technicznych całego katalogu.
- Tożsamość produktu bazuje na URL oferty; długofalowo warto uzyskać stabilny kod producenta (SKU/model) i historię wersji.
- Gdy liczba poprawnych specyfikacji wzrośnie, rozbudujemy wykresy oraz dodamy techniczne narzędzia doboru zestawu paneli.
