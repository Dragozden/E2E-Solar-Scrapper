# Development & local operations

> **Stan potwierdzony: 28.10.2026.** Działają: Playwright → PostgreSQL Bronze → dbt Silver/Gold → Apache Airflow. Lokalny zestaw testów: **8 passed**. Dashboard Streamlit nie został jeszcze wdrożony.

## Wymagania

- Windows + PowerShell, Git, Docker Desktop z obsługą Compose.
- Środowisko Pythona projektu (`.venv`, zarządzane przez `uv`); w dotychczasowej konfiguracji scraper działał z Pythonem 3.14.
- Playwright i przeglądarka Chromium (`uv run playwright install chromium`).
- dbt CLI może być uruchamiany osobno przez `uvx --python 3.13`; ten proces **nie** korzysta z paczek w `.venv` scrapera.
- Prywatny `.env` w katalogu głównym repozytorium; nie dodawać go do Git.

## Struktura uruchomienia Docker Compose

W katalogu `docker/` znajdują się:

- `docker-compose.yml` — PostgreSQL i pgAdmin;
- `docker-compose.override.yml` — Airflow, automatycznie łączony z bazowym Compose, **gdy polecenia uruchamiane są z katalogu `docker`**.

```powershell
# Z katalogu głównego repozytorium
cd docker
docker compose config --services   # oczekiwane: postgres, airflow, pgadmin
docker compose up -d --build
docker compose ps
cd ..
```

Nie używaj starego `compose.airflow.yml` — został zastąpiony plikiem override. Jeśli uruchamiasz polecenie `docker compose` z innego katalogu, upewnij się, że odwołujesz się do właściwych plików Compose. **Nie używaj `docker compose down -v` przy zwykłym restarcie:** usuwa wolumeny i może skasować bazę oraz stan Airflow.

Porty w obecnej konfiguracji lokalnej: Airflow `http://localhost:8080`, pgAdmin `http://localhost:5050`, PostgreSQL `localhost:5432`. Airflow jest zbindowany do `127.0.0.1`; konfiguracja PostgreSQL i pgAdmin w wersji developerskiej wymaga ograniczenia ekspozycji przed użyciem poza zaufaną maszyną.

## Pierwszy start (PowerShell, katalog główny repo)

```powershell
uv sync
uv run playwright install chromium

# Tylko jeśli .env jeszcze nie istnieje; następnie uzupełnij wartości
Copy-Item .env.example .env

cd docker
docker compose up -d --build
cd ..

.\.venv\Scripts\python.exe -m pytest -q
```

Ostatni potwierdzony wynik testów: `8 passed in 0.10s`. Zakres pokrycia testów wymaga osobnej oceny: taki wynik **nie oznacza**, że istnieją testy wszystkich przypadków paginacji i rollbacku.

**Częsty błąd:** `.\.venv\Scripts\python.exe` z folderu `docker/` nie zadziała, bo `.venv` jest w katalogu nadrzędnym. Wróć przez `cd ..` i uruchom `.\.venv\Scripts\python.exe -m pytest -q`.

## Uruchomienie scrapera poza Airflow

```powershell
# Z katalogu głównego repozytorium; zapisuje nowy run do PostgreSQL
uv run python -m scraper.main
```

Do testowania **samej ekstrakcji bez zapisu w bazie**:

```powershell
.\.venv\Scripts\python.exe -c "from uuid import uuid4; from scraper.extractor import scrape_panels; panels=scrape_panels(uuid4()); print(len(panels)); assert len(panels)==len({p.source_url for p in panels})"
```

Extractor śledzi link „Następne produkty”, wykrywa powtórzenia URL, puste strony i zapętlenia oraz ogranicza liczbę stron przez `MAX_PAGES=50` (bezpiecznik). Ostatni zweryfikowany wynik: **4 strony, 78 unikalnych produktów, 0 duplikatów**. Liczba ofert nie jest stałym kontraktem.

## Airflow — dzienne i ręczne uruchomienia

- Interfejs: `http://localhost:8080`.
- DAG: `solar_el_pipeline`, plik `airflow/dags/solar_pipeline.py`.
- Harmonogram: `schedule="2 0 * * *"`, czyli **codziennie o 00:02** w strefie `Europe/Warsaw` skonfigurowanej w DAG-u.
- `catchup=False`, `max_active_runs=1`.
- Ręczny przebieg powinien uruchamiać **cały DAG** (scraper i dbt). Samo ponowienie `build_dbt_models` nie wygeneruje nowego, naprawionego wsadu w Bronze.

Sprawdź, czy kontener widzi poprawiony kod scrapera:

```powershell
docker exec solar-airflow sh -lc "grep -n 'MAX_PAGES\|TOTAL_PAGES' /opt/airflow/solar/scraper/extractor.py"
```

Dzięki bind mount `../scraper:/opt/airflow/solar/scraper:rw` zmiany tego folderu są widoczne w kontenerze. Przebudowa może być potrzebna dla zmian w `airflow/Dockerfile` lub zależnościach obrazu:

```powershell
cd docker
docker compose up -d --build --no-deps airflow
cd ..
```

## dbt — uruchamianie ręczne z `.env`

