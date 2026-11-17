# E2E Solar — etap 11.4: ręczne wzbogacanie katalogu partiami

## Cel i stan wyjściowy

Po etapie 11.3 katalog liczył 72 oferty; dla dwóch paneli (LONGi 615 W i TW Solar 575 W) istnieją kompletne specyfikacje. Wiele podstron pokazuje wyłącznie przedziały dotyczące całej serii. **Nie wolno przepisywać przedziału wariantów jako dokładnych parametrów konkretnego panelu**. Bronze może jednak zachować takie źródłowe dane jako niekompletną specyfikację.

Etap 11.4 tworzy **osobne, manualnie uruchamiane** pobieranie w małych partiach. Nie modyfikuje `scraper.main`, DAG-ów Airflow, warstwy cenowej, istniejących widoków dbt ani dashboardu. Do uruchomienia wystarcza obecny Python/Playwright i PostgreSQL; nie instalujemy dodatkowych zależności.

## Zasady bezpieczeństwa i kultury pobierania

- **Przed włączeniem pobierania na żywo zapoznaj się z aktualnymi zasadami/robots.txt sklepu.** Samo techniczne działanie scrapera nie oznacza zgody na dowolny wolumen żądań. Nie można było zweryfikować aktualnych zasad w ramach pakietu.
- Domyślnie **5 produktów na uruchomienie**, maksymalnie **10**; domyślne opóźnienie **10 s** między żądaniami, minimum **8 s**; żadnych retry dla HTTP 403, 429, 5xx lub timeoutu.
- Nie obchodzimy CAPTCHA, limitów, ochrony antybotowej, autoryzacji ani blokad dostępu. Jeśli pojawi się `STOPPED` (np. `http_429`), wstrzymaj kolejne próby i sprawdź zasady źródła.
- Podstrona musi odpowiadać zatwierdzonej ścieżce HTTPS na `sklepsoltech.pl`; zmiana parametrów `?…` i fragmentu `#…` jest akceptowana tylko dla **tego samego produktu**. Zapisywany jest kanoniczny URL z Gold.
- Żaden nowy plik ani tabela nie zawiera haseł. Zapisujemy jedynie krótki rodzaj błędu, bez adresów z parametrami sesji i bez pobierania PDF.
- Nie wykonuj jednocześnie tego procesu i ręcznego pilota na tych samych produktach. Na razie **bez dodatkowego harmonogramu Airflow**.

## 1. Migracja — tylko nowa tabela prób

W katalogu głównym projektu:

```powershell
cd "E:\Repos Projects\E2E Solar Scrapper"
uv run --frozen python -m pytest tests/test_panel_spec_batch.py -q
uv run --frozen python -m pytest -q
uv run --frozen python scripts/migrate_panel_spec_batch.py
```

Skrypt tworzy `bronze.panel_spec_attempts` ze stanem każdej odwiedzonej strony i indeksem (URL, czas); jest idempotentny (`CREATE TABLE IF NOT EXISTS`). Istniejące ceny, runy, specyfikacje i widoki nie są dotykane. Przy odtwarzaniu **nowej, pustej** bazy SQL `007_panel_spec_attempts.sql` będzie zastosowany przez istniejące repozytoryjne skrypty inicjalizacyjne.

## 2. Plan: **bez żądań HTTP i bez zapisów**

```powershell
uv run --frozen python scripts/panel_spec_batch.py plan --limit 5
uv run --frozen python scripts/panel_spec_batch.py status
```

Plan odczytuje ostatni ranking Gold, najnowszą zapisaną specyfikację Bronze i ostatnią historię prób. Nie wymaga `dbt build` po każdej partii. Początkowo powinien zgłosić ~70 adresów kwalifikujących się do wzbogacenia (jeśli aktualny katalog i zapisane specyfikacje nie zmieniły się). Zawiera same aktywne oferty, bez nieprawidłowych lub zewnętrznych URL-i.

## 3. Pierwszy test na żywo: podgląd 2 produktów

```powershell
# 2 strony, bez żadnych INSERT-ów
uv run --frozen python -u scripts/panel_spec_batch.py run --limit 2
```

Obejrzyj wyniki `PASS`, `INCOMPLETE`, `REVIEW`, `POWER_MISMATCH`, `SKIPPED`. W przeciwieństwie do starego pilota, pojedynczy produkt `INCOMPLETE` nie blokuje zapisania informacji z innych stron. Wszystkie numeryczne, niepotwierdzone parametry pozostają `NULL` w modelu Silver.

## 4. Włączenie zapisu — każda pozycja zatwierdzana osobno

```powershell
# Każdy poprawnie odczytany produkt: odrębna transakcja Bronze+log próby
uv run --frozen python -u scripts/panel_spec_batch.py run --limit 2 --write

# Raport przejścia na żywo; po zakończeniu nowy plan pominie te produkty
uv run --frozen python scripts/panel_spec_batch.py status
uv run --frozen python scripts/panel_spec_batch.py plan --limit 5

# Istniejący check jakości dbt
uv run --frozen python scripts/check_panel_spec_models.py --min-complete 2
```

