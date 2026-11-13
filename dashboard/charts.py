"""Small Plotly charts fed exclusively by Gold data.

Only real observation dates are shown; missing days are not synthesized.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

BLUE = "#5BA9F7"
TEAL = "#27C1AF"


def _base(title: str, *, height: int = 270) -> go.Figure:
    fig = go.Figure()
    fig.update_layout(
        title=dict(text=title, font=dict(size=15)),
        height=height,
        margin=dict(l=12, r=12, t=46, b=16),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
        hovermode="x unified",
        font=dict(size=12),
    )
    fig.update_xaxes(showgrid=False, showline=False, zeroline=False, automargin=True)
    fig.update_yaxes(gridcolor="rgba(150,160,175,0.16)", zeroline=False, automargin=True)
    return fig


def _tick_observations(fig: go.Figure, times: pd.Series, *, max_ticks: int = 7) -> None:
    """Use only the actual measurements as readable date ticks."""
    times = pd.to_datetime(times, errors="coerce").dropna().drop_duplicates().sort_values()
    if times.empty:
        return
    if len(times) > max_ticks:
        indices = sorted(set(round(i * (len(times) - 1) / (max_ticks - 1)) for i in range(max_ticks)))
        times = times.iloc[indices]
    fig.update_xaxes(
        tickmode="array",
        tickvals=times.tolist(),
        ticktext=times.dt.strftime("%d %b").tolist(),
    )


def price_series(df: pd.DataFrame, *, date_col: str, value_col: str,
                 title: str, suffix: str, color: str = BLUE, height: int = 270) -> go.Figure:
    """Plot a time series with markers on *real* observations only."""
    data = df[[date_col, value_col]].copy()
    data[date_col] = pd.to_datetime(data[date_col], errors="coerce")
    data[value_col] = pd.to_numeric(data[value_col], errors="coerce")
    data = data.dropna().sort_values(date_col)

    fig = _base(title, height=height)
    if data.empty:
        fig.add_annotation(text="Brak danych", showarrow=False)
        return fig

    fig.add_trace(go.Scatter(
        x=data[date_col], y=data[value_col],
        mode="lines+markers",
        line=dict(color=color, width=2.5),
        marker=dict(color=color, size=8),
        hovertemplate=f"%{{x|%d.%m.%Y %H:%M}}<br>%{{y:.4f}} {suffix}<extra></extra>",
        connectgaps=False,
    ))
    _tick_observations(fig, data[date_col])
    fig.update_yaxes(ticksuffix=f" {suffix}", tickformat=".2f" if suffix == "zł" else ".3f")
    return fig


def daily_count_chart(daily: pd.DataFrame, *, height: int = 270) -> go.Figure:
    data = daily[["observation_date", "available_panels"]].copy()
    data["observation_date"] = pd.to_datetime(data["observation_date"], errors="coerce")
    data["available_panels"] = pd.to_numeric(data["available_panels"], errors="coerce")
    data = data.dropna().sort_values("observation_date")
    fig = _base("Dostępne oferty · dni pomiarowe", height=height)
    if data.empty:
        fig.add_annotation(text="Brak danych", showarrow=False)
        return fig
    fig.add_trace(go.Bar(
        x=data["observation_date"].dt.strftime("%d.%m.%Y"), y=data["available_panels"],
        marker_color=TEAL,
        hovertemplate="%{x}<br>%{y:.0f} ofert<extra></extra>",
    ))
    # Categorical axis deliberately avoids tiny bars across unobserved days.
    fig.update_xaxes(type="category", tickangle=0)
    fig.update_yaxes(rangemode="tozero", tickformat=",.0f")
    return fig


def top_value_chart(ranking: pd.DataFrame, *, n: int = 7) -> go.Figure:
    data = (
        ranking.loc[ranking["is_available"].eq(True)]
        .sort_values("pln_per_watt").head(n).copy()
    )
    fig = _base("Najtańsze dostępne panele · zł/W", height=310)
    if data.empty:
        fig.add_annotation(text="Brak ofert", showarrow=False)
        return fig
    data["short_title"] = data["title"].astype(str).str.replace(
        r"^Panel fotowoltaiczny\s+", "", regex=True
    ).str.slice(0, 38)
    fig.add_trace(go.Bar(
        x=data["pln_per_watt"], y=data["short_title"], orientation="h",
        marker_color=BLUE,
        customdata=data["title"],
        hovertemplate="%{customdata}<br>%{x:.4f} zł/W<extra></extra>",
    ))
    fig.update_layout(margin=dict(l=12, r=20, t=46, b=20))
    fig.update_yaxes(autorange="reversed", showgrid=False)
    fig.update_xaxes(tickformat=".2f", rangemode="tozero", showgrid=True)
    return fig


def price_power_scatter(ranking: pd.DataFrame) -> go.Figure:
    """All available latest-snapshot offers: compare total PLN and nominal W."""
    data = ranking.loc[ranking["is_available"].eq(True)].copy()
    fig = _base("Moc vs cena · dostępne oferty", height=310)
    if data.empty:
        fig.add_annotation(text="Brak ofert", showarrow=False)
        return fig
    fig.add_trace(go.Scatter(
        x=data["power_w"],
        y=data["price_pln"],
        mode="markers",
        marker=dict(size=10, color=TEAL, opacity=0.75, line=dict(width=0)),
        customdata=data[["title", "pln_per_watt"]].to_numpy(),
        hovertemplate=("%{customdata[0]}<br>Moc: %{x:.0f} W"
                       "<br>Cena: %{y:.2f} zł<br>%{customdata[1]:.4f} zł/W<extra></extra>"),
    ))
    fig.update_xaxes(title="Moc [W]")
    fig.update_yaxes(title="Cena [zł]", tickformat=".0f")
    return fig


def product_comparison_chart(
    history: pd.DataFrame,
    urls: list[str],
    labels: dict[str, str],
    *,
    metric: str = "pln_per_watt",
    daily: bool = True,
) -> go.Figure:
    """Compare up to 5 products using actual observation dates only."""
    from dashboard.analytics import latest_observation_per_day

    choices = {
        "pln_per_watt": ("Cena za wat", "zł/W"),
        "price_pln": ("Cena", "zł"),
    }
    if metric not in choices:
        raise ValueError(f"Unknown comparison metric: {metric}")
    if len(urls) > 5:
        raise ValueError("Select at most five products")

    title, unit = choices[metric]
    fig = _base(f"Porównanie · {title.lower()} [{unit}]", height=380)
    fig.update_layout(showlegend=True, hovermode="closest", legend=dict(orientation="h", y=-0.25))
    palette = [BLUE, TEAL, "#f59e0b", "#c084fc", "#fb7185"]

    all_times = []
    for i, url in enumerate(urls):
        values = history.loc[history["source_url"].eq(url)].copy()
        values["observed_at"] = pd.to_datetime(values["observed_at"], errors="coerce")
        values[metric] = pd.to_numeric(values[metric], errors="coerce")
        values = values.dropna(subset=["observed_at", metric]).sort_values(["observed_at", "scrape_id"])
        if daily:
            values = latest_observation_per_day(values)
        if values.empty:
            continue
        all_times.extend(values["observed_at"].tolist())
        short_name = str(labels.get(url, url)).removeprefix("Panel fotowoltaiczny ")[:34]
        fig.add_trace(go.Scatter(
            x=values["observed_at"], y=values[metric],
            mode="lines+markers", name=short_name,
            line=dict(width=2, color=palette[i]), marker=dict(size=7),
            hovertemplate=f"%{{x|%d.%m.%Y %H:%M}}<br>%{{y:.4f}} {unit}<extra>%{{fullData.name}}</extra>",
            connectgaps=False,
        ))
    if not all_times:
        fig.add_annotation(text="Brak pomiarów dla wybranych produktów", showarrow=False)
    else:
        _tick_observations(fig, pd.Series(all_times))
    return fig
