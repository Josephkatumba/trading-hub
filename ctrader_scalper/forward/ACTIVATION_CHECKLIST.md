# Forward experiment fwd-xau-001: activation checklist (DEMO only)

**Purpose:** measure whether real IC Markets cTrader execution matches the simulator.

**This is not a profitable strategy.** tds-1.0 was rejected by research (NO_EDGE, about −0.07R per trade expected after costs). Losses within the limits below are an expected cost of the experiment.

## What is enforced in code (tested: `python -m unittest discover -s tests`, 44 safety checks plus mutation tests)

| Rule | Value | Can a parameter loosen it? |
|---|---|---|
| Live account | Bot stops at start; re-checked before every order | No |
| Orders need | Mode = DemoTrading **and** activation code `fwd-xau-001` **and** exact demo account number **and** broker match **and** symbol XAUUSD | No; otherwise SignalsOnly |
| Risk per trade | ≤ 0.25% of balance. The stop is rounded up and size rounded down, so risk never exceeds this. | No (ceiling 0.25) |
| Open positions | 1. Also blocked if any manual/other XAUUSD position is open. | No (ceiling 1) |
| Daily loss | 1% of day-start balance, **including open risk**. An equity kill switch closes positions. | No (ceiling 1.0) |
| Losing streak | Halt after 2 consecutive losses, **not reset daily**. Resume only by setting "Resume after UTC". | No (ceiling 2) |
| Stop-loss | Sent with every order; a position without one is closed immediately | No |
| Sizing | Balance × fixed % ÷ stop distance. No martingale, averaging, scaling-in or recovery sizing. | No |
| Evidence | If the order-intent journal record can't be written, the order is not sent | No |

## Account in use (verified 2026-11-23)

| Item | Value |
|---|---|
| Account | IC Markets cTrader **Demo 10141056**, Raw Trading Ltd (IC Markets SC), Hedging, 1:100 |
| Balance / equity | $944.81 / $1,529.75. Equity includes floating P&L on manual positions. |
| Gate defaults | Expected account `10141056`, expected broker `Raw Trading`. The activation code must still be typed by the owner. |
| Risk base | **min(balance, equity)**, so floating profit never raises risk. 0.25% × $944.81 = **$2.36 per trade**. |
| XAUUSD volume | Minimum 0.01 lot = 1 oz, step 1 oz, so the minimum position risks $1 per $1 of stop |

**Consequence:** a trade is only possible when the stop is ≤ $2.36. Recent median stop: $7.27; only about 1% of signals qualify, roughly one trade every two weeks. Every other signal is journaled as `minimum volume would exceed the risk budget`, with the stop, the minimum-volume risk and the budget.

**Manual XAUUSD position:** while one is open on this account, the bot places no XAUUSD orders ("another (manual or foreign) position is open on this symbol").

## Steps

1. **Build:** cTrader → Algo → cBots → **TradeDenScalper** → Build. The source is already installed in `Documents\cAlgo\Sources\Robots\TradeDenScalper\`.
   - If it doesn't appear, restart cTrader.
   - Re-running `powershell -ExecutionPolicy Bypass -File ctrader_scalper\install_cbot.ps1` backs up and replaces the source.
2. **Confirm the account selector shows your IC Markets DEMO account.** Note the account number.
3. **Recommended dry run in the cTrader backtester:**
   - Settings: XAUUSD, M5, a recent week, Mode **DemoTrading**, your account number, activation code `fwd-xau-001`.
   - Check that every trade has a stop and that the risk is about 0.25% of balance.
   - Check that it stops after two losses.
   - Backtests write `backtest-*.jsonl` journals, which the reports ignore.
4. **Shadow first (optional, no orders):** start on an XAUUSD chart with Mode **SignalsOnly**. The panel and journal show signals only.
5. **Activate:** on an XAUUSD chart, add an instance with:

   | Parameter | Value |
   |---|---|
   | Symbols | `XAUUSD` |
   | Execution mode | `DemoTrading` |
   | Expected demo account number | *your demo number* |
   | Expected broker | `IC Markets` |
   | Activation code | `fwd-xau-001` |
   | Resume after UTC | blank |

   Leave everything else at its defaults: risk 0.25, positions 1, daily loss 1.0, halt after 2, label `TDS-FWD1`.

   Grant **Full Access** when asked; the bot needs it to write the journal. Then press Start.
6. **Verify within one minute:**
   - The cTrader log shows `FORWARD EXPERIMENT fwd-xau-001 ACTIVE on DEMO`.
   - The chart panel shows `DemoTrading | DEMO verified | fwd-xau-001`.
   - If it says `SignalsOnly: <reason>` instead (for example "broker does not match" because cTrader names the broker differently), no orders will be sent. Fix the parameter and restart.

## Operating

- **Stop:** press Stop on the instance. It doesn't close open positions; close the position manually if you want to be flat.
- **After a 2-loss halt:** review the daily report. To continue, set **Resume after UTC** to the current time (`yyyy-MM-dd HH:mm`) and restart. Earlier losses then no longer count toward the streak.
- **Reports:** `cd ctrader_scalper; python -m forward.report` writes `forward/reports/<date>.md/.json`.
- **Live dashboard:** `/trading-hub/scalper.html`, after restarting the Trading Hub engine.
- **Judging the experiment:**
  - Execution questions (spread, slippage, commission, signal parity) can be answered within days.
  - Expectancy needs at least 100 closed trades. At this strategy's rate, that may take months.
