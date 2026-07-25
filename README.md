# Institutional Rotation Proxy Engine — Python

A Python/Dash market-monitoring dashboard that infers sector rotation and participation from daily price, volume, cross-asset ratios, and official ETF holdings breadth.

This is deliberately described as a **proxy engine**. It does not identify the buyer or seller and does not treat secondary-market ETF turnover as creation/redemption flow.

## What changed in Phase 1.2

- Added a point-in-time historical backtest and model-governance pipeline.
- Recalculates 20/60-day relative strength, breadth, and relative volume at each historical rebalance date.
- Measures subsequent 20-session excess return, cross-sectional information coefficient, signal persistence, hit rate, and one-way turnover.
- Selects candidate weights only on the first 65% of dates, with a four-rebalance embargo before the held-out period.
- Includes 10bp transaction costs and chooses the training candidate by net information ratio.
- Compares the candidate with the documented composite and a 60-day-only benchmark.
- Promotes a candidate only when it weakly dominates the documented model on all four held-out criteria: net excess return, net information ratio, information coefficient, and turnover.
- Persists the active model, rejected candidate, metrics, parameters, periods, and limitations in `rotation_model.json`.
- Shows `BACKTEST PROMOTED`, `VALIDATED DEFAULT`, or `DEFAULT` beside the live rotation chart.

Phase 1.1 also:

- Renamed the headline signal from `Institutional Bias` to `Price / Volume Bias`.
- Labels accumulation and distribution as proxies, not observed institutional transactions.
- Replaced the unstable raw advance/decline ratio with:
  - normalized advance-minus-decline breadth in the `-1` to `+1` range;
  - a Laplace-smoothed A/D ratio retained in the snapshot for analysis.
- Relabeled the 0.5% tolerance bands as `NEAR 52-WEEK HIGH/LOW`.
- Rebuilt sector rotation scores from four components:
  - 35% cross-sectional rank of 20-day excess return;
  - 30% cross-sectional rank of 60-day excess return;
  - 20% official ETF-holdings breadth;
  - 15% benchmark ETF relative-volume participation.
- Expanded risk-regime classification beyond QQQ/SPY and breadth. It now combines:
  - QQQ/SPY;
  - HYG/LQD;
  - IWM/SPY;
  - XLY/XLP;
  - VIX/VIX3M term structure;
  - broad-market participation as a separate composite weight.

## Dashboard coverage

- Sector universe: Semiconductor, AI, Software, Cyber Security, Power, Defense
- Relative-strength monitoring for sector ETFs and major benchmarks
- Volume spike and O'Neil-style distribution-day proxy
- Near-52-week highs/lows and 50/200-day moving-average breadth
- Equal-weight and official ETF-weighted holdings breadth
- Multi-factor sector rotation map and ranking view
- Directional signed-dollar-turnover monitor
- Top-eight official ETF-holding leadership stack
- Five-signal cross-asset risk regime
- Backtest-governed model loading with a safe documented fallback

## Methodology

### Rotation model and governance

The live score and the backtest share the same implementation in `rotation_model.py`. The four factor inputs are always normalized to sum to one. A persisted `rotation_model.json` controls the live model; if that file is absent or invalid, the documented 35/30/20/15 model is used.

`backtest.py` uses weekly rebalances and a 20-session forward horizon by default. Features at date `t` use only observations available at or before `t`. The last four training rebalances are embargoed so their forward-return windows do not overlap the validation start.

Candidate selection never reads validation performance. It searches the 0.1 weight grid and maximizes training net information ratio after transaction costs. The held-out period is used only as a promotion gate. Failure at the gate leaves the current live model unchanged and records the rejected candidate for auditability.

### Latest five-year run

Data through 2026-07-24 produced the following held-out results for 2025-02-12 through 2026-06-23:

| Model | Net 20D excess | Net information ratio | IC | Persistence | One-way turnover | Hit rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Active documented composite | 1.5134% | 0.5174 | 0.0979 | 0.7868 | 0.2826 | 65.22% |
| Training-selected candidate | 0.6702% | 0.2100 | 0.0508 | 0.1229 | 0.6594 | 53.62% |
| 60-day rank only | 1.3098% | 0.4258 | 0.0819 | 0.8984 | 0.1957 | 63.77% |

The training-selected candidate was 20% breadth and 80% volume. It failed every held-out promotion criterion, so it was rejected and the documented composite remains active. This is intentional: the backtest may refuse to change the live model.

### Price/volume bias

A distribution day is a session where the benchmark closes lower while volume exceeds the previous session. The dashboard reports an `ACCUMULATION PROXY` only when the recent distribution-day count is low and normalized breadth is non-negative. This is an inference, not investor-class order-flow data.

### Directional turnover

```text
dollar_turnover = adjusted_close × exchange_volume
directional_turnover = sign(daily_return) × dollar_turnover
```

Directional turnover measures trading activity with price direction. It is **not** ETF net flow, shares-outstanding change, NAV-based creation/redemption, or proof of institutional activity.

### Breadth

Official holdings and weights are downloaded from VanEck, Global X, iShares, and First Trust. For each benchmark ETF, the engine calculates equal-weight and ETF-weighted participation above the 50-day and 200-day moving averages.

The normalized advance-minus-decline measure is:

```text
(advances - declines) / (advances + declines)
```

This avoids extreme values when there are no declining securities.

### Risk regime

Four ratios are positive when their 20-session trend is rising: QQQ/SPY, HYG/LQD, IWM/SPY, and XLY/XLP. VIX/VIX3M is positive for risk appetite when the current ratio is below 1. Available cross-asset signals receive 80% of the composite weight; broad-market breadth receives 20%.

- `RISK-ON`: composite score at least 65
- `RISK-OFF`: composite score at most 35
- `NEUTRAL`: values between those thresholds

Missing signals are excluded transparently from the available-signal count.

## Data reliability

- Daily adjusted prices and exchange volumes come from `yfinance`.
- Market data is cached for five minutes.
- Official holdings are cached for 18 hours.
- If an issuer refresh fails, the last official cache is retained.
- A labeled fallback holdings basket is used only when no official cache exists.
- Yahoo Finance data may be delayed and is intended for research/informational use.

## Run on Windows

Double-click `run_dashboard.bat`, or run:

```powershell
python -m pip install -r requirements.txt
python app.py
```

Then open <http://127.0.0.1:8055>.

Run the offline validation with:

```powershell
python smoke_test.py
```

Recalibrate and validate the model with:

```powershell
python backtest.py --years 5 --rebalance 5 --horizon 20 --train-fraction 0.65 --top-k 3 --cost-bps 10
```

The command rewrites `rotation_model.json`. Review its promotion decision and limitations before committing a newly promoted model.

## Backtest limitations

- Historical breadth applies today's top ETF holdings to the past and therefore has survivorship bias.
- Yahoo Finance adjusted prices and volumes are suitable for research, not execution-grade simulation.
- The held-out period is one market regime and does not guarantee future performance.
- Weekly observations use overlapping 20-session forward returns, so they are not statistically independent.
- Results are cross-sectional ETF excess returns, not a complete account-level performance simulation.

## Roadmap toward more direct flow measurement

The next data layer should prioritize daily ETF shares-outstanding and NAV changes, followed by CFTC COT positioning, FINRA short-volume context, FRED high-yield spreads, and options/futures positioning. Until those sources are licensed and integrated, the project should remain described as a price/volume/breadth proxy engine.