```powershell
uvx --env-file .env --python 3.13 --from "dbt-postgres>=1.10,<2" dbt debug --project-dir dbt/solar_dbt --profiles-dir dbt/solar_dbt
uvx --env-file .env --python 3.13 --from "dbt-postgres>=1.10,<2" dbt build --project-dir dbt/solar_dbt --profiles-dir dbt/solar_dbt
uvx --env-file .env --python 3.13 --from "dbt-postgres>=1.10,<2" dbt docs generate --project-dir dbt/solar_dbt --profiles-dir dbt/solar_dbt
uvx --env-file .env --python 3.13 --from "dbt-postgres>=1.10,<2" dbt docs serve --project-dir dbt/solar_dbt --profiles-dir dbt/solar_dbt
```

W Airflow `dbt build` jest uruchamiany wewnątrz kontenera z katalogiem projektu i profili `/opt/airflow/solar/dbt`. W diagnostyce z 28.10.2026 dbt wykrył **5 modeli i 15 testów danych**. Warto przypiąć dokładną przetestowaną wersję `dbt-postgres`, zamiast przedziału wersji, aby zwiększyć odtwarzalność.

## Diagnostyka — co sprawdzić przy błędzie

### Logi

| Źródło | Lokalizacja w kontenerze `solar-airflow` |
|---|---|
| Airflow task | `/opt/airflow/logs/dag_id=solar_el_pipeline/run_id=<RUN_ID>/task_id=<TASK_ID>/attempt=<N>.log` |
| dbt debug log | `/opt/airflow/solar/dbt/logs/dbt.log` |
| Wyniki dbt | `/opt/airflow/solar/dbt/target/run_results.json` |
| Skompilowany SQL | `/opt/airflow/solar/dbt/target/compiled/` |

```powershell
docker exec solar-airflow sh -lc "tail -n 120 /opt/airflow/solar/dbt/logs/dbt.log"
docker cp solar-airflow:/opt/airflow/solar/dbt/logs/dbt.log .\dbt-debug.log
```

`run_results.json` i inne artefakty w `target/` mogą zostać zastąpione przez następny `dbt build` — nie traktuj ich jako trwałego archiwum historii.

### Kontrola najnowszego runu w PostgreSQL

```sql
WITH last_run AS (
    SELECT scrape_run_id, products_count
    FROM bronze.scrape_runs
    WHERE status = 'SUCCESS'
    ORDER BY finished_at DESC NULLS LAST
    LIMIT 1
)
SELECT
    r.scrape_run_id,
    r.products_count AS expected_count,
    COUNT(p.scrape_id) AS actual_count,
    COUNT(p.scrape_id) FILTER (
        WHERE p.source_url IS NULL OR TRIM(p.source_url) = ''
    ) AS missing_urls,
    COUNT(p.scrape_id)
      - COUNT(DISTINCT NULLIF(TRIM(p.source_url), '')) AS non_unique_urls
FROM last_run r
LEFT JOIN bronze.panel_scrape_raw p ON p.scrape_run_id = r.scrape_run_id
GROUP BY r.scrape_run_id, r.products_count;
```

`assert_latest_run_integrity` zwraca błąd, gdy ostatni run `SUCCESS` nie ma danych, `products_count` jest NULL, liczba zapisanych rekordów się nie zgadza, brakuje URL albo występują duplikaty. Wtedy dbt może oznaczyć zależne modele `SKIP`; nie jest to błąd samego SQL modelu Silver.

### Inne uwagi

- Python uruchamiany na Windows łączy się z PostgreSQL przez `localhost`; usługi wewnątrz Compose używają nazwy `postgres`.
- `dbt_project.yml`, `profiles.yml` i makro `generate_schema_name` muszą wskazywać zamierzone schematy `silver`/`gold`.
- `docker/postgres/init/*.sql` działa tylko podczas inicjalizacji **pustego** wolumenu bazy, nie migracji istniejącej instalacji.
- Ostrzeżenia Git `LF will be replaced by CRLF` są zazwyczaj informacją o normalizacji zakończeń linii, nie błędem testów.

## Git, artefakty i sekrety

Commituj kod, modele SQL, YAML, testy, `pyproject.toml`, `uv.lock`, pliki Compose, `.env.example` oraz `docs/`. Ignoruj `.env`, `.venv`, pliki `dbt/solar_dbt/target/` i `dbt/solar_dbt/logs/`, logi Airflow oraz lokalne zrzuty bazy. Jeżeli takie pliki były wcześniej śledzone, samo dodanie do `.gitignore` ich nie usuwa z indeksu Git; sprawdź `git ls-files` przed `git rm --cached`.

Obecne przykładowe hasła w Compose i publicznie zbindowane porty PostgreSQL/pgAdmin są akceptowalne wyłącznie w odizolowanym środowisku deweloperskim. Przed szerszym wdrożeniem wymień hasła, ogranicz ekspozycję portów i skonfiguruj bezpieczne zarządzanie sekretami. Zmiana hasła zmienną `POSTGRES_PASSWORD` nie aktualizuje automatycznie hasła w istniejącym wolumenie PostgreSQL.
