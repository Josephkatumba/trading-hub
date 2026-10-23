# Engine resilience (investigation and tooling, 2026-10-23)

| Concern | Finding | Status |
|---|---|---|
| Process failure | Nothing restarts the engine if its console process dies | **New:** `python -m ops.watchdog --loop` relaunches with the official launcher **only** when port 8000 has not been listening for 3 consecutive minutes. Limits: at most 3 relaunches/hour, a 4-minute grace after each launch, and it never kills a running or slow engine. Every decision is logged to `backend/data/ops/watchdog.jsonl`. Tested with fakes. **Not installed** (see below). |
| MT5 reconnection | `ensure_mt5()` checks the terminal on every 30 s scan and reinitialises a dead session | Existing, adequate |
| Wrong terminal on reconnect | `TRADING_HUB_MT5_TERMINAL_PATH` is **not set**, and there are 7 MT5 installations on this laptop | **Recommendation:** set it to the IC Markets terminal path so a crashed terminal is relaunched correctly |
| Consumer restart | Per-snapshot exceptions are caught; the thread state is reported | Existing. **New:** the health status shows DOWN if the consumer stops or no snapshot has been processed for 5 minutes |
| Missed candles | Candles closed during downtime are never evaluated as live signals (fail-closed freshness gate) | Existing. **New:** `closed_bars_not_evaluated` per model and per symbol, in health and diagnostics |
| Safe catch-up | Outcomes of existing signals are resolved from history fetched after restart. Telegram never sends alerts older than their freshness window. | Existing |
| Replayed vs real-time | **New:** every live signal records `detection: REAL_TIME` and its entry regime. Replays and backtests never write to the live store. | Done |
| Duplicates | Unique (model, version, symbol, candle) and send-once outbox claims, preserved across restarts | Existing, tested |
| Data freshness / health indicator | **New:** `health` in `/api/quant-labs/live` and the dashboard notice. OK / DEGRADED / DOWN with reasons, covering: per-market input age (weekend closure is distinguished from staleness), per-model last evaluation, Telegram delivery failures in 24h, 24h uptime from the engine heartbeat, and unevaluated candles. | Done |
| Power or internet loss | The laptop can't scan while off or offline. The reports already flag offline windows, and the watchdog restores the engine after the machine and network return. | Mitigated, not solved without other infrastructure |

## Installing the watchdog (requires CEO approval: persistent system configuration)

Run in an elevated or normal PowerShell. It runs at logon under the current user:

```
schtasks /Create /TN "TradeDen Engine Watchdog" /SC ONLOGON /RL LIMITED /TR "cmd /c cd /d \"C:\Users\katjo\OneDrive\Documents\GitHub\trading-hub\backend\" && python -m ops.watchdog --loop"
```

Remove it with `schtasks /Delete /TN "TradeDen Engine Watchdog" /F`. Start with `--dry-run` for a day to review the log first.
