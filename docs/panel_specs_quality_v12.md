# E2E Solar — Etap 11.1c: jakość danych technicznych (parser v1.2)

## Dlaczego ten etap?

Pilot na trzech stronach (15.11.2026) zakończył się **3/3 odczytanych stron**. Liczba poprawnych stron nie jest jednak równoważna liczbie **kompletnych specyfikacji**:

- LONGi LR8-66HGD-615M: 23 atrybuty, 16 znormalizowanych, elektryczne parametry modelu dostępne.
- TW Solar 575 TWMND-72HD575: 32 atrybuty, 19 znormalizowanych, przed poprawką nierozdzielona gwarancja i niezapisany NMOT.
- TW Solar 505 TWMNH-54HD505: 12 atrybutów, 4 znormalizowane, sklep opisał zakres wariantów 495–515 W, zakres sprawności 22,3–23,2% i górną granicę bifacjalności „do 80%”.

**Zakres modelowy nie jest parametrem konkretnej wersji 505 W.** W szczególności nie wolno przypisać jej `efficiency_pct=22.3` jako dokładnej wartości z karty wariantu.

## Poprawki parsera

- Polskie `ł` jest poprawnie transliterowane w etykietach (`Współczynniki`, `materiałowa`).
- Liczbowe zakresy i limity (`od … do …`, `22,3%–23,2%`, `do 80%`) nie są mapowane na dokładną wartość; surowa para pozostaje w `attributes_raw`, a `parse_issues` zawiera nazwany problem.
- W tolerancjach nominalnych (`80% ±5%`, `45°C ±2°C`) wartość centralna jest nadal możliwa do rozpoznania; pełna tolerancja pozostaje w `attributes_raw`.
- Po wyraźnie opisanym podziale gwarancji (np. `12 lat gwarancji materiałowej, 30 lat gwarancji mocy`) zapisujemy oddzielnie `product_warranty_years` i `performance_warranty_years`. Samo `12 lat / 30 lat` pozostaje nierozpoznane.
- `NMOT` jest przechowywane jako `nmot_c`, a `NOCT` jako `noct_c`: nie utożsamiamy automatycznie tych dwóch oznaczeń.
- Zbiorcza wartość `Współczynniki temperaturowe` może dać osobno `temp_coeff_pmax_pct_c`, `temp_coeff_voc_pct_c` i `temp_coeff_isc_pct_c`, tylko przy jawnie oznaczonych wartościach i jednostkach.
- W `cell_technology` usuwamy wyraźnie oddzieloną marketingową końcówkę ` – ...` (surowa treść zachowana), a opisane jawnie `108 ogniw` pozwala odczytać `cell_count=108`.
- `spec_hash` uwzględnia wersję parsera oraz ujednolicone wartości; ponowne parsowanie tych samych stron nową wersją może zapisać nową wersję interpretacji bez modyfikowania poprzedniej.

## Nowa blokada jakości dla `--write`

Do pilotażowego zapisu wymagane są kompletne wartości **Pmax, Voc, Vmp, Isc, Imp** oraz brak twardych błędów fizycznych (np. `voc_not_above_vmp`, konfliktów, rozbieżności Pmax z Vmp×Imp). Nie wymagamy pozostałych pól, które mogą nie występować na stronie.

`--live` jest wyłącznie podglądem. Po każdym produkcie wyświetla `quality=PASS/INCOMPLETE`, brakujące podstawowe pola i ostrzeżenia. `--write` wstrzyma cały wsad, jeśli nawet jeden z produktów nie spełnia progu — żaden wiersz z tego wsadu nie zostanie zapisany. Ta restrykcja dotyczy **manualnego pilota**; przyszły produkcyjny Bronze może przechowywać również częściowe surowe dane z jednoznacznym statusem jakości i wykluczać je z Gold.

**Dla przykładu z logu:** najpierw przetestuj `--live --limit 2`. Jeżeli obydwa produkty mają `quality=PASS` i liczby wyglądają poprawnie, można wykonać `--live --limit 2 --write`. `--limit 3 --write` powinien zostać zablokowany, ponieważ opis TW Solar 505 nie zawiera kompletu parametrów modelowych. Dalsze dane 505 W należy odczytać z odpowiedniej karty katalogowej z identyfikacją **konkretnego wariantu**, a nie wnioskować z zakresu całej rodziny produktów.

## Testy offline

```powershell
cd "E:\Repos Projects\E2E Solar Scrapper"
uv run --frozen python -m pytest tests/test_panel_detail_specs.py tests/test_panel_detail_pilot.py tests/test_panel_live_hotfix.py tests/test_panel_navigation_consistency.py tests/test_panel_spec_quality_v12.py -q
uv run --frozen python -m pytest -q
```

Nowe testy w `test_panel_spec_quality_v12.py` odtwarzają fragmenty rzeczywistych wartości z logu (to nie są zarchiwizowane pełne strony ani zweryfikowane PDF-y producenta). Nie pobierają internetu i nie zapisują danych do PostgreSQL.

## Co dalej?

1. Zweryfikować test podglądu i ewentualnie zapisać **tylko dwa kompletne produkty**.
2. W pgAdmin sprawdzić aktualne rekordy w `bronze.panel_spec_snapshots`.
3. Przygotować dbt Silver: jawny `quality_status`, NULL dla wartości nieustalonych, pochodzenie i wersjonowanie specyfikacji.
4. Przygotować Gold: ranking techniczny, ale porównywać tylko pola potwierdzone, nie zakresy z opisów rodzin modułów.
5. Dopiero później projektować przetwarzanie źródłowych PDF-ów, z zachowaniem producenta, modelu i wersji danych katalogowych.

**Uwaga bezpieczeństwa:** nie zmieniono istniejących DAG-ów, modeli dbt, tabel cenowych ani haseł. Nie jest potrzebna żadna migracja PostgreSQL dla v1.2 parsera.
