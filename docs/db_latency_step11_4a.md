# E2E Solar — etap 11.4a: diagnostyka 3-minutowych poleceń

## Objaw i hipoteza

`panel_spec_batch.py status` i `plan --limit 5` operują na małej bazie lokalnej. Ani jedno nie odwiedza sklepu. Oba wywołują `scraper.load.get_connection()`, a pierwotna funkcja nie definiowała limitu połączenia. We wcześniejszym logu przerwano zadanie `--write` przy `psycopg.connect()`, co jest przesłanką problemu z połączeniem, lecz nie dowodem przyczyny całego opóźnienia.

## Wprowadzone zmiany

- `scraper/load.py`: `connect_timeout` domyślnie 10 sekund (ustawiany przez `SOLAR_DB_CONNECT_TIMEOUT`, akceptowane wartości 3–60). Zachowuje dotychczasowy adres hosta, użytkownika, hasło, schemat i zapytania SQL. Nie ingeruje w wolumen bazy.
- `scripts/diagnose_db_latency.py`: polecenie tylko do odczytu, które osobno mierzy zestawienie połączenia, `SELECT 1`, ranking Gold, grupowanie statusów Gold, historię prób Bronze i połączenia używane przez plan. Przez `SET TRANSACTION READ ONLY` blokuje zapis, a `statement_timeout=15s`, `lock_timeout=3s` obowiązują wyłącznie w jego sesji.
- `--ipv4`: w **tym pojedynczym procesie** używa `127.0.0.1` zamiast `localhost` i tylko gdy host z konfiguracji to adres lokalny. Nie zmienia `.env`, Dockera ani zapamiętanych ustawień.

## Instalacja i diagnostyka

Rozpakuj nowe pliki do repozytorium, nie rozpakowuj żadnych testowych `scraper/config.py` ani `scraper/models.py` (nie są częścią ZIP). W PowerShell z katalogu projektu:

```powershell
uv run --frozen python -m pytest tests/test_db_latency_probe.py -q
uv run --frozen python -m pytest -q

# Przebieg z obecnym hostem z .env
uv run --frozen python -u scripts/diagnose_db_latency.py

# Diagnostyczny przebieg z lokalnym IPv4; bez zmiany .env
uv run --frozen python -u scripts/diagnose_db_latency.py --ipv4

# Rzeczywiste polecenia użytkownika
Measure-Command { uv run --frozen python scripts/panel_spec_batch.py status }
Measure-Command { uv run --frozen python scripts/panel_spec_batch.py plan --limit 5 }
```

### Jak interpretować pomiary?

- **`PostgreSQL connect` zajmuje sekundy lub kończy się timeoutem, a przez `--ipv4` jest szybki**: prawdopodobnie problem dotyczy rozpoznawania `localhost`/sieci lokalnej Windows–Docker. Jeśli Docker udostępnia `127.0.0.1:5432`, można ustawić `POSTGRES_HOST=127.0.0.1` **w głównym pliku `.env` na Windows**. Nie zmieniaj `POSTGRES_HOST=postgres` używanego przez kontenery.
- **`PostgreSQL connect` jest szybki, ale wolny `catalog` lub `technical status`**: sprawdź obciążenie/bieżące blokady PostgreSQL i plan zapytania. Nie dodawaj indeksów w ciemno; dane są małe i istnieją indeksy na ostatnich wersjach specyfikacji/prób.
- **Wszystko w diagnozie jest szybkie, lecz oryginalny CLI nadal wolny**: zmierz importy procesu `python -X importtime` lub obserwuj Docker Desktop, zasoby i uśpienie systemu. Poczekanie 3 minut na samo `uv run` nie jest normą dla tego projektu.
- **Połączenie jest niestabilne**: 10-sekundowy timeout zamieni długie zawieszenie w czytelny błąd. Sam limit nie gwarantuje, że połączenia się przyspieszą; trzeba poprawić źródłową przyczynę.

### Dodatkowa szybka kontrola Docker

```powershell
docker ps --filter "name=solar-postgres"
docker exec solar-postgres pg_isready -U postgres -d solar_prices
```

Nie wykonuj `docker compose down -v`: usunęłoby to wolumen z historią. Wszystkie narzędzia etapu 11.4a są niewymagające migracji PostgreSQL, przebudowania obrazów Docker ani uruchamiania scrapera.

## Git

```powershell
git add scraper/load.py scripts/diagnose_db_latency.py tests/test_db_latency_probe.py docs/db_latency_step11_4a.md
git diff --cached --check
git commit -m "fix(db): bound connection waits and add batch latency diagnostics"
git push
```
