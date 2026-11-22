# TRADEDEN V2: Edge Discovery Research Plan (pre-registered 2026-11-22)

This plan was written and its candidate registry hashed **before any result in it was computed**.

- **Registry:** `backend/research/edge/registry.py`.
- **Hash:** the hash is recorded in `data/research/edge/ledger.jsonl`, and the tournament refuses to run if the registry has changed since it was hashed.
- **Ledger:** every configuration tried, including failures, is written to the same ledger.

## 1. Starting point and what we already know

- **Prior work tested about 227 configurations across about 39 families** (V6, T-033, T-036, Strategy Bank, Signal Quality):
  - D1/weekly momentum, Donchian, squeeze, turtle soup, RSI(2), overnight drift, turn of month, weekend gap, ML logit, Williams VB and others.
  - Nearly all were **pooled across instruments**.
  - None has a confidence interval above zero out of sample.
- **This program differs in four ways:**
  1. Each instrument is researched independently.
  2. It starts with measured return structure (experiment 0) instead of indicators.
  3. Every candidate must beat a matched random-entry control, not just zero.
  4. The multiple-testing burden is counted explicitly, including the prior 227 configurations as context.
- **All 21 existing strategies are research candidates.** They enter the tournament as comparators with their own exits.

## 2. Datasets

| Data | Coverage | Use |
|---|---|---|
| MT5 M15 / H1 / H4 / D1 bars with recorded spread, IC Markets, verified UTC basis | Aug 2024 → 19 Oct 2026, 16 instruments | All experiments |
| M30 | Aggregated from M15, complete buckets only | Timeframe robustness |
| M1 | Jul → Oct 2026 | Intrabar tie-break only |
| **M5** | **Jul → Oct 2026 only** | **Excluded from discovery.** Three months cannot support train, validation and test. Acquiring 2+ years of M1/M5 needs the MT5 terminal, which is intentionally stopped. |
| Volume | Broker tick counts only | Order-flow imbalance and true VWAP are **not testable**. A tick-weighted session average is used and labelled as a proxy. |
| Costs | Recorded bar spread on the correct side; IC-Markets-Raw-style commission; 0.5-spread stop slippage; current swap rates | Every result. Each result is re-run at 2× costs. |

**Chronological splits:**

| Split | Period | Rule |
|---|---|---|
| Train | 15 Oct 2024 – 1 Oct 2025 | All selection happens here |
| Validation | 1 Oct 2025 – 1 Apr 2026 | Gate only, never selection |
| Test | 1 Apr – 12 Oct 2026 | One shot, for configurations already chosen on train |

**Honesty note on the test window:**
- This window was already used as a holdout by earlier projects and by the Signal Quality walk-forward.
- It is untouched for every *new* rule and parameter here, but it is not a virgin period.
- **The only truly untouched test is forward shadow trading.** Any survivor must pass it before promotion.

## 3. Experiment order (cheapest and most informative first)

0. **Return structure (train only).** Per instrument and timeframe (M15, M30, H1, H4):
   - lag-1 autocorrelation and Lo–MacKinlay variance ratios (q = 2, 4, 8, 16);
   - return autocorrelation after large moves (|z| > 2);
   - time-of-day mean return and volatility.

   This says whether each market's native short-horizon behaviour is momentum or mean reversion. It costs no trades and involves no multiple testing of strategies. Results on validation show whether the structure persists.
1. **Session and level mechanics with the strongest theory** (families C and D, plus A1 and A2): New York opening range on indices, Asian-range London breakout and its failure, previous-day and previous-week high/low reactions, stop-hunt reversal.
2. **Statistical families** (B): anchored-mean reversion (VWAP proxy), volatility expansion, H4 momentum, and the large-move conditional-autocorrelation rule. The rule's direction comes from the train-period structure in experiment 0.
3. **Quantitative layer** (E), run only on what earlier stages produce:
   - a regime-dependent selector;
   - a causal 2-of-N ensemble;
   - one per-instrument logistic classifier.
4. **Tournament and leaderboard.** Includes the existing 21 strategies, random-entry controls and buy-and-hold.

## 4. Candidates with the strongest theoretical justification

