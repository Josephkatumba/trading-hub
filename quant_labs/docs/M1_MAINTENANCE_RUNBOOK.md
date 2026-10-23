# M1 history maintenance runbook

**Status:** prepared, not executed. The actual window needs **separate CEO approval**, because it stops the running TradeDen engine and restarts the MT5 terminal.

## Why

Research M1 history currently covers only Jul–Oct 2026, because the engine's MT5 terminal caps API history at `MaxBars=100000`. The terminal is `C:\Program Files\MetaTrader 5 IC Markets Global\terminal64.exe`, server `ICMarketsSC-Demo`, and the setting is in `config\common.ini` under `[Charts]`.

The broker's M1 history for 2023–2026 is already stored locally by that terminal (`bases\ICMarketsSC-Demo\history\<symbol>\<year>.hcc`). Raising the cap lets the existing download code retrieve it as genuine broker bars. Nothing is reconstructed from the `.hcc` files directly.

## Already done (no interruption)

* Terminal config backed up and hash-verified, kept local and outside OneDrive/git because it contains encrypted account/server data: `%LOCALAPPDATA%\TradeDen\mt5_config_backup\20261019T235925Z\` (`BACKUP_MANIFEST.json`).
* Tool and tests: `quant_labs/maintenance/m1_history_refresh.py`, `python -m unittest quant_labs.maintenance.test_m1_refresh`.

## Window procedure (about 30–60 minutes)

1. **Preflight** (engine still running, read-only):
   ```
   python -m quant_labs.maintenance.m1_history_refresh
   ```
   * Record the current live signals and outcomes: `GET /api/quant-labs/live`.
   * Confirm no research job is RUNNING: `python -m quant_labs.cli status`.
2. **Stop TradeDen** with `STOP TRADING HUB.bat`, then confirm `http://127.0.0.1:8000` no longer answers.
3. **Back up config again** if more than a day has passed since the backup above (copy `%APPDATA%\MetaQuotes\Terminal\010E047102812FC0C18890992854220E\config`).
4. **In the MT5 terminal:**
   * Tools → Options → Charts → "Max. bars in chart" = **Unlimited** (or at least 1,000,000).
   * Click OK, close MT5 completely, then reopen it and wait for it to connect to `ICMarketsSC-Demo`.
5. **Retrieve:**
   ```
   python -m quant_labs.maintenance.m1_history_refresh --apply
   ```
   * The tool refuses if the engine answers or if `maxbars < 1,000,000`.
   * It writes `backend/data/research/bars_m1_extended_<UTC>/` and a new content-addressed dataset under `quant_labs/state/shared/`, then prints `REFRESH_REPORT.json`. The report covers, per symbol: bars, first/last, gaps (reported, never filled), and minutes overlapping the old cache with any differences (must be 0).
6. **Restart TradeDen** with `START TRADING HUB.bat`. Check that:
   * `/api/quant-labs/live` shows the Codex and Claude models READY;
   * Telegram is `DRY_RUN`, outbound is not approved, and `last_error` is null.
7. **Optional rollback:** restore `common.ini` from the backup to return to `MaxBars=100000`. The new cache and dataset can stay; they are inert until adopted.

## After the window (owner decisions)

* Review `REFRESH_REPORT.json`. Do not adopt the dataset if any symbol shows non-zero `differing_minutes` or unexpected first dates.
* Adoption is not automatic. The v1 control plane pins its dataset at initialisation and has no migration API. Recommended: an M5 extension 1.1.0 with its own dataset setting, leaving v1 results and their dataset pinned and reproducible.
* Memory note: about 750k M1 bars per symbol per two years. The M5 worker's 384 MiB cap must be re-measured on the new dataset before large jobs.
