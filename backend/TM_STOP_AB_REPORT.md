# Phase 11: Trend / Momentum stop-model A/B (tm-pullback-v1 vs tm-pullback-v2)

Generated 2026-09-25 with `python tests/tools/tm_stop_ab_report.py OUT.json` (read-only: MT5
history only; nothing written to the store). Replay rules are in `stop_ab.py`. This is a
measurement of two fixed models, not an optimisation: no parameter was chosen from these results.

## What triggered the investigation — and what the data actually shows

The reported XAUUSD Trend/Momentum SHORT (entry 4291.72, stop 4293.06, risk 1.34, R:R 1:79) was
**not the plan the setup was confirmed with.** The stored records show:

| | Entry | Stop | Target | Risk | R:R |
|---|---|---|---|---|---|
| Confirmation snapshot (00:00 UTC, the event) | 4265.00 | 4293.06 | 4185.45 | 28.06 (1.56 ATR(H1)) | 1:2.84 |
| Last ACTIVE observation (01:21:40 UTC) | 4291.72 | 4293.06 | 4185.45 | 1.34 | 1:79 |

The strategy re-evaluates every scan with entry = the live price. While the confirmed short was
active, price rallied toward the (unchanged) stop, so each new observation re-planned from a worse
entry; the episode view and the analyst showed that latest observation instead of the confirmed
plan. The v1 stop itself was structural (pullback high 4288.56 + 0.25 ATR(H1)), its risk was
inside the 0.5–3.0 ATR envelope, and the confirmation gate would have rejected a 1.34-point stop
(`stop_ok` requires ≥ 0.5 ATR(H1) ≈ 9 points). Price then traded to 4295.87 (stop hit, −1.0R on
the confirmed plan) before falling to 4256 — a modestly wider buffer would still have been hit.

The display/lifecycle problem is fixed separately (confirmed plans are immutable and shown as such;
see the Phase 11 notes in the final report). This A/B only measures the stop model.

## Models

