# TradeDen Strategy Upgrade — Phase 1

Scope: TradeDen only. Company HQ, the Trading Floor, Risk Desk, paper accounts and
execution are untouched. Nothing is merged or pushed.

| Strategy | Before | After | Change |
|---|---|---|---|
| Support & Resistance | `sr-levels-v1` | `sr-levels-v2` | + candle confirmation at the level |
| Trendline (`trendline_v5`) | `trendline-first-v5` | `trendline-first-v5.1` | BREAK needs a rejected retest |
| Trend / Momentum | `tm-pullback-v2` | unchanged | reviewed only |
| SMC (`smc`) | — | `smc-confluence-v1` | new, LIVE in TradeDen, signals only |

Previous versions stay reproducible (unregistered classes / version argument); records
keep the version that produced them. Strategy ids are unchanged, so episodes, outcomes
and performance continue per strategy.

## Shared candle confirmation (`strategies/price_action.py`)

The last closed candle must close on the trade side of the level and show ANY ONE of
(LONG; SHORT mirrors):

- **wick_rejection**: the candle itself touched the level and its lower wick is >= 50% of its range;
- **engulfing**: bullish candle whose body engulfs a bearish previous candle's body, either candle touched the level;
- **close_away**: one of the 2 previous candles touched the level and this candle closes above that candle's high.

One pattern is enough (no stacking), all three are recorded. Parameters (50%, 2 bars) are
round values chosen before looking at results; nothing was tuned on the replay.

## Replay comparison (MT5 history, 180 days, 16 instruments, 205,382 M15 bars)

Tool: `tests/tools/strategy_upgrade_report.py` (read-only). Each M15 bar is evaluated
with exactly the bars the live collector would have had (closed bars + a flat forming
bar). A confirmation opens a simulated setup unless that model already has one open in
the same direction; it is resolved on the M15 path (first of stop / target; no spread,
slippage or commission). Times below are MT5 server time. **This is a detection
comparison, not a profitability claim.**

| Model | Setups | Target | Stop | Other | Target share of decided |
|---|---|---|---|---|---|
| S/R v1 | 193 | 58 | 135 | 0 | 30.1% |
| S/R v2 | 139 | 51 | 88 | 0 | 36.7% |
| Trendline v5 | 4,440 | 1,152 | 3,268 | 20 | 26.1% |
| Trendline v5.1 | 2,863 | 751 | 2,100 | 12 | 26.3% |
| SMC v1 | 53 | 12 | 41 | 0 | 22.6% |

CONFIRMING bars: S/R 15,252 → 10,668; Trendline 29,142 → 17,597; SMC 1,264.

### Support & Resistance

- Setups 193 → 139 (−28%). Bars where v1 confirmed: 273; v2 kept 181 (66%), rejected 92.
- Retained by pattern: wick_rejection 61, engulfing 49, close_away 71 — all three carry weight.
- By family: SR_BOUNCE 154 → 110 (target share 29.9% → 38.2%), SR_BREAK_RETEST 39 → 29 (30.8% → 31.0%).
- Rejected examples (v1 valid, no pattern):
  - XAUUSD 2026-06-08 08:00 LONG bounce at 4304.38, touched on the confirming candle, close position 0.79, no 50% wick, no engulfing, no prior touch candle.
  - XAUUSD 2026-08-11 06:15 LONG break/retest at 4405.44, touch 1 bar earlier, the confirming candle did not close above that touch candle's high.
  - BTCUSD 2026-04-30 01:30 SHORT at 76126.00, touched on the confirming candle, no wick/engulfing.
- Retained examples:
  - XAUUSD 2026-05-06 12:45 SHORT at 4701.35, wick_rejection.
  - XAUUSD 2026-04-28 23:00 SHORT at 4604.38, engulfing.
  - XAUUSD 2026-06-10 07:00 LONG at 4170.72, close_away (touch 2 bars earlier).
- Known trade-off (not tuned away): 27 of the first 40 rejected examples touched the zone on
  the confirming candle itself and closed in the favourable part of their range, but without a
  50% wick or an engulfing body (e.g. a strong-bodied candle launched from the level). The rule
  deliberately does not count such a candle; if it should, that would be a fourth pattern,
  decided on reasoning, not on this replay.

### Trendline

Finding: v5 had **no retest step**. A BREAK was confirmed on the break candle itself (any
close beyond the line within 0.8 ATR), although its trigger text said "break + retest/close
confirmation". v5.1 implements the retest.

- BREAK setups 2,712 → 566 (−79%); target share 24.9% → 26.2%.
- REVERSAL per-bar output is byte-identical (tested). REVERSAL setups rose 1,728 → 2,297 only
  because the replay (like the live lifecycle) opens one setup per direction at a time: fewer
  BREAK episodes leave those slots free.
