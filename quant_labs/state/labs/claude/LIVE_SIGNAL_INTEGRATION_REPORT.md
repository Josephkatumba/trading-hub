# Quant Labs live signal integration — report (2026-10-23)

## Phase 7 answers

| Question | Answer |
|---|---|
| 1. Found | **All 5.** Codex `compression_escape` 0.1.0 (`quant_labs/state/labs/codex/strategies/compression_escape/`) and Claude `index_trend_day` 0.2.0, `crypto_trend_breakout` 0.3.0, `hourly_shock_drift` 0.1.0, `index_gap_fade` 0.1.0 (`quant_labs/state/labs/claude/strategies/`). All five are executable `detect()` models, not prototypes. |
| 2. Integrated | **All 5**, in the existing live provider (`backend/quant_live`) fed by the existing MT5 scanner. Each runs on its own timeframe and instruments in an isolated, resource-limited worker, independent of the others. Source hashes match the research-ledger registrations. |
| 3. Actively monitoring | **All 5, now** (engine up, consumer running, no errors). The engine was not restarted. |
| 4. Can generate Telegram signals | **All 5 once the engine is restarted** to load the new delivery code; the approval and flag are already in place. Until then signals are recorded as DRY_RUN previews. |
| 5. Experimental | **All 5. None is production.** Tiers: Index Trend-Day and Crypto Trend Breakout = EXPERIMENTAL paper candidates. Compression Escape, Hourly Shock Drift and Index Gap Fade = EXPERIMENTAL · RESEARCH ONLY (no positive out-of-sample evidence). |
| 6. Need further development | Compression Escape has no edge in a historical replay (train −0.05R, validation −0.28R, test −0.005R) and was never run through the shared queue. Shock Drift and Gap Fade are negative out of sample. The two candidates need about 3 months of prospective paper results. |
| 7. TradeDen running | **Yes.** MT5 connected, scanner READY, execution disabled, quant consumer running, no errors. |
| 8. Telegram verified | **Yes.** One delivery test (message id 118) reached the private TradeDen chat through the existing bot. Automatic signal delivery starts after the restart. |

## What changed

* **Live registry** (`backend/data/quant_live`):
  * registered `hourly_shock_drift` 0.1.0 and `index_gap_fade` 0.1.0;
  * recorded the CEO delivery approval (`approvals/2026-10-23_quant_labs_live_signal_integration.json`), scoped to the five models with tiers and `production: false`.
  * Kimi's models are outside the scope and stay alerts-off.
* **`backend/quant_live/telegram.py`:**
  * the CEO message format (🚨 TRADEDEN QUANT LABS SIGNAL … 🔬 Status);
  * real delivery through the existing `telegram_notifier.TelegramClient`, only when the dedicated flag `TRADEDEN_QUANT_LIVE_TELEGRAM_ENABLED=1` is set **and** the approval exists **and** the model is EXPERIMENTAL, scanning, alert-enabled and in scope **and** the signal is ≤120 s old;
  * an atomic QUEUED→IN_FLIGHT claim, so each signal is sent at most once; uncertain network outcomes become DELIVERY_UNKNOWN and are never replayed, including after restarts;
  * incomplete signals are never formatted.
* **`store.py`:** `approve_delivery` / `revoke_delivery` (production cannot be approved), evidence `tier`, delivery claim/finish, and an event log.
* **`runtime.py`:**
  * reports the real delivery mode;
  * **gate fix:** higher-timeframe context (H4/D1) is no longer rejected as stale just because the weekend passed. Previously every Monday signal of a D1-using model, including 29% of Index Gap Fade's historical signals, would have been silently dropped. Midweek staleness is still rejected. No strategy rules changed.
* **`report.py` / `service.py` (performance tracking per strategy):**
  * confirmed signals, triggered entries, TP hits, SL hits, expired (time exits), open, unknown;
  * win rate, average R and net R after estimated costs;
  * a separate `evidence_tier` breakdown, so research-only and candidate results are never pooled.

  History is durable in SQLite and outcomes are append-only revisions.
* **CLI:** `python -m quant_live --store data/quant_live approve-delivery|revoke-delivery|report`.
* **`backend/.env`:** `TRADEDEN_QUANT_LIVE_TELEGRAM_ENABLED=1` appended. A backup exists, outside the repository, in this session's scratchpad.

## Tests

* `tests/test_quant_live_delivery.py`: 12 new tests, all passing. They cover:
  * approval and flag gates;
  * the exact message format;
  * send-once across a simulated restart;
  * crash mid-send and network uncertainty never replayed;
  * HTTP failure, expiry, disable/revoke and approval rules;
  * incomplete signals refused;
  * per-strategy tracking and tier separation;
  * weekend-aware staleness;
  * **historical end-to-end:** all five real models on genuine MT5 snapshots through the real runtime and workers. Each yields exactly one confirmed signal, with no duplicate on the same candle, delivered once in the CEO format, then resolved (Trend-Day and Crypto TIME_EXIT; Shock Drift and Gap Fade SL; Compression Escape INCOMPLETE, because its 12h window crosses the daily break).
* Existing `test_quant_live` and `test_provider_bridge` (25) still pass. The full backend suite shows no regressions.
* Notes on the backend suite:
  * Some files must be run from `backend/`.
  * `test_market_data` fails only because `.env` already enabled quant-live before this work.
  * `test_observation_index` exceeded my 2-minute per-file limit and was not completed.

## One remaining step: restart the market engine

The session's permission system blocked me from restarting production, so **you** need to restart the engine for Telegram delivery to start. Either:

* run `STOP TRADING HUB.bat`, then `START TRADING HUB.bat`; or
* close the "Trading Hub - Market Engine" window and run `backend\start_engine.bat`.

**Then verify** at `http://127.0.0.1:8000/api/quant-labs/live` that:
* `runtime.telegram_mode` = `EXPERIMENTAL_APPROVED`;
* `runtime.delivery_flag` = `true`;
* all five models show `alert_enabled: 1` with their tiers;
* `runtime.last_error` = `null`.

**To stop delivery at any time:**
```
python -m quant_live --store data/quant_live revoke-delivery --reason "..."
```
Or set the flag to 0 and restart.

## Unchanged

No broker execution, no production strategies, no paid services. The dashboard, existing TradeDen Telegram alerts, Strategy Bank, strategy registry and daily reports are unchanged. Strategy rules are unchanged.
