"""Walk-forward calibration for the cross-sectional sector rotation model.

The backtest uses only information available at each rebalance date. It selects
factor weights on an early training period and reports untouched validation
results on the later period. Current ETF holdings are used historically, so the
output explicitly carries a survivorship-bias limitation.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
import yfinance as yf

from etf_holdings import fetch_official_holdings
from market_data import BREADTH_UNIVERSE, ROTATION_ETFS, ROTATION_TO_SECTOR
from rotation_model import FACTORS, MODEL_PATH, normalize_weights, percentile_ranks


def _history(download: pd.DataFrame, ticker: str) -> pd.DataFrame:
    if download.empty:
        return pd.DataFrame()
    try:
        frame = download[ticker].copy() if isinstance(download.columns, pd.MultiIndex) else download.copy()
    except KeyError:
        return pd.DataFrame()
    columns = [column for column in ("Close", "Volume") if column in frame.columns]
    return frame[columns].dropna(subset=["Close"]) if "Close" in columns else pd.DataFrame()


def _return(series: pd.Series, sessions: int) -> float:
    clean = series.dropna()
    if len(clean) <= sessions:
        return float("nan")
    return float((clean.iloc[-1] / clean.iloc[-1 - sessions] - 1) * 100)


def _breadth_at(
    histories: dict[str, pd.DataFrame], tickers: Iterable[str], date: pd.Timestamp,
) -> tuple[float, int]:
    above50 = above200 = coverage = 0
    for ticker in tickers:
        frame = histories.get(ticker)
        if frame is None:
            continue
        close = frame.loc[:date, "Close"].dropna()
        if len(close) < 200:
            continue
        coverage += 1
        above50 += int(close.iloc[-1] > close.tail(50).mean())
        above200 += int(close.iloc[-1] > close.tail(200).mean())
    if not coverage:
        return 50.0, 0
    return (above50 / coverage * 100 + above200 / coverage * 100) / 2, coverage


def _forward_excess(
    frame: pd.DataFrame, spy: pd.DataFrame, date: pd.Timestamp, target_date: pd.Timestamp,
) -> float:
    asset = frame.loc[:target_date, "Close"].dropna()
    benchmark = spy.loc[:target_date, "Close"].dropna()
    if date not in asset.index or date not in benchmark.index or asset.empty or benchmark.empty:
        return float("nan")
    asset_future = asset.iloc[-1] / asset.loc[date] - 1
    benchmark_future = benchmark.iloc[-1] / benchmark.loc[date] - 1
    return float((asset_future - benchmark_future) * 100)


def build_feature_panel(
    histories: dict[str, pd.DataFrame],
    holdings: dict[str, list[str]],
    rebalance_every: int = 5,
    horizon: int = 20,
) -> pd.DataFrame:
    """Build point-in-time factor ranks and subsequent excess returns."""
    spy = histories.get("SPY", pd.DataFrame())
    if spy.empty:
        raise ValueError("SPY history is required")
    dates = spy.index[252:-horizon:rebalance_every]
    records: list[dict[str, Any]] = []
    for date in dates:
        location = int(spy.index.get_loc(date))
        target_date = spy.index[location + horizon]
        global_breadth, _ = _breadth_at(histories, BREADTH_UNIVERSE, date)
        daily: list[dict[str, Any]] = []
        for name, ticker in ROTATION_ETFS.items():
            frame = histories.get(ticker)
            if frame is None or date not in frame.index:
                continue
            aligned = pd.concat(
                [frame.loc[:date, "Close"], spy.loc[:date, "Close"]], axis=1, join="inner",
            ).dropna()
            if len(aligned) <= 60:
                continue
            excess20 = _return(aligned.iloc[:, 0], 20) - _return(aligned.iloc[:, 1], 20)
            excess60 = _return(aligned.iloc[:, 0], 60) - _return(aligned.iloc[:, 1], 60)
            volume = frame.loc[:date, "Volume"].dropna().tail(20) if "Volume" in frame else pd.Series(dtype=float)
            average = float(volume.iloc[:-1].mean()) if len(volume) > 1 else 0.0
            spike = float(volume.iloc[-1]) / max(average, 1) if len(volume) else 1.0
            sector = ROTATION_TO_SECTOR.get(name)
            sector_breadth, sector_coverage = _breadth_at(histories, holdings.get(sector, []), date)
            breadth = sector_breadth if sector_coverage >= 5 else global_breadth
            forward = _forward_excess(frame, spy, date, target_date)
            if np.isnan(forward):
                continue
            daily.append({
                "date": date, "name": name, "excess20": excess20, "excess60": excess60,
                "breadth": breadth, "volume": max(0.0, min(100.0, 50 + (spike - 1) * 50)),
                "forward_excess": forward,
            })
        if len(daily) < 5:
            continue
        ranks20 = percentile_ranks([row["excess20"] for row in daily])
        ranks60 = percentile_ranks([row["excess60"] for row in daily])
        for row, rank20, rank60 in zip(daily, ranks20, ranks60):
            row["rank20"] = rank20
            row["rank60"] = rank60
            records.append(row)
    panel = pd.DataFrame.from_records(records)
    if panel.empty:
        raise ValueError("No backtest observations were produced")
    return panel.sort_values(["date", "name"]).reset_index(drop=True)


def candidate_weights(step: float = 0.1) -> list[dict[str, float]]:
    """Enumerate non-negative weights that sum to one on a fixed grid."""
    units = round(1 / step)
    candidates = []
    for first in range(units + 1):
        for second in range(units - first + 1):
            for third in range(units - first - second + 1):
                fourth = units - first - second - third
                candidates.append(dict(zip(FACTORS, [first / units, second / units, third / units, fourth / units])))
    return candidates


def _rank_correlation(left: pd.Series, right: pd.Series) -> float:
    if len(left) < 2 or left.nunique() < 2 or right.nunique() < 2:
        return float("nan")
    return float(left.rank().corr(right.rank()))


def evaluate_model(
    panel: pd.DataFrame,
    weights: dict[str, float],
    top_k: int = 3,
    cost_bps: float = 10.0,
) -> dict[str, float | int]:
    """Evaluate signal IC, persistence, net forward excess return, and turnover."""
    model_weights = normalize_weights(weights)
    previous_positions: dict[str, float] = {}
    previous_scores: pd.Series | None = None
    net_returns: list[float] = []
    gross_returns: list[float] = []
    turnovers: list[float] = []
    information_coefficients: list[float] = []
    persistence_values: list[float] = []

    for _, group in panel.groupby("date", sort=True):
        group = group.copy()
        group["model_score"] = sum(group[factor] * model_weights[factor] for factor in FACTORS)
        ic = _rank_correlation(group["model_score"], group["forward_excess"])
        if pd.notna(ic):
            information_coefficients.append(float(ic))
        current_scores = group.set_index("name")["model_score"]
        if previous_scores is not None:
            shared = current_scores.index.intersection(previous_scores.index)
            persistence = _rank_correlation(current_scores.loc[shared], previous_scores.loc[shared])
            if pd.notna(persistence):
                persistence_values.append(float(persistence))
        selected = group.nlargest(min(top_k, len(group)), "model_score")
        positions = {name: 1 / len(selected) for name in selected["name"]}
        universe = set(previous_positions) | set(positions)
        turnover = 0.5 * sum(abs(positions.get(name, 0) - previous_positions.get(name, 0)) for name in universe)
        gross = float(selected["forward_excess"].mean())
        net = gross - turnover * cost_bps / 100
        gross_returns.append(gross)
        net_returns.append(net)
        turnovers.append(turnover)
        previous_positions = positions
        previous_scores = current_scores

    net_series = pd.Series(net_returns, dtype=float)
    net_std = float(net_series.std(ddof=1)) if len(net_series) > 1 else 0.0
    net_information_ratio = float(net_series.mean() / net_std) if net_std > 0 else 0.0
    return {
        "observations": len(net_returns),
        "mean_forward_excess_pct": round(float(np.mean(gross_returns)), 4) if gross_returns else 0.0,
        "mean_net_forward_excess_pct": round(float(np.mean(net_returns)), 4) if net_returns else 0.0,
        "median_net_forward_excess_pct": round(float(np.median(net_returns)), 4) if net_returns else 0.0,
        "net_information_ratio": round(net_information_ratio, 4),
        "hit_rate": round(float((net_series > 0).mean()), 4) if not net_series.empty else 0.0,
        "information_coefficient": round(float(np.mean(information_coefficients)), 4) if information_coefficients else 0.0,
        "signal_persistence": round(float(np.mean(persistence_values)), 4) if persistence_values else 0.0,
        "average_one_way_turnover": round(float(np.mean(turnovers)), 4) if turnovers else 0.0,
    }


def select_model(
    training_panel: pd.DataFrame,
    step: float = 0.1,
    top_k: int = 3,
    cost_bps: float = 10.0,
) -> tuple[dict[str, float], dict[str, float | int]]:
    """Select weights by training risk-adjusted net excess return only."""
    best_weights: dict[str, float] | None = None
    best_metrics: dict[str, float | int] | None = None
    for weights in candidate_weights(step):
        metrics = evaluate_model(training_panel, weights, top_k, cost_bps)
        key = (
            float(metrics["net_information_ratio"]),
            float(metrics["mean_net_forward_excess_pct"]),
            float(metrics["information_coefficient"]),
            -float(metrics["average_one_way_turnover"]),
        )
        if best_metrics is None:
            best_weights, best_metrics, best_key = weights, metrics, key
        elif key > best_key:
            best_weights, best_metrics, best_key = weights, metrics, key
    if best_weights is None or best_metrics is None:
        raise ValueError("No candidate model could be evaluated")
    return best_weights, best_metrics


def promotion_decision(
    candidate: dict[str, float | int], baseline: dict[str, float | int],
) -> tuple[bool, dict[str, bool]]:
    """Require held-out Pareto dominance before replacing the live model."""
    checks = {
        "net_excess_not_worse": candidate["mean_net_forward_excess_pct"] >= baseline["mean_net_forward_excess_pct"],
        "net_information_ratio_not_worse": candidate["net_information_ratio"] >= baseline["net_information_ratio"],
        "information_coefficient_not_worse": candidate["information_coefficient"] >= baseline["information_coefficient"],
        "turnover_not_higher": candidate["average_one_way_turnover"] <= baseline["average_one_way_turnover"],
    }
    return all(checks.values()), checks


def run_backtest(
    years: int = 5,
    rebalance_every: int = 5,
    horizon: int = 20,
    train_fraction: float = 0.65,
    top_k: int = 3,
    cost_bps: float = 10.0,
    holdings_limit: int = 30,
    grid_step: float = 0.1,
    output: Path = MODEL_PATH,
) -> dict[str, Any]:
    official = fetch_official_holdings(force=True)
    holdings = {
        sector: [row["ticker"] for row in data.get("holdings", [])[:holdings_limit] if row.get("ticker")]
        for sector, data in official.items()
    }
    tickers = sorted(set(
        ["SPY", *ROTATION_ETFS.values(), *BREADTH_UNIVERSE]
        + [ticker for values in holdings.values() for ticker in values]
    ))
    raw = yf.download(
        tickers, period=f"{years}y", interval="1d", auto_adjust=True,
        group_by="ticker", threads=True, progress=False, timeout=30,
    )
    histories = {ticker: _history(raw, ticker) for ticker in tickers}
    histories = {ticker: frame for ticker, frame in histories.items() if not frame.empty}
    panel = build_feature_panel(histories, holdings, rebalance_every, horizon)
    dates = list(panel["date"].drop_duplicates().sort_values())
    split = max(1, min(len(dates) - 1, int(len(dates) * train_fraction)))
    embargo = max(1, int(np.ceil(horizon / rebalance_every)))
    training_dates = dates[:max(1, split - embargo)]
    validation_dates = dates[split:]
    training_panel = panel[panel["date"].isin(training_dates)]
    validation_panel = panel[panel["date"].isin(validation_dates)]
    weights, training_metrics = select_model(training_panel, grid_step, top_k, cost_bps)
    validation_metrics = evaluate_model(validation_panel, weights, top_k, cost_bps)
    default_weights = {"rank20": 0.35, "rank60": 0.30, "breadth": 0.20, "volume": 0.15}
    rank60_weights = {"rank20": 0.0, "rank60": 1.0, "breadth": 0.0, "volume": 0.0}
    default_training = evaluate_model(training_panel, default_weights, top_k, cost_bps)
    default_validation = evaluate_model(validation_panel, default_weights, top_k, cost_bps)
    rank60_training = evaluate_model(training_panel, rank60_weights, top_k, cost_bps)
    rank60_validation = evaluate_model(validation_panel, rank60_weights, top_k, cost_bps)
    promoted, promotion_checks = promotion_decision(validation_metrics, default_validation)
    active_weights = weights if promoted else default_weights
    active_training = training_metrics if promoted else default_training
    active_validation = validation_metrics if promoted else default_validation
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_as_of": pd.Timestamp(histories["SPY"].index.max()).strftime("%Y-%m-%d"),
        "last_signal_date": pd.Timestamp(panel["date"].max()).strftime("%Y-%m-%d"),
        "source": "backtest-governed",
        "model_status": "candidate-promoted" if promoted else "default-retained",
        "weights": active_weights,
        "training": active_training,
        "validation": active_validation,
        "candidate": {
            "weights": weights,
            "training": training_metrics,
            "validation": validation_metrics,
        },
        "promotion": {
            "promoted": promoted,
            "rule": "candidate must weakly dominate the documented default on held-out net excess return, net information ratio, information coefficient, and turnover",
            "checks": promotion_checks,
        },
        "benchmarks": {
            "documented_default": {
                "weights": default_weights,
                "training": default_training,
                "validation": default_validation,
            },
            "rank60_only": {
                "weights": rank60_weights,
                "training": rank60_training,
                "validation": rank60_validation,
            },
        },
        "parameters": {
            "years": years, "rebalance_every_sessions": rebalance_every,
            "forward_horizon_sessions": horizon, "train_fraction": train_fraction,
            "embargo_rebalances": embargo, "top_k": top_k,
            "transaction_cost_bps": cost_bps, "holdings_limit_per_sector": holdings_limit,
            "weight_grid_step": grid_step,
            "selection_objective": "maximize training net information ratio after transaction costs",
        },
        "periods": {
            "training_start": pd.Timestamp(training_dates[0]).strftime("%Y-%m-%d"),
            "training_end": pd.Timestamp(training_dates[-1]).strftime("%Y-%m-%d"),
            "validation_start": pd.Timestamp(validation_dates[0]).strftime("%Y-%m-%d"),
            "validation_end": pd.Timestamp(validation_dates[-1]).strftime("%Y-%m-%d"),
        },
        "limitations": [
            "Historical breadth uses current ETF holdings and is subject to survivorship bias.",
            "Yahoo Finance adjusted prices and volumes are research-grade, not an institutional feed.",
            "Validation is a single held-out period and does not guarantee future performance.",
            "Overlapping 20-session forward returns make observations statistically dependent.",
        ],
    }
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Calibrate and validate the sector rotation model")
    parser.add_argument("--years", type=int, default=5)
    parser.add_argument("--rebalance", type=int, default=5)
    parser.add_argument("--horizon", type=int, default=20)
    parser.add_argument("--train-fraction", type=float, default=0.65)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--cost-bps", type=float, default=10.0)
    parser.add_argument("--holdings-limit", type=int, default=30)
    parser.add_argument("--grid-step", type=float, default=0.1)
    parser.add_argument("--output", type=Path, default=MODEL_PATH)
    args = parser.parse_args()
    result = run_backtest(
        years=args.years, rebalance_every=args.rebalance, horizon=args.horizon,
        train_fraction=args.train_fraction, top_k=args.top_k, cost_bps=args.cost_bps,
        holdings_limit=args.holdings_limit, grid_step=args.grid_step, output=args.output,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
