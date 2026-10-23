# Claude Quant Lab — research journal

Author: actual Claude Code session (claude-opus-5-5), desktop session
`14e835e0-e7e8-43cf-b286-855a18365bd7`, 2026-10-20, under the TradeDen CEO directive of
the same date. Local research only. Official job results come from the owner-run frozen
evaluator queue; the figures below come from running that **same frozen evaluator code**
locally (imported read-only from `quant_labs/evaluation/v1`, nothing modified).

## Method

* Dataset: shared snapshot `bf130602…62cd3` (bid OHLC + recorded spread, M1/M15/H1/H4/D1).
* Splits fixed by `evaluation/v1/policy.json`: train 2024-10-15 → 2025-10-01,
  validation → 2026-04-01, test → 2026-10-01. Historical data was already seen by other
  research, so none of it is a truly untouched holdout.
* Replay (`research/harness.py`): the registered `detect(snapshot)` source is executed after
  passing the live host's `validate_source`; at each primary-bar close it sees only candles
  whose close ≤ decision time. Quote proxy = open of the M15 candle starting at the decision
  time (+ recorded spread for the ask). The live `qualify()` geometry/cost gate is emulated
  (risk 0.5–5 ATR, entry drift ≤ 0.5 ATR, spread/risk ≤ 0.1, net planned RR ≥ 2).
* Costs: frozen policy (commission; 0.25 spread adverse entry/TP/time fill; 0.5 spread on
  stops; swap modes 1/5; stress = doubled spreads/adverse costs, no swap credit).
* Protocol: parameters fixed a priori, then train. Rejected at train → stop. Survivors →
  validation unchanged → one test run. All failures kept and registered.

## Broker/data facts found (relevant to every lab)

1. **Crypto has a weekly gap every Friday 21:00/22:00 UTC** (1 h). The evaluator marks any
   trade straddling a missing M15 candle `INCOMPLETE`, so multi-day crypto holds must exit
   before Friday ~20:45 UTC.
2. Indices/metals have a daily 21:00/22:00 UTC break. Intraday index trades closing before
   17:00 New York are evaluable (no financing night), contrary to a blanket
   "indices are FINANCING_UNSUPPORTED".
3. The live collector cache keeps **≈200 bars per timeframe**. Any model requiring more (e.g.
   300 H4 bars) silently never fires live.
4. Live `qualify()` requires every required timeframe's last bar to have closed within
   2× its duration. **A D1 requirement therefore fails every Monday for FX/index CFDs** (last
   D1 closed Friday). ~20% of index signals would be silently dropped live. Suggested shared
   fix for owner review (not applied): make the staleness test session-aware, or exempt D1
   context when the instrument's last session closed normally.

## Experiment log

| # | Model @ version | Change | Train (net R/trade, n) | Validation | Test | Verdict |
|---|---|---|---|---|---|---|
| 1 | index_trend_day @0.1.0 | initial | +0.159 (103) | +0.117 (66) | +0.159 (56) | SURVIVOR |
| 2 | crypto_trend_breakout @0.1.0 | initial, 7-day horizon | −0.218 (15 of 37; 22 INCOMPLETE) | — | — | FAILED: horizon straddles Friday gap |
| 3 | crypto_trend_breakout @0.2.0 | horizon = min(7d, Fri 20:45 UTC); entry rules unchanged | +0.205 (40) | +0.370 (12) | +0.583 (16) | SURVIVOR (small n) |
| 4 | hourly_shock_drift @0.1.0 | initial | −0.099 (613) | (−0.130, seen after rejection) | (−0.075) | REJECTED: negative on all 8 markets |
| 5 | index_turn_of_month @0.1.0 | initial | −0.016 (100) | (+0.199, seen after rejection) | (+0.206) | REJECTED at train; later splits positive — re-open only with prospective data |
| 6 | index_gap_fade @0.1.0 | initial | −0.049 (37) | (+0.083) | (−0.494) | REJECTED |
| 7 | crypto_trend_breakout @0.3.0 | 50-day baseline from 50 D1 closes (live cache depth) | +0.205 (40) | +0.171 (14) | +0.652 (15) | SURVIVOR, live-compatible; test not independent of #3 |
| 8 | index_trend_day @0.2.0 | daily ATR from H4 grouped into broker days (Monday D1 staleness) | identical 228/228 intents to #1 | | | SURVIVOR, live-compatible; queue marked DUPLICATE of #1 |

