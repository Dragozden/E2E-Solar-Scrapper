# E2E Solar — 11.5b: ręczne zatwierdzanie wyników STC z PDF

## Architektura i granice zaufania

`panel_pdf_preview.py` nadal tylko odczytuje pliki PDF lokalnie. Wynik `REVIEW_REQUIRED` to kandydat, a nie automatyczna akceptacja.

Nowy `approve_panel_pdf.py` wymaga:

1. pliku PDF istniejącego lokalnie, z nagłówkiem `%PDF-` i SHA-256 identycznym z raportem,
2. JSON o statusie `REVIEW_REQUIRED`, dokładnie jednym kandydacie oraz kompletnych parametrach STC,
3. jawnej ręcznej deklaracji `--confirm-model` i osobnego przełącznika `--approve`,
4. produktu **w aktualnym** `gold.panel_technical_comparison` o dokładnie zgodnej nazwie modelu i mocy,
5. zaufanego linku PDF w `datasheet_urls` tej oferty,
6. parametrów fizycznie spójnych (Voc > Vmp, Isc >= Imp, Vmp × Imp ≈ Pmax).

Uwaga: raport JSON jest wynikiem narzędzia lokalnego. Zgodność SHA-256 chroni przed przypadkowym pomieszaniem plików, ale nie potwierdza automatycznie autentyczności producenta. Ręczna kontrola modelu, rewizji dokumentu i kolumny STC pozostaje obowiązkowa.

### Co jest zapisywane?

Nowa tabela `bronze.panel_pdf_approvals` jest **dopisywana** i ma unikalność `(source_url, pdf_sha256, power_w, pdf_page, variant_column)`. Przechowuje identyfikator oferty, model, sześć potwierdzonych wartości STC, oryginalny adres PDF przy danej ofercie, SHA-256 dokumentu, SHA-256 raportu, numer strony, kolumnę i datę zatwierdzenia. Nie zawiera binarnego PDF, a importer nie odczytuje ani nie zapisuje cen.

Istniejące `bronze.panel_spec_snapshots`, `bronze.panel_spec_attempts`, `bronze.panel_scrape_raw` pozostają nietknięte. W `silver.stg_panel_pdf_approvals` wykonywana jest dodatkowa walidacja SQL. Zaktualizowany `gold.panel_technical_comparison` wybiera **najnowsze zatwierdzenie PDF po URL** dla elektrycznych STC (`rated_power_w`, `Voc`, `Vmp`, `Isc`, `Imp`, `efficiency_pct`). Dla niezatwierdzonych produktów nadal używa HTML. Pozostałe pola HTML i oryginalne ostrzeżenia są zachowane (także w `html_spec_quality` oraz `html_parse_issue_count`).

Nowe pola `technical_source`, `pdf_approval_id`, `pdf_sha256`, `pdf_review_sha256`, `pdf_source_url`, `pdf_page`, `pdf_variant_column`, `pdf_approved_at` są **dopisywane po dotychczasowych kolumnach widoku** — ważne dla `CREATE OR REPLACE VIEW` oraz istniejącego dashboardu.

## Instalacja (Windows PowerShell)

Rozpakuj `E2E_Solar_Step11_5B_Reviewed_PDF_Import.zip` do katalogu repozytorium, zachowując podfoldery.

```powershell
cd "E:\Repos Projects\E2E Solar Scrapper"
uv run --frozen python -m pytest tests/test_panel_pdf_approval.py -q
uv run --frozen python -m pytest -q
uv run --frozen python scripts/migrate_panel_pdf_approvals.py
```

**Ważne:** migrację trzeba wykonać przed przebudową dbt. Nie używać `docker compose down -v`.

## Zatwierdzenie TW Solar 500 W

Obydwa linki produktów 500 W i 505 W zwróciły identyczny SHA-256 `3b6d1f41ea4496b51655dc4533b3807dd0a83939266c36146797abc08fe9698f`. Dane modelu **500 W** zostały ręcznie potwierdzone przez użytkownika. Nie wolno traktować tego jako ręcznego zatwierdzenia wariantu **505 W**.

Upewnij się, że `TW_500_review.json` powstał z parsera 11.5a.2 i odpowiada parametrom strony 2, kolumny indeksowanej od 0 jako `1`:

| Parametr | TW Solar 500 W |
|---|---:|
| Pmax | 500 W |
| Voc | 40.06 V |
| Vmp | 33.70 V |
| Isc | 15.89 A |
| Imp | 14.84 A |
| Efficiency | 22.5% |