- Bars v5 confirmed but v5.1 did not: 4,007 (break candle itself, retest without a rejection
  candle, or no crossing). Bars only v5.1 confirmed (the rejected retest): 679.
- Removed: XAUUSD 2026-04-09 23:30 LONG, v5 confirmed on the break candle; v5.1 "waiting for a
  retest of the broken line" (DEVELOPING). XAUUSD 2026-04-10 01:00 LONG, retest touched 2 bars
  after the break but no rejection candle.
- Added: XAUUSD 2026-04-09 21:15 SHORT, support break retested and rejected (engulfing) 2 bars
  after the break; XAUUSD 2026-04-28 07:45 LONG, resistance break retest rejected (engulfing).

### Outcome tracking

Unchanged and verified by tests: snapshots, confirmations, lifecycle and market outcomes are
keyed by `setup_id` / `strategy_id`; the new versions only change payload content.
`tests/test_live_strategies.py` now persists, confirms and resolves an outcome for all four
LIVE strategies (including SMC), and the golden persistence / scanner snapshot suites pass
unchanged.

## SMC (`strategies/smc.py`) — what qualifies

All required (LONG; SHORT mirrors). A single FVG, order block or sweep is never a signal.

1. **HTF context**: H4 structure trend bullish (latest H4 structure break up; H1 fallback recorded).
2. **Structure shift**: M15 structure trend bullish; its latest break (BOS, or CHoCH from a bearish structure) within 48 closed bars. Swings are 2-bar fractals, used only once known (no look-ahead).
3. **Displacement**: a bullish FVG (>= 0.1 ATR(M15)) in the leg from the origin low to the break bar.
4. **Order block**: last bearish candle before the displacement.
5. **Liquidity**: a CHoCH also needs a sell-side sweep at the leg origin (wick below an untaken swing low, close back above). A BOS does not.
6. **Retest**: price trades back into the order block (no close below it); reaction within 3 bars of the first tap, else mitigated.
7. **Reaction**: rejection candle (shared patterns) closing back above the order block.

Plan gates: entry within 1.0 ATR(H1) of the block, risk 0.5 ATR(M15)–2.5 ATR(H1), target = nearest H1
swing high above entry (buy-side liquidity), R:R >= 1.5. States: WATCHING (structure shift, awaiting
retrace), DEVELOPING (in the block), CONFIRMING (reaction).

Replay: 53 setups (45 BOS continuation, 8 CHoCH + sweep) over 180 days and 16 instruments: selective by
construction. Examples:

- **XAUUSD 2026-04-29 05:30 SHORT, SMC_CHOCH_SWEEP_REVERSAL** (score 95): H4 bearish (LH/LL, BOS down at
  4667.16). M15 swept buy-side liquidity at 4600.86 (high 4610.29, closed back below), then a bearish CHoCH
  through 4587.91 with a 1.0 ATR FVG (4586.45–4596.40). Order block 4599.56–4604.98 retested; wick
  rejection. Entry 4599.26, stop 4615.23, target H1 swing low 4554.79, 2.79R.
- **XAUUSD 2026-04-07 02:45 LONG, SMC_BOS_CONTINUATION** (score 80): H4 bullish (HH/HL). M15 bullish BOS
  through 4658.10 with an FVG 4654.44–4659.26 overlapping the order block 4649.20–4654.44; first tap,
  then a wick rejection closing above the block. Entry 4655.14, stop 4646.04, target 4671.80, 1.83R.
- **BTCUSD 2026-05-16 04:15 LONG, SMC_BOS_CONTINUATION** (score 85): H4 bullish (latest CHoCH up). M15 BOS
  through 79117.03, FVG 79088.12–79102.89, order block 79043.84–79088.12 retested 1 bar earlier, wick
  rejection. Entry 79094.11, stop 78971.48, target 79527.75, 3.54R.

Scope: `strategy_evidence.scope = "TRADEDEN_SIGNAL_ONLY"`. Company HQ's TradeDen bridge only reads
`/api/health`, `/api/market/performance` and the observation records; nothing routes SMC setups
to execution.

## Trend / Momentum review (no change)

Confirmation today: H4 trend (rising swing highs and lows, EMA50 slope >= 0.2 ATR, close above
EMA50), D1 not opposing, H1 EMA20/50 alignment, an H1 impulse >= 2 ATR with efficiency >= 0.35, a
controlled pullback (0.236–0.618, 2–15 bars, held near EMA50, no collapse bar) and an **M15 trigger
candle**: bullish, closing above the prior 4 highs and EMA20, after the pullback extreme. Plan gates:
not chasing, stop 0.5–3.0 ATR(H1), R:R >= 1.5. It already has a deterministic candle confirmation; no
clear implementation defect was found. Observations for later: the pullback hold check uses the
current EMA50 rather than the EMA at the pullback bar, and the M15 trigger does not require the
trigger candle to come from near the pullback extreme (only after it). Neither is a defect.