Diagnostics (not selection; 21 runs, train+validation only, `results/sensitivity_summary.json`):
* index_trend_day: positive in both splits for every stop (0.25/0.40), target (3.0R), move
  threshold (0.35/0.55) and range-location (0.65/0.85) perturbation. **Fragile in decision
  time:** 60 min and 90 min after the open are negative/flat; 150/180 min weakly positive.
  TARGET_R 2.0 produces 0 trades because the live net-RR ≥ 2 gate rejects it.
* crypto_trend_breakout (run on @0.2.0): every perturbation positive in train and validation,
  but most effects are small (+0.02…+0.22R) on 35–50 trades.

## Pooled 2024-10 → 2026-10 (normal costs; stress in brackets)

| Model | n | Win | Net R/trade | PF | Max DD (R) | Longest losing run | Realized W/L | Trades/month | Weekly-bootstrap 95% CI | sign-flip p |
|---|---|---|---|---|---|---|---|---|---|---|
| index_trend_day @0.2.0 | 225 | 52.4% | +0.147 (+0.134) | 1.39 | 8.2 | 6 | 1.26 | 9.7 | [−0.008, +0.313] | 0.040 |
| crypto_trend_breakout @0.3.0 | 69 | 47.8% | +0.295 (+0.263) | 1.73 | 6.9 | 8 | 1.89 | 3.0 | [−0.096, +0.679] | 0.076 |
| index_turn_of_month @0.1.0 (rejected) | 211 | 47.9% | +0.099 (+0.086) | 1.20 | 14.4 | 10 | 1.31 | 9.1 | [−0.097, +0.308] | 0.185 |
| hourly_shock_drift @0.1.0 (rejected) | 1257 | 29.0% | −0.100 (−0.161) | 0.86 | 147.4 | 20 | 2.10 | 54.2 | [−0.192, −0.005] | 0.980 |
| index_gap_fade @0.1.0 (rejected) | 85 | 29.4% | −0.185 (−0.203) | 0.73 | 16.3 | 8 | 1.74 | 3.6 | [−0.496, +0.151] | 0.857 |

"Win" = any trade with positive net R, including profitable time exits. Planned RR was
2.2 (index) / 3.0 (crypto), but most trades end at the time limit, so realized win/loss is
1.26 / 1.89. index_trend_day is positive for both longs (+0.168, n=115) and shorts (+0.124, n=110).

p-values are unadjusted. With 8 registered versions and 21 diagnostics in this lab alone, no
result survives a multiple-testing correction. **No model is certified profitable.**

## Next hypotheses (not yet run)

* Prospective paper data for index_turn_of_month only (no more historical tuning).
* Index trend-day on the European cash close (GER40, 13:30 UTC) as an independent replication.
* Crypto breakout: needs years more events. Prospective observation is the only honest path.

## Phase 2 — frequency expansion (CEO directive 2026-10-20, second)

Live models index_trend_day 0.2.0 and crypto_trend_breakout 0.3.0 left unchanged.
Harness extended: M5 replay (aggregated from shared M1, complete 5/5-minute buckets only;
evaluated with an M1 confirming frame because the frozen evaluator has no M5) and
signals-per-weekday statistics. Shared helpers (`research/model_helpers.py.txt`) are
inlined into each model by `research/build_models.py` because the restricted host
permits no lab imports. All models exit before the next broker data gap.

