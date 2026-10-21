# Development & local operations

## Wymagania
Windows + PowerShell, Python 3.14 przez `uv` (scraper), Git, Docker Desktop / Compose, przeglądarka Playwright. Osobny dbt CLI uruchamiany przez `uvx --python 3.13`.

## Start od zera (PowerShell, z korzenia repo)
```powershell
uv sync
uv run playwright install chromium
Copy-Item .env.example .env  # gdy .env jeszcze nie istnieje, uzupełnij lokalne dane
# Uruchomienie PostgreSQL z docker/docker-compose.yml:
docker compose -f docker/docker-compose.yml up -d
uv run pytest -v
uv run python -m scraper.main
```

## dbt — korzysta z .env w korzeniu
```powershell
uvx --env-file .env --python 3.13 --from "dbt-postgres>=1.10,<2" dbt debug --project-dir dbt/solar_dbt --profiles-dir dbt/solar_dbt
uvx --env-file .env --python 3.13 --from "dbt-postgres>=1.10,<2" dbt build --project-dir dbt/solar_dbt --profiles-dir dbt/solar_dbt
uvx --env-file .env --python 3.13 --from "dbt-postgres>=1.10,<2" dbt docs generate --project-dir dbt/solar_dbt --profiles-dir dbt/solar_dbt
uvx --env-file .env --python 3.13 --from "dbt-postgres>=1.10,<2" dbt docs serve --project-dir dbt/solar_dbt --profiles-dir dbt/solar_dbt
```
UWAGA: po ustabilizowaniu wybierz i przypnij dokładną wersję `dbt-postgres` dla odtwarzalności. `uvx` nie używa zależności `.venv` scrapera.

## Debugowanie
- Sprawdź wolumen bazy i działanie kontenera przez `docker compose -f docker/docker-compose.yml ps`.
- pgAdmin łączy się do hosta `postgres` wewnątrz Compose; Python uruchamiany na Windows do `localhost` (z mapowanym portem).
- `dbt_project.yml` i `profiles.yml` muszą wskazywać te same nazwy modelu, profilu i schematów co projekt.
- Nazwy `silver` i `gold` wymagają sprawdzenia konfiguracji `generate_schema_name`; default dbt może wygenerować `silver_gold`.
- Pliki `docker/postgres/init/*.sql` inicjalizują bazę **tylko na pustym wolumenie**; nie są mechanizmem migracji istniejącej bazy.
- Nie stosować `docker compose down -v` podczas zwykłego debugowania — usuwa dane z wolumenu.

## Git / sekrety
- Commituj `pyproject.toml`, `uv.lock`, SQL, YAML, testy, dokumentację i przykładową konfigurację.
- Nie commituj `.env`, `.venv`, `dbt/**/target`, `dbt/**/logs`, `dbt/**/dbt_packages` ani surowych dumpów zawierających sekrety.
- `README` = start użytkownika; `docs/` = kontrakty i decyzje; dbt YAML descriptions = dokumentacja modeli/kolumn i lineage.
