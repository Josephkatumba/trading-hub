# TradeDen Edge Discovery V2: XAUUSD results (2026-11-23)

## Verdict: NO_EDGE

- **Nothing was promoted.** 0 of 8 pre-registered gold hypotheses passed both gates.
- **One hypothesis (H7, news momentum) passed development** and then failed both sealed holdouts.
- **Automated execution stays locked.** The cBot keeps `ExecutionUnlocked = false` and runs SignalsOnly.

All figures are historical simulations on IC Markets MT5 XAUUSD M15 data, net of spread, slippage and $3 per $100k notional commission per side. They are not live results.

## Reproducibility

| Item | Location |
|---|---|
| Plan | [EDGE_DISCOVERY_V2_PLAN.md](EDGE_DISCOVERY_V2_PLAN.md) |
| Protocol hash | `8ef8fb68…c94b`, registered before any result |
| Code | `backend/research/edge_v2/` |
| Reproduce | `cd backend; python -m research.edge_v2.runner develop; python -m research.edge_v2.runner holdout; python -m research.edge_v2.diagnose_v1` |
| Archived output | `docs/edge-discovery-v2-{develop,holdout,diagnose_v1}-2026-11-23.json` and `docs/edge-discovery-v2-ledger-2026-11-23.jsonl` (448 train/development trials, 47 out-of-sample fold evaluations, 1 holdout) |
| Reproducibility | An accidental partial re-run of `develop` (H1 and H2 only) reproduced the original gate-1 results exactly. The live ledger carries a note row; it is append-only, so no rows were deleted. |
| Preserved prior evidence | Scalper tds-1.0: `docs/scalper-v1-evidence-2026-11-23/` (SHA-256 manifest). edge-discovery-v1: `docs/EDGE_DISCOVERY_REPORT.md`, unchanged. |

## 1. Why tds-1.0 had about zero gross expectancy

The frozen tds-1.0 rules were run on development data only: XAUUSD M5, Jun 2025 – Jun 2026, 5,426 signals. Five findings:

1. **The signals contain no directional information.**
   - Signed forward return after a signal was +0.035 ATR at 30 min (t = 1.35) and +0.015 ATR at 2 h (t = 0.28).
   - The same bars with a random direction scored +0.002 and +0.038 ATR.
   - At no horizon from 5 min to 4 h is the signal distinguishable from a coin flip.
2. **The entries are late.**
   - Every setup requires a move that has already happened: on average +1.06 ATR in the 30 minutes before the signal (t = 61).
   - Gold M5 is a random walk at these horizons, so that past move tells you nothing:
     - lag-1 autocorrelation 0.007;
     - variance ratios 1.007 / 1.008 / 1.001 at 10 / 20 / 60 min;
     - after a 2.5σ bar, the next 30 minutes drift −0.14 bp.
3. **The trade geometry is symmetric noise.**
   - Over 2 hours, favourable excursion averaged 2.92 ATR and adverse excursion 2.85 ATR.
   - With a median stop of 1.41 ATR, 64% of trades touch −1R and 49% reach +1.5R. That is what a random walk produces, so gross expectancy is about 0.
4. **The quality score is not quality.**
   - Outcome by score bucket is *anti*-monotonic: score < 70 gave +0.16 ATR, score 90+ gave −0.02 ATR.
   - Every component's rank correlation with the 1-hour outcome lies within ±0.04.
   - Filtering on score selected nothing.
5. **Costs then decide the sign.** The median round trip costs 0.094 ATR, which is 0.067R. Adding that to a gross of about 0 gives the −0.07R measured in the walk-forward.

**Post-hoc slices,** not acted on because they are among dozens of slices:
- Breakout-retest signals: +0.14 ATR at 1 h (t = 2.3).
- Signals after the largest prior moves: +0.18 ATR (t = 2.3).

Both point the same way as every gold "lead" so far (continuation after large moves). Section 3 shows how that lead fared when tested properly.

## 2. Development walk-forward (Sep 2024 – Jul 2026, 26-week train / 13-week test)

Each test window uses only the config chosen on the train window before it. "Configs +" is the share of the family's 8 configs that were positive over all of development.

| Hypothesis | OOS trades | Trades/mo | Win % | Exp. R | PF | Max DD (R) | p (one-sided) | 95% CI | Beats direction control | Configs + | 2× costs | Gate 1 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| H1 Structure break + displacement | 134 | 8.8 | 34.3 | −0.087 | 0.85 | 24.1 | 0.78 | −0.30 … +0.14 | 26% | 50% | −0.107 | fail |
| H2 Liquidity sweep reversal | 80 | 5.2 | 36.2 | −0.116 | 0.79 | 18.6 | 0.82 | −0.35 … +0.13 | 13% | 0% | −0.135 | fail |
| H3 Opening-range breakout | 312 | 19.6 | 42.9 | +0.011 | 1.02 | 16.1 | 0.43 | −0.10 … +0.13 | 57% | 38% | −0.009 | fail |
| H4 Trend-day continuation | 76 | 4.9 | 53.9 | +0.079 | 1.49 | 3.0 | 0.12 | −0.05 … +0.21 | 93% | 50%* | +0.067 | fail (p) |
| H5 Compression → expansion | 420 | 26.4 | 34.8 | −0.039 | 0.93 | 39.6 | 0.73 | −0.16 … +0.08 | 27% | 0% | −0.067 | fail |
| H6 Gold session (NY reversal / Asia fade) | 104 | 6.8 | 47.1 | −0.115 | 0.72 | 14.0 | 0.92 | −0.27 … +0.04 | 14% | 25% | −0.132 | fail |
| **H7 News momentum** | **54** | 3.5 | 46.3 | **+0.262** | **1.57** | 4.3 | **0.076** | −0.08 … +0.63 | **96%** | **100%** | +0.152 | **PASS** |
| H8 Failed breakout / trapped traders | 50 | 3.3 | 30.0 | −0.353 | 0.46 | 22.1 | 0.99 | −0.62 … −0.07 | 6% | 0% | −0.407 | fail |

