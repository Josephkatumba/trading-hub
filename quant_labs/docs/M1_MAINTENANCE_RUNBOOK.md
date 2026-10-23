# MT5 history maintenance plan

**Status:** prepared and tested, **not executed**. The window needs CEO approval, because it stops the engine and restarts the MT5 terminal.

## Why

The engine's MT5 terminal is `C:\Program Files\MetaTrader 5 IC Markets Global\terminal64.exe`, server `ICMarketsSC-Demo`. Its `config\common.ini [Charts] MaxBars=100000` caps every history request at the newest 100,000 candles. Two research limits follow from that:

| Limit today | Effect |
|---|---|
| M1 history only from Jul 2026 (about 3 months) | M5 research has no train or validation split. M15 trades that touch stop and target in the same candle before Jul 2026 can't be resolved and stay AMBIGUOUS. |
| Shared M15/H1/H4 data starts Aug 2024, and every split has been seen by three labs | **No untouched historical holdout exists.** Every strategy's "test" result is on previously exposed data. |

The broker's history is already stored locally by the terminal (`bases\ICMarketsSC-Demo\history\<symbol>\<year>.hcc`):
* 2023–2026 for every TradeDen symbol except USDCAD (2025–2026);
* XAUUSD and XAGUSD back to 2021;
* GER40 and NAS100 under the broker names DE40 and USTEC.

It is not reconstructed from those files. It is requested through the normal MT5 API once the cap is raised.

## Instruments and priority

1. **XAUUSD, BTCUSD:** the Gold & Bitcoin research priority, and the Category B candidates (crypto momentum).
2. **NAS100 (USTEC), US500, GER40 (DE40):** Index Trend-Day, a Category B candidate.
3. ETHUSD and the FX majors and crosses (EURUSD, GBPUSD, GBPJPY, USDJPY, AUDUSD, NZDUSD, USDCHF, EURJPY, USDCAD), and XAGUSD: the other monitored strategies. The whole watchlist is fetched in one pass.

## Expected research benefits

1. **An untouched pre-sample holdout.** Roughly 2022/2023 → 13 Aug 2024 (`--presample-start`), all timeframes, saved as a **separate** dataset. No lab has seen it. Each Category B candidate (Index Trend-Day 0.2.0, Crypto Trend Breakout 0.3.0, Codex BTCUSD Trend Reclaim R4, with the R4 regime question) can then be evaluated **once**, pre-registered, with no tuning. This is the only way to get independent historical evidence; otherwise it has to come from months of forward paper trading.
2. **Deeper M1** (from about 2024-10): M5 strategies get train and validation splits, and M15 same-candle stop/target ties become resolvable.

## Current limitations that remain

* The pre-sample period is a different regime era: gold and bitcoin were not in the same 2024–26 bull phase. That's a feature for robustness, but it makes the comparison harder to interpret.
* Broker CFD spreads in older data may differ from today's.
* Historical swap rates are still unknown, so overnight index trades stay unscoreable.
* Treasury yields, the economic calendar, and BTC funding and open interest are not part of MT5 history.

## Potential downtime

About **30–60 minutes** of engine downtime:
* stop the engine;
* change the setting and restart MT5, then wait for the connection;
* run the download (16 symbols × 5 timeframes; mostly M1 volume, roughly 750k–1.5M bars per symbol);
* restart the engine.

**Schedule it at a weekend**, after Friday 21:00 UTC and before Sunday 21:00 UTC. FX, metals and indices are closed then, so nothing can be missed. Crypto models miss a few weekend H4/M15 evaluations; they are counted as missed, never replayed.

## Backup procedure

1. Already done: the terminal `config` folder was backed up and hash-verified at `%LOCALAPPDATA%\TradeDen\mt5_config_backup\20261019T235925Z\` (`BACKUP_MANIFEST.json`). Take a fresh copy in the window if more than a day has passed.
2. The existing research cache (`backend/data/research/bars`) and the shared dataset `bf130602…` are **never modified**. New data goes to new folders and new content-addressed datasets.
3. Record `GET /api/quant-labs/live` and `GET /api/health` before stopping.

## Procedure

1. **Preflight** (engine running, read-only): `python -m quant_labs.maintenance.m1_history_refresh`. Confirm no research job is RUNNING with `python -m quant_labs.cli status`.
2. **Stop the engine only:** close the "Trading Hub - Market Engine" window, or run `STOP TRADING HUB.bat`. Confirm port 8000 is closed.
3. **In MT5:**
   * Tools → Options → Charts → **Max. bars in chart = Unlimited** (or at least 2,000,000).
   * Click OK, close MT5 completely, reopen it, and wait for `ICMarketsSC-Demo` to connect.
4. **Fetch:**
   ```
   python -m quant_labs.maintenance.m1_history_refresh --apply --start 2024-10-15 --presample-start 2022-01-01
   ```
   * The tool refuses to run if the engine answers or if `maxbars` is below 1,000,000.
   * It writes `backend/data/research/bars_m1_extended_<UTC>` and `bars_presample_<UTC>`, plus two new datasets, and prints `REFRESH_REPORT.json`.
5. **Restart the engine** with `START TRADING HUB.bat`, or just the engine.

## Rollback procedure

* **MT5 setting:** restore `common.ini` from the backup (or set Max bars back to 100000) and restart MT5. Nothing else depends on the setting.
* **Data:** the new caches and datasets are inert until adopted, so leave them in place or delete them. The existing dataset, ledger and live registry are untouched by design.
* **Engine:** the start scripts are unchanged; restarting returns to the current state.

## Post-maintenance verification

* `REFRESH_REPORT.json`:
  * every symbol and timeframe has bars;
  * the first dates are as expected (pre-sample starts on or before 2023-01 where the broker has it);
  * **`differing_minutes` = 0** wherever new and old M1 overlap;
  * gaps are reported and none are filled;
  * the pre-sample ends before 2024-08-14.
* After restart, check:
  * `/api/health`: MT5 connected, execution disabled;
  * `/api/quant-labs/live`: health OK, 16 strategies, delivery `EXPERIMENTAL_APPROVED` for the two candidates only, no errors;
  * the dashboard loads;
  * the next 23:00 EAT report arrives.
* **Do not adopt** a dataset if any check fails. Adoption, and the one-time pre-registered holdout evaluation, is a separate step.
