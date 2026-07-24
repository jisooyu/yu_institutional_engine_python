"""Institutional Flow Engine — live Python/Dash dashboard."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from dash import Dash, Input, Output, State, callback, dcc, html, no_update
import plotly.graph_objects as go

from market_data import PERIOD_LENGTH, _fallback, fetch_snapshot, period_slice


APP_TITLE = "Institutional Flow — Live Rotation Intelligence"
ACCENT = "#b6f36a"
RED = "#ff6b70"
AMBER = "#e8a75b"
MUTED = "#69757a"
GRID = "#20282b"


def label(text: str) -> html.P:
    return html.P(text, className="eyebrow")


def badge(text: str, positive: bool = True, element_id: str | None = None) -> html.Span:
    return html.Span(text, id=element_id, className=f"badge {'positive' if positive else 'warning'}")


def card_header(kicker: str, title: str, extra=None, kicker_id: str | None = None, title_id: str | None = None) -> html.Div:
    kicker_element = html.P(kicker, id=kicker_id, className="eyebrow") if kicker_id else label(kicker)
    title_element = html.H2(title, id=title_id) if title_id else html.H2(title)
    return html.Div([html.Div([kicker_element, title_element]), extra], className="card-head")


def base_figure(height: int = 220) -> dict[str, Any]:
    return {
        "height": height,
        "margin": {"l": 36, "r": 14, "t": 8, "b": 26},
        "paper_bgcolor": "rgba(0,0,0,0)", "plot_bgcolor": "rgba(0,0,0,0)",
        "font": {"family": "IBM Plex Mono, monospace", "color": MUTED, "size": 9},
        "xaxis": {"showgrid": True, "gridcolor": "#161d20", "zeroline": False},
        "yaxis": {"showgrid": True, "gridcolor": GRID, "zeroline": False, "side": "right"},
        "showlegend": False, "hovermode": "x unified",
    }


def empty_figure(message: str = "Waiting for market data") -> go.Figure:
    figure = go.Figure()
    figure.update_layout(**base_figure())
    figure.add_annotation(text=message, showarrow=False, font={"color": MUTED, "size": 11})
    return figure


def relative_strength_figure(snapshot: dict, period: str, pair: str) -> go.Figure:
    series = snapshot.get("rs", {}).get(pair)
    if not series:
        return empty_figure()
    dates, values = period_slice(series, period)
    if not values:
        return empty_figure()
    average = []
    for index in range(len(values)):
        window = values[max(0, index - 4): index + 1]
        average.append(sum(window) / len(window))
    figure = go.Figure()
    figure.add_trace(go.Scatter(
        x=dates, y=values, mode="lines", name=pair,
        line={"color": ACCENT, "width": 2.5},
    ))
    figure.add_trace(go.Scatter(
        x=dates, y=average, mode="lines", name="5D Avg",
        line={"color": "#647176", "width": 1, "dash": "dot"},
    ))
    figure.update_layout(**base_figure(220))
    low, high = min(values), max(values)
    padding = max((high - low) * 0.18, abs(high) * 0.0025, 0.001)
    figure.update_yaxes(range=[low - padding, high + padding], tickformat=".4f")
    figure.update_xaxes(type="category", nticks=min(len(dates), 6))
    return figure


def volume_figure(volume: dict) -> go.Figure:
    values = volume.get("values", [])
    if not values:
        return empty_figure()
    colors = ["#3c484d"] * len(values)
    colors[-1] = ACCENT
    figure = go.Figure(go.Bar(x=list(range(len(values))), y=values, marker_color=colors))
    layout = base_figure(170)
    layout["margin"] = {"l": 6, "r": 8, "t": 8, "b": 8}
    figure.update_layout(**layout)
    figure.update_xaxes(visible=False)
    figure.update_yaxes(visible=False)
    return figure


def rotation_figure(snapshot: dict, view: str) -> go.Figure:
    rows = snapshot.get("rotation", [])
    if not rows:
        return empty_figure()
    names = [row["name"] for row in rows]
    momentum = [row["momentum"] for row in rows]
    scores = [row["score"] for row in rows]
    colors = [ACCENT if value >= 0 else RED for value in momentum]
    figure = go.Figure()
    if view == "rank":
        figure.add_trace(go.Bar(
            x=momentum[::-1], y=names[::-1], orientation="h", marker_color=colors[::-1],
            text=[f"{value:+.1f}%" for value in momentum[::-1]], textposition="outside", cliponaxis=False,
        ))
        layout = base_figure(255)
        layout["margin"] = {"l": 76, "r": 48, "t": 4, "b": 24}
        figure.update_layout(**layout)
    else:
        figure.add_trace(go.Scatter(
            x=scores, y=momentum, mode="markers+text", text=names, textposition="top center",
            marker={"size": [33 + min(abs(value), 10) * 2 for value in momentum], "color": colors, "opacity": .78, "line": {"color": "#101416", "width": 2}},
            hovertemplate="%{text}<br>RS %{x:.1f}<br>20D excess %{y:+.1f}%<extra></extra>",
        ))
        layout = base_figure(255)
        layout["margin"] = {"l": 38, "r": 12, "t": 18, "b": 32}
        figure.update_layout(**layout)
        figure.update_xaxes(title="RELATIVE STRENGTH", range=[30, 100])
        figure.update_yaxes(title="20D EXCESS RETURN")
        figure.add_vline(x=70, line_width=1, line_dash="dot", line_color="#344044")
        figure.add_hline(y=0, line_width=1, line_dash="dot", line_color="#344044")
    return figure


def sector_options(snapshot: dict) -> list[dict]:
    return [
        {"label": html.Span([
            html.I(item["ticker"][:2]),
            html.Span([html.B(item["name"]), html.Small(item["ticker"])]),
            html.Em(str(item["score"])),
        ]), "value": item["name"]}
        for item in snapshot.get("sectors", [])
    ]


def breadth_row(name: str, value: str, percent: float, positive: bool = True) -> html.Div:
    return html.Div([
        html.Span(name), html.Div(html.I(style={"width": f"{max(0, min(percent, 100)):.0f}%"}, className="good" if positive else "bad")), html.B(value),
    ], className="breadth-row")


def rs_pair_cards(snapshot: dict, period: str, primary_pair: str) -> list[html.Div]:
    cards = []
    period_length = PERIOD_LENGTH.get(period, 22)
    pairs = list(dict.fromkeys([primary_pair, "SOXX / QQQ", "QQQ / SPY", "XLI / SPY", "XLK / SPY"]))[:5]
    for pair in pairs:
        series = snapshot.get("rs", {}).get(pair, {})
        values = series.get("values", [])[-period_length:]
        move = ((values[-1] / values[0] - 1) * 100) if len(values) > 1 else 0.0
        up = move >= 0
        cards.append(html.Div([
            html.Span(pair), html.Small(f"{period} CHANGE"),
            html.B(f"{move:+.2f}%", className="up" if up else "down"),
            html.I(className="pair-line up-line" if up else "pair-line down-line"),
        ]))
    return cards


def etf_rows(snapshot: dict, sector_name: str = "Semiconductor") -> list[html.Div]:
    return [html.Div([
        html.Span(row["ticker"], className="ticker"), html.Span(row["name"], className="fund-name"),
        html.B(row["activity"], className="up" if row["activity"].startswith("+") else "down"),
        html.Em(f"{row['return']:+.2f}%", className="up" if row["return"] >= 0 else "down"),
    ]) for row in snapshot.get("sector_etfs", {}).get(sector_name, [])]


def ai_sparkline_figure(row: dict) -> go.Figure:
    values = row.get("trend", [])
    color = ACCENT if row.get("momentum", 0) >= 0 else RED
    figure = go.Figure()
    if values:
        figure.add_trace(go.Scatter(
            x=list(range(len(values))), y=values, mode="lines",
            line={"color": color, "width": 2}, hoverinfo="skip",
        ))
        figure.add_hline(y=0, line_width=1, line_color="#313a3d")
    figure.update_layout(
        height=34, margin={"l": 1, "r": 1, "t": 2, "b": 2},
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        showlegend=False, xaxis={"visible": False}, yaxis={"visible": False},
    )
    return figure


def leadership_rows(snapshot: dict, sector_name: str = "AI") -> list[html.Div]:
    cards = []
    for index, row in enumerate(snapshot.get("sector_leaders", {}).get(sector_name, [])[:8], 1):
        trend_class = "trend-up" if row.get("momentum", 0) >= 0 else "trend-down"
        leader_class = " relative-leader" if index == 1 else ""
        cards.append(html.Div([
            html.Span([html.Small("ETF WT"), f"{index:02d}"], className="rank", title="Official ETF holding weight rank"),
            html.Div([html.B(row["ticker"]), html.Small(row["name"]), html.Small(f"{row.get('weight', 0):.2f}% weight", className="holding-weight")]),
            html.Div(dcc.Graph(
                figure=ai_sparkline_figure(row), config={"displayModeBar": False, "staticPlot": True},
                className="supply-sparkline",
            ), title="Actual 20-trading-day price trend"),
            html.Div([html.Small("1D"), html.Strong(
                f"{row['move']:+.2f}%", className="up" if row["move"] >= 0 else "down",
            )], className="supply-change"),
            html.Div([html.Small("20D"), html.Em(
                f"{row['momentum']:+.2f}%", className="up" if row["momentum"] >= 0 else "down",
            )], className="supply-change"),
        ], className=f"supply-row {trend_class}{leader_class}"))
    return cards


def top_bar() -> html.Header:
    return html.Header([
        html.Div([html.Span("IF", className="brand-mark"), html.Div([html.Strong("INSTITUTIONAL FLOW"), html.Small("LIVE ROTATION INTELLIGENCE")])], className="brand"),
        html.Div([html.I(className="status-dot"), "LIVE MARKET DATA", html.B("DAILY / EOD")], className="market-status"),
        html.Div([html.Button("⌕", className="icon-button"), html.Button("◌", className="icon-button"), html.Div("JD", className="desk-badge"), html.Div(["J. DOH", html.Br(), html.Span("PORTFOLIO DESK")], className="desk-name")], className="header-actions"),
    ], className="topbar")


def app_layout(initial_snapshot: dict | None = None) -> html.Main:
    initial = initial_snapshot if initial_snapshot is not None else _fallback("Loading live market data…")
    if initial_snapshot is None:
        initial["loading"] = True
    selected_sector = initial.get("sectors", [{}])[0].get("name", "Semiconductor") if initial.get("sectors") else "Semiconductor"
    return html.Main([
        dcc.Store(id="market-store", data=initial),
        dcc.Interval(id="market-bootstrap", interval=500, max_intervals=1),
        top_bar(),
        html.Aside([
            label("SECTOR UNIVERSE"),
            dcc.RadioItems(id="sector-selector", options=sector_options(initial), value=selected_sector, className="sector-selector", inputClassName="sector-input", labelClassName="sector-option"),
            html.Div([
                label("DATA FEED"),
                html.Button(["↻", html.Span(" Refresh Live Data")], id="sidebar-refresh", className="utility", n_clicks=0),
                html.Button(["⚙", html.Span(" Settings")], className="utility"),
                html.Div([html.Span([html.I(className="status-dot"), "YAHOO FINANCE"]), html.B("CONNECTING" if initial.get("loading") else "LIVE" if initial.get("ok") else "ERROR", id="data-health-value"), html.Small(f"{initial.get('coverage', 0)} breadth symbols", id="coverage-label")], className="data-health"),
            ], className="sidebar-bottom"),
        ], className="sidebar"),
        html.Section([
            html.Div([
                html.Div([label("LIVE MARKET OVERVIEW"), html.H1("Institutional Rotation Monitor"), html.P("Detecting capital migration from live daily price and volume data.")]),
                html.Div([html.Span("LIVE DATA", id="feed-badge"), html.Button("↻ Refresh", id="refresh-button", n_clicks=0), html.Small(f"As of {initial.get('as_of', '—')}", id="updated-time")], className="workspace-tools"),
            ], className="workspace-head"),
            html.Div(id="feed-message", className="feed-message"),
            html.Div([
                html.Div([html.P("RISK REGIME"), html.B(id="risk-value"), html.Small(id="risk-note")]),
                html.Div([html.P("INSTITUTIONAL BIAS"), html.B(id="bias-value"), html.Small(id="bias-note")]),
                html.Div([html.P("LEADING SECTOR"), html.B(id="leading-sector"), html.Small(id="leading-note")]),
                html.Div([html.P("MARKET BREADTH"), html.B(id="breadth-value"), html.Small(id="breadth-note")]),
            ], className="signal-strip"),
            dcc.Loading(html.Div([
                html.Section([
                    card_header("RELATIVE STRENGTH", "Leadership Trend", dcc.RadioItems(id="period-selector", options=list(PERIOD_LENGTH), value="1M", inline=True, className="periods", inputClassName="period-input", labelClassName="period-option")),
                    html.Div([html.Div([
                        html.B(id="rs-pair-label"),
                        html.Div([html.Small("CURRENT RATIO"), html.Strong(id="rs-ratio")], className="rs-headline-metric"),
                        html.Div([html.Small(id="rs-change-label"), html.Span(id="rs-change")], className="rs-headline-change"),
                    ]), html.Div([html.I(), html.Span(id="rs-legend-label"), html.I(className="gray"), " 5D AVG"], className="legend")], className="chart-summary"),
                    dcc.Graph(id="relative-strength-chart", config={"displayModeBar": False}, className="main-chart"),
                    html.Div(id="rs-pairs", className="rs-pairs"),
                ], className="card rs-card"),
                html.Section([
                    card_header("VOLUME ANALYSIS", "Participation", badge("LIVE", element_id="volume-badge")),
                    html.Div([html.Div([html.Span(id="volume-symbol"), html.B(id="today-volume"), html.Small(" shares")]), html.Div([html.Span("20D AVG"), html.B(id="average-volume"), html.Small(id="volume-difference")])], className="volume-kpi"),
                    dcc.Graph(id="volume-chart", config={"displayModeBar": False}, className="volume-chart"),
                    html.Div([html.Div([html.Span("VOLUME SPIKE"), html.B(id="volume-spike"), html.Small("Latest ÷ 20D avg")]), html.Div([html.Span("DISTRIBUTION DAYS"), html.B(id="distribution-days", className="warn"), html.Small("Last 25 sessions")])], className="volume-footer"),
                ], className="card volume-card"),
                html.Section([
                    card_header("SECTOR BREADTH", "Semiconductor Internal Health", badge("LIVE SAMPLE", element_id="breadth-badge"), title_id="breadth-title"),
                    html.Div([html.Div([html.Div([html.B(id="gauge-value"), html.Span("PARTICIPATION")])], className="gauge"), html.P(["Official benchmark ETF holdings.", html.Br(), html.Span(id="breadth-coverage"), " holdings with price coverage."])], className="breadth-meter"),
                    html.Div(id="breadth-list", className="breadth-list"),
                ], className="card breadth-card"),
                html.Section([
                    card_header("SECTOR ROTATION", "Momentum Map", dcc.RadioItems(id="rotation-view", options=[{"label":"Map","value":"map"},{"label":"Rank","value":"rank"}], value="map", inline=True, className="periods", inputClassName="period-input", labelClassName="period-option")),
                    dcc.Graph(id="rotation-chart", config={"displayModeBar": False}),
                    html.Div([html.Span("WEAKENING"), html.I(), html.Span("IMPROVING"), html.B("20D excess return × 60D relative strength")], className="rotation-legend"),
                ], className="card rotation-card"),
                html.Section([
                    card_header("SECTOR ETF MONITOR", "Semiconductor ETF Activity", html.Span("SIGNED $ TURNOVER PROXY", className="subtle"), title_id="etf-title"),
                    html.Div([html.Span("ETF"), html.Span("ACTIVITY"), html.Span("RETURN")], className="table-head"), html.Div(id="etf-table", className="etf-table"),
                ], className="card etf-card"),
                html.Section([card_header("SECTOR LEADERSHIP", "Semiconductor Leadership Stack", badge("LIVE PRICES", element_id="ai-badge"), title_id="leadership-title"), html.Div(id="supply-grid", className="supply-grid")], className="card supply-card"),
            ], className="dashboard-grid"), type="circle", color=ACCENT),
            html.Footer([html.Span([html.I(className="status-dot"), "YAHOO FINANCE EOD FEED"]), html.Span("ETF ACTIVITY IS A TURNOVER PROXY · NOT CREATION/REDEMPTION FLOW"), html.Span("INSTITUTIONAL FLOW ENGINE · PYTHON/DASH")]),
        ], className="workspace"),
    ], className="app-shell")


app = Dash(__name__, title=APP_TITLE, update_title=None)
server = app.server
app.layout = app_layout


@callback(
    Output("market-store", "data"),
    Input("refresh-button", "n_clicks"), Input("sidebar-refresh", "n_clicks"), Input("market-bootstrap", "n_intervals"),
    prevent_initial_call=True,
)
def refresh_market_data(_: int, __: int, ___: int) -> dict:
    return fetch_snapshot(force=True)


@callback(
    Output("sector-selector", "options"), Output("risk-value", "children"), Output("risk-note", "children"),
    Output("bias-value", "children"), Output("bias-note", "children"), Output("updated-time", "children"), Output("feed-badge", "children"),
    Output("data-health-value", "children"), Output("coverage-label", "children"), Output("feed-message", "children"),
    Input("market-store", "data"),
)
def render_snapshot(snapshot: dict):
    coverage = snapshot.get("coverage", 0)
    message = snapshot.get("error", "")
    loading = snapshot.get("loading", False)
    return (
        sector_options(snapshot), snapshot.get("risk_regime", "—"), snapshot.get("risk_note", ""),
        snapshot.get("bias", "—"), snapshot.get("bias_note", ""), f"As of {snapshot.get('as_of', '—')}",
        "CONNECTING" if loading else "LIVE DATA" if snapshot.get("ok") else "DATA ERROR",
        "CONNECTING" if loading else "LIVE" if snapshot.get("ok") else "ERROR",
        f"{coverage} breadth symbols", message,
    )


@callback(
    Output("breadth-value", "children"), Output("breadth-note", "children"),
    Output("gauge-value", "children"), Output("breadth-coverage", "children"), Output("breadth-list", "children"),
    Output("etf-table", "children"), Output("supply-grid", "children"),
    Output("breadth-title", "children"), Output("etf-title", "children"), Output("leadership-title", "children"),
    Output("breadth-badge", "children"), Output("ai-badge", "children"),
    Input("sector-selector", "value"), Input("market-store", "data"),
)
def render_sector_panels(sector_name: str, snapshot: dict):
    sector_name = sector_name or "Semiconductor"
    sector_data = snapshot.get("sector_breadth", {}).get(sector_name, {})
    breadth = sector_data.get("metrics", {})
    coverage = sector_data.get("coverage", 0)
    total = sector_data.get("total", coverage)
    breadth_score = sector_data.get("score", 0)
    weighted_score = sector_data.get("weighted_score", 0)
    benchmark = sector_data.get("benchmark_etf", "—")
    holdings_as_of = sector_data.get("holdings_as_of", "Unknown")
    fallback = sector_data.get("holdings_fallback", False)
    leaders = snapshot.get("sector_leaders", {}).get(sector_name, [])
    return (
        f"{breadth_score:.1f}%", f"{benchmark} holdings {coverage}/{total} · weighted {weighted_score:.1f}%",
        f"{breadth_score:.1f}%", f"{coverage}/{total}", [
            breadth_row("52-WEEK HIGH", str(breadth.get("highs", 0)), breadth.get("highs", 0) / max(coverage, 1) * 100),
            breadth_row("52-WEEK LOW", str(breadth.get("lows", 0)), breadth.get("lows", 0) / max(coverage, 1) * 100, False),
            breadth_row("ADVANCE / DECLINE", f"{breadth.get('ad', 0):.2f}", min(breadth.get("ad", 0) / 3 * 100, 100)),
            breadth_row("EQUAL-WT ABOVE 50DMA", f"{breadth.get('above50', 0):.1f}%", breadth.get("above50", 0)),
            breadth_row("ETF-WT ABOVE 50DMA", f"{breadth.get('weighted_above50', 0):.1f}%", breadth.get("weighted_above50", 0)),
            breadth_row("EQUAL-WT ABOVE 200DMA", f"{breadth.get('above200', 0):.1f}%", breadth.get("above200", 0)),
            breadth_row("ETF-WT ABOVE 200DMA", f"{breadth.get('weighted_above200', 0):.1f}%", breadth.get("weighted_above200", 0)),
        ], etf_rows(snapshot, sector_name), leadership_rows(snapshot, sector_name),
        f"{sector_name} · {benchmark} Holdings Health", f"{sector_name} ETF Activity", f"{benchmark} Top Holdings",
        f"{'FALLBACK' if fallback else benchmark} · {holdings_as_of}", f"TOP {min(8, len(leaders))} BY ETF WEIGHT",
    )


@callback(
    Output("leading-sector", "children"), Output("leading-note", "children"),
    Input("sector-selector", "value"), Input("market-store", "data"),
)
def update_sector(sector_name: str, snapshot: dict) -> tuple[str, str]:
    selected = next((item for item in snapshot.get("sectors", []) if item["name"] == sector_name), None)
    return (selected["name"].upper(), f"Score {selected['score']} / 100") if selected else ("—", "No data")


@callback(
    Output("relative-strength-chart", "figure"), Output("rs-ratio", "children"),
    Output("rs-change-label", "children"), Output("rs-change", "children"), Output("rs-pairs", "children"),
    Output("rs-pair-label", "children"), Output("rs-legend-label", "children"),
    Input("period-selector", "value"), Input("market-store", "data"), Input("sector-selector", "value"),
)
def update_relative_strength(period: str, snapshot: dict, sector_name: str):
    selected = next((item for item in snapshot.get("sectors", []) if item["name"] == sector_name), {})
    ticker = selected.get("ticker", "SMH")
    pair = f"{ticker} / SPY"
    series = snapshot.get("rs", {}).get(pair, {})
    _, values = period_slice(series, period) if series else ([], [])
    ratio = values[-1] if values else 0
    change = ((values[-1] / values[0] - 1) * 100) if len(values) > 1 else 0
    return (
        relative_strength_figure(snapshot, period, pair), f"{ratio:.4f}", f"{period} CHANGE",
        html.Span(f"{change:+.2f}%", className="up" if change >= 0 else "down"),
        rs_pair_cards(snapshot, period, pair), pair, f" {pair} ",
    )


@callback(
    Output("volume-symbol", "children"), Output("today-volume", "children"),
    Output("average-volume", "children"), Output("volume-difference", "children"),
    Output("volume-spike", "children"), Output("distribution-days", "children"),
    Output("volume-chart", "figure"),
    Input("sector-selector", "value"), Input("market-store", "data"),
)
def update_sector_volume(sector_name: str, snapshot: dict):
    volume = snapshot.get("sector_volumes", {}).get(sector_name, snapshot.get("volume", {}))
    ticker = volume.get("ticker", "—")
    average = volume.get("average", 0)
    today = volume.get("today", 0)
    difference = ((today / average - 1) * 100) if average else 0
    return (
        f"{ticker} LATEST", f"{today / 1_000_000:.1f}M", f"{average / 1_000_000:.1f}M",
        f"{difference:+.1f}%", f"{volume.get('spike', 0):.2f}×",
        str(volume.get("distribution", 0)), volume_figure(volume),
    )


@callback(Output("rotation-chart", "figure"), Input("rotation-view", "value"), Input("market-store", "data"))
def update_rotation(view: str, snapshot: dict) -> go.Figure:
    return rotation_figure(snapshot, view)


if __name__ == "__main__":
    app.run(debug=False, host="127.0.0.1", port=8055)