Zapis wykonuje `INSERT ... ON CONFLICT (source_url, spec_hash) DO NOTHING`. Przy powtórnym pobraniu identycznego HTML/tej samej wersji parsera nie powstanie nowy wariant specyfikacji. Jednocześnie zapisujemy **każdą rzeczywistą próbę** w `bronze.panel_spec_attempts` wraz z `spec_id` i informacją, czy wersja została dodana. **Niedokończony proces nie cofa wcześniej zatwierdzonych pozycji.**

Odśwież dashboard `http://localhost:8501` przyciskiem „Odśwież dane”. Modele Silver/Gold w tej konfiguracji są **widokami**, więc pokazują nowe rekordy bez ręcznego `dbt build`; uwzględnij maksymalnie pięciominutowy cache Streamlit. Dashboard w zakładce technicznej pokazuje status `INCOMPLETE`, ale nie traktuje takiego produktu jako poprawnego do porównań.

## 5. Kolejne partie, kontrola i powtórne próby

```powershell
uv run --frozen python scripts/panel_spec_batch.py plan --limit 5
uv run --frozen python -u scripts/panel_spec_batch.py run --limit 5 --write
uv run --frozen python scripts/panel_spec_batch.py status
```

**Domyślnie pomijamy wszystkie wcześniej zapisane specyfikacje**, zarówno `PASS`, jak i `INCOMPLETE/REVIEW`; nie pobieramy tego samego modelu przy każdym uruchomieniu. Dla błędnych stron bez specyfikacji obowiązuje okres przerwy (domyślnie 30 dni).

Jeśli po upływie czasu sklep poprawi opis i chcesz ręcznie ponowić niekompletną specyfikację:

```powershell
uv run --frozen python scripts/panel_spec_batch.py plan --limit 3 --retry-incomplete --cooldown-days 30
uv run --frozen python -u scripts/panel_spec_batch.py run --limit 3 --retry-incomplete --cooldown-days 30 --write
```

Minimum przerwy to **7 dni**; nie ma przełącznika wymuszającego natychmiastowe ponawianie. Modele pełne i aktualne nigdy nie są domyślnie ponownie pobierane. Jeśli wynik dla panelu zawiera `POWER_MISMATCH`, zachowaj go do ręcznej kontroli wariantu.

## 6. SQL do pgAdmin — historia prób i pokrycie

```sql
SELECT outcome, COUNT(*) AS attempts
FROM bronze.panel_spec_attempts
GROUP BY outcome ORDER BY outcome;

SELECT a.attempted_at, a.outcome, a.inserted_new_version,
       s.page_title, a.note
FROM bronze.panel_spec_attempts a
LEFT JOIN bronze.panel_spec_snapshots s ON s.spec_id = a.spec_id
ORDER BY a.attempt_id DESC LIMIT 20;

SELECT technical_status, COUNT(*) AS products
FROM gold.panel_technical_comparison
GROUP BY technical_status ORDER BY technical_status;
```

## 7. Uruchomienie testów, commit

```powershell
uv run --frozen python -m pytest tests/test_panel_spec_batch.py -q
uv run --frozen python -m pytest -q

git add scripts/panel_spec_batch.py scripts/migrate_panel_spec_batch.py docker/postgres/init/007_panel_spec_attempts.sql tests/test_panel_spec_batch.py docs/panel_spec_batch_11_4.md
git diff --cached --check
git commit -m "feat(enrichment): add bounded resumable PV spec batches"
git push
```

Nie używaj `git add .`: w repo mogą wciąż pozostawać pliki z wcześniejszych etapów lub lokalne konfiguracje. Nie wykonuj `docker compose down -v` — usunąłbyś trwałe wolumeny PostgreSQL.

## 8. Dlaczego to osobny proces, a nie DAG?

Ręcznie obserwujemy pierwsze partie i sprawdzamy jakość. Dopiero po kilku bezbłędnych uruchomieniach i potwierdzeniu zasad źródła można dodać osobny, niskoczęstotliwościowy DAG z limitami. Kolejna rozbudowa obejmie pozyskiwanie konkretnych wariantów z PDF producentów, osobne pole `source_type` i ocenę źródeł. Nie przenosimy automatycznie zakresów mocy całej rodziny na wybrany model.

## Ograniczenia

- Testy jednostkowe są offline: **nie dowodzą** zgodności z aktualną stroną ani poprawnej transakcji na Twoim PostgreSQL. To zweryfikujesz poleceniami z kroków 2–6.
- Nowy proces jest sterowany **ręcznie**; nie jest jeszcze automatycznym zadaniem w Airflow.
- Log prób zapisuje status i minimalny opis błędu; nie przechowuje pełnego HTML nieudanego żądania. Surowe dane techniczne są zachowywane dla prawidłowo rozpoznanych podstron, również niekompletnych.
- Trzymamy obecny identyfikator ofertowy `source_url`. Jeśli sklep zmieni URL tego samego fizycznego panelu, połączenie wymaga przyszłej normalizacji identyfikatorów producent/model.
