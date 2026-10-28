# Business Logic — E2E Solar Price Pipeline

> **Stan: 28.10.2026.** Modele rankingu, historii cen i dziennych metryk działają w dbt Gold. Poniżej opisano przyjętą logikę biznesową i interpretację wyników; szczegóły implementacyjne są określone przez źródłowe modele SQL w `dbt/solar_dbt/models/`.

## Przedmiot analizy

Analizujemy **oferty paneli fotowoltaicznych w jednym sklepie internetowym** w kolejnych chwilach pomiaru. Wynik nie jest cennikiem transakcyjnym, nie mierzy faktycznej sprzedaży ani ilości towaru na magazynie. Każdy poprawny scraping stanowi kolejny snapshot zaobserwowanego katalogu.

## Identyfikatory i granularity

| Pojęcie | Identyfikator / grain | Znaczenie |
|---|---|---|
| Run scrapera | `scrape_run_id` | Jeden pomiar katalogu |
| Wiersz Bronze/Silver | `scrape_id` | Jedna zapisana obserwacja oferty |
| Produkt MVP | `source_url` | Identyfikator ofertowy używany do porównywania runów |
| Obserwacja historii | (`scrape_run_id`, `source_url`) | Jedna obserwacja produktu w danym runie |
| Trend dzienny | `observation_date` | Jeden agregat dzienny |

Powtórzenie URL między kolejnymi runami jest zamierzone, natomiast powtórzenia URL w tym samym runie powinny zostać wykryte i odrzucone przez kontrole jakości.

## Główne wskaźniki

| Wskaźnik | Wzór | Interpretacja |
|---|---|---|
| `pln_per_watt` | `price_pln / power_w` | **Niżej = taniej** za 1 W mocy znamionowej |
| `watt_per_pln` | `power_w / price_pln` | **Wyżej = więcej** W za 1 PLN |
| Różnica ceny | `price_pln - previous_price_pln` | Dodatnia: podwyżka, ujemna: obniżka |
| Zmiana procentowa ceny | `100 * (price_pln - previous_price_pln) / previous_price_pln` | Porównanie z poprzednią dostępną obserwacją tego samego URL |

Wskaźniki wymagają dodatniej, poprawnie sparsowanej ceny i dodatniej mocy. Brak poprzedniej ceny albo poprzednia cena niepoprawna/zerowa nie pozwalają obliczyć sensownej zmiany procentowej. **PLN/W nie jest miarą uzysku energii**, sprawności modułu, kosztów montażu ani LCOE.

## Ranking bieżących ofert — `gold.current_panel_ranking`

Kontrakt biznesowy:

1. Dane pochodzą z **najnowszego runu `SUCCESS`**, ustalonego po czasie zakończenia, a nie z całej historycznej tabeli.
2. Do rankingu kwalifikują się wiersze o niepustym URL, dodatniej cenie `price_pln` i mocy `power_w`.
3. Dla jednego URL występuje jedna oferta (historycznie model może preferować nowszy rekord; duplikat w samym runie pozostaje naruszeniem jakości).
4. Produkty dostępne (`is_available = TRUE`) są priorytetyzowane przed niedostępnymi; dalej rosnąco według `pln_per_watt`, a następnie stabilizujące kryterium nazwy.
5. Kategorie cenowe: **poniżej 200 PLN**, **200–299,99 PLN**, **300–399,99 PLN**, **od 400 PLN**. Dolne granice kolejnych przedziałów są włączone.

Ranking pomaga znaleźć atrakcyjne cenowo oferty w bieżącej próbce sklepu. Nie dowodzi, że dany panel jest technicznie najlepszy lub że produkt jest dostępny w dowolnej ilości.

## Historia cen — `gold.product_price_history`

- Historyczne obserwacje pozostają w Bronze i Silver; nowy scraping **nie nadpisuje** poprzedniej ceny.
- Połączenie kolejnych pomiarów bazuje obecnie na `source_url`; przy zmianie URL identyfikacja tego samego fizycznego modelu może zostać przerwana.
- W Gold używamy m.in. pól `observed_at`, `price_pln`, `previous_price_pln` i `price_change_pln` (występują w obecnym zapytaniu dokumentacyjnym). Szczegółowy zestaw kolumn i sortowanie określa aktualny plik SQL modelu.
- Jeśli produkt nie występuje w którymś runie, nie należy automatycznie interpretować tego jako „wycofany ze sprzedaży”; może to wynikać ze zmiany katalogu, filtra, awarii źródła albo scraperowego błędu.
- Wykres „historia ceny produktu” pokazuje **obserwacje**, nie wszystkie zmiany ceny między momentami pomiaru.

## Trend rynku — `gold.daily_market_prices`

- Model agreguje historię do pojedynczego wiersza na `observation_date`.
- Założenie przy wielu scrapingach tego samego dnia: dla danego URL użyć jego ostatniej obserwacji z tego dnia. Inaczej ten sam produkt zwiększa wagę statystyk tylko dlatego, że był częściej skanowany.
- Porównania średniej ceny, liczby dostępnych produktów i średniej PLN/W opisują **skład obserwowanych ofert** w danym dniu.
- Zmiana średniej PLN/W nie musi oznaczać zmiany ceny tych samych paneli: może wynikać z dodania, usunięcia albo niedostępności produktów (efekt składu koszyka).
- W dashboardzie należy odróżnić trend całego dostępnego katalogu od trendu stałego zestawu identycznych produktów; indeks koszykowy wymaga osobnej metody.

## Interpretacja znanej zmiany katalogu

| Data | Zarejestrowana liczba unikalnych ofert | Uwagi |
|---|---:|---|
| 27.10.2026 | 288 | Poprawne przebiegi z 288 unikalnymi URL |
| 28.10.2026 — przed poprawką | 78 z 126 wierszy | 48 nadmiarowych wystąpień URL z błędnej, stałej paginacji |
| 28.10.2026 — po poprawce | 78 | 4 strony, bez duplikatów; poprawny przebieg wszystkich etapów |

Spadek z 288 do 78 unikalnych ofert **nie jest sam w sobie zmianą cen ani potwierdzoną utratą magazynową**. Nie wolno dokładać sztucznych zer cenowych do brakujących ofert, żeby „uzupełnić” trend.

## Założenia wymagające weryfikacji

- **Cena:** wartość pochodzi z atrybutu kafelka; nie potwierdzono niezależnie, czy jest brutto czy netto.
- **Moc:** wyprowadzana regexem z nazwy; opis techniczny produktu może wymagać oddzielnej walidacji.
- **Sprawność i bifaciality:** pola Bronze są przygotowane, ale obecnie nie stanowią zweryfikowanych metryk analitycznych.
- **Tożsamość produktu:** URL nie gwarantuje niezmienności w dłuższym okresie; docelowo warto pozyskiwać stabilny identyfikator sklepu/modelu.
- **Znacznik czasu i dzień:** przed użyciem wielostrefowym należy ujednolicić UTC oraz zasady wyznaczania dnia obserwacji.

Powiązane pliki: [Data dictionary](data_dictionary.md), [Data quality](data_quality.md), [Architecture](architecture.md).