| Rank | Family | Mechanism | Prior evidence |
|---|---|---|---|
| 1 | NY opening range, intraday momentum on indices | Overnight information and institutional rebalancing concentrate order flow at the open. Early-session returns predict late-session returns (Gao, Han, Li & Zhou 2018). | Strong in index futures. Weaker after costs on CFDs. |
| 2 | Stop-hunt and failed breakout at well-known levels (previous day/week high/low, Asian range) | Stop-loss and breakout orders cluster beyond obvious levels (Osler 2003, 2005). The cascade overshoots, then reverts. | Documented in FX. Untested here per instrument at M15. |
| 3 | Time-series momentum on H4 (crypto, gold) | Slow information diffusion and trend-following flows (Moskowitz, Ooi & Pedersen 2012). Crypto shows short-horizon momentum. | D1 pooled version failed on test here. Per-instrument H4 not yet tested. |
| 4 | Anchored-mean reversion in ranges | Liquidity-provision reversal after temporary imbalances. | Weak. Bollinger reversion was the only bank strategy positive unfiltered (+0.05R, not significant). |
| 5 | Volatility expansion after compression | Volatility clustering. | Squeeze was rejected in V6 (pooled). Weak prior. |
| 6 | Classifier / ensemble | Only as good as the features. | T-033 logit failed. Low prior, included for completeness. |

## 5. How many trades count as evidence

- Net R outcomes have a standard deviation of about 1.2–1.5R.
- For a one-sided 95% test, the trades needed are n ≈ (1.645·σ / E)².

| True expectancy (σ ≈ 1.4R) | Trades needed | Real-world meaning |
|---|---|---|
| +0.10R | ~530 | Rarely achievable per instrument in 12 months |
| +0.15R | ~240 | Plausible for intraday families over validation + test |
| +0.25R | ~85 | — |

**Thresholds** (fixed now):

| Stage | Requirement |
|---|---|
| Train | ≥ 60 trades to be eligible for selection |
| Validation | ≥ 30 trades |
| Test | ≥ 30 trades |
| "Credible" | ≥ 100 out-of-sample trades (validation + test) |

A 10-trade result is never ranked above a 100-trade result.

## 6. Overfitting controls across 16 instruments and several timeframes

- **Discovery universe is the six target instruments only** (XAUUSD, BTCUSD, ETHUSD, NAS100, US500, GER40).
  - The other 10 instruments are an **out-of-universe consistency check** for survivors. A gold mechanic should show in silver; an index mechanic in the other indices.
- **Small fixed grids:**
  - ≤ 3 parameter configurations per family.
  - 6 common exits (1.5R, 2R, 3R, ATR trail, partial (half at 1R, half trailed), time exit), plus the family's natural target where one exists.
  - Timeframe is a grid dimension only for the four timeframe-agnostic families, and it is counted.
- **Selection** of one configuration per (family, instrument) uses **train only**.
- **Validation gate:**
  - expectancy > 0;
  - PF > 1.1;
  - ≥ 30 trades;
  - better than the 95th percentile of 20 matched random-entry controls;
  - **Holm-adjusted one-sided p < 0.10 across every (family, instrument) pair** that reached validation.
- **Test is one shot.** A candidate is **credible** only if all of these hold:
  - test expectancy > 0 and PF > 1.1;
  - validation + test expectancy CI lower bound > 0;
  - positive at 2× costs;
  - positive in ≥ 3 of 4 out-of-sample quarters.
- **Random-entry control** matches instrument, hours of day, long/short mix, stop distance in ATR, exits and trade count.
- **Benchmarks:** buy-and-hold return and drawdown per instrument per period, and the 21 existing strategies on the same periods.
- **Every result is recorded**, including failures, with parameters and the registry hash.
- **Survivors go to shadow mode only.** Nothing is activated live.

## 7. Leaderboard ranking

| Order | Criterion |
|---|---|
| Status tier | Credible → passed validation only → failed |
| Then 1 | Out-of-sample expectancy (validation + test) |
| Then 2 | Profit factor |
| Then 3 | Maximum drawdown |
| Then 4 | Trade count |
| Then 5 | Regimes positive (of those with ≥ 20 trades) |
| Then 6 | Expectancy at 2× costs |
| Then 7 | Quarters positive |

## 8. Adaptive selector hypotheses (tested, not hardcoded)

| Market state | Hypothesis |
|---|---|
| Trending gold | Continuation |
| Ranging gold | Reversion |
| Compression release | Breakout |
| Failed breakout | Reversal |

**How they are tested:**
- On train, for each instrument and regime (signal_quality.regime), the best eligible family is selected (≥ 30 train trades in that regime, positive expectancy).
- The resulting map is then traded on validation and test exactly like any other candidate.
- The map itself is reported, so each hypothesis is confirmed or contradicted by data.
