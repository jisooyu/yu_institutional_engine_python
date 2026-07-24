"""Minimal validation that does not require a live network response."""

from app import app, app_layout
from etf_holdings import ETF_SOURCES, FALLBACK_HOLDINGS
from market_data import BREADTH_UNIVERSE, ETF_NAMES, SECTOR_ETFS, SECTOR_ETF_GROUPS, _fallback


def main() -> None:
    assert app.title == "Institutional Flow — Live Rotation Intelligence"
    assert len(SECTOR_ETFS) == 6
    assert set(SECTOR_ETF_GROUPS) == set(SECTOR_ETFS)
    assert set(ETF_SOURCES) == set(SECTOR_ETFS)
    assert set(FALLBACK_HOLDINGS) == set(SECTOR_ETFS)
    assert all(len(tickers) >= 4 for tickers in SECTOR_ETF_GROUPS.values())
    assert all(len(leaders) == 8 for leaders in FALLBACK_HOLDINGS.values())
    assert len(ETF_NAMES) >= 30
    assert len(BREADTH_UNIVERSE) >= 50
    layout = app_layout(_fallback("Offline smoke-test fixture"))
    assert layout is not None
    print("Smoke test passed: dashboard layout and datasets are available.")


if __name__ == "__main__":
    main()
