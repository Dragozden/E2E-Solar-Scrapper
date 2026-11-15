# E2E Solar — cotygodniowe backupy (etap 9.4)

**Cel:** zautomatyzować już sprawdzony proces `create → verify` bez zmieniania PostgreSQL, Airflow, Streamlit i istniejących wolumenów.

## Co wykonuje zadanie?

1. Uruchamia istniejące `scripts/postgres_backup.py: create_backup` — zapisuje spójny `pg_dump` w formacie custom do `backups/`.
2. Uruchamia istniejące `verify_backup` — **odtwarza** archiwum w osobnym kontenerze PostgreSQL 17 bez sieci i portów, weryfikuje liczniki Bronze/Silver/Gold, usuwa zasoby testowe.
3. Ponownie sprawdza sumę SHA-256 i raport `RESTORE PASS`.
4. Zapisuje `backups/status/last_attempt.json` oraz `backups/status/latest_success.json` (raport lokalny; oba pliki są ignorowane przez Git).
5. **Opcjonalnie:** kopiuje archiwum `.dump`, manifest `.dump.json` i raport `.dump.verified.json` do istniejącego katalogu na innym nośniku; porównuje SHA-256 po skopiowaniu.
6. **Opcjonalnie:** usuwa starsze *lokalne* kopie tylko wtedy, gdy istnieje ich kompletna, identyczna i zweryfikowana kopia na drugim nośniku. Pozostawia **co najmniej cztery najnowsze zweryfikowane kopie lokalne**. Brak zdefiniowanej retencji = brak usuwania.

Narzędzia nie wykonują `docker compose down -v`, nie modyfikują wolumenu `postgres_data`, nie odtwarzają archiwum do `solar-postgres` i nie resetują haseł.

## Pierwszy ręczny przebieg

Uruchom PowerShell w katalogu głównym projektu:

```powershell
cd "E:\Repos Projects\E2E Solar Scrapper"
uv run --frozen python -m pytest tests/test_backup_automation.py -q
uv run --frozen python scripts/backup_automation.py run
uv run --frozen python scripts/backup_automation.py status
```

Status `PASS` oznacza, że **ten konkretny nowy backup** został odtworzony i przetestowany, a nie tylko zapisany na dysku. Jeśli błąd wystąpi po wykonaniu `pg_dump`, ale przed końcem weryfikacji, wynik jest `FAIL` i nie przeprowadzamy retencji. Przy błędzie skrypt powinien pozostawić starsze, zweryfikowane kopie nienaruszone.

### Kopia na innym nośniku (zalecana)

Najpierw utwórz katalog na osobnym, najlepiej **szyfrowanym** dysku, np. `F:\SolarBackups`. Dysk musi być podłączony i katalog istnieć, zanim zacznie się zadanie. Dla wygody:

```powershell
New-Item -ItemType Directory -Force -Path "F:\SolarBackups"
uv run --frozen python scripts/backup_automation.py run --mirror-dir "F:\SolarBackups"
```

Katalog kopii nie może znajdować się wewnątrz `backups/`. Skrypt technicznie dopuszcza inny folder na tym samym dysku, ale **to nie zapewnia ochrony przed awarią dysku**. Za wybór rzeczywiście osobnego nośnika odpowiada użytkownik. Kopie nie są zaszyfrowane przez skrypt.

### Bezpieczna retencja

Włączaj ją dopiero po kilku tygodniach i po zweryfikowaniu kopii na drugim nośniku. Minimalny okres: 30 dni. Domyślnie retencja jest wyłączona.

```powershell
# TYLKO podgląd: lista lokalnych plików kwalifikujących się do usunięcia
uv run --frozen python scripts/backup_automation.py plan --mirror-dir "F:\SolarBackups" --retention-days 90

# Rzeczywisty przebieg: nowy backup, restore test, kopia na dysk F:, retencja
uv run --frozen python scripts/backup_automation.py run --mirror-dir "F:\SolarBackups" --retention-days 90
```

Przy retencji archiwum zewnętrzne pozostaje zachowane. Nie jest prowadzona rotacja ani usuwanie kopii **z dysku zewnętrznego**; tę politykę trzeba ustalić osobno. Skrypt nigdy nie usuwa plików, których nie rozpoznaje lub których raport/checksum jest nieprawidłowy. Nie usuwa również kopii, której pliki na drugim nośniku są niekompletne lub różnią się SHA-256.

## Harmonogram Windows — bez serwera i bez nowej usługi

W projekcie jest `scripts/register_weekly_backup_task.ps1`, który rejestruje zadanie Windows Task Scheduler dla **aktualnie zalogowanego użytkownika**. Domyślnie: **niedziela 10:00, lokalna strefa czasowa komputera** (na Twoim Windows: Europe/Warsaw, jeśli tak jest ustawiona).

```powershell
cd "E:\Repos Projects\E2E Solar Scrapper"

# Wariant bez drugiego dysku: 1 zweryfikowany backup tygodniowo, bez usuwania
.\scripts\register_weekly_backup_task.ps1

# ALBO: z zewnętrznym szyfrowanym dyskiem i retencją 90 dni
.\scripts\register_weekly_backup_task.ps1 -MirrorDirectory "F:\SolarBackups" -RetentionDays 90 -Force
```

Skrypt sprawdza, czy istnieje `.venv\Scripts\python.exe`. Jeśli go nie ma, wykonaj `uv sync --frozen`. Nie umieszcza żadnych haseł PostgreSQL w definicji zadania. Nie wymaga hasła Windows do uruchomienia, ponieważ wybiera tryb **Interactive**. Jeśli polityki lokalne blokują rejestrowanie zadań, Windows zwróci błąd uprawnień.

**Ważne ograniczenie:** komputer musi być uruchomiony, **użytkownik zalogowany**, a Docker Desktop dostępny. `StartWhenAvailable` pomaga przy pominiętej godzinie, ale nie zastępuje działającego hosta. Nie jest to backup wysokiej dostępności ani zewnętrzny monitoring. Po wylogowaniu/zamknięciu komputera zadanie nie wykona backupu. Na laptopie warto też sprawdzić warunki dotyczące zasilania w Harmonogramie zadań.

### Ręczny test zadania Windows

```powershell
Get-ScheduledTask -TaskName "E2E Solar - Weekly Verified Backup"
Start-ScheduledTask -TaskName "E2E Solar - Weekly Verified Backup"
Get-ScheduledTaskInfo -TaskName "E2E Solar - Weekly Verified Backup"
uv run --frozen python scripts/backup_automation.py status
```

Zadanie może nadal pracować po zwróceniu wyniku `Start-ScheduledTask`. Zaczekaj na jego zakończenie i odczytaj `status`, a także pole `LastTaskResult` w `Get-ScheduledTaskInfo`. Nie uruchamiaj drugiej kopii równolegle: skrypt używa pliku blokady `backups/.weekly_backup.lock`.

**Zmiana harmonogramu:** użyj `-Force`, np. `-DayOfWeek Saturday -At "11:30" -Force`. **Wyłączenie:** `Disable-ScheduledTask -TaskName "E2E Solar - Weekly Verified Backup"`. **Usunięcie zadania:**

```powershell
Unregister-ScheduledTask -TaskName "E2E Solar - Weekly Verified Backup" -Confirm:$false
```

Usunięcie samego zadania nie usuwa backupów ani bazy PostgreSQL.

## Raporty i awarie

- `backups/status/last_attempt.json` — ostatnia próba, `PASS` lub `FAIL`. W przypadku błędu zapisuje typ błędu, nie hasła.
- `backups/status/latest_success.json` — ostatni potwierdzony sukces, zachowywany nawet jeśli następny backup się nie powiedzie.
- `backups/*.dump[.json|.verified.json]` — dane, manifest i raport odtworzenia.
- `backups/.weekly_backup.lock` — blokada w trakcie uruchomienia. Po awarii procesu może pozostać; **sprawdź, czy backup nie działa**, przed ręcznym usunięciem blokady.

Diagnostyka po nieudanym zadaniu:

```powershell
docker ps --filter "name=solar-postgres"
uv run --frozen python scripts/backup_automation.py status
Get-ScheduledTaskInfo -TaskName "E2E Solar - Weekly Verified Backup"
```

Przykładowe przyczyny: Docker Desktop nie został uruchomiony, brak miejsca, brak podłączonego dysku `F:`, nieudany `pg_dump`, błąd odtworzenia lub brak dostępu do katalogu. Nie publikuj archiwów ani pełnych ścieżek z prywatnymi danymi.

## Co dalej, jeśli zależy Ci na niezawodności?

Na osobnym serwerze (albo dedykowanym PC pracującym 24/7) harmonogram może działać bez zalogowanego użytkownika, ale wymaga innej konfiguracji usług i uprawnień. Można także dodać zewnętrzny monitor dostępności i alarm, jeśli `latest_success.json` jest starszy niż 8 dni. Sam obecny Airflow watchdog nie wykrywa sytuacji, w której cały komputer jest wyłączony.

## Testy bez dostępu do bazy

```powershell
uv run --frozen python -m pytest tests/test_backup_automation.py -q
uv run --frozen python -m pytest -q
```

Nowe testy stosują syntetyczne manifesty i podmieniają funkcje tworzenia/odtwarzania archiwów; nie wykonują żadnego `docker exec`, SQL ani rzeczywistego usuwania danych z projektu.
