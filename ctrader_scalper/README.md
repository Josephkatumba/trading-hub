# TradeDen Scalper (tds-1.0)

A cTrader cBot for IC Markets **demo** accounts, plus the Python simulator,
walk-forward optimiser, Trading Hub journal integration and live dashboard
built around it.

> **Evidence status (2026-11-23): NO EDGE. Forward experiment `fwd-xau-001` is prepared, not running.**
> - Research rejected tds-1.0 and found no validated gold edge ([V2](../docs/EDGE_DISCOVERY_V2_REPORT.md), [V3](../docs/TRADEDEN_V3_REPORT.md)).
>   `ExecutionUnlocked` stays `false`.
> - A separate, demo-only forward experiment measures real broker execution against the simulator.
>   It is limited to XAUUSD, 0.25% risk, 1 position, 1% daily loss and a halt after 2 losses.
> - Orders require your activation code and exact demo account number. See
>   [forward/ACTIVATION_CHECKLIST.md](forward/ACTIVATION_CHECKLIST.md).

## What is where

| Path | What it is |
|---|---|
| `cbot/TradeDenScalper.cs` | The cBot. Single file, C# 5 syntax, compiles in cTrader. |
| `cbot/tests/SignalParity.cs` | Harness that runs the cBot's signal core on exported bars. |
| `engine/` | Python reference implementation: indicators, signals, cost-aware simulator, walk-forward. |
| `tests/` | Simulator risk-rule tests and the C# ↔ Python parity test. |
| `reports/` | Walk-forward reports (JSON) and out-of-sample trade lists (CSV). |
| `install_cbot.ps1` | Copies the cBot into `Documents\cAlgo\Sources\Robots`. |
| `build_check.ps1` | Offline compile check against cTrader's `cAlgo.API.dll`. |
| `../backend/scalper_journal.py` | Read-only API: `/api/scalper/summary`, `/trades`, `/daily-report`. |
| `../scalper.html`, `../src/scalper/` | Live demo dashboard. |

## Install and start (about 5 minutes)

1. Close any cBot editor tabs in cTrader, then run:
   ```powershell
   powershell -ExecutionPolicy Bypass -File ctrader_scalper\install_cbot.ps1
   ```
2. In cTrader open **Algo → cBots → TradeDenScalper** and press **Build**.
   If it doesn't appear, restart cTrader. As a fallback, create a new cBot
   named `TradeDenScalper`, paste the contents of `cbot/TradeDenScalper.cs`,
   and press Build.
3. Check that the account selector shows your **IC Markets demo** account.
4. Add an instance on any chart, ideally XAUUSD M5. Leave the defaults and
   start it. With default parameters it runs SignalsOnly (shadow). To place
   demo orders, follow [forward/ACTIVATION_CHECKLIST.md](forward/ACTIVATION_CHECKLIST.md). cTrader asks you to grant **Full Access**; the cBot needs it to
   write its journal file. It does not use the access for anything else.
5. Optional, recommended: set **Expected demo account number** to your demo
   account number. The cBot then refuses to run on any other account.
6. Restart the Trading Hub engine (`STOP` then `START TRADING HUB.bat`) so it
   loads the new API routes. Then open
   `http://localhost:5173/trading-hub/scalper.html`.

Start **one instance only**. It trades every symbol in its `Symbols`
parameter, and the global limits (2 positions, daily loss) are enforced
across instances anyway.

## Data collector (read-only, no orders)

