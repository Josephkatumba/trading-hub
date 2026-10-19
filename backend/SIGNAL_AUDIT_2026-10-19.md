# TRADEden signal performance audit (2026-10-19)

Read-only audit. No strategy rules, outcome calculations, stores or settings were changed. Sources:
- the running engine's own API (`/api/market/setup-episodes`, `/outcomes`, `/setups/{id}`, `/performance?days=30`, `/strategy-lab`)
- an independent replay on **MT5 M1 candles** (IC Markets, verified clock basis `America/New_York+07:00`) for all 134 live-strategy confirmations of the last 30 days

## Answer in one paragraph

The stop losses are real, and take-profit detection works. The "16 confirmed, 8 stops, 0 targets" view is mainly a **sampling artefact of the dashboard archive**:
- The archive keeps the 40 most recent *closed* episodes per strategy. Because Trend/Momentum (0 TP in its whole history) produces few setups, its 40 reach back three weeks and supply 13 of the 16 confirmed signals. The far busier `trendline_v5` contributes only 2.
- Across all live confirmations, the engine has **28 verified targets and 88 verified stops**, and MT5 agrees on 131 of 134 signals.

The underlying problem is real, though: within 24 hours the live signals hit TP first 29 times and SL first 89 times. That is a **25% target-first rate, -27.4R over 134 signals**, below the ~31% break-even for their median 2.3R targets. In addition, 132 of those 134 signals predate the executable-price qualification added on 12 Oct, so the current rules have only 2 signals of evidence.

## 1. Reconciling the dashboard totals (item 8)

The Garden archive (`marketRadar.js` → `/api/market/setup-episodes?bucket=all&limit=40&per_strategy=true`, `gardenModel.archiveSummary`) contains the closed bucket only:

| Strategy id | Closed episodes in archive | Confirmed among them |
|---|---|---|
| support_resistance | 40 | 0 |
| trendline_v5 | 40 | 2 |
| trend_momentum | 40 | 13 |
| trendline (retired v4, unregistered) | 40 | 0 |
| smc | 36 | 1 |
| **Total** | **196** | **16** |

- **The 196 are not "all observed setups".** They are the last 40 closed per strategy id, and each strategy's 40 cover a different period (25 Sep – 19 Oct overall). The retired legacy `trendline` id still takes 40 places.
- **The tiles don't add up to 16.** The 16 confirmed = 8 stop + 1 "unverified" (actually *pending*: no outcome was ever labelled) + **7 NO_HIT**, and NO_HIT has no tile. That is why the numbers look incomplete.
- **The tiles don't overlap.** "Invalidated" (92) and "expired" (88) count only *unconfirmed* episodes (92 + 88 + 16 = 196). The 16 confirmed episodes closed as 6 INVALIDATED, 9 EXPIRED and 1 RESOLVED in the lifecycle, but they are counted by outcome instead. Only the invalidated tile says "before confirmation"; the expired tile doesn't.
- **Lifecycle and outcome disagree on one signal.** USDCHF `c9a48565` is lifecycle `RESOLVED / TARGET_PRICE_CROSSED` but outcome **stop**. MT5 shows the stop was hit first at 21:00 UTC (daily rollover), 2.2h after confirmation; price reached the target only later. The lifecycle works from 30-second scan quotes and missed the short rollover spike, while the outcome engine reads candle extremes. The outcome engine is right.

The whole-history view (Strategy Lab, all live confirmations, verified outcomes):

| Strategy | Confirmed | Verified TP | Verified SL | Other (no hit/ambiguous) | Net R |
|---|---|---|---|---|---|
| trendline_v5 | 93 | 18 | 64 | 11 | -21.8 (PF 0.66) |
| support_resistance | 27 | 10 | 16 | 1 | +0.65 |
| trend_momentum | 14 | **0** | 7 | 6 (+1 pending) | -7.0 |
| smc | 1 | 0 | 1 | 0 | -1.0 |

## 2. The 16 confirmed signals: lifecycle, outcome and MT5 replay (items 1–3)

| Setup | Strategy | Instrument | Side | Score | Confirmed (UTC) | Lifecycle close | Engine labels 15m/1h/4h/24h | Dashboard tile | MT5 M1: first barrier | After (h) | Target (R) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `98b46301` | trendline_v5 | XAUUSD | SELL | 66 | 2026-10-19 05:16 | INVALIDATED (INVALIDATION_PRICE_CROSSED) | LOSS / - / - / - | Stop | Stop | 0.4 | 1.82 |
| `8a0afe2a` | trendline_v5 | USDCAD | SELL | 79 | 2026-10-12 10:15 | EXPIRED (INACTIVITY_TIMEOUT) | NO_HIT / NO_HIT / - / - | none (NO_HIT) | **TP** | 3.45 | 1.74 |
| `46c2a0e6` | trend_momentum | EURUSD | SELL | 93 | 2026-10-05 13:45 | EXPIRED (INACTIVITY_TIMEOUT) | NO_HIT / NO_HIT / NO_HIT / LOSS | Stop | Stop | 11.71 | 2.59 |
| `9cfc848c` | trend_momentum | NAS100 | BUY | 83 | 2026-10-04 22:15 | EXPIRED (INACTIVITY_TIMEOUT) | NO_HIT / NO_HIT / NO_HIT / NO_HIT | none (NO_HIT) | Stop | 90.77 | 3.15 |
| `a8400268` | trend_momentum | USDCAD | BUY | 83 | 2026-10-05 00:13 | INVALIDATED (INVALIDATION_PRICE_CROSSED) | NO_HIT / NO_HIT / NO_HIT / LOSS | Stop | Stop | 8.93 | 3.82 |
| `8cdc9f48` | smc | US500 | BUY | 95 | 2026-10-05 07:02 | INVALIDATED (INVALIDATION_PRICE_CROSSED) | LOSS / LOSS / LOSS / LOSS | Stop | Stop | 0.36 | 1.51 |
| `220910a6` | trend_momentum | XAUUSD | SELL | 76 | 2026-10-04 11:03 | INVALIDATED (INVALIDATION_PRICE_CROSSED) | - / - / - / LOSS | Stop | Stop | 13.32 | 5.63 |
| `25aa5ac1` | trend_momentum | EURJPY | SELL | 81 | 2026-10-04 21:10 | EXPIRED (EPISODE_REPLACED:SIGNIFICANT_PRICE_DISPLACEMENT) | NO_HIT / NO_HIT / NO_HIT / NO_HIT | none (NO_HIT) | Stop | 35.85 | 4.52 |
| `68cf625d` | trend_momentum | NAS100 | BUY | 82 | 2026-10-02 19:46 | EXPIRED (INACTIVITY_TIMEOUT) | NO_HIT / NO_HIT / - / - | none (NO_HIT) | Stop | 141.33 | 4.87 |
| `2d636781` | trend_momentum | XAUUSD | SELL | 76 | 2026-10-02 20:45 | EXPIRED (INACTIVITY_TIMEOUT) | - / - / - / - | Unverified (pending) | Stop | 51.63 | 4.88 |
| `55895216` | trend_momentum | EURJPY | SELL | 81 | 2026-10-02 18:30 | EXPIRED (INACTIVITY_TIMEOUT) | NO_HIT / NO_HIT / - / - | none (NO_HIT) | Stop | 87.82 | 6.09 |
| `617ec9dd` | trend_momentum | GBPUSD | SELL | 69 | 2026-10-02 08:52 | INVALIDATED (INVALIDATION_PRICE_CROSSED) | NO_HIT / NO_HIT / LOSS / - | Stop | Stop | 3.62 | 5.93 |
| `c9a48565` | trend_momentum | USDCHF | BUY | 89 | 2026-09-28 18:45 | RESOLVED (TARGET_PRICE_CROSSED) | NO_HIT / NO_HIT / LOSS / LOSS | Stop | Stop | 2.24 | 1.97 |
| `da5580fe` | trend_momentum | EURJPY | SELL | 75 | 2026-09-28 16:29 | EXPIRED (EPISODE_REPLACED:SIGNIFICANT_PRICE_DISPLACEMENT) | NO_HIT / NO_HIT / NO_HIT / NO_HIT | none (NO_HIT) | Stop | 57.02 | 4.72 |
| `6bdc1555` | trend_momentum | GBPJPY | SELL | 73 | 2026-09-28 00:00 | INVALIDATED (INVALIDATION_PRICE_CROSSED) | LOSS / LOSS / LOSS / LOSS | Stop | Stop | 0.31 | 4.24 |
| `f46dbbea` | trend_momentum | USDCAD | BUY | 82 | 2026-09-24 22:15 | EXPIRED (INACTIVITY_TIMEOUT) | NO_HIT / NO_HIT / NO_HIT / - | none (NO_HIT) | **TP** | 107.2 | 2.82 |

