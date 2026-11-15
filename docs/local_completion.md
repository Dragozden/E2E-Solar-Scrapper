# E2E Solar — lokalne zamknięcie etapu MVP (Step 10)

Ten etap **nie** publikuje aplikacji do internetu, nie uruchamia scrapera i nie modyfikuje PostgreSQL ani widoków dbt. Zamyka kontrole operacyjne istniejącego projektu oraz włącza kopię archiwum na pendrive `F:\`.

## 1. Pendrive F: — backup lustrzany

Sprawdź, czy `F:` to rzeczywiście pendrive i ma dość wolnego miejsca:

```powershell
Get-Volume -DriveLetter F | Select-Object DriveLetter,DriveType,FileSystem,Size,SizeRemaining
```

Nie trzeba formatować nośnika. Dla obecnej bazy 32 GB jest więcej niż wystarczające, ale nie jest to magazyn o gwarantowanej trwałości. Zachowuj nadal kopie na `E:`. Jeśli masz BitLocker To Go, możesz zaszyfrować pendrive; pamiętaj, że zadanie automatyczne zadziała tylko po zamontowaniu i odblokowaniu nośnika.

W PowerShell z katalogu głównego projektu:

```powershell
cd 'E:\Repos Projects\E2E Solar Scrapper'
New-Item -ItemType Directory -Force -Path 'F:\SolarBackups'

# Pierwszy pełny przebieg: create -> isolated restore -> mirror -> SHA256
uv run --frozen python scripts/backup_automation.py run --mirror-dir 'F:\SolarBackups'
uv run --frozen python scripts/backup_automation.py status

# Sprawdź, czy komplet plików znajduje się na F:
Get-ChildItem 'F:\SolarBackups' -Filter 'solar_prices_*.dump*' | Sort-Object LastWriteTime -Descending | Select-Object -First 12 Name,Length,LastWriteTime
```

Oczekuj `"status": "PASS"` i `"mirrored_to": "F:\\SolarBackups"`. Backup trafia z `E:` na osobny fizyczny nośnik. Nie uruchamiaj jeszcze retencji ani nie kasuj wcześniejszych kopii.

## 2. Zaktualizuj zadanie Windows

Poprzedni harmonogram działał bez `--mirror-dir`. Ponowna rejestracja podmienia **jedynie definicję zadania** (nie usuwa bazy, historii ani backupów):

```powershell
.\scripts\register_weekly_backup_task.ps1 -MirrorDirectory 'F:\SolarBackups' -Force

# Sprawdź, czy nowa definicja ma argument --mirror-dir
(Get-ScheduledTask -TaskName 'E2E Solar - Weekly Verified Backup').Actions |
    Format-List Execute,Arguments,WorkingDirectory

# Sprawdź datę przyszłego uruchomienia
Get-ScheduledTaskInfo -TaskName 'E2E Solar - Weekly Verified Backup'
```

Opcjonalnie uruchom zadanie przez `Start-ScheduledTask`, a po zakończeniu sprawdź `LastTaskResult = 0` i `backup_automation.py status`. Ponieważ skrypt `run` już przed chwilą wykonał backup z lustrem, drugi ręczny start stworzy kolejny archiwum; jest to bezpieczne, ale niekonieczne.

**Ważne:** pendrive musi być obecny pod literą `F:`, użytkownik musi być zalogowany, Docker Desktop uruchomiony, a komputer włączony. Jeśli nośnik jest odłączony, zadanie zgłosi `FAIL` i nie utworzy backupu. Poprawka w `scripts/backup_automation.py` sprawia, że taki błąd jest zapisany w `backups/status/last_attempt.json` (nie udaje starego `PASS`).

## 3. Końcowa kontrola lokalnego MVP

```powershell
cd 'E:\Repos Projects\E2E Solar Scrapper'

uv run --frozen python -m pytest -q
uv run --frozen python scripts/local_release_check.py --mirror-dir 'F:\SolarBackups'
```

Druga komenda wykonuje wyłącznie odczyty i sprawdza:

- czy działają `solar-postgres`, `solar-airflow`, `solar-dashboard`, `solar-pgadmin`;
- czy Streamlit zwraca HTTP 200 dla `/_stcore/health`;
- czy Airflow rejestruje oba DAG-i (`solar_el_pipeline`, `solar_data_watchdog`);
- czy dedykowany użytkownik `solar_dashboard` może czytać widoki Gold i tabele Bronze (test `--check`, bez nadawania uprawnień);
- czy ostatni SUCCESS z Bronze jest świeży i spójny (istniejący `scraper.watchdog`, bez scrapingu);
- czy ostatnia próba backupu zakończyła się `PASS` nie dalej niż 8 dni temu, z prawidłowym raportem restore oraz SHA-256;
- czy na F:\ znajduje się kompletna, identyczna kopia tego backupu.

Komenda zwraca **kod wyjścia 1**, jeśli którykolwiek test ma `FAIL`. Wypisuje PASS/WARN/FAIL, ale **nigdy wartości haseł**. Nie zastępuje testu pełnego Airflow DAG na żywo: CI dbt i scraper regression to osobne kontrole, a źródło sklepu może się zmieniać.

Jeśli sprawdzenie freshness da `FAIL`, diagnostykę znajdziesz w Airflow. Nie uruchamiaj automatycznie nowego scrapingu tylko po to, żeby „zrobiło się zielono”. Jeśli USB zostało odłączone, podłącz ponownie i świadomie uruchom backup.

## 4. Commit

```powershell
git add scripts/backup_automation.py scripts/local_release_check.py tests/test_local_release_check.py docs/local_completion.md
git diff --cached --check
git commit -m 'chore(ops): verify local release and USB backup mirror'
git push
```

Wszystkie testy Pythona, w tym nowe, zostaną wykryte przez istniejące GitHub Actions. Prawdziwa weryfikacja `F:` musi zostać wykonana na Twoim Windows, nie w CI.

## 5. Co zostawiamy na następny etap — bogatsze dane PV

MVP pozostaje lokalne. Po stabilizacji można rozszerzyć schemat **bez nadpisywania historii cen**:

1. Osobne dane produktu / katalog: `product_id` (kanoniczny URL/SKU), producent, model, typ ogniw i karta produktu.
2. Parametry znamionowe modułu: `Pmax`, `Voc`, `Isc`, `Vmp`, `Imp`, sprawność, liczba ogniw, wymiary i masa.
3. Informacje dodatkowe: bifacialność i jej rodzaj, współczynniki temperaturowe, gwarancja, technologia ogniw (TOPCon / HJT / PERC) i dokument techniczny.
4. Surowy HTML/tekst opisowy jako źródło dla parsera i zachowanie wartości oryginalnej; wartości normalizowane z jednostkami w Silver.
5. Testy jakości: zakres fizycznie wiarygodnych wartości, spójność mocy `Pmax ≈ Vmp × Imp`, brak pomieszanych jednostek, kompletność wg producenta.
6. Dopiero później kolejne kategorie: falowniki, magazyny energii, regulatory, akcesoria — z osobnymi modelami parametrów zamiast jednej tabeli z dziesiątkami NULL-i.

Strony szczegółowe produktów mogą zwiększyć liczbę zapytań do sklepu. Najpierw sprawdzimy dozwoloną częstotliwość i sposób pozyskania danych (strona, karty PDF lub publiczny katalog), a dopiero potem włączymy je do harmonogramu.
