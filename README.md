# TRADeden 🌿

A market intelligence garden that watches the market for you. (Formerly "Trading Hub".)

Trading Hub is being built as a trading intelligence platform: one workspace for accounts, execution data, analytics, AI insights, social trading, and eventually a marketplace.

## Product direction

Account connection → trade normalization → analytics → trading fingerprint → AI analyst → integrations → social network → marketplace.

## Current prototype

- Sophisticated trading command center UI
- Multi-account workspace concept
- Structured trade data engine
- CSV trade-history importer
- Browser persistence with localStorage
- Calculated P&L, win rate, profit factor, average R, drawdown, best instrument and session
- Analytics and AI-intelligence views

## Run locally (Windows)

1. Open MetaTrader 5 and log in.
2. Double-click `START TRADING HUB.bat`. It starts the market engine on
   `http://127.0.0.1:8000` (loopback only) and the dashboard on
   `http://localhost:5173/trading-hub/`. `STOP TRADING HUB.bat` stops both.
3. Market Radar connects to `http://127.0.0.1:8000` by default; no URL needs editing.
   Port 8000 is the only engine port. See `backend/README.md` for details and for
   what must change before exposing the engine beyond this machine.

Tests: `npm test` (frontend), `cd backend && python -m unittest discover -s tests`
(backend; run `test_scanner_quality.py` from the repo root with `PYTHONPATH=backend`).

## The TRADeden Garden (Market Radar)

The radar page is the Garden: a light, card-first view of every setup the engine is
watching, with a small 3D garden that mirrors the backend lifecycle.

| Garden | Backend lifecycle (authoritative, unchanged) |
|---|---|
| 🌱 Growing | DETECTED, DEVELOPING |
| 🌿 Taking Shape | CONFIRMING |
| 🌸 Bloomed | CONFIRMED |
| 🌳 Active | ACTIVE |
| 🍂 History | INVALIDATED, EXPIRED, RESOLVED |

- Cards show only API values; missing levels read "Not yet calculated" (entry/stop/
  target appear only once the engine has computed both a stop and a target).
- The Analyst panel restates recorded, rule-based evidence
  (`deterministic-setup-analyst-v1`); it is not an AI/ML prediction.
- No execution buttons: View setup / View evidence / View analysis / Track setup
  (tracking is a local, per-browser pin — it never writes to the engine).
- 3D (Three.js, lazily loaded) is used on desktop when WebGL is available. A 2D CSS
  garden is used on screens under 720px, with Data Saver, on low-memory devices, or
  when WebGL is missing. `prefers-reduced-motion` renders static frames.
  Force a mode with `localStorage.th_garden_3d = "0"` (2D) or `"1"` (3D).
- Code: `src/garden/` (`gardenModel.mjs`, `gardenCards.mjs` are pure and tested;
  `gardenScene.mjs` is the 3D scene; `gardenMount.mjs` chooses and falls back).

## Data honesty

- **Sessions.** MT5 exports use the broker's server time, not UTC. Sessions
  (London 08-13 UTC, New York 13-18 UTC, otherwise Asia) are only classified after
  the timestamp is converted with an explicit broker timezone (IANA name, e.g.
  `Europe/Athens`, or `UTC`) chosen in the import dialog. Without it, sessions show
  as **Unverified**; raw timestamps are never changed. DST gaps/overlaps are
  rejected rather than guessed. Logic: `src/tradeTime.mjs` (mirrors
  `backend/market_time.py`).
- **Imports are idempotent.** Re-importing a file or overlapping exports never
  duplicates trades (IDs come from the id/ticket column or a content hash);
  existing trades are never modified; bundled sample data is kept separate.
- **Risk and R.** MT5 history exports do not contain the stop loss at entry, so
  imported trades have no risk. Risk, R multiples and risk consistency are shown as
  **Unavailable** rather than estimated. Real risk metrics require, per trade:
  the initial stop-loss price (or the risk amount directly), entry price, volume,
  the instrument's contract size / tick value in account currency, and ideally
  commission and swap. Supplying `Risk` (money) and/or `R` columns in the CSV
  enables them.
- **Market Radar demo data** is off by default. When enabled for UI work it is
  labelled DEMO MODE / ENGINE OFFLINE / SIMULATED SETUPS on every card.

## Next build targets

1. Trade detail / Trade Intelligence drawer
2. Real equity curve from imported trades
3. Filters by account, instrument, session and date
4. Trading fingerprint
5. AI analyst based on real trade history
6. MT5 / cTrader / futures account integrations
7. Trader profiles and verified social features
8. Prop-firm and broker marketplace

The long-term principle is simple:

**The trading account becomes the journal. The data becomes the coach.**