Notes on specific signals:
- **All 8 stops are genuine.** The stop came first on bid candles and also with the recorded spread added, so none was produced by a spread artefact.
- **USDCAD `8a0afe2a`: a real TP that was never recorded.** MT5 shows TP after 3.45h. The engine labelled only the 15m and 1h windows, and the 4h/24h windows were never resolved. The engine was not running between 12 Oct and 19 Oct (the episode expired by inactivity on restart). After a restart, the resolver only uses the recent candle window it fetches, so the missed horizons stay unlabelled (by design: `outcomes.resolve_due_market_outcomes` refuses truncated paths). Today the dashboard shows this signal as "no tile", not as a target.
- **XAUUSD `2d636781`: "unverified".** It was confirmed Friday 20:45 UTC, just before the weekend close, and no horizon was ever labelled. MT5 shows the stop after 51.6h, outside the 24h window.
- **USDCAD `f46dbbea`: TP after 107h.** That's outside the longest (24h) window, so NO_HIT is correct by definition.
- **XAUUSD `220910a6`: confirmed on stale data.** It was confirmed 4 Oct 11:03 UTC from a bar dated 2 Oct 20:45, about 38h old while the market was closed. The engine labelled only its 24h window. The `quote_fresh` qualification check added on 12 Oct now blocks this case.
- **Trend/Momentum targets are 2.6–6.1R away.** Several signals reuse the same fixed target level (NAS100 31482.2 twice, XAUUSD 4047.19 twice, EURJPY 175.147 twice). None was reached within 24h or, for most, within 7 days.

## 3. Is take-profit detection working? (item 3)

Yes. Across all 134 live confirmations, engine vs MT5 M1 (first barrier within 24h):

| Engine | MT5 agrees | MT5 differs |
|---|---|---|
| verified TP (28) | 28 | 0 |
| verified SL (88) | 88 | 0 |
| no hit / ambiguous (17) | 15 | 2: `8a0afe2a` TP (downtime, above); `c441e5b4` SL (both barriers inside one M15 candle at 00:00 UTC, so correctly AMBIGUOUS on M15; M1 shows the stop first) |
| pending (1) | 1 | 0 |

Systematic limits (not bugs, but they bias what the dashboard shows):
1. **The 24h maximum horizon.** A target further away than a day's travel can only end as NO_HIT, while a nearby stop is counted as a loss. This mostly affects Trend/Momentum (median target 5.6 ATR).
2. **Bid-only barriers for SELL signals.** MT5 bars are bid prices; a SELL closes at the ask. With the recorded spread added, 3 of the 29 M1 targets become stops. The engine labels bid-only, so it slightly *overstates* TPs for SELLs. The qualification step already uses the ask for SELLs, so the two are inconsistent.
3. **Downtime.** Horizons that fall due while the engine is off are never labelled afterwards.

## 4. Price precision (item 4)

