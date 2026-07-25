"""Shared rotation-model scoring and persisted calibration support."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


FACTORS = ("rank20", "rank60", "breadth", "volume")
DEFAULT_WEIGHTS = {
    "rank20": 0.35,
    "rank60": 0.30,
    "breadth": 0.20,
    "volume": 0.15,
}
MODEL_PATH = Path(__file__).resolve().parent / "rotation_model.json"


def percentile_ranks(values: list[float]) -> list[float]:
    """Return stable 0-100 percentile ranks, averaging ties."""
    if not values:
        return []
    if len(values) == 1:
        return [50.0]
    ranks = pd.Series(values, dtype=float).rank(method="average", pct=True) * 100
    return [float(value) for value in ranks]


def normalize_weights(weights: dict[str, float] | None) -> dict[str, float]:
    """Validate and normalize non-negative factor weights."""
    candidate = weights or DEFAULT_WEIGHTS
    cleaned = {factor: max(float(candidate.get(factor, 0)), 0.0) for factor in FACTORS}
    total = sum(cleaned.values())
    if total <= 0:
        return dict(DEFAULT_WEIGHTS)
    return {factor: value / total for factor, value in cleaned.items()}


def load_rotation_model(path: Path = MODEL_PATH) -> dict[str, Any]:
    """Load a backtest-selected model, falling back to documented defaults."""
    fallback = {
        "source": "default",
        "weights": dict(DEFAULT_WEIGHTS),
        "generated_at": None,
        "validation": {},
        "limitations": ["No persisted backtest calibration is available."],
    }
    if not path.exists():
        return fallback
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["weights"] = normalize_weights(payload.get("weights"))
        payload.setdefault("source", "backtest")
        return payload
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        fallback["limitations"] = [f"Backtest model could not be loaded: {exc}"]
        return fallback


def score_rotation(inputs: list[dict[str, Any]], weights: dict[str, float] | None = None) -> list[dict[str, Any]]:
    """Score cross-sectional rotation inputs with one shared factor model."""
    model_weights = normalize_weights(weights)
    ranks20 = percentile_ranks([float(item["excess20"]) for item in inputs])
    ranks60 = percentile_ranks([float(item["excess60"]) for item in inputs])
    scored: list[dict[str, Any]] = []
    for item, rank20, rank60 in zip(inputs, ranks20, ranks60):
        breadth = max(0.0, min(100.0, float(item.get("breadth", 50))))
        volume = max(0.0, min(100.0, float(item.get("volume_score", 50))))
        factor_values = {
            "rank20": rank20,
            "rank60": rank60,
            "breadth": breadth,
            "volume": volume,
        }
        score = sum(model_weights[factor] * factor_values[factor] for factor in FACTORS)
        scored.append({
            "name": item["name"],
            "momentum": round(float(item["excess20"]), 2),
            "excess60": round(float(item["excess60"]), 2),
            "score": round(score, 1),
            "breadth": round(breadth, 1),
            "volume_score": round(volume, 1),
            "rank20": round(rank20, 1),
            "rank60": round(rank60, 1),
        })
    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored
