# TRADEden 20-strategy signal bank: final report and deployment plan

Prepared for: CEO review. Date: 2026-10-19.
Status: **built, tested and switched off.**
- Nothing is enabled. No message has been sent. The live engine was not restarted. Nothing was committed or pushed.
- The live Telegram files (`telegram_notifier.py`, `signal_presentation.py` and their tests) are byte-identical to commit `7e141fc`.
- Neither bank flag is set in `backend/.env`.

## Summary

| Question | Answer |
|---|---|
| Is the 20-strategy bank built? | Yes: rules, independent scanners, confirmation gates, deduplication, signal records, outcome tracking, Telegram delivery, API and dashboard. |
| Do all 20 work technically? | 19 are implemented; #13 VWAP Reversion is **unsupported** (no traded-volume data). Across about 87,000 historical decisions, every signal that passed the gates had valid levels. |
| Are any of them profitable? | **None has demonstrated it.** Over two years of MT5 history after realistic costs, 15 are negative and 4 are about zero. No strategy is statistically better than zero after multiple-testing correction. |
| Is it safe to switch on? | Yes, as a **monitoring** system in stages (section 6). It should not send trade alerts to subscribers until a strategy earns it with recorded forward results. |

**Technically valid is not the same as profitable.** Every implemented strategy does exactly what its rules say. That alone says nothing about whether following those rules makes money, and the history says so far it doesn't.

## 1. Architecture

```
MT5 bars (M15/H1/H4/D1, forming bar dropped, UTC via the verified broker clock)
  -> 16 independent scanners + 3 linked production strategies (+1 unsupported)
  -> confirmation gates (per strategy)
  -> per-strategy duplicate control
  -> opportunity merge (one alert per symbol and direction; all confirming strategies attributed)
  -> signal store -> Telegram (separate flag) -> authoritative outcomes -> per-strategy statistics -> dashboard
```

| Component | File |
|---|---|
| Rules: the 20 specifications and their `decide()` functions | `backend/strategy_bank/rules.py` |
| Causal indicators (value at bar *i* uses bars ≤ *i* only) | `backend/strategy_bank/indicators.py` |
| Gates, deduplication, signal store, outcome resolution, statistics | `backend/strategy_bank/engine.py` |
| Telegram alert format and delivery (own dedup file) | `backend/strategy_bank/telegram.py` |
| Live loop, run in its own thread when enabled | `backend/strategy_bank/worker.py` |
| Engine wiring (flag-gated), `GET /api/strategy-bank`, `/api/health` → `strategy_bank` | `backend/main.py` |
| Dashboard section and nav link "Strategy Bank" | `src/garden/strategyBank.mjs`, `src/marketRadar.js`, `src/main.js` |
| Historical testing (same rules and gates as live) | `backend/research/bank_backtest.py` → `data/strategy_bank/historical.json` |

**Independence:** each strategy confirms on its own rules only, and no strategy needs another's agreement. If one strategy raises an error, it is recorded and the others still run.

**Reuse:** #1–3 are the live production strategies; the bank attributes and measures them but does not re-implement or re-alert them. The bank also reuses:
- `signal_outcomes.resolve` for TP/SL outcomes
- the live `TelegramClient` and `NotificationStore` class
- the live price formatting, HTML escaping and the exact live disclaimer

`telegram_notifier.py` and `signal_presentation.py` were **not modified**.

## 2. The 20 strategies: objective rules

Common terms:
- **ATR:** Wilder ATR(14) of the strategy's timeframe.
- **Bar timing:** every confirmation is on a **completed** candle. Entry is the live executable quote (ask for BUY, bid for SELL) right after that close.
- **"2R"** means the target sits two times the entry-to-stop risk from the entry.

Every signal must also pass the common gates in section 3. The full specification of each strategy (entry, indicators, confirmation, stop, take profit, minimum R:R, invalidation, data) is in `rules.SPECS` and is returned by `/api/strategy-bank` → `rules`.

