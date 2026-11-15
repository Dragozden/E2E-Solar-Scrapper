"""Technical data tab — optional, read-only, safe for sparse enrichment."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.technical_db import load_technical_comparison
from dashboard.technical import (
    RANGE_FIELDS, TECHNICAL_LABELS, filter_technical, safe_datasheet_url,
    technical_comparison, technical_coverage,
)


@st.cache_data(ttl=300, show_spinner="Pobieram parametry techniczne paneli...")
def technical_data() -> pd.DataFrame:
    return load_technical_comparison()


def clear_technical_cache() -> None:
    technical_data.clear()


TABLE_FIELDS = [
    "overall_rank", "title", "price_pln", "catalog_power_w", "pln_per_watt",
    "efficiency_pct", "voc_v", "vmp_v", "isc_a", "imp_a", "area_m2",
    "power_density_w_m2", "technical_status", "source_url", "datasheet_url",
]
DISPLAY_FIELDS = {
    "efficiency_pct": "Sprawność [%]",
    "voc_v": "Voc [V]",
    "vmp_v": "Vmp [V]",
    "isc_a": "Isc [A]",
    "imp_a": "Imp [A]",
}
COMPARE_FIELDS = [
    ("Cena [zł]", "price_pln"),
    ("Moc katalogowa [W]", "catalog_power_w"),
    ("Moc techniczna [W]", "technical_power_w"),
    ("Cena za wat [zł/W]", "pln_per_watt"),
    ("Sprawność [%]", "efficiency_pct"),
    ("Voc [V]", "voc_v"),
    ("Vmp [V]", "vmp_v"),
    ("Isc [A]", "isc_a"),
    ("Imp [A]", "imp_a"),
    ("Bifacjalność [%]", "bifaciality_pct"),
    ("Powierzchnia [m²]", "area_m2"),
    ("Moc na m² [W/m²]", "power_density_w_m2"),
    ("Masa [kg]", "mass_kg"),
    ("Gwarancja produktu [lata]", "product_warranty_years"),
    ("Gwarancja mocy [lata]", "performance_warranty_years"),
]


def _slider_range(frame: pd.DataFrame, field: str) -> tuple[float, float] | None:
    values = pd.to_numeric(frame[field], errors="coerce").dropna()
    if values.empty:
        st.caption(f"{DISPLAY_FIELDS[field]}: brak wartości")
        return None
    bottom = float(values.min())
    top = float(values.max())
    if abs(top - bottom) < 0.001:
        st.caption(f"{DISPLAY_FIELDS[field]}: {bottom:.2f} (jedna wartość)")
        return (bottom - 0.001, top + 0.001)
    return st.slider(
        DISPLAY_FIELDS[field], min_value=bottom, max_value=top,
        value=(bottom, top), key=f"tech_filter_{field}",
    )


def render_technical_tab() -> None:
    st.subheader("Parametry techniczne paneli fotowoltaicznych")
    st.caption("Aktualne ceny z ostatniego udanego katalogu + ostatnia zapisana specyfikacja danego URL. "
               "Dane techniczne i cena mogą pochodzić z różnych dni.")
    try:
        frame = technical_data()
    except Exception as exc:
        st.warning("Nie można odczytać gold.panel_technical_comparison. "
                   "Pozostałe zakładki dashboardu działają niezależnie.")
        st.caption("Sprawdź dbt build i uprawnienia SELECT dla solar_dashboard.")
        with st.expander("Diagnostyka (bez danych logowania)"):
            st.code(type(exc).__name__)
        return

    if frame.empty:
        st.info("Najnowszy katalog nie zawiera obecnie ofert.")
        return

    metrics = technical_coverage(frame)
    one, two, three, four = st.columns(4, gap="small")
    one.metric("Oferty", metrics["total"])
    two.metric("Pobrane specyfikacje", metrics["enriched"])
    three.metric("Poprawne i porównywalne", metrics["comparable"])
    four.metric("Pokrycie techniczne", f"{metrics['coverage_pct']:.1f}%")
    st.progress(metrics["coverage_pct"] / 100.0)
    st.caption("PASS: {pass_count} · INCOMPLETE: {incomplete} · REVIEW: {review} · "
               "POWER_MISMATCH: {mismatch} · NOT_ENRICHED: {missing}".format(
                   pass_count=metrics["PASS"], incomplete=metrics["INCOMPLETE"],
                   review=metrics["REVIEW"], mismatch=metrics["POWER_MISMATCH"],
                   missing=metrics["NOT_ENRICHED"]))

    first, second, third = st.columns([1.35, 0.85, 1.6], gap="medium")
    with first:
        mode = st.selectbox("Zakres danych", (
            "Tylko porównywalne", "Wszystkie oferty", "Do uzupełnienia"), key="tech_mode")
    with second:
        available = st.checkbox("Tylko dostępne", value=True, key="tech_available")
    with third:
        search = st.text_input("Szukaj modelu lub producenta", placeholder="np. LONGi, TW Solar",
                               key="tech_search")

    ranges = {}
    with st.expander("Filtry liczbowe (Voc / Vmp / Isc / Imp / sprawność)"):
        apply_numeric = st.checkbox("Włącz filtry liczbowe (brak danych = poza filtrem)",
                                    value=False, key="tech_apply_ranges")
        if apply_numeric:
            # Use qualified specs only to derive slider bounds; otherwise an
            # incomplete product could drive a misleading numeric range.
            qualified = frame.loc[frame["is_technical_comparable"].eq(True)]
            filter_columns = st.columns(2)
            for index, field in enumerate(RANGE_FIELDS):
                with filter_columns[index % 2]:
                    bounds = _slider_range(qualified, field)
                    if bounds is not None:
                        ranges[field] = bounds

    shown = filter_technical(frame, mode=mode, available_only=available,
                             search=search, ranges=ranges)
    st.write(f"**{len(shown)} ofert** spełnia wybrane kryteria")
    if shown.empty:
        st.info("Brak produktów dla obecnych filtrów. Możesz wybrać „Wszystkie oferty”.")
    else:
        table = shown[TABLE_FIELDS].copy()
        table["technical_status"] = table["technical_status"].map(TECHNICAL_LABELS).fillna("Nieznany")
        table["datasheet_url"] = table["datasheet_url"].map(safe_datasheet_url)
        st.dataframe(
            table, hide_index=True, width="stretch", height=455,
            column_config={
                "overall_rank": st.column_config.NumberColumn("#", format="%d"),
                "title": st.column_config.TextColumn("Panel", width="large"),
                "price_pln": st.column_config.NumberColumn("Cena [zł]", format="%.2f"),
                "catalog_power_w": st.column_config.NumberColumn("Moc [W]", format="%.0f"),
                "pln_per_watt": st.column_config.NumberColumn("zł/W", format="%.4f"),
                "efficiency_pct": st.column_config.NumberColumn("Sprawność [%]", format="%.2f"),
                "voc_v": st.column_config.NumberColumn("Voc [V]", format="%.2f"),
                "vmp_v": st.column_config.NumberColumn("Vmp [V]", format="%.2f"),
                "isc_a": st.column_config.NumberColumn("Isc [A]", format="%.2f"),
                "imp_a": st.column_config.NumberColumn("Imp [A]", format="%.2f"),
                "area_m2": st.column_config.NumberColumn("Pow. [m²]", format="%.3f"),
                "power_density_w_m2": st.column_config.NumberColumn("W/m²", format="%.1f"),
                "technical_status": st.column_config.TextColumn("Dane techniczne"),
                "source_url": st.column_config.LinkColumn("Sklep", display_text="Oferta ↗"),
                "datasheet_url": st.column_config.LinkColumn("PDF", display_text="Karta ↗"),
            },
        )
        csv = shown[TABLE_FIELDS].copy()
        csv["datasheet_url"] = csv["datasheet_url"].map(safe_datasheet_url)
        st.download_button("Eksport widocznych ofert (CSV)",
                           data=csv.to_csv(index=False).encode("utf-8-sig"),
                           file_name="pv_technical_comparison.csv", mime="text/csv",
                           key="tech_export", width="content")

    st.divider()
    st.markdown("#### Porównaj dwa do pięciu paneli z poprawną specyfikacją")
    complete = frame.loc[frame["is_technical_comparable"].eq(True)].copy()
    if len(complete) < 2:
        st.info("Potrzebujemy co najmniej dwóch poprawnych specyfikacji do porównania.")
    else:
        labels = dict(zip(complete["source_url"], complete["title"]))
        urls = complete["source_url"].tolist()
        selected = st.multiselect(
            "Panele", options=urls, default=urls[:2], max_selections=5,
            format_func=lambda url: labels.get(url, url), key="tech_compare_urls",
        )
        if len(selected) >= 2:
            compared = technical_comparison(frame, selected)
            matrix = compared.set_index("title")[[field for _, field in COMPARE_FIELDS]].T
            matrix.index = [label for label, _ in COMPARE_FIELDS]
            st.dataframe(matrix, width="stretch", height=480)
            st.caption("Parametry elektryczne podane są dla warunków katalogowych STC. "
                       "Nie zastępują sprawdzenia zakresów napięcia/prądu falownika, "
                       "temperatury i dokumentacji producenta.")
        else:
            st.caption("Zaznacz minimum dwa panele.")
