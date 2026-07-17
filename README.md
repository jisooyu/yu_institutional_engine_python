# Institutional Flow Engine — Python

A Python/Dash implementation of the Institutional Flow Dashboard for early detection of sector and risk rotation.

## Included

- Sector universe: Semiconductor, AI, Software, Cyber Security, Power, Defense
- Relative strength for SMH/SPY, SOXX/QQQ, QQQ/SPY, XLI/SPY, XLK/SPY
- Volume spike and distribution-day monitoring
- 52-week highs/lows, advance/decline, 50DMA and 200DMA breadth
- ETF fund-flow tape
- Sector rotation map and ranking view
- AI supply-chain leadership stack
- Responsive institutional dark-terminal interface

The bundled values are deterministic demo data and are clearly labeled in the interface.

## Run on Windows

Double-click `run_dashboard.bat`, or run:

```powershell
python -m pip install -r requirements.txt
python app.py
```

Then open <http://127.0.0.1:8050>.

## Connect live data

Replace the constants and figure data functions in `app.py` with your preferred market-data provider. The UI and callbacks can remain unchanged.
