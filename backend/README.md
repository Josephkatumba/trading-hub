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
3. From this folder, install requirements and run (or double-click `start_engine.bat`):
   python -m pip install -r requirements.txt
   python -m uvicorn main:app --host 127.0.0.1 --port 8000

4. The endpoint will be available at http://127.0.0.1:8000/api/market/radar

Port 8000 is the single canonical engine port. The dashboard (`src/engine.js`)
connects to `http://127.0.0.1:8000` by default, so no URL needs to be edited.

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
   `python -m uvicorn main:app --host 127.0.0.1 --port 8000`
4. For a first local test, open:
   `http://127.0.0.1:8000/api/health`
5. Open Trading Hub → Market Radar. With the engine running it shows **LIVE MT5 ENGINE**;
   otherwise it shows **ENGINE OFFLINE** and no market data. Simulated demo setups are
   off by default (enable for UI work only with `localStorage.th_radar_demo = "1"` or
   `VITE_RADAR_DEMO=1`), and are always labelled DEMO MODE / SIMULATED SETUPS.

For phone access, the engine needs a reachable HTTPS endpoint. Do not expose MT5 credentials or add trading credentials to the frontend. This V1 connection is market-data/scanner only, with execution intentionally disabled.

## Security: local-only by default

- The engine binds to `127.0.0.1` (loopback), so other machines cannot reach it.
- CORS is an explicit allowlist (`TRADING_HUB_CORS_ORIGINS`, see `.env.example`);
  `*` is rejected. The default allows only the local Vite dev/preview origins.
  To use the GitHub Pages dashboard against a local engine, add its origin, e.g.
  `https://<your-user>.github.io` (some browsers additionally block public pages
  from calling `127.0.0.1`).
- `/api/health` reports connection state (`mt5_status` CONNECTED/OFFLINE,
  `data_freshness` FRESH/STALE, `bridge.status` CONNECTED/STALE/OFFLINE) but never
  the MT5 login, server, balance, equity or local file paths.

### Before exposing the engine beyond this machine

Do not bind to `0.0.0.0` or put the engine behind a public URL until all of these exist:

1. **Authentication** on every route (at minimum a secret bearer token checked
   server-side; better, per-user auth), because the API has no auth today.
2. **TLS** via a reverse proxy (Caddy/nginx/Cloudflare Tunnel) — never plain HTTP.
3. **Write routes locked down**: the `POST` lifecycle/trade-outcome routes change
   persisted research data and must require auth (or be disabled remotely).
4. **Rate limiting**: each radar request triggers a full MT5 scan.
5. **CORS** set to the exact dashboard origin(s) only.
6. **Review of every response** for account data (setup/observation records
   include broker symbol names; confirm nothing identifies the account).
7. **Firewall**: expose only the proxy port, never 8000 directly.

## Observation store and index

`data/*.jsonl` are the canonical, append-only records. `jsonl_index.py` keeps a
derived index (byte offsets + small per-row summaries) so radar, episodes,
performance, setup detail/history and analysis no longer re-read the whole
observation log per request.

- The index is refreshed on every query by reading only newly appended bytes, so
  it never lags the JSONL and does not change observation frequency.
- A sidecar is persisted in `data/.index/` (git-ignored). It is safe to delete at
  any time: a missing, corrupt, tampered, schema-changed or mismatched sidecar is
  rebuilt from the JSONL (about 0.7 s for 81 MB); a stale one catches up
  incrementally.
- Incomplete trailing lines are not indexed until finished, and every append first
  terminates any half-written line so it cannot swallow the next record.
  Unparseable lines are counted in `/api/health` → `storage.setup_observations.jsonl.index`.
- `tests/test_observation_index.py` proves the indexed queries return the same
  results as the former full scans (frozen in `tests/legacy_observations.py`).