Max drawdown at 0.5% risk per trade is half the R figure in %. For example, H5's 39.6R is about 20%.

**\* Protocol flaw, disclosed:**
- The universal news blackout blocks entries into the 10:00 New York bar. H4's four "decide at 10:00" configs therefore never traded.
- H4's results come from its 12:00 configs only, and 50% was the most it could score on robustness.
- H4 failed on its p-value (0.12), independently of this.
- Fixing it means a new protocol version, counted as new trials. It is listed under follow-ups, not quietly re-run.

### By session (development out-of-sample expectancy in R, trades in brackets)

| Hypothesis | Asia | London | Overlap (London + New York) | New York only |
|---|---|---|---|---|
| H1 | +1.99 (1) | −0.01 (41) | −0.15 (69) | −0.12 (23) |
| H2 | – | −0.23 (51) | +0.18 (20) | −0.14 (9) |
| H3 | – | −0.04 (112) | +0.06 (172) | −0.08 (28) |
| H4 | – | – | +0.06 (9) | +0.08 (67) |
| H5 | −0.75 (7) | −0.07 (205) | +0.09 (114) | −0.08 (94) |
| H6 | −0.11 (104) | – | – | – |
| H7 | – | – | +0.21 (51) | +1.14 (3) |
| H8 | −1.01 (1) | −0.59 (23) | −0.03 (18) | −0.31 (8) |

- **The overlap session is the least hostile** for five of the seven families that traded it.
- **No session cell is significant.** The best overlap result, H2 +0.18R on 20 trades, is well inside the noise band.
- **London is negative for every family** that trades it.
- **Asia trades** (H6 Asia fade) lost.

## 3. Sealed holdouts (one shot, H7 only)

H7 was tested with the config chosen on the last 26 weeks of development: shock ≥ 2 ATR, 1 confirmation close, 4-hour time exit.

| Window | Trades | Exp. R | PF | Win % | 95% CI |
|---|---|---|---|---|---|
| Early holdout, Sep 2022 – Aug 2024 (never used by any program) | 190 | −0.052 | 0.92 | 30.5 | −0.27 … +0.20 |
| Recent holdout, Jul – Nov 2026 | 23 | −0.458 | 0.32 | 21.7 | −0.77 … −0.10 |
| Combined | 213 | −0.096 | 0.85 | 29.6 | −0.30 … +0.13 |
| Combined at 2× costs | 214 | −0.166 | 0.75 | 28.5 | |

Regimes:

| Regime | Trades | Exp. R |
|---|---|---|
| Low volatility | 117 | −0.00 |
| Mid volatility | 85 | −0.14 |
| High volatility | 11 | −0.73 |
| Up-trend | 142 | −0.00 |
| Down-trend | 71 | −0.28 |

- **Holm-adjusted p = 0.81.** All six gate-2 checks failed.
- **Verdict: REJECTED_AT_HOLDOUT.**

**What happened:**
- In development, H7's profit came mostly from **longs** (+0.34R vs +0.10R for shorts), during gold's 2025–26 uptrend.
- In the early holdout, a different and choppier regime, the effect disappeared. In down-trends it was clearly negative.
- This is the same signature edge-discovery-v1 saw:
  - a validation-period winner that was long-beta in a trending market;
  - a "beats random direction" result that held only while gold kept rising.

## 4. What this establishes

- **Fourteen intraday gold mechanisms have now failed out of sample**, across three independent programs and about 2,900 trials:
  - edge-discovery-v1: 1,962 trials;
  - tds-1.0: 288 configs;
  - edge-discovery-v2: 448 trials plus 47 out-of-sample fold evaluations;
  - earlier programs: about 227 configs.
- **The families cover** structure breaks, displacement, sweeps, failed breakouts, opening ranges, trend days, compression, session effects and news shocks.
- **On price and tick-volume data, at M5–M15, after realistic IC Markets costs, there is no evidence of a repeatable XAUUSD edge.** The return-structure measurements explain why: M5 and M15 gold is statistically a random walk, so price-pattern entries cannot know the next move.
- **The recurring "lead" is continuation after large moves:** H4 and H7 in development, and v1's MACD momentum. Each time it has either failed a holdout or depended on gold trending up during the test window.

## 5. Recommendations

1. **Do not unlock execution.** The verdict is NO_EDGE. The cBot runs SignalsOnly, journaling signals for forward evidence, at no risk.
2. **Stop testing price-only intraday gold patterns on this data.** More families on the same bars will mostly produce false positives; the noise ceiling is already being hit.
3. **If research continues, change the information set, not the indicators.** Each item below would be a new pre-registered protocol:
   - **A real economic calendar with consensus vs actual values,** so news momentum is conditioned on surprise size and sign. H7 used a time-of-day proxy that cannot tell a big surprise from a non-event. Note that the 2022–24 holdout is now spent for news-shock ideas.
   - **COMEX gold futures volume and order flow,** and CFTC positioning (COT), for genuine flow information that CFDs do not show.
   - **Longer horizons** (H4 to daily, holding days to weeks), where costs are small relative to moves. Validating those needs the 4+ years of M15/H1 history now available.
4. **Follow-up not run:** H4 with the 10:00 blackout conflict fixed. It is a new protocol version, worth running only alongside a broader daily-horizon study.
