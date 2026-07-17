"""Institutional Flow Engine — Python/Dash implementation.

This application uses deterministic demo data so it can be launched without
market-data credentials. Replace the data functions with a live provider when
you are ready to connect production feeds.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable

import dash
from dash import Dash, Input, Output, State, callback, dcc, html
import plotly.graph_objects as go


APP_TITLE = "Institutional Flow — Rotation Intelligence"
ACCENT = "#b6f36a"
RED = "#ff6b70"
MUTED = "#69757a"
GRID = "#20282b"
PANEL = "#101416"

SECTORS = [
    {"name": "Semiconductor", "ticker": "SMH", "score": 82},
    {"name": "AI", "ticker": "AI", "score": 76},
    {"name": "Software", "ticker": "IGV", "score": 61},
    {"name": "Cyber Security", "ticker": "CIBR", "score": 68},
    {"name": "Power", "ticker": "GRID", "score": 72},
    {"name": "Defense", "ticker": "ITA", "score": 58},
]

RS_SERIES = {
    "1D": [22, 30, 25, 36, 33, 44, 40, 58, 55, 63, 69, 74],
    "1W": [18, 24, 21, 31, 27, 42, 48, 45, 57, 61, 68, 76],
    "1M": [14, 19, 28, 25, 33, 39, 52, 48, 59, 66, 62, 78],
    "3M": [9, 15, 13, 24, 31, 28, 42, 49, 56, 53, 67, 82],
}

RS_PAIRS = [
    ("SMH / SPY", "+8.42%", True),
    ("SOXX / QQQ", "+2.18%", True),
    ("QQQ / SPY", "+4.76%", True),
    ("XLI / SPY", "−1.24%", False),
    ("XLK / SPY", "+6.31%", True),
]

ETF_ROWS = [
    ("SMH", "VanEck Semiconductor", "+$428M", "+3.28%"),
    ("SOXX", "iShares Semiconductor", "+$291M", "+2.84%"),
    ("QQQ", "Invesco QQQ", "+$816M", "+1.62%"),
    ("SPY", "SPDR S&P 500", "+$342M", "+0.71%"),
    ("XLI", "Industrial Select", "−$76M", "−0.42%"),
    ("XLE", "Energy Select", "−$118M", "−1.08%"),
    ("XLV", "Health Care Select", "+$64M", "+0.34%"),
    ("XLF", "Financial Select", "+$155M", "+0.89%"),
]

AI_CHAIN = [
    ("NVDA", "NVIDIA", "+4.82%", 92),
    ("AVGO", "Broadcom", "+3.41%", 86),
    ("TSM", "TSMC", "+2.12%", 79),
    ("MU", "Micron", "+5.26%", 88),
    ("000660", "SK Hynix", "+3.08%", 83),
    ("005930", "Samsung", "+1.24%", 64),
    ("VRT", "Vertiv", "+6.18%", 95),
    ("GEV", "GE Vernova", "+2.76%", 81),
]

ROTATION = [
    ("Semis", 8.4, 91), ("AI Infra", 7.2, 87), ("Power", 5.8, 83),
    ("Cyber", 4.1, 79), ("Software", 2.6, 75), ("Defense", 1.4, 71),
    ("Financials", -0.8, 67), ("Health", -1.3, 63),
    ("Industrials", -2.1, 59), ("Energy", -3.7, 55),
]

VOLUME = [42, 48, 46, 58, 52, 67, 74, 65, 86, 70, 92, 81, 108, 76, 88, 117, 94, 132, 110, 126]


def label(text: str) -> html.P:
    return html.P(text, className="eyebrow")


def badge(text: str, positive: bool = True) -> html.Span:
    return html.Span(text, className=f"badge {'positive' if positive else 'warning'}")


def card_header(kicker: str, title: str, extra=None) -> html.Div:
    return html.Div(
        [html.Div([label(kicker), html.H2(title)]), extra],
        className="card-head",
    )


def base_figure(height: int = 220) -> dict:
    return {
        "height": height,
        "margin": {"l": 36, "r": 14, "t": 8, "b": 26},
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": "rgba(0,0,0,0)",
        "font": {"family": "IBM Plex Mono, monospace", "color": MUTED, "size": 9},
        "xaxis": {"showgrid": True, "gridcolor": "#161d20", "zeroline": False},
        "yaxis": {"showgrid": True, "gridcolor": GRID, "zeroline": False, "side": "right"},
        "showlegend": False,
        "hovermode": "x unified",
    }


def relative_strength_figure(period: str) -> go.Figure:
    values = RS_SERIES.get(period, RS_SERIES["1M"])
    scaled = [0.95 + (value - min(values)) / (max(values) - min(values)) * 0.14 for value in values]
    average = [sum(scaled[max(0, i - 3): i + 1]) / len(scaled[max(0, i - 3): i + 1]) for i in range(len(scaled))]
    figure = go.Figure()
    figure.add_trace(go.Scatter(
        x=list(range(len(scaled))), y=scaled, mode="lines",
        line={"color": ACCENT, "width": 2.5},
        fill="tozeroy", fillcolor="rgba(182,243,106,.07)", name="SMH / SPY",
    ))
    figure.add_trace(go.Scatter(
        x=list(range(len(average))), y=average, mode="lines",
        line={"color": "#647176", "width": 1, "dash": "dot"}, name="50D Avg",
    ))
    figure.update_layout(**base_figure(220))
    figure.update_yaxes(range=[0.93, 1.11], tickformat=".2f")
    figure.update_xaxes(
        tickvals=[0, 3, 6, 9, 11],
        ticktext=["JUN 17", "JUN 24", "JUL 01", "JUL 08", "JUL 16"],
    )
    return figure


def volume_figure() -> go.Figure:
    colors = ["#3c484d"] * len(VOLUME)
    colors[17] = "#e8a75b"
    colors[-2:] = [ACCENT, ACCENT]
    figure = go.Figure(go.Bar(x=list(range(len(VOLUME))), y=VOLUME, marker_color=colors))
    layout = base_figure(170)
    layout["margin"] = {"l": 6, "r": 8, "t": 8, "b": 8}
    figure.update_layout(**layout)
    figure.update_xaxes(visible=False)
    figure.update_yaxes(visible=False)
    return figure


def rotation_figure(view: str) -> go.Figure:
    names = [item[0] for item in ROTATION]
    momentum = [item[1] for item in ROTATION]
    scores = [item[2] for item in ROTATION]
    colors = [ACCENT if value >= 0 else RED for value in momentum]
    figure = go.Figure()
    if view == "rank":
        figure.add_trace(go.Bar(
            x=momentum[::-1], y=names[::-1], orientation="h",
            marker_color=colors[::-1], text=[f"{v:+.1f}%" for v in momentum[::-1]],
            textposition="outside", cliponaxis=False,
        ))
        layout = base_figure(255)
        layout["margin"] = {"l": 76, "r": 48, "t": 4, "b": 24}
        figure.update_layout(**layout)
    else:
        figure.add_trace(go.Scatter(
            x=scores, y=momentum, mode="markers+text",
            text=names, textposition="top center",
            marker={"size": [33 + abs(v) * 2 for v in momentum], "color": colors, "opacity": .78, "line": {"color": "#101416", "width": 2}},
            hovertemplate="%{text}<br>RS %{x}<br>Momentum %{y:+.1f}%<extra></extra>",
        ))
        layout = base_figure(255)
        layout["margin"] = {"l": 38, "r": 12, "t": 18, "b": 32}
        figure.update_layout(**layout)
        figure.update_xaxes(title="RELATIVE STRENGTH", range=[48, 96])
        figure.update_yaxes(title="MOMENTUM", range=[-5, 10])
        figure.add_vline(x=70, line_width=1, line_dash="dot", line_color="#344044")
        figure.add_hline(y=0, line_width=1, line_dash="dot", line_color="#344044")
    return figure


def breadth_row(name: str, value: str, percent: int, positive: bool = True) -> html.Div:
    return html.Div([
        html.Span(name),
        html.Div(html.I(style={"width": f"{percent}%"}, className="good" if positive else "bad")),
        html.B(value),
    ], className="breadth-row")


def signal_item(title: str, value_id: str, initial: str, note_id: str, note: str, lime: bool = False) -> html.Div:
    return html.Div([
        html.P(title),
        html.B(initial, id=value_id, className="lime" if lime else ""),
        html.Small(note, id=note_id),
    ])


def sector_sidebar() -> html.Aside:
    options = [
        {"label": html.Span([
            html.I(item["ticker"][:2]),
            html.Span([html.B(item["name"]), html.Small(item["ticker"])]),
            html.Em(str(item["score"])),
        ]), "value": item["name"]}
        for item in SECTORS
    ]
    return html.Aside([
        label("SECTOR UNIVERSE"),
        dcc.RadioItems(
            id="sector-selector", options=options, value="Semiconductor",
            className="sector-selector", inputClassName="sector-input", labelClassName="sector-option",
        ),
        html.Div([
            label("SYSTEM"),
            html.Button(["⌁", html.Span(" Data Sources"), html.I(className="status-dot")], className="utility"),
            html.Button(["⚙", html.Span(" Settings")], className="utility"),
            html.Div([
                html.Span([html.I(className="status-dot"), "DATA HEALTH"]),
                html.B("98.7%"), html.Small("12 feeds connected"),
            ], className="data-health"),
        ], className="sidebar-bottom"),
    ], className="sidebar")


def top_bar() -> html.Header:
    return html.Header([
        html.Div([
            html.Span("IF", className="brand-mark"),
            html.Div([html.Strong("INSTITUTIONAL FLOW"), html.Small("EARLY ROTATION INTELLIGENCE")]),
        ], className="brand"),
        html.Div([html.I(className="status-dot"), "MARKET OPEN", html.B("NYSE 14:42")], className="market-status"),
        html.Div([
            html.Button("⌕", className="icon-button", title="Search"),
            html.Button("◌", className="icon-button", title="Notifications"),
            html.Div("JD", className="desk-badge"),
            html.Div(["J. DOH", html.Br(), html.Span("PORTFOLIO DESK")], className="desk-name"),
        ], className="header-actions"),
    ], className="topbar")


def app_layout() -> html.Main:
    return html.Main([
        dcc.Store(id="refresh-counter", data=0),
        top_bar(), sector_sidebar(),
        html.Section([
            html.Div([
                html.Div([label("LIVE MARKET OVERVIEW"), html.H1("Institutional Rotation Monitor"), html.P("Detecting capital migration before it becomes consensus.")]),
                html.Div([
                    html.Span("DEMO DATA"),
                    html.Button("↻ Refresh", id="refresh-button", n_clicks=0),
                    html.Small(f"Updated {datetime.now():%H:%M:%S} KST", id="updated-time"),
                ], className="workspace-tools"),
            ], className="workspace-head"),
            html.Div([
                signal_item("RISK REGIME", "risk-value", "RISK-ON", "risk-note", "↗ Improving", True),
                signal_item("INSTITUTIONAL BIAS", "bias-value", "ACCUMULATION", "bias-note", "5 of 7 sessions"),
                signal_item("LEADING SECTOR", "leading-sector", "SEMICONDUCTOR", "leading-note", "Score 82 / 100"),
                signal_item("MARKET BREADTH", "breadth-value", "67.8%", "breadth-note", "+4.2% vs. 20D", True),
            ], className="signal-strip"),
            html.Div([
                html.Section([
                    card_header("RELATIVE STRENGTH", "Leadership Trend", dcc.RadioItems(
                        id="period-selector", options=list(RS_SERIES), value="1M",
                        inline=True, className="periods", inputClassName="period-input", labelClassName="period-option",
                    )),
                    html.Div([
                        html.Div([html.B("SMH / SPY"), html.Strong("1.0842"), html.Span("+8.42%")]),
                        html.Div([html.I(), " SMH / SPY ", html.I(className="gray"), " 50D AVG"], className="legend"),
                    ], className="chart-summary"),
                    dcc.Graph(id="relative-strength-chart", figure=relative_strength_figure("1M"), config={"displayModeBar": False}, className="main-chart"),
                    html.Div([
                        html.Div([html.Span(pair), html.B(value, className="up" if up else "down"), html.I(className="pair-line up-line" if up else "pair-line down-line")])
                        for pair, value, up in RS_PAIRS
                    ], className="rs-pairs"),
                ], className="card rs-card"),
                html.Section([
                    card_header("VOLUME ANALYSIS", "Participation", badge("ABOVE AVG")),
                    html.Div([
                        html.Div([html.Span("TODAY"), html.B("68.4M"), html.Small(" shares")]),
                        html.Div([html.Span("20D AVG"), html.B("51.2M"), html.Small(" +33.6%")]),
                    ], className="volume-kpi"),
                    dcc.Graph(figure=volume_figure(), config={"displayModeBar": False}, className="volume-chart"),
                    html.Div([
                        html.Div([html.Span("VOLUME SPIKE"), html.B("1.34×"), html.Small("Threshold 1.25×")]),
                        html.Div([html.Span("DISTRIBUTION DAYS"), html.B("2", className="warn"), html.Small("Last 25 sessions")]),
                    ], className="volume-footer"),
                ], className="card volume-card"),
                html.Section([
                    card_header("MARKET BREADTH", "Internal Health", badge("EXPANDING")),
                    html.Div([
                        html.Div([html.Div([html.B("67.8%"), html.Span("HEALTHY")])], className="gauge"),
                        html.P(["Participation is broadening across the market.", html.Br(), html.Span("+4.2%"), " improvement over 20 sessions."]),
                    ], className="breadth-meter"),
                    html.Div([
                        breadth_row("52-WEEK HIGH", "184", 78),
                        breadth_row("52-WEEK LOW", "36", 18, False),
                        breadth_row("ADVANCE / DECLINE", "2.41", 69),
                        breadth_row("ABOVE 50DMA", "68.2%", 68),
                        breadth_row("ABOVE 200DMA", "61.4%", 61),
                    ], className="breadth-list"),
                ], className="card breadth-card"),
                html.Section([
                    card_header("SECTOR ROTATION", "Momentum Map", dcc.RadioItems(
                        id="rotation-view", options=[{"label": "Map", "value": "map"}, {"label": "Rank", "value": "rank"}],
                        value="map", inline=True, className="periods", inputClassName="period-input", labelClassName="period-option",
                    )),
                    dcc.Graph(id="rotation-chart", figure=rotation_figure("map"), config={"displayModeBar": False}),
                    html.Div([html.Span("WEAKENING"), html.I(), html.Span("IMPROVING"), html.B("Momentum × Relative Strength · 20D")], className="rotation-legend"),
                ], className="card rotation-card"),
                html.Section([
                    card_header("ETF MONITOR", "Fund Flow Tape", html.Span("1D NET FLOW", className="subtle")),
                    html.Div([html.Span("ETF"), html.Span("NET FLOW"), html.Span("RETURN")], className="table-head"),
                    html.Div([
                        html.Div([
                            html.Span(ticker, className="ticker"), html.Span(name, className="fund-name"),
                            html.B(flow, className="up" if flow.startswith("+") else "down"),
                            html.Em(ret, className="up" if ret.startswith("+") else "down"),
                        ]) for ticker, name, flow, ret in ETF_ROWS
                    ], className="etf-table"),
                ], className="card etf-card"),
                html.Section([
                    card_header("AI SUPPLY CHAIN", "Leadership Stack", badge("7 / 8 POSITIVE")),
                    html.Div([
                        html.Div([
                            html.Span(f"{index:02d}", className="rank"),
                            html.Div([html.B(ticker), html.Small(name)]),
                            html.I(className="supply-line"), html.Strong(move), html.Em(str(score)),
                        ], className="supply-row leader" if ticker == "VRT" else "supply-row")
                        for index, (ticker, name, move, score) in enumerate(AI_CHAIN, 1)
                    ], className="supply-grid"),
                ], className="card supply-card"),
            ], className="dashboard-grid"),
            html.Footer([
                html.Span([html.I(className="status-dot"), "ALL SYSTEMS OPERATIONAL"]),
                html.Span("DATA DELAY ≤ 15 MIN · FOR RESEARCH PURPOSES ONLY"),
                html.Span("INSTITUTIONAL FLOW ENGINE · PYTHON/DASH"),
            ]),
        ], className="workspace"),
    ], className="app-shell")


app: Dash = Dash(__name__, title=APP_TITLE, update_title=None)
server = app.server
app.layout = app_layout


@callback(
    Output("leading-sector", "children"),
    Output("leading-note", "children"),
    Input("sector-selector", "value"),
)
def update_sector(sector_name: str) -> tuple[str, str]:
    selected = next((item for item in SECTORS if item["name"] == sector_name), SECTORS[0])
    return selected["name"].upper(), f"Score {selected['score']} / 100"


@callback(Output("relative-strength-chart", "figure"), Input("period-selector", "value"))
def update_relative_strength(period: str) -> go.Figure:
    return relative_strength_figure(period)


@callback(Output("rotation-chart", "figure"), Input("rotation-view", "value"))
def update_rotation(view: str) -> go.Figure:
    return rotation_figure(view)


@callback(Output("updated-time", "children"), Input("refresh-button", "n_clicks"), prevent_initial_call=True)
def refresh_timestamp(_: int) -> str:
    return f"Updated {datetime.now():%H:%M:%S} KST"


if __name__ == "__main__":
    app.run(debug=False, host="127.0.0.1", port=8050)
