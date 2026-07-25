"""Offline validation for dashboard layout and core market logic."""

import pandas as pd

from app import app, app_layout
from backtest import candidate_weights, evaluate_model, promotion_decision, select_model
from etf_holdings import ETF_SOURCES, FALLBACK_HOLDINGS
from market_data import (
    BREADTH_UNIVERSE,
    ETF_NAMES,
    SECTOR_ETFS,
    SECTOR_ETF_GROUPS,
    _breadth_metrics,
    _fallback,
    _percentile_ranks,
    _risk_regime,
    _rotation_scores,
)
from rotation_model import DEFAULT_WEIGHTS, load_rotation_model, normalize_weights


def _frame(start: float, end: float, periods: int = 80) -> pd.DataFrame:
    closes = [start + (end - start) * index / (periods - 1) for index in range(periods)]
    return pd.DataFrame({"Close": closes, "Volume": [1_000_000.0] * periods})


def main() -> None:
    assert app.title == "Institutional Rotation Proxy — Market Participation Intelligence"
    assert len(SECTOR_ETFS) == 6
    assert set(SECTOR_ETF_GROUPS) == set(SECTOR_ETFS)
    assert set(ETF_SOURCES) == set(SECTOR_ETFS)
    assert set(FALLBACK_HOLDINGS) == set(SECTOR_ETFS)
    assert all(len(tickers) >= 4 for tickers in SECTOR_ETF_GROUPS.values())
    assert all(len(leaders) == 8 for leaders in FALLBACK_HOLDINGS.values())
    assert len(ETF_NAMES) >= 30
    assert len(BREADTH_UNIVERSE) >= 50

    ranks = _percentile_ranks([-2, 0, 4])
    assert ranks[0] < ranks[1] < ranks[2]
    rotation = _rotation_scores([
        {"name": "Weak", "excess20": -2, "excess60": -4, "breadth": 25, "volume_score": 30},
        {"name": "Strong", "excess20": 4, "excess60": 8, "breadth": 80, "volume_score": 75},
    ])
    assert rotation[0]["name"] == "Strong"
    assert 0 <= rotation[0]["score"] <= 100

    breadth_valid = {"UP": _frame(100, 120), "DOWN": _frame(120, 100)}
    _, _, breadth = _breadth_metrics(breadth_valid, ["UP", "DOWN"])
    assert breadth["ad_diff"] == 0
    assert breadth["ad"] == 1

    risk_valid = {
        "QQQ": _frame(100, 130), "SPY": _frame(100, 110),
        "HYG": _frame(100, 108), "LQD": _frame(100, 101),
        "IWM": _frame(100, 120), "XLY": _frame(100, 125), "XLP": _frame(100, 103),
        "^VIX": _frame(18, 16), "^VIX3M": _frame(20, 19),
    }
    regime, _, risk_score, signals = _risk_regime(risk_valid, 70)
    assert regime == "RISK-ON"
    assert risk_score >= 65
    assert len(signals) == 5
    no_data_regime, _, no_data_score, no_data_signals = _risk_regime({}, 70)
    assert no_data_regime == "NO DATA"
    assert no_data_score == 0
    assert no_data_signals == []

    assert abs(sum(normalize_weights(DEFAULT_WEIGHTS).values()) - 1) < 1e-9
    persisted_model = load_rotation_model()
    assert abs(sum(persisted_model["weights"].values()) - 1) < 1e-9
    assert persisted_model.get("model_status") in {"candidate-promoted", "default-retained"}
    assert all(abs(sum(candidate.values()) - 1) < 1e-9 for candidate in candidate_weights(0.5))
    panel_rows = []
    for date in pd.date_range("2024-01-01", periods=8, freq="W"):
        for rank, name in enumerate(["A", "B", "C", "D", "E"], 1):
            panel_rows.append({
                "date": date, "name": name, "rank20": rank * 20, "rank60": 60,
                "breadth": 50, "volume": 50, "forward_excess": rank - 3,
            })
    panel = pd.DataFrame(panel_rows)
    selected_weights, selected_training = select_model(panel, step=0.5, top_k=2, cost_bps=10)
    selected_metrics = evaluate_model(panel, selected_weights, top_k=2, cost_bps=10)
    assert selected_weights["rank20"] > 0
    assert selected_training["mean_net_forward_excess_pct"] > 0
    assert selected_metrics["information_coefficient"] > 0
    promoted, checks = promotion_decision(selected_metrics, selected_metrics)
    assert promoted and all(checks.values())
    worse = dict(selected_metrics)
    worse["average_one_way_turnover"] = float(selected_metrics["average_one_way_turnover"]) + 0.1
    assert not promotion_decision(worse, selected_metrics)[0]

    layout = app_layout(_fallback("Offline smoke-test fixture"))
    assert layout is not None
    print("Smoke test passed: dashboard layout and datasets are available.")


if __name__ == "__main__":
    main()
