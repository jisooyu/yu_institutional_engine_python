# Institutional Flow Engine — Python

A Python/Dash implementation of the Institutional Flow Dashboard for early detection of sector and risk rotation, calculated from live daily market data.

## Included

- Sector universe: Semiconductor, AI, Software, Cyber Security, Power, Defense
- Relative strength for SMH/SPY, SOXX/QQQ, QQQ/SPY, XLI/SPY, XLK/SPY
- Volume spike and distribution-day monitoring
- 52-week highs/lows, advance/decline, 50DMA and 200DMA breadth
- Benchmark ETF activity tape
- Sector rotation map and ranking view
- Official benchmark-ETF holdings breadth and top-weight leadership stack
- Responsive institutional dark-terminal interface

## Data source and calculations

- Daily adjusted prices and exchange volumes are fetched through `yfinance`.
- Relative-strength series are calculated from live ETF closing-price ratios.
- Volume spike and distribution days are calculated from SMH and SPY histories.
- Each sector uses one benchmark ETF: SMH, BOTZ, IGV, CIBR, GRID, or ITA.
- Holdings and weights are downloaded from the ETF issuer's official VanEck, Global X, iShares, or First Trust data.
- Equal-weight and ETF-weighted breadth are calculated across all holdings with available price history.
- Leadership stacks show the eight largest official ETF holdings by portfolio weight, with live 1D and 20D price momentum.
- ETF activity is **signed dollar turnover**, a transparent proxy. It is not ETF creation/redemption flow.
- Market data is cached for five minutes and official holdings for 18 hours. If an issuer refresh fails, the last official cache is retained; a clearly labeled fallback basket is used only when no official cache exists.

Yahoo Finance data is intended for informational/research use and may be delayed. Verify critical decisions against an authorized market-data feed.

## Run on Windows

Double-click `run_dashboard.bat`, or run:

```powershell
python -m pip install -r requirements.txt
python app.py
```

Then open <http://127.0.0.1:8055>.

## Connect live data

Replace `fetch_snapshot()` in `market_data.py` with your licensed market-data provider. The UI and callbacks can remain unchanged.
