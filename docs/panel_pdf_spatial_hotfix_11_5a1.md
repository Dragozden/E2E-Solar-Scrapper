# E2E Solar — hotfix 11.5a.1: Spatial PDF/STC inspector

## Cel i przyczyna

Wynik testu oryginalnego PDF `TW_505.pdf`: `NO_UNAMBIGUOUS_STC_TABLE`, `candidates: []`, `diagnostics: []`, `database_write: false`, SHA-256 `3b6d1f41ea4496b51655dc4533b3807dd0a83939266c36146797abc08fe9698f`.

W starszej wersji `scripts/panel_pdf_preview.py` nagłówek *CHARAKTERYSTYKA ELEKTRYCZNA (STC)* musiał zostać rozpoznany w jednej linii `extract_text_lines`. Kompozycja PDF bywa wielokolumnowa, a tekst tabeli rozbity na osobne obiekty. Wersja 11.5a.1 próbuje najpierw dotychczasowej ekstrakcji tekstowej, a gdy nie dostanie jednoznacznego kandydata, odczytuje geometrię słów na stronie.

**Uwaga:** nie udało się niezależnie otworzyć binarnego pliku użytkownika w środowisku testowym. Implementację sprawdzono na syntetycznym PDF o podobnym dwukolumnowym układzie; rzeczywisty PDF Soltech jest testem akceptacyjnym u użytkownika. Nie zakładaj, że wynik `REVIEW_REQUIRED` jest potwierdzony bez wizualnej weryfikacji oryginalnej karty i kolumny.

## Instalacja (Windows)

1. Wypakuj ZIP **do korzenia repo**, zastępując wyłącznie:
   - `scraper/panel_pdf_stc.py`
   - `scripts/panel_pdf_preview.py`
   oraz dodając dwa nowe pliki testowe i dokumentację.
2. Uruchom:

```powershell
cd "E:\Repos Projects\E2E Solar Scrapper"
uv run --frozen python -m pytest tests/test_panel_pdf_spatial.py tests/test_panel_pdf_spatial_cli.py tests/test_panel_pdf_stc.py tests/test_panel_pdf_cli.py -q
uv run --frozen python -m pytest -q
```

3. **Nie nadpisuj poprzedniego JSON-a** — użyj nowej nazwy:

```powershell
$pdf = Join-Path $HOME "Downloads\SolarSpecs\TW_505.pdf"
Test-Path $pdf
uv run --frozen --with "pdfplumber==0.11.9" python scripts/panel_pdf_preview.py `
  --pdf $pdf `
  --model "TWMNH-54HD505" `
  --power 505 `
  --json-output "$HOME\Downloads\SolarSpecs\TW_505_review_v2.json"
```

## Jak interpretować wynik

- **`REVIEW_REQUIRED`** z jednym `candidate`: parser wyodrębnił jeden układ STC; sprawdź **stronę, kolumnę 505 W, moc, Voc/Vmp/Isc/Imp, sprawność**, identyfikator dokumentu oraz zgodność wariantu z ofertą. To **nie jest zatwierdzony zapis**.
- **`NO_UNAMBIGUOUS_STC_TABLE`**: odpowiedź jest bezpieczna. Teraz `diagnostics` nie będzie puste — zawiera liczbę słów, przykłady tekstu nagłówków i powody odmowy (np. `NO_SPATIAL_STC_HEADING`, `MISSING_SPATIAL_METRICS`, `MISALIGNED_SPATIAL_COLUMNS`, `PHYSICS_OR_STC_VALIDATION_FAILED`). Nie stosuj OCR ani zgadywania wartości bez sprawdzenia konkretnego pliku.
- **`database_write`** zawsze `false`; nie ma zmian Bronze, Silver, Gold, Airflow, Docker ani `.env`.
- Jeśli nadal brak wyniku, najskuteczniejsza weryfikacja to przesłanie **oryginalnego `TW_505.pdf`**, nie tylko raportu JSON. Z samych pustych kandydatów nie da się stwierdzić dokładnej struktury PDF.

## Testy / commit

W lokalnej kopii przechodzi 39/39 odpowiednich testów (27 poprzednich + 12 nowych). Dodatkowo uruchomiono inspektor na zbudowanym lokalnie testowym PDF z dwoma kolumnami; wybrał 505 W w indeksie 2 oraz odpowiednie parametry STC. Nie testowano pełnego repozytorium użytkownika ani oryginalnego Soltech PDF.

```powershell
git status --short
git add scraper/panel_pdf_stc.py scripts/panel_pdf_preview.py tests/test_panel_pdf_spatial.py tests/test_panel_pdf_spatial_cli.py docs/panel_pdf_spatial_hotfix_11_5a1.md
git diff --cached --check
git diff --cached --stat
git commit -m "fix(enrichment): recover STC candidates from PDF word geometry"
git push
```

Commit zrób po lokalnych testach, zwłaszcza na rzeczywistym PDF. Nie wykonuj `git add .`; poprzednie niezacommitowane modyfikacje bezpieczeństwa oraz lokalne instrukcje pozostają poza tym patchem.