```powershell
$root = "E:\Repos Projects\E2E Solar Scrapper"
cd $root
$dir = Join-Path $HOME "Downloads\SolarSpecs"
$pdf = Join-Path $dir "TW_500_original.pdf"
$report = Join-Path $dir "TW_500_review.json"
$url = "https://sklepsoltech.pl/pl/p/Panel-fotowoltaiczny-TW-Solar-500-TWMNH-54HD500-BF/3515"

# ZAWSZE najpierw podgląd (bez zapisu)
uv run --frozen python scripts/approve_panel_pdf.py `
  --pdf $pdf --review-json $report --source-url $url `
  --confirm-model "TWMNH-54HD500"

# Dopiero po potwierdzeniu statusu PREVIEW_ONLY i poprawnych pól:
uv run --frozen python scripts/approve_panel_pdf.py `
  --pdf $pdf --review-json $report --source-url $url `
  --confirm-model "TWMNH-54HD500" --approve
```

Oczekiwany wynik to `APPROVED_NEW` (pierwszy raz) albo `APPROVED_ALREADY_EXISTS` (identyczny ponowny import). Raport PDF 505 W nie będzie importowany w tym kroku.

### Uruchomienie dbt po dodaniu zatwierdzenia

```powershell
cd "E:\Repos Projects\E2E Solar Scrapper\docker"
docker compose exec airflow /opt/airflow/solar-venv/bin/dbt build --project-dir /opt/airflow/solar/dbt --profiles-dir /opt/airflow/solar/dbt
cd ..
uv run --frozen python scripts/grant_panel_comparison_reader.py --check
uv run --frozen python scripts/check_panel_spec_models.py --min-complete 5
uv run --frozen python scripts/panel_spec_batch.py status
```

Gdy `grant_panel_comparison_reader.py --check` zgłosi brak uprawnień po ponownym utworzeniu widoku, wykonaj `uv run --frozen python scripts/grant_panel_comparison_reader.py`, a następnie ponów `--check`.

Prawidłowe dane początkowe (bez innych wsadów między krokami): katalog 72, PASS 5, INCOMPLETE 3, REVIEW 1, NOT_ENRICHED 63. To wartości **oczekiwane, nie wyniki zmierzone na Twojej bazie**.

Kontrola źródła w pgAdmin:

```sql
SELECT overall_rank, title, technical_status, technical_source,
       technical_power_w, voc_v, vmp_v, isc_a, imp_a, efficiency_pct,
       html_spec_quality, html_parse_issue_count,
       pdf_page, pdf_variant_column, pdf_sha256
FROM gold.panel_technical_comparison
WHERE source_url = 'https://sklepsoltech.pl/pl/p/Panel-fotowoltaiczny-TW-Solar-500-TWMNH-54HD500-BF/3515';
```

Gold jest widokiem: po zatwierdzeniu i poprawnym `dbt build` zmiana jest widoczna bez kolejnego scrapowania. Dashboard przechowuje cache do 5 minut — użyj „Odśwież dane” albo poczekaj na wygaśnięcie cache. Nie trzeba przebudowywać obrazu dashboardu, bo zachowujemy stare kolumny.

## Uwaga o bezpieczeństwie i dalszej rozbudowie

- `--approve` zapisuje nowy, **niemodyfikowalny** rekord, a nie edytuje istniejących HTML lub zatwierdzeń. Nie ma na razie polecenia „cofnij” — w razie pomyłki nie uruchamiaj ręcznych `UPDATE`/`DELETE`; przygotujemy zdarzenie unieważnienia w osobnym kroku.
- Ten etap zakłada jeden poprawny raport dla konkretnej oferty; nie ma automatycznego pobierania PDF, masowego zatwierdzania ani Airflow.
- Jeżeli pojawi się nowsza zatwierdzona rewizja dla tego samego URL, Gold wybierze ją według daty i ID. Pole `technical_source` pokazuje, czy aktualna specyfikacja pochodzi z zatwierdzonego PDF czy HTML.
- Zmiana SQL jest chroniona testami jakości, ale **lokalny pakiet nie został zintegrowany z rzeczywistym PostgreSQL**. Koniecznie zweryfikuj dbt build i wynik Gold przed kolejnym wdrożeniem.
- Nie commituj lokalnych PDF, plików `.env`, prywatnych raportów JSON ani plików konfiguracyjnych z hasłami.

## Kontrolowany commit

```powershell
git add docker/postgres/init/008_panel_pdf_approvals.sql
git add scripts/migrate_panel_pdf_approvals.py scripts/approve_panel_pdf.py
git add scraper/panel_pdf_approval.py
git add dbt/solar_dbt/models/staging/source.yml
git add dbt/solar_dbt/models/staging/stg_panel_pdf_approvals.sql dbt/solar_dbt/models/staging/stg_panel_pdf_approvals.yml
git add dbt/solar_dbt/models/marts/panel_technical_comparison.sql
git add dbt/solar_dbt/tests/technical_pdf_approval_provenance.sql dbt/solar_dbt/tests/technical_pdf_approval_no_unapproved.sql
git add tests/test_panel_pdf_approval.py docs/panel_pdf_approved_import_11_5b.md

git diff --cached --check
git diff --cached --stat
# Zatwierdź dopiero po przeglądzie i poprawnym dbt build
git commit -m "feat(enrichment): add reviewed PDF STC provenance and Gold overlay"
git push
```