| | A: tm-pullback-v1 (`fixed-h1-buffer-v1`) | B: tm-pullback-v2 (`structure-atr-guard-v2`) |
|---|---|---|
| Structural invalidation | H1 pullback extreme P | H1 pullback extreme P (same) |
| Buffer beyond P | 0.25 ATR(H1) | clamp(1.0 ATR(M15), 0.25 ATR(H1), 0.5 ATR(H1)) — closed bars |
| Risk envelope (`stop_ok`) | 0.5–3.0 ATR(H1) | 0.5–3.0 ATR(H1) (same), classified: NORMAL_RISK ≤ 2.0 < WIDE_STRUCTURE ≤ 3.0 < RISK_REJECTED; < 0.5 STOP_TOO_TIGHT |
| Oversized structure | not confirmed (`stop_ok`) | not confirmed, recorded as RISK_REJECTED with "Structural invalidation requires excessive risk. Setup rejected." The stop is never moved to force a trade. |
| Setup rules, target, min R:R 1.5 | — | identical (a bar's state and direction never differ) |

B's buffer is never smaller than A's, so on the same confirmation B's stop is always at least as far
away: B can only survive longer on a given path, at the cost of R:R and of more oversized rejections.

## Replay

16 scanned instruments, every M15 bar from 2025-09-01 to 2026-09-25 (439,310 evaluations). At each
bar the strategy saw only the bars that had opened by then; the forming M15 bar is flat at its open
(no future range). A confirmation opens a simulated setup unless one in the same direction is still
open (same live episode); an opposite-direction confirmation is a separate competing setup.
Resolution on the M15 path from the entry bar: TARGET / STOP (first touched), AMBIGUOUS (both in one
bar), EXPIRED (neither within 5 trading days), OPEN (history ends). **Market paths, not trade
results:** no spread, slippage or commission.

## Results (all instruments)

| | A (v1) | B (v2) | Change |
|---|---|---|---|
| Trigger evaluations (CONFIRMING bars) | 3,221 | 3,221 | — |
| … confirmed | 2,736 | 2,633 | −103 |
| … rejected, structural risk > 3.0 ATR (too wide) | 291 | 407 | +116 |
| … rejected, risk < 0.5 ATR (too tight) | 1 | 0 | −1 |
| … rejected, R:R < 1.5 | 125 | 136 | +11 |
| Confirmed setups (after episode de-duplication) | 677 | 643 | −34 (−5.0%) |
| TARGET first | 122 | 125 | +3 |
| STOP first | 522 | 484 | −38 |
| AMBIGUOUS | 0 | 0 | |
| EXPIRED (no barrier in 5 days) | 27 | 28 | +1 |
| OPEN (history ends) | 6 | 6 | |
| Target share of decided (TARGET/(TARGET+STOP)) | 18.9% | 20.5% | +1.6 pts |
| Stop distance, mean / median (ATR(H1)) | 1.503 / 1.440 | 1.654 / 1.621 | +10% / +13% |
| Stop distance, min / max (ATR(H1)) | 0.638 / 2.972 | 0.586 / 2.962 | |
| Extremely tight stops (< 0.75 ATR(H1)) | 10 | 5 | −5 |
| Stops < 1.0 ATR(H1) | 66 | 43 | −23 |
| Stops > 2.0 ATR(H1) (WIDE_STRUCTURE in v2) | 90 | 136 | +46 |
| R:R mean / median | 4.81 / 4.43 | 4.38 / 3.98 | −0.43 / −0.45 |
| R:R 10th / 90th percentile | 2.54 / 7.52 | 2.31 / 6.78 | |
| R:R max | 13.4 | 15.3 | |
| Mean R per decided setup (TARGET = +R:R, STOP = −1) | −0.007 | +0.002 | +0.009 |
| Median favourable excursion before a stop (R) | 0.62 | 0.62 | |
| Mean M15 bars to outcome | 70.3 | 77.1 | |

Paired comparison (same symbol, bar and direction confirmed under both): 638 pairs, 626 identical
outcomes. **12 survived under B but stopped under A** (10 then reached the target, 1 expired, 1 is
still open); **0 survived under A but stopped under B** (by construction). 39 setups were confirmed
only under A (B's wider stop pushed them past the 3.0 ATR envelope or below R:R 1.5) and 5 only
under B.

No confirmation in either model had an R:R anywhere near 1:79 (A's maximum was 13.4). An extreme
R:R at confirmation is prevented by the 0.5 ATR(H1) floor in both versions.

By direction: LONG A 80 T / 300 S (21.1%), B 81 / 280 (22.4%); SHORT A 42 / 222 (15.9%), B 44 / 204 (17.7%).

### By instrument (confirmed, TARGET, STOP, target share of decided, median stop ATR(H1))

Samples per instrument are 30–60 setups; differences at this size are not evidence of a better model.

| | A conf / T / S | A share | A median stop | B conf / T / S | B share | B median stop |
|---|---|---|---|---|---|---|
| XAUUSD | 42 / 12 / 27 | 30.8% | 1.54 | 42 / 12 / 27 | 30.8% | 1.73 |
| BTCUSD | 56 / 10 / 45 | 18.2% | 1.23 | 52 / 10 / 41 | 19.6% | 1.40 |
| ETHUSD | 50 / 9 / 39 | 18.8% | 1.35 | 49 / 9 / 38 | 19.1% | 1.52 |
| EURUSD | 44 / 6 / 35 | 14.6% | 1.44 | 41 / 6 / 32 | 15.8% | 1.54 |
| GBPUSD | 31 / 4 / 24 | 14.3% | 1.41 | 30 / 4 / 23 | 14.8% | 1.55 |
| GBPJPY | 34 / 5 / 28 | 15.2% | 1.40 | 32 / 5 / 25 | 16.7% | 1.62 |
| USDJPY | 43 / 5 / 33 | 13.2% | 1.46 | 42 / 5 / 32 | 13.5% | 1.60 |
| NAS100 | 37 / 10 / 27 | 27.0% | 1.72 | 35 / 10 / 25 | 28.6% | 1.86 |
| US500 | 32 / 4 / 28 | 12.5% | 1.61 | 31 / 4 / 27 | 12.9% | 1.71 |
| GER40 | 38 / 7 / 29 | 19.4% | 1.57 | 35 / 8 / 25 | 24.2% | 1.77 |
| USDCHF | 43 / 9 / 33 | 21.4% | 1.55 | 41 / 9 / 31 | 22.5% | 1.79 |
| USDCAD | 39 / 5 / 31 | 13.9% | 1.42 | 35 / 5 / 27 | 15.6% | 1.54 |
| AUDUSD | 40 / 5 / 33 | 13.2% | 1.40 | 38 / 6 / 30 | 16.7% | 1.62 |
| NZDUSD | 60 / 10 / 50 | 16.7% | 1.29 | 53 / 11 / 42 | 20.8% | 1.46 |
| XAGUSD | 47 / 15 / 28 | 34.9% | 1.44 | 46 / 14 / 28 | 33.3% | 1.67 |
| EURJPY | 41 / 6 / 32 | 15.8% | 1.49 | 41 / 7 / 31 | 18.4% | 1.68 |

## Reading the trade-off

- **Survivability:** B turns 38 stop-outs into 12 paired survivals plus 34 fewer confirmations;
  most of the stop-out reduction comes from confirming fewer setups, not from rescuing trades.
- **Stop size:** +13% median stop distance; wide structures (> 2 ATR) rise from 90 to 136 and are
  now labelled WIDE_STRUCTURE instead of looking like any other stop.
- **R:R:** median 4.43 → 3.98. Both are realistic (1:2.3–1:7 for 80% of setups). Neither model
  targets an R:R; it follows from entry, stop and target.
- **Frequency:** −5% confirmations; oversized-risk rejections at trigger bars +40% (291 → 407).
- **Market-path R:** both ≈ 0 per decided setup before costs (−0.007 vs +0.002). The difference is
  far inside noise at n ≈ 600. **This replay does not show that v2 is better, or that either model
  has an edge.** v2's gains are in explainability: every stop now carries its structural level,
  buffer, distance, envelope, quality label and — if rejected — the reason.

Limitations: M15 OHLC cannot order touches inside one bar (none were ambiguous here); no costs; the
live engine scans every few seconds, the replay once per M15 bar; live episode lifecycle
(pre-confirmation invalidation/expiry, terminal suppression) is simplified to "one open setup per
direction"; one year of one broker's data.