| # | Strategy | Status | TF | Entry and confirmation (completed candle) | Stop | Take profit | Min R:R |
|---|---|---|---|---|---|---|---|
| 1 | Trendline Break & Retest | LINKED (production `trendline_v5`, BREAK) | M15 | Genuine close through the trendline; within 12 bars a retest to within 0.15 ATR of the line and a deterministic rejection candle on the break side; executable-price qualification | Production structural stop | H1 structural target | 1.5 |
| 2 | Trendline Bounce | LINKED (`trendline_v5`, REVERSAL) | M15 | Rejection candle from a validated multi-touch trendline; qualification | Beyond the rejection / line | H1 structural target | 1.5 |
| 3 | Support & Resistance | LINKED (`support_resistance`) | M15 | Rejection (or break and retest) at a multi-timeframe level with ≥ 3 reactions, closed rejection candle plus momentum; qualification | Beyond the zone | Next S/R zone edge | 1.5 |
| 4 | Breakout Trading | EXPERIMENTAL | H1 | First close beyond the prior 20-bar high/low by > 0.1 ATR, when that range is ≤ 3 ATR wide | Range middle | 2R | 1.5 |
| 5 | EMA Crossover | EXPERIMENTAL | H1 | EMA20 crosses EMA50 on the close; close on the same side of EMA200 | 1.5 ATR | 2R | 1.5 |
| 6 | EMA Pullback | EXPERIMENTAL | H1 | EMA50 above EMA200 and higher than 10 bars ago; candle range contains EMA20; closes bullish above EMA20 (mirror for shorts) | Candle low (or close − 0.5 ATR, lower) − 0.5 ATR | 2R | 1.5 |
| 7 | RSI Divergence | EXPERIMENTAL | H1 | Two confirmed 3-bar swing lows 5–40 bars apart, the second lower in price and higher in RSI(14), first RSI < 35. Structure confirmation: first close above the second pivot candle's high within 10 bars (mirror: RSI > 65) | 0.3 ATR beyond the second swing | 2R | 1.5 |
| 8 | MACD Momentum | EXPERIMENTAL | H1 | MACD(12,26,9) crosses its signal above zero; close higher than the previous close and above EMA50 (mirror) | 1.5 ATR | 2R | 1.5 |
| 9 | Bollinger Band Mean Reversion | EXPERIMENTAL | H1 | Flat regime (EMA50 change over 10 bars ≤ 0.3 ATR); previous close outside the 20-bar 2.5σ band, current close back inside | 1 ATR beyond the two-bar extreme | 20-bar mean | **0.5** (high win-rate profile, by design) |
| 10 | Donchian Channel Breakout | EXPERIMENTAL | H1 | First close beyond the prior 20-bar high/low | 2 ATR | 2R | 1.5 |
| 11 | London Session Breakout | EXPERIMENTAL | M15 | Asian range = 00:00–07:00 UTC; between 07:00 and 11:00, the first close beyond it by > 0.1 H1-ATR (FX, metals, GER40) | Opposite range side (range ≤ 1.5 ATR) or the range middle | 2R; time exit 16:00 UTC | 1.5 |
| 12 | Opening Range Breakout | EXPERIMENTAL | M15 | First 30 minutes of the cash session (New York 09:30 for NAS100/US500, Frankfurt 09:00 for GER40, DST-aware); first close beyond it within 2 h | Opposite side of the opening range | 2R; exit at session close | 1.5 |
| 13 | VWAP Reversion | **UNSUPPORTED** | – | Not implemented as a signal (see below) | – | – | – |
| 14 | Liquidity Sweep | EXPERIMENTAL | H1 | Candle trades beyond the previous day's high/low, closes back inside, rejection wick ≥ 50% of a range ≥ 0.8 ATR | 0.2 ATR beyond the sweep extreme | 2R | 1.5 |
| 15 | Fair Value Gap | EXPERIMENTAL | H1 | Three-candle gap ≥ 0.3 ATR, 3–30 bars old, never closed through; price enters it and the candle closes bullish above the gap top (mirror) | 0.3 ATR beyond the far gap edge | 2R | 1.5 |
| 16 | Order Block Retest | EXPERIMENTAL | H1 | Last opposite-colour candle before a displacement (body ≥ 1 ATR within 3 bars) that closes beyond the last confirmed swing. **First** retest into the block (≤ 0.1 ATR through) closing beyond the block midpoint | 0.2 ATR beyond the block | 2R | 1.5 |
| 17 | Market Structure Break | EXPERIMENTAL | H1 | Last two confirmed swing highs and lows descending; first close > 0.1 ATR above the last swing high (change of character; mirror) | 0.2 ATR beyond the opposite swing (skipped if > 3 ATR) | 2R | 1.5 |
| 18 | Inside Bar Breakout | EXPERIMENTAL | H1 | Inside candle within a mother candle of range ≥ 0.5 ATR; next close beyond the mother | Opposite side of the mother | 2R | 1.5 |
| 19 | ATR Volatility Breakout | EXPERIMENTAL | H1 | First close beyond EMA20 ± 2 ATR (Keltner breakout) | 1.5 ATR | 2R | 1.5 |
| 20 | Ichimoku Trend Following | EXPERIMENTAL | H1 | First close where all of these hold: above the cloud (spans as plotted at that bar), Tenkan above Kijun, close above the close 26 bars earlier (mirror) | 0.5 ATR beyond Kijun (≥ 0.5 ATR from close; skipped if > 3 ATR) | 2R | 1.5 |

