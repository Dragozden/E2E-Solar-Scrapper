# Etap 11.1a — poprawka odczytu rzeczywistych podstron PV

## Dlaczego była potrzebna?

W pilocie `--live --limit 3` pojawił się `ValueError` w `parse_panel_details` informujący o niedozwolonym URL, mimo wcześniejszej kontroli URL w `live_samples`. Przyczyną może być asynchroniczna zmiana `page.url` po wcześniejszej walidacji (np. przekierowanie JS / produkt niedostępny). Bez zapisu końcowego URL przy analizie HTML parser dostawał inny adres niż ten, który sprawdzano. Dokładnego celu przekierowania nie znamy z poprzedniego logu.

Osobny test `--live --limit 1` prawidłowo odczytał rzeczywistą stronę LONGi LR8-66HGD-615M: 615 W, 22,8%, Voc 48,58 V, Vmp 40,71 V, Isc 16,00 A, Imp 15,11 A. `datasheet_urls=[]` oznacza jedynie, że w HTML nie znaleziono kwalifikującego się linku PDF.

## Zmiany

- Produkty są logowane jeden po drugim wraz z postępem i liczbą znalezionych parametrów.
- Kontrola `page.url` następuje **po** krótkim oczekiwaniu i **ponownie po** pobraniu HTML; parser dostaje zamrożony, zatwierdzony adres.
- Przekierowania poza dozwoloną podstronę *lub na inny produkt* są pomijane w podglądzie z ostrzeżeniem. Nie odgadujemy kanonicznego identyfikatora produktu, nie podmieniamy URL i nie omijamy zabezpieczeń sklepu.
- HTTP >=400 (w tym 429) nadal natychmiast przerywa operację, bez retry.
- `--write` używa ostrzejszego trybu: jeśli pominięto choć jedną stronę, **nic nie zostaje zapisane**.
- Przy parsowaniu paragrafów/list ignorowane są zdania marketingowe o formacie `**etykieta** — dłuższy opis` oraz pole `Uwaga`. Nowe nieznane, ale strukturalne atrybuty w tabelach lub parach `Etykieta: wartość` pozostają.
- Wersja parsera zmieniona na `panel-details-v1.1`.

## Kolejność po podmianie plików

```powershell
cd "E:\Repos Projects\E2E Solar Scrapper"
uv run --frozen python -m pytest tests/test_panel_detail_specs.py tests/test_panel_detail_pilot.py tests/test_panel_live_hotfix.py -q
uv run --frozen python -m pytest -q
uv run --frozen python -u scripts/panel_detail_pilot.py --live --limit 3
```

Jeśli podgląd zwróci trzy prawidłowe strony, brak problemów jakościowych i wystarczającą liczbę parametrów, można uruchomić pilota z `--write`; osobna tabela `bronze.panel_spec_snapshots` powinna już istnieć. Po udanym zapisie sprawdź `SELECT source_url, page_title, normalized_values, parse_issues FROM bronze.panel_spec_snapshots ORDER BY spec_id DESC LIMIT 5;` w pgAdmin. Pierwszy zapis wykonuj dopiero po obejrzeniu wyników. Skrypt nie modyfikuje istniejącego DAG-a, modeli Gold ani historii cen.

Na kolejnym etapie zbudujemy dbt `silver.stg_panel_specs` i `gold.panel_technical_comparison` po zatwierdzeniu danych rzeczywistych.
