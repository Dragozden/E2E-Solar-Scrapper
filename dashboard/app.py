"""E2E Solar — Streamlit v3 (Gold analytics + Bronze quality)."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.analytics import (
    available_metrics,
    filter_ranking,
    latest_observation_per_day,
    latest_product_labels,
    product_history,
    product_summary,
)
from dashboard.charts import (
    daily_count_chart, price_series, price_power_scatter,
    product_comparison_chart, BLUE, TEAL,
)
from dashboard.insights import latest_prices_for_comparison, price_drop_events
from dashboard.monitoring import evaluate_runs
from dashboard.db import load_run_quality
from dashboard.db import load_gold_data
from dashboard.technical_ui import clear_technical_cache, render_technical_tab


st.set_page_config(
    page_title="E2E Solar | PV Market Analytics",
    page_icon="☀️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
      .block-container { max-width: 1530px; padding-top: 1.6rem; padding-bottom: 3rem; }
      div[data-testid="stMetricValue"] { font-size: clamp(1.5rem, 2vw, 2rem); }
      div[data-testid="stMetricLabel"] { font-weight: 550; }
      div[data-testid="stTabs"] { margin-top: .6rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(ttl=300, show_spinner="Odczytuję modele Gold z PostgreSQL...")
def get_data() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    return load_gold_data()


@st.cache_data(ttl=300, show_spinner="Sprawdzam ostatnie wykonania scrapera...")
def get_run_quality() -> pd.DataFrame:
    return load_run_quality()


def format_ratio(value: float | None) -> str:
    return f"{value:.4f} zł/W" if value is not None else "—"


def ranking_table(frame: pd.DataFrame, *, height: int = 390) -> None:
    """Compact table with friendly outbound links, not raw 100-char URLs."""
    columns = [
        "overall_rank", "title", "power_w", "price_pln",
        "pln_per_watt", "is_available", "source_url",
    ]
    st.dataframe(
        frame[columns],
        hide_index=True,
        width="stretch",
        height=height,
        row_height=32,
        column_config={
            "overall_rank": st.column_config.NumberColumn("#", format="%d", width="small"),
            "title": st.column_config.TextColumn("Panel", width="large"),
            "power_w": st.column_config.NumberColumn("Moc [W]", format="%d", width="small"),
            "price_pln": st.column_config.NumberColumn("Cena [zł]", format="%.2f", width="small"),
            "pln_per_watt": st.column_config.NumberColumn("zł/W", format="%.4f", width="small"),
            "is_available": st.column_config.CheckboxColumn("Dostępny", width="small"),
            "source_url": st.column_config.LinkColumn(
                "Sklep", display_text="Otwórz ofertę ↗", width="medium"
            ),
        },
    )


with st.sidebar:
    st.header("☀️ E2E Solar")
    st.caption("PV Market Analytics · dashboard v3")
    if st.button("↻ Odśwież dane", width="stretch"):
        get_data.clear()
        get_run_quality.clear()
        clear_technical_cache()
        st.rerun()
    st.caption("Odczyt z PostgreSQL / dbt Gold · cache: 5 minut")
    st.divider()
    st.write("**Źródło danych**")
    st.caption("Oferty paneli fotowoltaicznych ze sklepu Soltech. Nie są to dane o transakcjach.")
    st.caption("Aplikacja nie uruchamia scrapera i nie zmienia rekordów w bazie.")

try:
    ranking, history, daily = get_data()
except Exception as exc:
    st.error("Nie można odczytać widoków Gold z PostgreSQL.")
    st.exception(exc)
    st.info(
        "Sprawdź kontener solar-postgres, plik .env w katalogu głównym "
        "oraz widoki gold.current_panel_ranking, gold.product_price_history "
        "i gold.daily_market_prices."
    )
    st.stop()

st.title("PV Market Analytics")
st.caption("E2E Solar · Playwright → PostgreSQL Bronze → dbt Silver/Gold → Streamlit")

if ranking.empty:
    st.warning("Brak produktów w ostatnim udanym wsadzie. Uruchom pipeline Airflow i odśwież dane.")
    st.stop()

metrics = available_metrics(ranking)
cols = st.columns(4, gap="small")
kpis = [
    ("Oferty w ostatnim wsadzie", str(metrics["total"])),
    ("Oferty dostępne", str(metrics["available"])),
    ("Najlepsza cena/W", format_ratio(metrics["min_pln_per_watt"])),
    ("Średnia cena/W", format_ratio(metrics["avg_pln_per_watt"])),
]
for column, (label, value) in zip(cols, kpis):
    with column:
        with st.container(border=True):
            st.metric(label, value)

run_id = str(ranking["scrape_run_id"].iloc[0])
latest_time = pd.to_datetime(ranking["scraped_at"], errors="coerce").max()
latest_text = latest_time.strftime("%d.%m.%Y %H:%M") if pd.notna(latest_time) else "nieznany"
st.caption(f"Ostatni wsad: {latest_text} · scrape_run_id: `{run_id[:8]}…` · KPI dotyczą wszystkich ofert dostępnych w tym wsadzie.")

overview_tab, ranking_tab, drops_tab, compare_tab, history_tab, market_tab, quality_tab, technical_tab = st.tabs([
    "Przegląd", "Ranking paneli", "Przeceny", "Porównanie", "Historia produktu",
    "Trendy rynku", "Jakość danych", "Parametry techniczne",
])

with overview_tab:
    st.subheader("Rynek w skrócie")
    if daily.empty:
        st.info("Brak zagregowanych dziennych danych do wykresów.")
    else:
        left, right = st.columns(2, gap="medium")
        with left:
            st.plotly_chart(
                price_series(daily, date_col="observation_date", value_col="avg_pln_per_watt",
                             title="Średnia cena dostępnych ofert · zł/W", suffix="zł/W", color=BLUE),
                width="stretch", key="overview_market_ratio",
                alt="Średnia cena za wat w dniach, w których wykonano pomiary.",
            )
        with right:
            st.plotly_chart(daily_count_chart(daily), width="stretch", key="overview_market_count",
                            alt="Liczba dostępnych ofert w dniach pomiarowych.")

    left, right = st.columns([1.1, 1.4], gap="large")
    with left:
        st.plotly_chart(price_power_scatter(ranking), width="stretch", key="price_vs_power",
                        alt="Wykres zależności mocy znamionowej i ceny dostępnych paneli.")
    with right:
        st.markdown("#### Najlepsze oferty z ostatniego wsadu")
        best = ranking.loc[ranking["is_available"].eq(True)].nsmallest(7, "pln_per_watt")
        if best.empty:
            st.info("Brak dostępnych ofert w ostatnim wsadzie.")
        else:
            ranking_table(best, height=310)
    st.caption("Zmiany średniej mogą wynikać także ze zmiany asortymentu, a nie wyłącznie ze zmian cen tych samych produktów.")

with ranking_tab:
    st.subheader("Ranking paneli według zł/W")
    st.caption("Filtry dotyczą tylko tej zakładki. Pozycja # to ranking z pełnego ostatniego wsadu.")
    search_col, availability_col = st.columns([2, 1], gap="medium")
    with search_col:
        search = st.text_input("Wyszukaj panel", placeholder="np. JA Solar, TW Solar, 575W")
    with availability_col:
        availability = st.selectbox("Dostępność", ["Dostępne", "Wszystkie", "Niedostępne"])

    min_w = int(ranking["power_w"].min())
    max_w = int(ranking["power_w"].max())
    ratio_upper = max(0.01, float(ranking["pln_per_watt"].max()))
    ratio_upper = round(ratio_upper + 0.01, 2)
    power_col, ratio_col = st.columns(2, gap="large")
    with power_col:
        if min_w < max_w:
            power_range = st.slider("Moc panelu [W]", min_w, max_w, (min_w, max_w))
        else:
            power_range = (min_w, max_w)
            st.caption(f"Moc: {min_w} W")
    with ratio_col:
        ratio_limit = st.slider("Maksymalna cena [zł/W]", 0.0, ratio_upper, ratio_upper, 0.01)

    filtered = filter_ranking(
        ranking, availability=availability, search=search,
        min_power=power_range[0], max_power=power_range[1],
        max_pln_per_watt=ratio_limit,
    )
    st.markdown(f"**{len(filtered)} ofert** z {len(ranking)} w ostatnim wsadzie")
    if filtered.empty:
        st.info("Brak ofert spełniających te kryteria. Rozszerz filtry.")
    else:
        ranking_table(filtered, height=460)
        st.download_button(
            "↓ Eksportuj przefiltrowane wyniki (CSV)",
            data=filtered.to_csv(index=False).encode("utf-8-sig"),
            file_name="pv_panel_ranking.csv", mime="text/csv", width="content",
        )

with drops_tab:
    st.subheader("Detektor obniżek cen")
    st.caption(
        "Przecena oznacza spadek ceny tego samego URL produktu między dwoma "
        "kolejnymi udanymi pomiarami. Okno czasowe liczymy od ostatniego pomiaru "
        "w bazie, nie od bieżącego dnia."
    )
    f1, f2, f3, f4 = st.columns([1, 1.2, 1.4, 1.4])
    with f1:
        lookback = st.selectbox("Okres [dni]", [7, 30, 90, 365], index=1)
    with f2:
        min_drop = st.slider("Minimalna przecena [%]", 0.0, 25.0, 0.5, 0.5)
    with f3:
        present_only = st.checkbox("Tylko w ostatnim katalogu", value=True)
    with f4:
        avail_only = st.checkbox("Tylko obecnie dostępne", value=True)

    events = price_drop_events(
        history, ranking, days=lookback,
        min_drop_pct=min_drop, current_only=present_only,
        available_only=avail_only,
    )
    if events.empty:
        st.info(
            "W wybranym okresie i przy podanych filtrach nie znaleziono przecen. "
            "To poprawny rezultat również wtedy, gdy wszystkie ceny pozostają stałe."
        )
    else:
        biggest = events.sort_values("drop_pct", ascending=False).iloc[0]
        k1, k2, k3 = st.columns(3)
        k1.metric("Wykryte przeceny (zdarzenia)", len(events))
        k2.metric("Produkty z przeceną", events["source_url"].nunique())
        k3.metric("Największy spadek", f"{biggest['drop_pct']:.2f}%")
        st.caption("Jedno źródło URL może mieć wiele osobnych zdarzeń przeceny w tym okresie.")
        drops_view = events.rename(columns={
            "title": "Panel", "observed_at": "Data przeceny",
            "previous_price_pln": "Było [zł]", "price_pln": "Jest [zł]",
            "drop_pln": "Spadek [zł]", "drop_pct": "Spadek [%]",
            "source_url": "Sklep",
        })
        st.dataframe(
            drops_view[["Data przeceny", "Panel", "Było [zł]", "Jest [zł]", "Spadek [zł]", "Spadek [%]", "Sklep"]],
            hide_index=True, width="stretch", height=420,
            column_config={
                "Data przeceny": st.column_config.DatetimeColumn(format="DD.MM.YYYY HH:mm"),
                "Sklep": st.column_config.LinkColumn(display_text="Oferta ↗"),
                "Było [zł]": st.column_config.NumberColumn(format="%.2f"),
                "Jest [zł]": st.column_config.NumberColumn(format="%.2f"),
                "Spadek [zł]": st.column_config.NumberColumn(format="%.2f"),
                "Spadek [%]": st.column_config.NumberColumn(format="%.2f"),
            },
        )
        st.download_button(
            "↓ Eksportuj przeceny (CSV)",
            data=events.to_csv(index=False).encode("utf-8-sig"),
            file_name="pv_price_drops.csv", mime="text/csv",
        )
        st.caption("To zmiany cen ofertowych, a nie potwierdzone rabaty lub promocje sklepu.")

with compare_tab:
    st.subheader("Porównanie produktów")
    st.caption("Wybierz od 2 do 5 paneli z najnowszego katalogu. Wykres bazuje na rzeczywistych pomiarach historycznych.")
    option_urls = ranking["source_url"].dropna().drop_duplicates().tolist()
    latest_names = dict(zip(ranking["source_url"], ranking["title"]))
    default_urls = ranking.loc[ranking["is_available"].eq(True), "source_url"].head(3).tolist()
    chosen = st.multiselect(
        "Porównywane panele", options=option_urls, default=default_urls,
        format_func=lambda url: f"{str(latest_names.get(url, url)).removeprefix('Panel fotowoltaiczny ')} · {url.rstrip('/').split('/')[-1]}",
        max_selections=5,
    )
    if len(chosen) < 2:
        st.info("Wybierz co najmniej dwa panele, aby uruchomić porównanie.")
    else:
        metric_choice = st.radio("Porównuj", ["Cena za wat [zł/W]", "Cena panelu [zł]"], horizontal=True)
        metric_col = "pln_per_watt" if metric_choice.startswith("Cena za wat") else "price_pln"
        one_day = st.checkbox("Ostatni pomiar każdego dnia", value=True, key="compare_daily")
        st.plotly_chart(
            product_comparison_chart(history, chosen, latest_names, metric=metric_col, daily=one_day),
            width="stretch", key="comparison_chart",
            alt="Porównanie historycznych cen wybranych paneli w rzeczywistych datach pomiaru.",
        )
        snapshot = latest_prices_for_comparison(ranking, chosen)
        st.markdown("#### Parametry w ostatnim wsadzie")
        st.dataframe(
            snapshot[["title", "power_w", "price_pln", "pln_per_watt", "is_available", "source_url"]],
            hide_index=True, width="stretch",
            column_config={
                "title": st.column_config.TextColumn("Panel"),
                "power_w": st.column_config.NumberColumn("Moc [W]", format="%d"),
                "price_pln": st.column_config.NumberColumn("Cena [zł]", format="%.2f"),
                "pln_per_watt": st.column_config.NumberColumn("zł/W", format="%.4f"),
                "is_available": st.column_config.CheckboxColumn("Dostępny"),
                "source_url": st.column_config.LinkColumn("Sklep", display_text="Oferta ↗"),
            },
        )
        st.caption("Brak punktu na wykresie oznacza brak pomiaru; nie przyjmujemy, że cena była wtedy stała.")

with history_tab:
    st.subheader("Historia cen produktu")
    labels = latest_product_labels(history)
    if not labels:
        st.info("Brak historycznych obserwacji w modelu gold.product_price_history.")
    else:
        urls = sorted(labels, key=lambda url: str(labels[url]).casefold())
        top_url = ranking.loc[ranking["is_available"].eq(True), "source_url"].head(1).tolist()
        initial_index = urls.index(top_url[0]) if top_url and top_url[0] in urls else 0
        selected_url = st.selectbox(
            "Produkt (również wycofane z obecnego katalogu)",
            options=urls,
            index=initial_index,
            format_func=lambda url: f"{labels[url]} · ID {url.rstrip('/').split('/')[-1]}",
        )
        product = product_history(history, selected_url)
        summary = product_summary(product)
        c1, c2, c3 = st.columns(3)
        c1.metric("Ostatnia cena", f"{summary['current_price']:.2f} zł" if summary["current_price"] is not None else "—")
        c2.metric("Zmiana od pierwszego pomiaru", f"{summary['difference_pln']:+.2f} zł" if summary["difference_pln"] is not None else "—")
        c3.metric("Liczba obserwacji", str(summary["observations"]))
        if summary["difference_pln"] == 0 and summary["observations"] > 1:
            st.info("Cena tego produktu nie zmieniła się między pierwszym a ostatnim pomiarem. Płaska linia jest prawidłowa.")

        one_per_day = st.checkbox("Na wykresach pokazuj tylko ostatnią obserwację z każdego dnia", value=False)
        plotted = latest_observation_per_day(product) if one_per_day else product
        left, right = st.columns(2, gap="medium")
        with left:
            st.plotly_chart(
                price_series(plotted, date_col="observed_at", value_col="price_pln",
                             title="Cena produktu · PLN", suffix="zł", color=BLUE),
                width="stretch", key="history_price", alt="Cena produktu w kolejnych rzeczywistych pomiarach.",
            )
        with right:
            st.plotly_chart(
                price_series(plotted, date_col="observed_at", value_col="pln_per_watt",
                             title="Cena za wat · zł/W", suffix="zł/W", color=TEAL),
                width="stretch", key="history_ratio", alt="Cena za wat w kolejnych rzeczywistych pomiarach.",
            )
        with st.expander("Tabela wszystkich pomiarów", expanded=False):
            st.dataframe(
                product[["observed_at", "price_pln", "previous_price_pln", "price_change_pln", "price_change_pct", "is_available"]]
                .sort_values("observed_at", ascending=False),
                hide_index=True, width="stretch",
            )
        st.link_button("Otwórz produkt w sklepie ↗", selected_url)
        st.caption("Zmiana ceny porównuje pierwszy i ostatni pomiar; przy kilku pomiarach dziennie pełna historia pozostaje dostępna w tabeli.")

with market_tab:
    st.subheader("Trendy rynku")
    st.info(
        "Średnie dotyczą ofert dostępnych w danym dziennym koszyku, nie stałej grupy paneli. "
        "Zmiana liczby produktów w katalogu może zmienić średnią bez przeceny lub podwyżki konkretnych ofert."
    )
    if daily.empty:
        st.warning("Model gold.daily_market_prices nie ma jeszcze obserwacji dostępnych ofert.")
    else:
        left, right = st.columns(2, gap="medium")
        with left:
            st.plotly_chart(price_series(
                daily, date_col="observation_date", value_col="avg_pln_per_watt",
                title="Średnia cena · zł/W", suffix="zł/W", color=BLUE),
                width="stretch", key="market_price",
                alt="Średnia cena za wat w dniach pomiarów.")
        with right:
            st.plotly_chart(daily_count_chart(daily), width="stretch", key="market_count",
                            alt="Liczba ofert dostępnych w dniach pomiarów.")
        st.markdown("#### Dzienne statystyki")
        st.dataframe(
            daily.sort_values("observation_date", ascending=False),
            width="stretch", hide_index=True,
            column_config={
                "observation_date": st.column_config.DateColumn("Dzień", format="DD.MM.YYYY"),
                "available_panels": st.column_config.NumberColumn("Dostępne", format="%d"),
                "avg_price_pln": st.column_config.NumberColumn("Śr. cena [zł]", format="%.2f"),
                "avg_pln_per_watt": st.column_config.NumberColumn("Śr. zł/W", format="%.4f"),
                "min_pln_per_watt": st.column_config.NumberColumn("Min. zł/W", format="%.4f"),
                "max_pln_per_watt": st.column_config.NumberColumn("Max. zł/W", format="%.4f"),
            },
        )
        st.caption("Słupki reprezentują wyłącznie dni z pomiarami; nie interpolujemy brakujących dni.")

with quality_tab:
    st.subheader("Monitoring jakości danych")
    st.caption(
        "Odczyt ostatnich 80 wykonań z Bronze. Stan jakości i anomalia wielkości katalogu "
        "to osobne sygnały; spadek liczby ofert sam w sobie nie oznacza błędnego scrapingu."
    )
    try:
        runs = evaluate_runs(get_run_quality(), drop_warning_pct=30.0)
    except Exception as exc:
        st.warning("Nie mogę pobrać historii wykonań z Bronze. Pozostałe zakładki korzystają dalej z Gold.")
        with st.expander("Szczegóły połączenia / uprawnień"):
            st.exception(exc)
    else:
        if runs.empty:
            st.info("Brak wpisów w bronze.scrape_runs.")
        else:
            latest_run = runs.iloc[0]
            succeeded = runs.loc[runs["status"].eq("SUCCESS")]
            q1, q2, q3, q4 = st.columns(4)
            q1.metric("Ostatni status", str(latest_run["status"]))
            q2.metric("Ostatni test jakości", str(latest_run["quality_status"]))
            q3.metric("Błędne SUCCESS", int(succeeded["quality_status"].eq("FAIL").sum()))
            q4.metric("Spadki ofert ≥30%", int(runs["volume_warning"].sum()))

            if latest_run["quality_status"] == "FAIL":
                st.error("Ostatni run ma status SUCCESS, ale nie spełnia warunków integralności danych.")
            elif latest_run["quality_status"] == "PASS":
                st.success("Ostatni udany scraping przeszedł sprawdzenie liczby rekordów, URL-i i duplikatów.")
            else:
                st.info("Ostatni run nie ma statusu SUCCESS — sprawdź zadania Airflow.")

            if runs["volume_warning"].any():
                st.warning(
                    "W historii wykryto spadek liczby unikalnych ofert o co najmniej 30% "
                    "względem poprzedniego SUCCESS. To wskazówka do zbadania katalogu, nie automatyczny FAIL."
                )

            st.markdown("#### Historia kontroli")
            st.dataframe(
                runs[[
                    "started_at", "status", "quality_status", "expected_count",
                    "actual_count", "missing_urls", "duplicate_urls",
                    "drop_pct_vs_previous_success", "volume_warning", "scrape_run_id",
                ]].rename(columns={
                    "started_at": "Początek", "status": "Run",
                    "quality_status": "Jakość", "expected_count": "Oczekiwane",
                    "actual_count": "Zapisane", "missing_urls": "Brak URL",
                    "duplicate_urls": "Duplikaty URL", "drop_pct_vs_previous_success": "Spadek [%]",
                    "volume_warning": "Ostrzeżenie", "scrape_run_id": "Run ID",
                }),
                hide_index=True, width="stretch", height=450,
                column_config={
                    "Początek": st.column_config.DatetimeColumn(format="DD.MM.YYYY HH:mm"),
                    "Spadek [%]": st.column_config.NumberColumn(format="%.1f"),
                    "Ostrzeżenie": st.column_config.CheckboxColumn(),
                },
            )
            st.caption(
                "FAIL: 0 rekordów, rozbieżność liczby, brakujące URL lub powtórzone URL. "
                "Porównanie liczności używa kolejnych runów oznaczonych SUCCESS, nawet jeśli historycznie "
                "nie przeszły kontroli integralności."
            )

# STAGE11.3-TECHNICAL-TAB
with technical_tab:
    render_technical_tab()


st.divider()
st.caption(
    "Źródło: publiczne oferty Soltech. PLN/W odnosi się do znamionowej mocy panelu, nie jego produkcji energii. "
    "Status ceny brutto/netto nie został niezależnie zweryfikowany."
)