Instruments: all 16 TRADEden instruments, except where the table says otherwise (#11, #12).

**Why #13 VWAP Reversion is unsupported:**
- **No traded volume:** MT5 supplies only `tick_volume` for these CFDs, a count of price updates in one broker's feed, not traded volume.
- **Not the VWAP traders use:** a tick-volume VWAP is a broker-specific quantity that can't be checked against the exchange VWAP, and spot FX has no consolidated volume at all.
- **Decision:** rather than fabricate confirmations, the strategy is marked **UNSUPPORTED** and never signals.
- **To support it:** connect a real volume source, such as exchange futures data.

## 3. Confirmation engine: what stops a bad signal

Applied to every decision, live and historical alike (`engine.confirm`):

| Gate | Rule | Prevents |
|---|---|---|
| Completed candle | The forming bar is dropped before any decision; indicators are causal | Repainting, look-ahead |
| Fresh data | The confirming bar closed within 2 bar-lengths of now; the quote's tick age is ≤ 300 s (verified broker clock) | Signals from stale data or closed markets |
| Entry drift | The executable entry is within 0.5 ATR of the confirming close | Chasing a move already gone |
| Valid levels | Stop on the loss side, 0.2–5 ATR from the entry; target on the profit side | Invalid SL/TP calculations |
| Execution cost | Spread ≤ 25% of the risk | Unrealistic spreads and costs |
| Minimum R:R | Executable reward/risk ≥ the strategy's minimum | Poor-quality plans |
| Duplicates | No new signal from the same strategy and symbol while its previous one is open | Repeated alerts |
| Opportunity merge | Same symbol and direction within 4 h of an open opportunity → merged and attributed; a production alert within 1 h → not re-sent | Multiple alerts for one opportunity |

**Verification:**
- **Look-ahead:** a test compares every strategy's decision using full history against its decision using only the bars closed by then; they must be identical. Injecting a one-bar look-ahead fails the test.
- **Historical gates:** across about 87,000 decisions, the gates rejected about 1–3% for sensible reasons. 0 accepted signals had invalid levels.

## 4. Historical testing results

> **HISTORICAL BACKTEST: simulated on past MT5 data, not live results.**
>
> - **Periods:** train 2024-10-15 → 2025-10-01, validation → 2026-04-01, test → 2026-10-12.
> - **Costs:** spread on the correct side, IC-Markets-Raw-style commission, 0.5-spread stop slippage, and overnight financing (current swap specifications).
> - **Mechanics:** the same `decide()` and gates as live; entry at the next M15 open; one open position per strategy and symbol.
> - **Statistics:** Holm–Bonferroni across 19 strategies.

| # | Strategy | Technical validation | Trades | Win rate | Expectancy, R (95% CI) | Train / Validation / Test E | ×2 costs E | Holm p | Profitability |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Trendline Break & Retest | Production replay (live strategy) | 2,153 | 25% | -0.203 (-0.29, -0.12) | -0.139 / -0.270 / -0.244 | -0.371 | 1.0 | Unprofitable |
| 2 | Trendline Bounce | Production replay (live strategy) | 8,076 | 24% | -0.232 (-0.27, -0.19) | -0.186 / -0.228 / -0.314 | -0.435 | 1.0 | Unprofitable |
| 3 | Support & Resistance | Production replay (live strategy) | 697 | 30% | -0.130 (-0.24, -0.02) | -0.176 / -0.130 / -0.042 | -0.253 | 1.0 | Unprofitable |
| 4 | Breakout Trading | Valid: 2,272 decisions, 2,235 passed, 0 invalid | 1,882 | 34% | -0.053 (-0.12, +0.01) | -0.040 / +0.003 / -0.132 | -0.126 | 1.0 | Unprofitable |
| 5 | EMA Crossover | Valid: 2,432 / 2,406 / 0 | 2,327 | 32% | -0.097 (-0.16, -0.04) | -0.110 / -0.091 / -0.079 | -0.183 | 1.0 | Unprofitable |
| 6 | EMA Pullback | Valid: 15,338 / 15,112 / 0 | 5,293 | 32% | -0.103 (-0.14, -0.06) | -0.095 / -0.054 / -0.168 | -0.178 | 1.0 | Unprofitable |
| 7 | RSI Divergence | Valid: 1,202 / 1,181 / 0 | 895 | 33% | -0.062 (-0.15, +0.03) | -0.055 / +0.034 / -0.174 | -0.132 | 1.0 | Unprofitable |
| 8 | MACD Momentum | Valid: 5,324 / 5,279 / 0 | 4,318 | 34% | -0.033 (-0.07, +0.01) | -0.048 / -0.009 / -0.029 | -0.097 | 1.0 | Unprofitable |
| 9 | Bollinger Band Mean Reversion | Valid: 1,161 / 799 / 0 | 774 | 56% | +0.032 (-0.04, +0.10) | +0.009 / +0.029 / +0.077 | -0.024 | 1.0 | **Not proven** (positive in all three periods, CI includes 0, fails ×2 costs) |
| 10 | Donchian Channel Breakout | Valid: 14,664 / 14,575 / 0 | 6,745 | 33% | -0.051 (-0.09, -0.02) | -0.043 / -0.021 / -0.094 | -0.111 | 1.0 | Unprofitable |
| 11 | London Session Breakout | Valid: 4,376 / 4,208 / 0 | 4,198 | 42% | +0.004 (-0.03, +0.04) | +0.042 / -0.150 / +0.083 | -0.031 | 1.0 | Not proven (about zero) |
| 12 | Opening Range Breakout | Valid: 1,453 / 1,341 / 0 | 1,341 | 47% | +0.003 (-0.05, +0.06) | +0.035 / +0.100 / -0.132 | -0.011 | 1.0 | Not proven (about zero) |
| 13 | VWAP Reversion | Unsupported | – | – | – | – | – | – | Unsupported |
| 14 | Liquidity Sweep | Valid: 3,525 / 3,490 / 0 | 2,873 | 32% | -0.078 (-0.13, -0.02) | -0.047 / -0.114 / -0.099 | -0.153 | 1.0 | Unprofitable |
| 15 | Fair Value Gap | Valid: 937 / 925 / 0 | 876 | 34% | -0.024 (-0.12, +0.07) | +0.062 / -0.014 / -0.222 | -0.074 | 1.0 | Unprofitable |
| 16 | Order Block Retest | Valid: 766 / 757 / 0 | 717 | 35% | -0.002 (-0.11, +0.10) | -0.087 / +0.164 / +0.025 | -0.086 | 1.0 | About zero, not proven |
| 17 | Market Structure Break | Valid: 2,037 / 2,021 / 0 | 1,425 | 36% | +0.008 (-0.07, +0.08) | -0.022 / +0.022 / +0.050 | -0.052 | 1.0 | Not proven (about zero) |
| 18 | Inside Bar Breakout | Valid: 9,368 / 9,194 / 0 | 5,717 | 32% | -0.100 (-0.14, -0.06) | -0.090 / -0.059 / -0.155 | -0.183 | 1.0 | Unprofitable |
| 19 | ATR Volatility Breakout | Valid: 8,512 / 8,460 / 0 | 5,816 | 33% | -0.069 (-0.11, -0.03) | -0.045 / +0.003 / -0.180 | -0.135 | 1.0 | Unprofitable |
| 20 | Ichimoku Trend Following | Valid: 9,353 / 9,156 / 0 | 5,050 | 33% | -0.075 (-0.12, -0.04) | -0.079 / -0.037 / -0.097 | -0.149 | 1.0 | Unprofitable |

How to read the table:
- **Technical validation:** "Valid" means the strategy triggered, its signals passed the gates at normal rates, and every accepted signal had valid stop and target levels.
- **Profitability:** a separate question. **No strategy passes.** The best five (#9, #11, #12, #16, #17) are within noise of zero, and all turn negative when costs are doubled.
- **Agreement with earlier research:** these results match V6 and T-033. On this data, at these frequencies, costs consume what little edge these methods have.

## 5. Outcome tracking and dashboard behaviour

**Signal records** (`data/strategy_bank/signals.jsonl`, append-only). Each record holds:
- confirmation time, entry, stop loss, take profit, risk, R:R and spread
- whether the entry was **executable** and on what basis (live quote and its tick age)
- the explanation and the contradictory evidence
- the opportunity it belongs to
- the outcome status and **hypothetical** R multiple, with the basis "signal outcome, not an executed trade"

Executed-trade (realised) results exist only in the user's journal; the bank never presents hypothetical R as realised profit.

**Outcomes:**
- Resolved with `signal_outcomes.resolve`: the first barrier hit, SELLs exiting at the ask, and an M1 tie-break when both levels fall in one candle.
- Statuses: AMBIGUOUS / UNAVAILABLE / NO_HIT when the outcome can't be verified; **TIME_EXIT** for session strategies.

**Statistics** (`engine.statistics`), per strategy and broken down by instrument and timeframe:
- signals, resolved, open, unresolvable
- win rate, expectancy, total R, maximum drawdown
- gate rejections by reason

**Linked #1–3:** their statistics come from the authoritative outcomes of the production confirmations.

**Opportunity records** (`opportunities.jsonl`): list every strategy that independently confirmed the same opportunity.

**Dashboard** (Markets → **Strategy Bank** nav link, or the "🏦 Strategy Bank" panel):
- **Table:** Strategy | Status | Signals | Win Rate | Expectancy | Max DD.
- **Live columns** show only recorded data. A strategy with no resolved signals shows **Pending**.
  - Today: the 16 experimental strategies show `0 · Pending · Pending`.
  - #1–3 show their real live record: Break & Retest 44 signals / 18%; Bounce 51 / 24%; S&R 27 / 37%.
- **Status** states what is actually running: "Experimental · not running" while the flag is off, "Monitoring · experimental" when on, "Monitoring · live production strategy" for #1–3, and "Unsupported" for #13 with its reason.
- **Historical results** appear only in a separate expandable section headed "HISTORICAL BACKTEST (simulated, not live results)". A test checks that backtest numbers never appear in the live columns.

## 6. Test results

| Suite | Result |
|---|---|
| Backend full suite `python tests/run_suite.py` (run by the session that owns the live Telegram code, after the bank changes) | **592 tests, OK** |
| Strategy bank tests `tests/test_strategy_bank.py` | **14 OK**: 20 specs complete, no vague rules, no repainting or look-ahead (an injected leak is caught), strategies trigger, rule fixtures, every gate, merge and attribution, duplicates, Telegram format and once-only delivery, time exit, Pending statistics, flags off, live notifier untouched |
| Frontend `npm test` | **171 OK** (3 new Strategy Bank tests) |
| Browser `playwright test`, built with the documented commercial flags (`VITE_AUTH_REQUIRED=1`, `VITE_ENGINE_SAME_ORIGIN=1`, `VITE_BASE_PATH=/`) | **2 OK** |
| Production build `vite build` | **Succeeds** (the existing chunk-size warning only) |
| Live Telegram files vs commit `7e141fc` | **Byte-identical** |

## 7. Deployment and approval plan

Each stage is independent and reversible. Stages 1–2 cannot affect subscribers. **Nothing below has been done.**

| Stage | Action (exact) | What it changes | Roll back | Approval |
|---|---|---|---|---|
| 0 | Commit the work on `codex/commercial-mvp-phase1` (no push) | Nothing at runtime | `git revert` | **CEO** |
| 1 | Restart the engine with the new code; no flags | Heartbeat thread, `/api/strategy-bank` and the dashboard panel go live; the bank stays off (panel shows "Experimental · not running"). Live alerts unchanged | Restart on the previous commit | **CEO** (engine restart) |
| 2 | Set `TRADEDEN_STRATEGY_BANK_ENABLED=1` in `backend/.env` and restart | The bank scans 16 strategies on each M15 close in its own thread: it records signals, resolves outcomes and fills the dashboard. **No Telegram** | Remove the flag and restart; the records stay for audit | **CEO** |
| 3 | Monitor for **4–8 weeks** | Recorded forward statistics accumulate per strategy (dashboard plus `data/strategy_bank/`). Watch gate rejections, duplicates and MT5 load | – | – |
| 4 | Per-strategy review against **pre-registered criteria**: at least 60 resolved signals, expectancy ≥ +0.05R, PF ≥ 1.10, consistent with the historical sign | Decides which strategies may alert | – | **CEO**, per strategy |
| 5 | Set `TRADEDEN_STRATEGY_BANK_TELEGRAM_ENABLED=1` and restart; optionally restrict alerting to approved strategies (a small allow-list change) | Bank alerts go to the existing chat, **one per opportunity**, labelled Experimental, with the live disclaimer and contradictory evidence | Remove the flag and restart; nothing is sent late (alerts older than 10 min expire) | **CEO** |
| 6 | Production status for any strategy (remove "Experimental") | Changes how alerts are presented | Revert the label | **CEO**, after forward evidence |

Also pending CEO decisions, which affect what subscribers receive today. None has been acted on:
1. **Live trendline_v5 and Trend/Momentum alerts** (V6 recommendation):
   - Bank #1/#2 are historically -0.20R and -0.23R per trade, and their live record matches (18% / 24% win rate).
   - Options: move them to SHADOW, or relabel them "research signals".
2. **S&R and SMC alerts:** label them "research signal, unproven", or pause them (V6).
3. **The 1.5R minimum reward/risk** in production qualification:
   - It blocks mean-reversion strategies (#9 targets the mean, about 1R) if they are ever registered as production strategies.
   - The bank applies its own per-strategy minimum (#9 = 0.5) and doesn't touch production qualification. Changing the production rule is a risk-parameter decision.
4. **Authoritative outcome resolver and scheduled reports** (T-032 G1–G2). Flags: `TRADEDEN_SIGNAL_OUTCOMES_ENABLED`, `TRADEDEN_TELEGRAM_REPORTS_ENABLED`.
5. **Longer history** (T-033): 5–10 years of M1/tick data with spreads would let the bank's historical tests distinguish small edges. External download; needs approval.

**Recommendation:** approve stages 0–2. Run the bank as a recorded, monitoring-only system, and decide on alerts (stages 4–5) only from its forward record. Separately, decide item 1. The evidence that the current live trendline alerts lose money is the strongest finding in this whole body of work.

## 8. Files

- **New:**
  - `backend/strategy_bank/` (`__init__.py`, `indicators.py`, `rules.py`, `engine.py`, `telegram.py`, `worker.py`)
  - `backend/research/bank_backtest.py`
  - `backend/tests/test_strategy_bank.py`
  - `src/garden/strategyBank.mjs`
  - `tests/strategyBank.test.mjs`
  - this report
- **Modified:**
  - `backend/main.py`: additive, flag-gated thread, health field and `/api/strategy-bank`
  - `src/marketRadar.js`: panel, on-open fetch, nav-anchor open
  - `src/main.js`: nav link
- **Data (git-ignored):** `data/strategy_bank/historical.json`. Once enabled, the bank also writes `signals.jsonl`, `opportunities.jsonl` and `telegram_notifications.jsonl` there.
- **Reproduce the historical results:** `python -m research.bank_backtest` (needs the cached MT5 history from `python -m research.lab generate`).

## T-036 addendum: no strategy limit, promotion gate, expansion research

- **The 20-strategy limit is removed.**
  - `rules.register(spec)` adds strategies at runtime, with no maximum. It validates required fields, rejects duplicate keys and assigns display numbers in order.
  - The tests no longer assume 20 rows. A test registers 40 extra strategies.
- **Promotion gate.**
  - New strategies enter as **RESEARCH**: scanned and recorded, **never alerted**. They never open an opportunity, so they can't block an alert from the 16 T-034 strategies, whose alert behaviour is unchanged.
  - A RESEARCH strategy may alert only after `qualification.promote(key, "QUALIFIED", approval=...)`. Code enforces three conditions:
    - FORWARD_TESTING came first
    - recorded forward results: at least 60 resolved signals, expectancy ≥ +0.05R and PF ≥ 1.10
    - a CEO approval reference
  - Every promotion and demotion is logged with a timestamp.
- **Qualification registry** (`strategy_bank/qualification.py`, `data/strategy_bank/qualification.jsonl`):
  - Append-only status history for all bank strategies (baseline dated to the T-034 commit) and research-library strategies (imported with their original timestamps).
  - `lifecycle_report(start, end)` supplies the daily and weekly reports.
- **Expansion research** (`strategy_bank/expansion.py`, `research/bank_expansion.py`; results in `data/strategy_bank/expansion_results.json` and the ledger):
  - 6 new families and 12 pre-registered configurations, using the same pipeline and costs as the bank.
  - The families: FX session momentum (Elaut et al. 2018), weekend gap fade, Turtle Soup (Raschke & Connors), Heikin-Ashi trend, KAMA trend (Kaufman) and prior-close reversion.
  - **None was admitted.** Five were rejected on train; prior-close reversion (k=1.5) looked strong on train (+0.30R, CI +0.05 to +0.57, n=171) but lost on validation (-0.08R), so it never reached the test.
  - All 12 configurations are ARCHIVED with their evidence. No strategy was added just to raise the count.
- **Capacity on this laptop:**
  - **Live scanning:** about 1.4 ms per strategy per symbol per M15 close. Over 1,000 strategies would fit a 30 s budget across 16 symbols; the MT5 bar fetch (~0.1–0.3 s per symbol) doesn't grow with strategy count.
  - **Backtesting:** the heaviest strategy takes ~11 s end to end over 16 symbols on one core, so ~2,500 full backtests an hour in parallel.
  - **The binding constraint is statistical, not compute:** every extra strategy tested raises the multiple-testing bar.