`cbot/TradeDenCollector.cs` is a separate, **data-only** cBot. It contains no order code (enforced by
`tests/test_collector.py`) and refuses to run on a live account unless "Allow live account" is set.
It writes to `Documents\TradeDenScalper\collector\`:

| File | Content |
|---|---|
| `status.json` | rewritten every 5 s: account (masked number, balance, equity, margin), bid/ask per symbol, open positions |
| `account-YYYYMMDD.jsonl` | balance/equity every 60 s |
| `deals.jsonl` | closed deals from cTrader history (all at start, then each close) |
| `bars\<SYMBOL>\M1-YYYYMMDD.jsonl` | closed M1 bars (1440 backfilled at start) |

Default symbols: XAUUSD, BTCUSD, ETHUSD, NAS100 (USTEC), US500, GER40 (DE40), GBPJPY, EURUSD, GBPUSD.
Symbols the broker doesn't offer are listed in `missing_symbols`.

Install: `powershell -ExecutionPolicy Bypass -File ctrader_scalper\install_cbot.ps1 -Bot TradeDenCollector`,
then in cTrader **Algo → cBots → TradeDenCollector → Build**, add an instance on any chart, grant
**Full Access** (needed to write the files) and Start. Run one instance only.

The engine reads it read-only at `/api/ctrader/status`, `/api/ctrader/bars?symbol=XAUUSD&limit=500`,
`/api/ctrader/deals` and `/api/ctrader/equity` (`backend/ctrader_feed.py`). `connected` is true only while
`status.json` is under 30 s old.

## Safety contract (enforced in code)

- `Account.IsLive == true` → the cBot logs a safety record and stops at
  start. It checks again immediately before every order.
- An optional exact account-number match.
- Every order is sent with a stop-loss and take-profit. If a filled position
  has no stop, the cBot closes it at once and logs a safety event.
- Slippage is bounded with `ExecuteMarketRangeOrder`, by default to 0.1 × M5 ATR.
- Hard ceilings that no parameter can raise: risk ≤ 1% per trade (default
  0.5%), ≤ 2 positions, daily loss ≤ 3%, stop after ≤ 3 consecutive losses
  for the rest of the UTC day.
- The daily loss budget counts **open risk to stops**, not just realised P&L.
  An equity kill switch closes the bot's positions if equity falls to the
  day's limit.
- One position per symbol. No martingale, averaging or scaling in. A
  cooldown follows each exit.
- The cBot never changes account settings and never moves funds.

## Strategy (identical in C# and Python)

Decisions happen only on **closed** bars, at each M5 close:

- **M15 bias:** close vs EMA50, and the EMA50 slope over 3 bars must agree.
- **M5 trend:** EMA9 vs EMA21 must agree with the bias. EMA21 vs EMA50 adds score.
- **Setups:**
  - *Breakout-retest (BRT):* close beyond the 2-hour high or low by 0.1 ATR,
    then within 6 bars a retest within 0.25 ATR of the level, closing back
    beyond it with a directional candle.
  - *Trend pullback (PB):* the bar touches the EMA21 zone, closes back
    beyond EMA9 with a directional candle, and RSI turns up from ≤ 52 into 45–70.
- **Hard filters:** rollover, weekend and Friday-close windows; an M1 spike
  filter (last M1 range > 3 × M1 ATR); spread ≤ 0.15 × M5 ATR; stop distance
  0.5–3 ATR; total cost ≤ 25% of risk.
- **Quality score (0–100):** EMA stack 20, RSI zone 15, ATR regime 15,
  spread/ATR 15, candle quality 15, session 10, setup 10. Only scores
  ≥ `MinScore` (default 80) trade.
- **Exits:** stop beyond the setup's structure plus a buffer; target at
  `RewardRisk` × risk; time exit after `MaxHoldMinutes`; optional breakeven.

The cBot and the Python engine generate **identical candidates**, checked bar
by bar on real data (`tests/test_parity.py`: XAUUSD 1500/1500, EURUSD
1363/1363, BTCUSD 1466/1466, same scores and stops).

## Simulation and cost model

- Fills use M1 bid bars with the ask derived from the spread. Market entry
  is at the next M1 open. If the stop and target are hit in the same minute,
  the stop counts first. A gap through the stop fills at the open.
- Spread is the bar spread, floored at XAU $0.08, BTC $6, EURUSD 0.2 pip,
  GBPUSD 0.4 pip. Slippage per market fill is XAU $0.03, BTC $3, FX 0.2 pip.
  Commission is $3 per $100k notional per side.
- Portfolio rules match the cBot exactly.
- **Sanity check:** random-direction entries with zero costs score about 0R,
  so the simulator isn't biased toward losses.

Re-run with:
```powershell
cd ctrader_scalper; python -c "from engine.market import export_from_mt5; export_from_mt5()"
python -m engine.walkforward XAUUSD BTCUSD EURUSD GBPUSD --portfolio
python -m unittest discover -s tests
```

## Results

Walk-forward setup: 288 parameter configs (reward:risk, stop buffer, minimum
score, setups, breakeven, hold time). Each config is selected on a 6-week
train window and then traded on the next, unseen 2-week window. Only the
test windows count. Starting equity $10,000, 0.5% risk.

| Symbol | Data (UTC) | OOS trades | Win % | PF | Exp. R | t | Return | Max DD | Profitable configs in-sample |
|---|---|---|---|---|---|---|---|---|---|
| XAUUSD | 13 Aug – 23 Nov 2026 | 146 | 34.9 | 0.59 | −0.26 | −3.04 | −17.5% | 17.9% | 43 / 288 |
| BTCUSD | 14 Sep – 23 Nov 2026 | 60 | 38.3 | 0.81 | −0.12 | −0.81 | −3.5% | 6.2% | 25 / 288 |
| EURUSD | 18 Aug – 23 Nov 2026 | 58 | 32.8 | 0.49 | −0.32 | −2.19 | −9.1% | 11.0% | 0 / 288 |
| GBPUSD | 18 Aug – 23 Nov 2026 | 44 | 29.5 | 0.67 | −0.24 | −1.23 | −5.2% | 5.4% | 17 / 288 |
| **Portfolio** | | **227** | 32.6 | **0.54** | **−0.30** | **−4.23** | **−28.0%** | 28.0% | |

What this shows:

- **The signals have no gross edge.** With costs set to zero, the untuned
  default config scores −0.02R per trade on XAUUSD and 0.00R on EURUSD.
  Spread and commission then make it negative.
- **Optimisation overfits.** Up to 43 of 288 configs looked profitable
  in-sample, but the configs chosen on each train window lost on the
  following test window. Their out-of-sample results were worse than the
  untuned default (XAUUSD: −0.26R vs −0.07R).
- **The breakdowns don't point to a fix.** No setup or session was
  significantly positive out-of-sample. A few small cells were positive,
  such as BTCUSD overlap, 15 trades at +0.42R. That is too few trades to
  separate from noise, and trading on such cells would be data mining.
- The data covers about 3 months, because MT5's API is capped at 100k M1
  bars. That is short, but the losses are consistent across instruments.

**What would change the verdict:** forward demo trades logged by the cBot
with cTrader's real fills and commissions, at least 100 of them, judged by
expectancy and t-stat rather than win rate. The dashboard shows this
live. Any new strategy idea should be written down *before* testing, run
once through `engine.walkforward`, and counted as another trial.

## Journal format

`Documents\TradeDenScalper\journal\journal-YYYYMMDD.jsonl`, one JSON object per line:

| `event` | Written when | Key fields |
|---|---|---|
| `start` | cBot starts | `demo_verified`, `is_live`, masked `account`, broker, currency, leverage, params |
| `signal` | candidate seen | `decision` (`opened`/`skipped`/`signals_only`/`order_failed`), `reason`, score and components, planned and actual entry, stop, target, slippage |
| `close` | position closed | cTrader `NetProfit`, `GrossProfit`, `Commissions`, `Swap`, exit price, `r_multiple`, `balance_after` |
| `heartbeat` | every 60 s | balance, equity, realised today, open risk, daily limit, consecutive losses, halt state, open positions |
| `halt` / `safety` / `time_exit` / `breakeven` / `stop` | as named | reason |

Backtests run inside cTrader write to `backtest-<run>.jsonl` instead. The
dashboard ignores those.