- **Entry:** correct for 133 of 134 (matches the broker's digits).
- **Stop loss:** 130 of 134 have more decimals than the instrument allows. Stops are ATR-derived and never rounded to the tick, e.g. USDCAD 1.4267865 on a 5-digit symbol, or XAUUSD 4155.932142857143 on a 2-digit symbol.
- **Take profit:** 16 of 134 are unrounded the same way.
- **Effect on outcomes:** negligible. The difference is below one point, barriers are compared consistently, and in all 134 signals the stop used for labelling equals the planned stop.
- **Effect elsewhere:** it matters for anything shown to a person or sent to a broker. Telegram alerts currently print these unrounded values.

## 5. Do confirmations arrive too late? (item 5)

Lateness is measured from the close of the signal bar to the moment of confirmation:
- **Typical:** median about 32 s, 90th percentile about 10 min.
- **Outliers:** 24 signals took more than 5 min; one took 38h (the stale weekend bar above).
- **Effect on results:** late signals did **not** do worse. Those more than 5 min late hit TP first 36% of the time (8 TP / 14 SL), against 22% for on-time signals (21 / 75).
- **Monday:** 40% of confirmations fall on Mondays, but they perform the same as other weekdays (24% vs 25%).

Lateness is not the cause. What stands out is **how quickly stops are hit**:
- median 1.2h after confirmation
- 42 of 89 within 1 hour, and 11 within 15 minutes

Stops sit at about **1 M15 ATR** (median 0.99 ATR for trendline_v5), roughly one candle's range, and stop-outs cluster at 00:00 UTC (11) and 07:00 UTC (10). Wider stops did not do better in this sample (20% TP first at 1.25–2 ATR).

## 6. Is the confidence score calibrated? (item 6)

Live confirmations from the last 30 days. Target-first rate = TP / (TP + SL):

| Score | Signals | TP | SL | Target-first |
|---|---|---|---|---|
| < 70 | 23 | 2 | 19 | 10% |
| 70–79 | 57 | 12 | 39 | 24% |
| 80–89 | 32 | 6 | 17 | 26% |
| 90+ | 22 | 8 | 13 | 38% |

- **Ranking:** the score ranks in the right direction. Higher scores do better, and below 70 is clearly poor.
- **Not calibrated:** a score of 90 does not mean 90%. The best band reaches 38%, and only the 90+ band clears the ~31% break-even. The scores are rule points, as the README already says; the dashboard and alerts should not present them as confidence.
- **Driven by S/R:** the 90+ band is mostly Support & Resistance (17 of 22).

## 7. By strategy and instrument (item 7)

MT5 M1 replay, live strategies, last 30 days, first barrier within 24h:

| Strategy | Signals | TP | SL | None | Target-first | Net R |
|---|---|---|---|---|---|---|
| trendline_v5 | 93 | 19 | 65 | 9 | 23% | -21.1 |
| support_resistance | 27 | 10 | 16 | 1 | 38% | +0.6 |
| trend_momentum | 13 | 0 | 7 | 6 | 0% | -7.0 |
| smc | 1 | 0 | 1 | 0 | 0% | -1.0 |
| **BUY** | 62 | 8 | 45 | 9 | **15%** | -26.8 |
| **SELL** | 72 | 21 | 44 | 7 | 32% | -1.6 |

Instruments, worst first:
- **EURUSD:** 0 TP / 9 SL, -9.0R
- **NZDUSD:** 1 / 9, -7.4R
- **EURJPY:** 2 / 10, -7.0R
- **XAGUSD:** 1 / 8, -6.2R
- **ETHUSD:** 1 / 7, -5.0R

Instruments, best first:
- **GER40:** 3 / 1, +5.7R
- **USDJPY:** 2 / 1, +3.7R
- **NAS100:** 3 / 2, +3.4R
- **XAUUSD:** 3 / 6, +1.5R

Every instrument has 18 signals or fewer, too few to conclude anything per instrument.

## Recommendations (nothing implemented; each needs approval)

**Reporting:**
1. Show whole-history verified totals per strategy (the Strategy Lab numbers), not the archive sample. Label the archive "last 40 closed per strategy".
2. Add a "no barrier / ambiguous" tile so confirmed signals add up.
3. Drop the retired `trendline` id from the live archive.
4. Treat the outcome engine as the source of truth when a lifecycle "TARGET" closure contradicts it (USDCHF `c9a48565`).

**Outcome engine:**
5. Backfill horizons that fell due during downtime from MT5 history (with the same chronology checks), so cases like `8a0afe2a` are not lost.
6. Resolve AMBIGUOUS M15 candles with M1 data when it is available.
7. Use the ask for SELL barriers, consistent with qualification.
8. Consider a "first barrier, up to N days" label in addition to the fixed horizons, so far targets are not structurally invisible.

**Precision:**
9. Round stop loss and take profit to the instrument's tick size when the plan is made, or at least in every display and in Telegram messages.

**Strategy review (for the strategy owner):**
10. Trend/Momentum has 0 targets in its history; its targets are 5.6 ATR away. Review the target rule or move it to shadow.
11. trendline_v5 BUY signals hit TP first in only 15% of cases.
12. Review the score < 70 confirmations (10%).
13. Review stops of about 1 ATR during the 00:00 UTC rollover hour.

**Telegram:**
14. Alerts currently go out for every live strategy. Consider limiting them, for example to S/R or score >= 90, until the review is done.

**Re-audit:**
15. Re-run this audit once there are at least 30 confirmations after the 12 Oct qualification change. Today's numbers mostly describe the pre-qualification engine.

## Method and evidence

- **Totals:** reproduced exactly from the live API; the counting logic is in `gardenModel.archiveEntry` and `archiveSummary`.
- **Engine outcomes:** classified with the dashboard's own rule (`isValidatedOutcome`) and the backend rule (`strategy_lab.classify_outcome`), using the confirmation observation only. Later WATCH observations of the same setup generate many more outcome rows (17,627 for these 16 setups); none of them were counted.
- **MT5 replay:**
  - M1 bars normalised with `market_time.normalize_mt5_epoch`, using bars strictly after the confirmation minute
  - TP/SL taken from the immutable confirmation snapshot
  - bid-based, plus a variant that adds each bar's recorded spread for SELLs
  - a barrier is counted only on the first minute that touches it
- **Net R:** +plan R for a target, -1 for a stop. It includes the spread but no commissions.
- **Scripts and raw evidence:** kept outside the repository in the session scratchpad (`audit/`), not committed. They can be added under `backend/tests/tools/` if wanted.