| # | Model @ version | TF | Train net R (n) | Validation | Test | Signals/weekday | Verdict |
|---|---|---|---|---|---|---|---|
| 9 | fvg_retest @0.1.0 | M15 | −0.082 (1666) | −0.090 | −0.102 | 6.7 | REJECTED (train) |
| 10 | pdhl_acceptance @0.1.0 | M15 | +0.030 (56), stress −0.034 | −0.258 | −0.426 | 0.2 | REJECTED (train, stress negative) |
| 11 | session_mean_reversion @0.1.0 | M15 | −0.360 (327) | −0.051 | −0.256 | 1.3 | REJECTED (train) |
| 12 | london_momentum @0.1.0 | M15 | −0.164 (186) | −0.291 | +0.169 | 0.7 | REJECTED (train) |
| 13 | index_first_candle_drive @0.1.0 | M15 | +0.186 (550) | +0.066 | −0.002 | 2.2 | REJECTED (test) |
| 14 | channel_trend_m15 @0.1.0 | M15 | −0.057 (3186) | −0.034 | −0.065 | 28.9 raw / 13.0 eval | REJECTED (train) |
| 15 | channel_trend_m15 @0.2.0 (train-selected XAU/BTC/ETH) | M15 | +0.134 (673) | −0.029 | −0.005 | 5.4 | REJECTED (validation) |
| 16 | fx_fix_reversal @0.1.0 | M15 | −0.107 (162) | −0.081 | −0.133 | 0.6 | REJECTED (train) |
| 17 | index_orb_m5 @0.1.0 | M5 | — | — | −0.026 (145, Jul–Oct 2026 only) | 2.4 | REJECTED (exploratory) |

Later-split figures for train-rejected models were produced afterwards for the record only.
index_orb_m5 could not be registered: the research ledger rejects timeframe M5.
Only index_first_candle_drive was submitted (8-job lab cap); other intents await queue capacity.
Conclusion: no phase-2 model qualifies. Higher signal frequency came with worse expectancy.

## Milestone 2-3 (2026-10-23): cross-lab audit and pre-registered hypotheses

Audit of 87 instrument cells (all labs) with Holm correction: no positive cell survives; five
losing cells do (Trend Reclaim EURUSD/XAUUSD). Classification in research/audit/classification.json.
Crypto momentum theme (crypto_trend_breakout 0.3.0 + Codex BTCUSD trend_reclaim_r4): weekly
correlation 0.22, combined +0.272R / 150 trades, weekly-clustered p=0.16.

| # | Model @ version | Pre-registered | Train net R (n) | Verdict |
|---|---|---|---|---|
| 18 | london_sweep_continuation @0.1.0 | 674ab1e | -0.046 (115) | REJECTED at train gate |
| 19 | vol_climax_acceleration @0.1.0 | 674ab1e | -0.181 (406) | REJECTED at train gate |
| 20 | failed_orb_reversal @0.1.0 | 674ab1e | -0.095 (428) | REJECTED at train gate |

Range Sweep Reversion regime diagnostic: no stable conditional edge (research/audit/range_sweep_regimes.json).

## Phase 3 (2026-10-23): pre-registered gold & bitcoin hypotheses (commit 862075e)

| # | Hypothesis | Train | Validation | Verdict |
|---|---|---|---|---|
| H4 | Regime conditioning (R1 TRENDING at entry) of momentum candidates | crypto breakout: no effect; index trend-day: opposite in validation; Codex R4 BTCUSD: TRENDING +0.46/+0.44R vs OTHER +0.02/+0.00R (test +0.58 vs -0.08) | (same) | NOT ADOPTED: pre-registered minimum of 15 trades per cell not met; R4 regime effect recorded as a forward-monitoring diagnostic only |
| H5 | gold_session_drift 0.1.0 (vs always-long baseline B5) | +0.213R (49), stress +0.203; baseline +0.045 | +0.028R (19) < baseline +0.044 | REJECTED at validation (fails baseline condition); test not run |
| H6 | btc_weekend_momentum 0.1.0 (vs B6) | 2 resolved trades: 2.0R target fails the live net-RR>=2 gate after costs | not run | INVALID AS SPECIFIED; not amended post hoc; ~3 qualifying weekends/year, underpowered |
