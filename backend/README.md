# Trading Hub Market Engine

This folder is the backend foundation for the Market Radar.

## What it does now

- Connects to a locally running MetaTrader 5 terminal when the MetaTrader5 Python package is available.
- Reads live bid/ask/last quotes for the Trading Hub watchlist.
- Exposes GET /api/market/radar for the frontend.
- Exposes GET /api/health for a simple health check.

## Run locally

1. Install Python 3.11+ and MetaTrader 5 on the same Windows machine.
2. Log into the MT5 account and keep the terminal running.
3. From this folder, install requirements and run:
   python -m pip install -r requirements.txt
   uvicorn main:app --host 0.0.0.0 --port 8000

4. The endpoint will be available at http://localhost:8000/api/market/radar

## Next engine layer

The backend intentionally stops at market quotes for this commit. The next layer will calculate:
1. candles and ATR
2. swing structure
3. trendlines
4. support/resistance
5. London/New York session state
6. confirmation rules
7. transparent 0-100 setup scoring

Do not enable automated execution yet. The first objective is reliable detection and paper/simulation validation.

## Connect Trading Hub to the live dashboard

The GitHub Pages dashboard cannot run MetaTrader 5 itself. Run this backend on the Windows machine/VPS where the MT5 terminal is installed and logged into the broker account.

1. Open MetaTrader 5 and log into the intended account.
2. From this folder install dependencies:
   `python -m pip install -r requirements.txt`
3. Start the engine:
   `uvicorn main:app --host 0.0.0.0 --port 8000`
4. For a first local test, open:
   `http://127.0.0.1:8000/api/health`
5. In Trading Hub → Market Radar, enter the engine's reachable HTTPS address and press **Connect**.

For phone access, the engine needs a reachable HTTPS endpoint. Do not expose MT5 credentials or add trading credentials to the frontend. This V1 connection is market-data/scanner only, with execution intentionally disabled.
