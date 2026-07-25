"""Live market-data retrieval and dashboard calculations.

Prices and volumes come from Yahoo Finance through yfinance. ETF "flow proxy"
is signed dollar turnover, not primary-market creation/redemption data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf

from etf_holdings import fetch_official_holdings
from rotation_model import load_rotation_model, percentile_ranks as _percentile_ranks, score_rotation as _rotation_scores


_YF_CACHE = Path(__file__).resolve().parent / ".cache" / "yfinance"
_YF_CACHE.mkdir(parents=True, exist_ok=True)
yf.set_tz_cache_location(str(_YF_CACHE))


SECTOR_ETFS = {
    "Semiconductor": ("SMH", "SMH"),
    "AI": ("BOTZ", "BOTZ"),
    "Software": ("IGV", "IGV"),
    "Cyber Security": ("CIBR", "CIBR"),
    "Power": ("GRID", "GRID"),
    "Defense": ("ITA", "ITA"),
}

SECTOR_ETF_GROUPS = {
    "Semiconductor": ["SMH", "SOXX", "XSD", "PSI", "FTXL"],
    "AI": ["BOTZ", "AIQ", "ROBO", "IRBO", "THNQ"],
    "Software": ["IGV", "XSW", "WCLD", "SKYY", "CLOU"],
    "Cyber Security": ["CIBR", "HACK", "IHAK", "BUG"],
    "Power": ["GRID", "XLU", "VPU", "PAVE", "UTES"],
    "Defense": ["ITA", "XAR", "PPA", "SHLD"],
}

ETF_NAMES = {
    "SMH": "VanEck Semiconductor", "SOXX": "iShares Semiconductor", "XSD": "SPDR Semiconductor",
    "PSI": "Invesco Dynamic Semiconductors", "FTXL": "First Trust Nasdaq Semiconductor",
    "BOTZ": "Global X Robotics & AI", "AIQ": "Global X Artificial Intelligence", "ROBO": "ROBO Global Robotics",
    "IRBO": "iShares Robotics & AI", "THNQ": "ROBO Global AI",
    "IGV": "iShares Expanded Tech-Software", "XSW": "SPDR Software & Services", "WCLD": "WisdomTree Cloud Computing",
    "SKYY": "First Trust Cloud Computing", "CLOU": "Global X Cloud Computing",
    "CIBR": "First Trust Nasdaq Cybersecurity", "HACK": "ETFMG Prime Cyber Security",
    "IHAK": "iShares Cybersecurity & Tech", "BUG": "Global X Cybersecurity",
    "GRID": "First Trust Smart Grid", "XLU": "Utilities Select Sector", "VPU": "Vanguard Utilities",
    "PAVE": "Global X U.S. Infrastructure", "UTES": "Virtus Reaves Utilities",
    "ITA": "iShares U.S. Aerospace & Defense", "XAR": "SPDR Aerospace & Defense",
    "PPA": "Invesco Aerospace & Defense", "SHLD": "Global X Defense Tech",
    "QQQ": "Invesco QQQ", "SPY": "SPDR S&P 500", "XLI": "Industrial Select",
    "XLE": "Energy Select", "XLV": "Health Care Select", "XLF": "Financial Select",
    "HYG": "iShares High Yield Corporate Bond", "LQD": "iShares Investment Grade Corporate Bond",
    "IWM": "iShares Russell 2000", "XLY": "Consumer Discretionary Select", "XLP": "Consumer Staples Select",
    "^VIX": "CBOE Volatility Index", "^VIX3M": "CBOE 3-Month Volatility Index",
}

ROTATION_ETFS = {
    "Semis": "SMH", "AI Infra": "BOTZ", "Power": "GRID", "Cyber": "CIBR",
    "Software": "IGV", "Defense": "ITA", "Financials": "XLF",
    "Health": "XLV", "Industrials": "XLI", "Energy": "XLE",
}

ROTATION_TO_SECTOR = {
    "Semis": "Semiconductor", "AI Infra": "AI", "Power": "Power",
    "Cyber": "Cyber Security", "Software": "Software", "Defense": "Defense",
}

RISK_SIGNAL_SPECS = (
    ("QQQ/SPY", "QQQ", "SPY"),
    ("HYG/LQD", "HYG", "LQD"),
    ("IWM/SPY", "IWM", "SPY"),
    ("XLY/XLP", "XLY", "XLP"),
)

# Liquid cross-sector universe used for breadth. This is intentionally fixed so
# coverage is transparent and the dashboard does not scrape an index webpage.
BREADTH_UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "AVGO", "TSLA",
    "BRK-B", "JPM", "V", "MA", "WMT", "LLY", "UNH", "XOM", "COST", "HD",
    "PG", "JNJ", "ORCL", "NFLX", "CRM", "BAC", "KO", "PEP", "CVX", "ABBV",
    "MRK", "TMO", "CSCO", "ACN", "AMD", "IBM", "CAT", "GE", "RTX", "BA",
    "GS", "MS", "AXP", "BLK", "NOW", "QCOM", "TXN", "AMAT", "MU", "LRCX",
    "PANW", "CRWD", "PLTR", "VRT", "GEV", "NEE", "CEG", "ETN", "DE", "HON",
    "LIN", "UBER",
]

ETF_TICKERS = list(ETF_NAMES)
ALL_TICKERS = sorted(set(
    BREADTH_UNIVERSE
    + ETF_TICKERS
    + list(ticker for ticker, _ in SECTOR_ETFS.values())
    + list(ROTATION_ETFS.values())
    + ["XLK"]
))

PERIOD_LENGTH = {"1D": 2, "5D": 6, "1M": 22, "3M": 66}
_cache: dict[str, Any] = {"snapshot": None, "fetched_at": None}
_lock = Lock()


def _history(download: pd.DataFrame, ticker: str) -> pd.DataFrame:
    if download.empty:
        return pd.DataFrame()
    try:
        frame = download[ticker].copy() if isinstance(download.columns, pd.MultiIndex) else download.copy()
    except KeyError:
        return pd.DataFrame()
    needed = [column for column in ("Close", "Volume") if column in frame.columns]
    if not needed:
        return pd.DataFrame()
    frame = frame[needed].dropna(subset=["Close"])
    return frame


def _pct(series: pd.Series, sessions: int = 1) -> float:
    clean = series.dropna()
    if len(clean) <= sessions:
        return 0.0
    return float((clean.iloc[-1] / clean.iloc[-1 - sessions] - 1) * 100)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _money(value: float) -> str:
    sign = "+" if value >= 0 else "−"
    amount = abs(value)
    if amount >= 1_000_000_000:
        return f"{sign}${amount / 1_000_000_000:.2f}B"
    return f"{sign}${amount / 1_000_000:.0f}M"


def _risk_regime(valid: dict[str, pd.DataFrame], breadth_score: float) -> tuple[str, str, float, list[dict[str, Any]]]:
    """Classify risk appetite from cross-asset ratios plus market breadth."""
    signals: list[dict[str, Any]] = []
    for label, numerator, denominator in RISK_SIGNAL_SPECS:
        if numerator not in valid or denominator not in valid:
            continue
        joined = pd.concat(
            [valid[numerator]["Close"], valid[denominator]["Close"]], axis=1, join="inner",
        ).dropna()
        if len(joined) <= 20:
            continue
        ratio = joined.iloc[:, 0] / joined.iloc[:, 1]
        change = _pct(ratio, 20)
        signals.append({"name": label, "value": round(change, 2), "risk_on": change > 0, "unit": "% 20D"})

    if "^VIX" in valid and "^VIX3M" in valid:
        joined = pd.concat(
            [valid["^VIX"]["Close"], valid["^VIX3M"]["Close"]], axis=1, join="inner",
        ).dropna()
        if not joined.empty:
            ratio = float(joined.iloc[-1, 0] / joined.iloc[-1, 1])
            signals.append({"name": "VIX/VIX3M", "value": round(ratio, 3), "risk_on": ratio < 1, "unit": "ratio"})

    confirming = sum(bool(signal["risk_on"]) for signal in signals)
    if not signals:
        return "NO DATA", f"Cross-asset unavailable · breadth {breadth_score:.0f}%", 0.0, []
    signal_score = confirming / max(len(signals), 1) * 100
    composite = round(signal_score * 0.8 + breadth_score * 0.2, 1)
    if len(signals) < 3:
        regime = "PARTIAL"
    elif composite >= 65:
        regime = "RISK-ON"
    elif composite <= 35:
        regime = "RISK-OFF"
    else:
        regime = "NEUTRAL"
    note = f"{confirming}/{len(signals)} cross-asset · breadth {breadth_score:.0f}%" if signals else f"Breadth-only · {breadth_score:.0f}%"
    return regime, note, composite, signals


def _breadth_metrics(
    valid: dict[str, pd.DataFrame], tickers: list[str], weights: dict[str, float] | None = None,
) -> tuple[int, float, dict[str, float]]:
    frames = [(ticker, valid[ticker]) for ticker in tickers if ticker in valid and len(valid[ticker]) >= 50]
    advances = declines = highs = lows = above50 = above200 = 0
    weight_total = weighted_above50 = weighted_above200 = 0.0
    for ticker, frame in frames:
        close = frame["Close"].dropna()
        if len(close) < 2:
            continue
        weight = float((weights or {}).get(ticker, 1.0))
        weight_total += weight
        advances += int(close.iloc[-1] > close.iloc[-2])
        declines += int(close.iloc[-1] < close.iloc[-2])
        year = close.tail(252)
        highs += int(close.iloc[-1] >= year.max() * 0.995)
        lows += int(close.iloc[-1] <= year.min() * 1.005)
        is_above50 = close.iloc[-1] > close.tail(50).mean()
        is_above200 = len(close) >= 200 and close.iloc[-1] > close.tail(200).mean()
        above50 += int(is_above50)
        above200 += int(is_above200)
        weighted_above50 += weight if is_above50 else 0.0
        weighted_above200 += weight if is_above200 else 0.0

    coverage = len(frames)
    ad_ratio = (advances + 1) / (declines + 1)
    ad_diff = (advances - declines) / max(advances + declines, 1)
    above50_pct = above50 / max(coverage, 1) * 100
    above200_pct = above200 / max(coverage, 1) * 100
    score = round((above50_pct + above200_pct) / 2, 1)
    weighted50_pct = weighted_above50 / max(weight_total, 1) * 100
    weighted200_pct = weighted_above200 / max(weight_total, 1) * 100
    return coverage, score, {
        "highs": highs, "lows": lows, "ad": ad_ratio, "ad_diff": ad_diff,
        "advances": advances, "declines": declines,
        "above50": above50_pct, "above200": above200_pct,
        "weighted_above50": weighted50_pct, "weighted_above200": weighted200_pct,
        "weighted_score": round((weighted50_pct + weighted200_pct) / 2, 1),
    }


def _fallback(error: str) -> dict[str, Any]:
    return {
        "ok": False, "error": error, "as_of": "Unavailable", "coverage": 0,
        "sectors": [{"name": name, "ticker": ticker, "score": 0} for name, (ticker, _) in SECTOR_ETFS.items()],
        "risk_regime": "NO DATA", "risk_note": "Check connection",
        "bias": "NO DATA", "bias_note": "Awaiting feed", "breadth_score": 0.0,
        "rs": {}, "volume": {"values": [], "today": 0, "average": 0, "spike": 0, "distribution": 0},
        "sector_volumes": {
            name: {"ticker": ticker, "values": [], "today": 0, "average": 0, "spike": 0, "distribution": 0}
            for name, (ticker, _) in SECTOR_ETFS.items()
        },
        "breadth": {"highs": 0, "lows": 0, "ad": 0, "ad_diff": 0, "advances": 0, "declines": 0, "above50": 0, "above200": 0},
        "sector_breadth": {
            name: {"coverage": 0, "total": 0, "score": 0.0, "weighted_score": 0.0, "benchmark_etf": ticker,
                   "holdings_as_of": "Unavailable", "holdings_fallback": True, "holdings_error": "",
                   "metrics": {"highs": 0, "lows": 0, "ad": 0, "ad_diff": 0, "advances": 0, "declines": 0, "above50": 0, "above200": 0,
                               "weighted_above50": 0, "weighted_above200": 0, "weighted_score": 0}}
            for name, (ticker, _) in SECTOR_ETFS.items()
        },
        "sector_etfs": {name: [] for name in SECTOR_ETFS},
        "sector_leaders": {name: [] for name in SECTOR_ETFS},
        "etfs": [], "rotation": [], "ai": [], "risk_score": 0.0, "risk_signals": [],
        "rotation_model": load_rotation_model(),
    }


def fetch_snapshot(force: bool = False) -> dict[str, Any]:
    """Download and calculate a snapshot, caching successful results for 5 min."""
    with _lock:
        fetched_at = _cache.get("fetched_at")
        if not force and _cache.get("snapshot") and fetched_at and datetime.now(timezone.utc) - fetched_at < timedelta(minutes=5):
            return _cache["snapshot"]

        try:
            official_holdings = fetch_official_holdings()
            holding_tickers = [
                row["ticker"]
                for sector in official_holdings.values()
                for row in sector.get("holdings", [])
                if row.get("ticker")
            ]
            download_tickers = sorted(set(ALL_TICKERS + holding_tickers))
            raw = yf.download(
                download_tickers, period="1y", interval="1d", auto_adjust=True,
                group_by="ticker", threads=True, progress=False, timeout=20,
            )
            histories = {ticker: _history(raw, ticker) for ticker in download_tickers}
            valid = {ticker: frame for ticker, frame in histories.items() if len(frame) >= 2}
            if "SPY" not in valid or "SMH" not in valid:
                raise RuntimeError("Required benchmark histories were not returned")

            spy = valid["SPY"]
            latest_date = spy.index[-1]
            as_of = pd.Timestamp(latest_date).strftime("%Y-%m-%d")

            coverage, breadth_score, breadth = _breadth_metrics(valid, BREADTH_UNIVERSE)
            ad_diff = breadth["ad_diff"]

            rs: dict[str, dict[str, list[Any]]] = {}
            pair_specs = [
                ("SMH / SPY", "SMH", "SPY"), ("SOXX / QQQ", "SOXX", "QQQ"),
                ("QQQ / SPY", "QQQ", "SPY"), ("XLI / SPY", "XLI", "SPY"),
                ("XLK / SPY", "XLK", "SPY"),
            ]
            pair_specs.extend(
                (f"{ticker} / SPY", ticker, "SPY")
                for ticker, _ in SECTOR_ETFS.values()
            )
            for pair, numerator, denominator in dict.fromkeys(pair_specs):
                if numerator not in valid or denominator not in valid:
                    continue
                joined = pd.concat([valid[numerator]["Close"], valid[denominator]["Close"]], axis=1, join="inner").dropna()
                ratio = joined.iloc[:, 0] / joined.iloc[:, 1]
                rs[pair] = {
                    "dates": [pd.Timestamp(index).strftime("%Y-%m-%d") for index in ratio.index[-66:]],
                    "values": [float(value) for value in ratio.iloc[-66:]],
                }

            spy_recent = spy.tail(26)
            distribution = int(((spy_recent["Close"].pct_change() < 0) & (spy_recent["Volume"] > spy_recent["Volume"].shift(1))).tail(25).sum())
            sector_volumes = {}
            for name, (ticker, _) in SECTOR_ETFS.items():
                frame = valid.get(ticker)
                sector_volume = frame["Volume"].dropna().tail(20) if frame is not None else pd.Series(dtype=float)
                recent = frame.tail(26) if frame is not None else pd.DataFrame()
                sector_distribution = int(((recent["Close"].pct_change() < 0) & (recent["Volume"] > recent["Volume"].shift(1))).tail(25).sum()) if not recent.empty else 0
                average_volume = float(sector_volume.iloc[:-1].mean()) if len(sector_volume) > 1 else float(sector_volume.mean()) if len(sector_volume) else 0
                today_volume = float(sector_volume.iloc[-1]) if len(sector_volume) else 0
                sector_volumes[name] = {
                    "ticker": ticker, "values": [float(value) for value in sector_volume],
                    "today": today_volume, "average": average_volume,
                    "spike": today_volume / max(average_volume, 1), "distribution": sector_distribution,
                }

            etfs_by_ticker = {}
            for ticker, name in ETF_NAMES.items():
                frame = valid.get(ticker)
                if frame is None or len(frame) < 2:
                    continue
                daily_return = _pct(frame["Close"])
                dollar_turnover = float(frame["Close"].iloc[-1] * frame["Volume"].iloc[-1])
                proxy = dollar_turnover if daily_return >= 0 else -dollar_turnover
                etfs_by_ticker[ticker] = {"ticker": ticker, "name": name, "activity": _money(proxy), "return": daily_return}
            sector_etfs = {
                sector: [etfs_by_ticker[ticker] for ticker in tickers if ticker in etfs_by_ticker]
                for sector, tickers in SECTOR_ETF_GROUPS.items()
            }
            etfs = sector_etfs.get("Semiconductor", [])

            rotation_inputs = []
            for name, ticker in ROTATION_ETFS.items():
                frame = valid.get(ticker)
                if frame is None:
                    continue
                aligned = pd.concat([frame["Close"], spy["Close"]], axis=1, join="inner").dropna()
                excess20 = _pct(aligned.iloc[:, 0], 20) - _pct(aligned.iloc[:, 1], 20)
                excess60 = _pct(aligned.iloc[:, 0], 60) - _pct(aligned.iloc[:, 1], 60)
                volume = frame["Volume"].dropna().tail(20)
                average = float(volume.iloc[:-1].mean()) if len(volume) > 1 else 0.0
                latest = float(volume.iloc[-1]) if len(volume) else 0.0
                spike = latest / max(average, 1)
                rotation_inputs.append({
                    "name": name, "excess20": excess20, "excess60": excess60,
                    "volume_score": _clamp(50 + (spike - 1) * 50, 0, 100),
                })

            sector_leaders = {}
            sector_breadth = {}
            for sector, holdings_data in official_holdings.items():
                holdings = holdings_data.get("holdings", [])
                rows = []
                weights = {row["ticker"]: float(row.get("weight", 0)) for row in holdings}
                for holding in holdings:
                    ticker = holding["ticker"]
                    frame = valid.get(ticker)
                    if frame is None:
                        continue
                    move = _pct(frame["Close"])
                    momentum = _pct(frame["Close"], 20)
                    trend_close = frame["Close"].dropna().tail(21)
                    baseline = float(trend_close.iloc[0]) if len(trend_close) else 1.0
                    trend = [float((value / baseline - 1) * 100) for value in trend_close]
                    rows.append({
                        "ticker": ticker, "official_ticker": holding.get("official_ticker", ticker),
                        "name": holding["name"], "weight": float(holding.get("weight", 0)),
                        "move": move, "momentum": momentum, "trend": trend,
                    })
                sector_leaders[sector] = rows
                sector_coverage, sector_score, sector_metrics = _breadth_metrics(
                    valid, [row["ticker"] for row in holdings], weights,
                )
                sector_breadth[sector] = {
                    "coverage": sector_coverage, "total": len(holdings), "score": sector_score,
                    "weighted_score": sector_metrics.get("weighted_score", 0), "metrics": sector_metrics,
                    "benchmark_etf": holdings_data.get("etf", SECTOR_ETFS[sector][0]),
                    "holdings_as_of": holdings_data.get("as_of", "Unknown"),
                    "holdings_fallback": holdings_data.get("fallback", False),
                    "holdings_error": holdings_data.get("error", ""),
                    "holdings_source_url": holdings_data.get("source_url", ""),
                    "holdings_issuer": holdings_data.get("issuer", ""),
                }

            ai_rows = sector_leaders.get("AI", [])

            for item in rotation_inputs:
                sector_name = ROTATION_TO_SECTOR.get(item["name"])
                item["breadth"] = sector_breadth.get(sector_name, {}).get("score", breadth_score)
            rotation_model = load_rotation_model()
            rotation = _rotation_scores(rotation_inputs, rotation_model.get("weights"))

            sectors = []
            for name, (ticker, display_ticker) in SECTOR_ETFS.items():
                item = next((row for row in rotation if ROTATION_ETFS.get(row["name"]) == ticker), None)
                score = int(round(item["score"])) if item else 0
                sectors.append({"name": name, "ticker": display_ticker, "score": score})

            risk_regime, risk_note, risk_score, risk_signals = _risk_regime(valid, breadth_score)
            bias = "ACCUMULATION PROXY" if distribution <= 3 and ad_diff >= 0 else "DISTRIBUTION PROXY"

            snapshot = {
                "ok": True, "error": "", "as_of": as_of, "coverage": coverage,
                "sectors": sectors, "risk_regime": risk_regime,
                "risk_note": risk_note, "risk_score": risk_score, "risk_signals": risk_signals,
                "bias": bias, "bias_note": f"{distribution} distribution days / 25",
                "breadth_score": breadth_score, "rs": rs,
                "volume": sector_volumes["Semiconductor"],
                "sector_volumes": sector_volumes,
                "breadth": breadth, "sector_breadth": sector_breadth,
                "sector_etfs": sector_etfs, "sector_leaders": sector_leaders,
                "etfs": etfs, "rotation": rotation, "ai": ai_rows,
                "rotation_model": rotation_model,
            }
            _cache.update({"snapshot": snapshot, "fetched_at": datetime.now(timezone.utc)})
            return snapshot
        except Exception as exc:  # network/provider errors should not crash Dash
            if _cache.get("snapshot"):
                stale = dict(_cache["snapshot"])
                stale["error"] = f"Refresh failed; showing cached data: {exc}"
                return stale
            return _fallback(str(exc))


def period_slice(series: dict[str, list[Any]], period: str) -> tuple[list[str], list[float]]:
    length = PERIOD_LENGTH.get(period, 22)
    return series.get("dates", [])[-length:], series.get("values", [])[-length:]
