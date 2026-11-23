# TradeDen overnight report (2026-11-24): partial

**Stopped early:** the session's usage limit was reached. This report covers what was actually done and verified.

## 1. Initial condition (verified 21:42 UTC)

- **cBot not running.**
  - cTrader logged `stopped by user` at 21:16:17 UTC; the last heartbeat was 21:15:58.
  - The window now open is the older cTrader 5.9.5 install (Copy page). The bot ran in cTrader 5.10.22.
  - The copy-mode build (fwd-tdn-001) was never compiled in cTrader: the `.algo` dates from 20:20 UTC.
- **Account:** Demo 10141056 (Raw Trading Ltd = IC Markets SC), balance and equity **$1,516.46**, no open positions.
- **Bridge:** running in the Terminal tab "TradeDen bridge". It forwarded 2 Garden signals (US500 21:00, AUDUSD 21:15); the cBot wasn't running to receive them.
- **Engine:** healthy. MT5 connected, scanner ready, Strategy Bank worker running (last scan 21:30 UTC, no errors).
  - No bank signals since 15:30 UTC. That looks market-driven, not a stall.

## 2. Problem found and FIXED

**Stops were not aligned to the broker tick grid.**
- Sizing used 0.1-pip stop resolution, but XAUUSD's tick is 0.01.
- Seen in the EXECUTION_TEST: a 338.3-pip stop was placed at 338 pips.
- If cTrader rounded up instead, real risk could slightly exceed the sized 0.25%.

**Fix:**
- Stops are rounded **up** to whole ticks *before* sizing; targets are rounded **down**.
- This applies to strategy, copy and execution-test orders (`Sizing.CeilPips`/`FloorPips`, which take `Symbol.TickSize`).

## 3. Tests ACTUALLY RUN

- `ctrader_scalper`: `python -m unittest discover -s tests`: **18 tests OK**, including C#/Python signal parity on XAUUSD, EURUSD and BTCUSD, and the bridge and report tests.
- C# safety suite: **88/88 passed**, including the new tick-grid tests and 20,000 random sizings.
- `build_check.ps1`: cBot **compiles** against cTrader 5.10.22 `cAlgo.API`.
- The updated source is installed in `Documents\cAlgo\Sources\Robots\TradeDenScalper`.

## 4. NOT VERIFIED or NOT DONE (session limit)

- Full backend test suite, frontend tests, dashboard and API checks were not re-run tonight. They last passed earlier on 23 Nov.
- Not started:
  - dashboard upgrades (live price/status panel, real vs simulated split);
  - Telegram notifications for bot events;
  - weekly summary;
  - strategy scorecard;
  - logging a symbol-spec record at start;
  - top-level error reporting in timer handlers.

## 5. REQUIRES HUMAN ACTION

1. In **cTrader 5.10.22**: Algo → TradeDenScalper → **Build**, then start the local XAUUSD m5 instance. These settings persist:

   | Parameter | Value |
   |---|---|
   | Execution mode | DemoTrading |
   | Activation code | `fwd-xau-001` |
   | Copy TradeDen signals | Yes |
   | Copy activation code | `fwd-tdn-001` |
   | Run ONE execution test order | No |

2. Keep the "TradeDen bridge" terminal running, or restart it: `cd ctrader_scalper; python -m forward.bridge`.
3. Daily report: `cd ctrader_scalper; python -m forward.report`. It's also scheduled at about 22:38 UTC.

Nothing was pushed. Limits are unchanged: 0.25% risk, 1% daily loss, 1 position, halt after 2 losses, demo-only gate.
