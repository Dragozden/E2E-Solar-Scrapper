# Business Logic

## Główne metryki
- `pln_per_watt = price_pln / power_w` — **niżej = lepiej**; porównuje koszt mocy nominalnej, nie generację w kWh.
- `watt_per_pln = power_w / price_pln` — **wyżej = lepiej**; odwrotność poprzedniego wskaźnika.
- Cena musi być dodatnia, moc musi być dodatnia (dzielenie przez zero jest niedozwolone).

## Aktualny ranking (`gold.current_panel_ranking`)
1. Tylko obserwacje z **ostatniego** runu `SUCCESS`.
2. Tylko wiersze z poprawną dodatnią ceną i mocą i niepustym URL-em.
3. Jedna obserwacja na URL.
4. `is_available = TRUE` przed niedostępnymi; w obrębie dostępności sortowanie po `pln_per_watt ASC`, następnie po nazwie.
5. Koszyki cenowe: `<200 zł`, `200-300 zł`, `300-400 zł`, `400+ zł`, przedziały dolnie domknięte.

## Historia cen
- Jeden produkt może występować w wielu runach: **nie kasować wcześniejszych obserwacji**.
- Klucz produktu w MVP: `source_url` (założenie zależne od trwałości linku sklepu).
- Zmiana ceny: `new_price - previous_price`.
- Zmiana procentowa: `(new_price - previous_price)/previous_price * 100`, jeżeli poprzednia cena > 0.
- Przy wielu scrape'ach w jednym dniu, do wskaźnika dziennego używać najpóźniejszej obserwacji produktu w tym dniu, aby produkt nie ważył więcej tylko dlatego, że był częściej scrapowany.
- Średnia cena/W paneli dostępnych jest *wskaźnikiem składu bieżącej oferty*, a nie stałym indeksem tych samych produktów (zmiana koszyka wpływa na średnią).

## Dane, których jeszcze nie znamy
- Czy atrybut `price` przedstawia cenę brutto czy netto: wymaga potwierdzenia na sklepie, nie zakładać.
- Czy model panelu może zmienić URL: wymaga obserwacji lub identyfikatora produktu ze sklepu.
- Sprawność/bifaciality nie są jeszcze zweryfikowane — nie tworzyć rankingów opartych na tych parametrach.
