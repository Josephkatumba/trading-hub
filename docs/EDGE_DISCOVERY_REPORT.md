# TRADEDEN V2 Edge Discovery: results of program `edge-discovery-v1` (2026-11-22)

**Bottom line:**
- **No strategy passed the pre-registered protocol.** 0 of 153 (instrument, strategy) pairs passed validation; none is CREDIBLE.
- **The evidence points to no exploitable short-horizon edge after costs in these six markets.** This is not a failure of the search. The p-values are no better than chance, train winners revert, the best result sits below the noise ceiling, and the price series are statistically close to random walks.
- **Gold momentum is a lead, not a proven edge.** The existing MACD momentum strategy is positive in all three periods on XAUUSD and on BTCUSD, but it fails multiple-testing correction and fails on the peer instruments.
- **Nothing was promoted.** Nothing was activated; all strategies stay in shadow/research.

All figures are HISTORICAL RESEARCH: simulated on MT5 history, net of spread, commission, slippage and financing. They are not live results.

**Plan, locks and reproduction:**
- **Plan:** [EDGE_DISCOVERY_PLAN.md](EDGE_DISCOVERY_PLAN.md).
- **Registry fingerprint:** `640635d5…70e3`, recorded in the ledger before any outcome was computed.
- **Reproduce:**

```
python -m research.edge.tournament
python -m research.edge.analysis
```

- **Archived:**
  - `docs/edge-discovery-v1-tournament-2026-11-22.json` (leaderboard, diagnostics, benchmarks, regime maps)
  - `docs/edge-discovery-v1-analysis-2026-11-22.json`
  - `docs/edge-discovery-v1-ledger-2026-11-22.jsonl` (all 1,962 trials)

## 1. What was run

| Item | Detail |
|---|---|
| Instruments | XAUUSD, BTCUSD, ETHUSD, NAS100, US500, GER40, each researched independently. XAGUSD and the other target instruments used as peers. |
| Families (14 new) | **A:** stop-hunt at previous-day high/low, failed Asian-range breakout, displacement pullback. **B:** anchored-mean (VWAP proxy) reversion, volatility expansion, time-series momentum, large-move autocorrelation. **C:** opening-range breakout (NY 09:30 / Frankfurt 09:00), intraday momentum, London compression breakout, London/NY overlap continuation, London exhaustion fade. **D:** previous-day high/low break-and-retest, previous-week high/low reaction. |
| Quant layer (3) | Regime-dependent selector, causal 2-of-N ensemble, per-instrument logistic classifier |
| Existing strategies | The 21 existing production and bank strategies, each competing with its own fixed rules |
| Timeframes | M15, M30, H1, H4. **M5 excluded:** only Jul–Oct 2026 exists, and acquiring more needs the intentionally stopped MT5 terminal. |
| Exits | Family natural target, 1.5R, 2R, 3R, ATR trail, partial (half at 1R, half trailed), time exit |
| Trials | 1,962 configuration × exit trials. 153 train-selected pairs tested at validation (68 new, 67 existing, 18 quant). Prior programs had already tested ~227 configurations. |
| Controls | 20-seed matched random entries per pair; buy-and-hold; Holm correction across all 153 pairs |
| Splits | Train 15 Oct 2024 – 1 Oct 2025 (selection only); validation to 1 Apr 2026 (gate); test to 12 Oct 2026 (one shot) |

## 2. Experiment 0: the markets are statistically close to random walks at M15–H4

- **Variance ratios:** VR(4) lies between 0.92 and 1.05 on train for every target and timeframe.
  - The only ratios with |z| > 2 are GER40 H4 on validation (VR(2) 1.12, VR(4) 1.25), a trending stretch that did not exist on train.
- **Lag-1 autocorrelations:** within ±0.04 everywhere except GER40 H4 on validation (+0.13).
- **The train-period structure does not persist.**
  - Examples of the large-move continuation sign flipping between train and validation:
    - XAUUSD H4: +0.44σ → −0.67σ
    - GER40 H1: −0.17σ → +0.24σ
    - BTCUSD H1: −0.08σ → +0.24σ
- **The diagnostics alone predicted the outcome:** there is no stable short-horizon predictability large enough to pay the spread.

## 3. Tournament results

**Status:**

| Status | Pairs |
|---|---|
| CREDIBLE | **0** |
| Passed validation, failed test | 0 |
| Failed validation | 153 |
| Ineligible (fewer than 60 train trades) | 68 |

**Top 10 of the leaderboard** (out of sample = validation + test):

| Pair | Exit | Trades | Win rate | Expectancy (95% CI) | PF | Max DD | 2× costs | Val / Test E | Quarters + | Raw p |
|---|---|---|---|---|---|---|---|---|---|---|
| ETHUSD · tsmom (H1, L=20) | time | 87 | 18% | +0.359 (−0.44 to +1.39) | 1.42 | 19R | +0.155 | +0.394 / +0.331 | 3/4 | 0.25 |
| XAUUSD · volatility_expansion | time | 84 | 31% | +0.297 (−0.17 to +0.82) | 1.42 | 13R | +0.288 | +0.056 / +0.618 | 3/4 | 0.43 |
| **XAUUSD · existing MACD momentum** | own 2R | **129** | 43% | **+0.290 (+0.03 to +0.55)** | **1.51** | **8R** | **+0.284** | **+0.290 / +0.291** | **4/4** | 0.053 |
| GER40 · existing EMA crossover | own | 57 | 42% | +0.230 (−0.15 to +0.61) | 1.39 | 7R | +0.141 | +0.195 / +0.263 | 2/4 | 0.25 |
| XAUUSD · existing London breakout | own | 118 | 52% | +0.219 (+0.01 to +0.43) | 1.53 | 8R | +0.214 | −0.065 / +0.458 | 2/4 | 0.66 |
| BTCUSD · existing MACD momentum | own 2R | 182 | 40% | +0.183 (−0.03 to +0.40) | 1.30 | 7R | +0.140 | +0.145 / +0.223 | 4/4 | 0.17 |
| US500 · existing EMA crossover | own | 63 | 41% | +0.181 (−0.18 to +0.56) | 1.28 | 14R | +0.133 | +0.372 / −0.043 | 3/4 | 0.08 |
| ETHUSD · regime selector | per family | 118 | 28% | +0.161 (−0.38 to +0.89) | 1.22 | 21R | −0.021 | +0.207 / +0.126 | 3/4 | 0.30 |
| XAUUSD · existing trendline break-retest | own | 65 | 32% | +0.153 (−0.29 to +0.62) | 1.22 | 17R | +0.140 | +0.424 / −0.111 | 2/4 | 0.13 |
| BTCUSD · existing EMA crossover | own | 90 | 39% | +0.151 (−0.15 to +0.45) | 1.24 | 10R | +0.130 | +0.037 / +0.255 | 3/4 | 0.43 |

**Why nothing passed:**
- **The smallest raw validation p-value was 0.0094** (BTCUSD previous-day break-retest, validation +0.44R). It then lost −0.17R on test, a textbook validation false positive.
- **Holm across 153 tests requires p < 0.0007.** The best Holm-adjusted p is 1.0.

## 4. Why this is evidence of no edge, not a failed search

| Check | Result | What it means |
|---|---|---|
| Validation p-values < 0.05 | 3 observed vs 7.7 expected by pure chance; < 0.10: 13 vs 15.3 | Fewer "discoveries" than noise alone would produce |
| Train → out-of-sample persistence | Rank correlation 0.22 over 1,569 trials. 37% of train-positive configs stay positive vs 29% of train-negative ones. | Selection on train barely helps |
| Selection decay | Train-selected new families: +0.072R train → −0.055R out of sample | In-sample edges evaporate |
| Noise ceiling | If no pair had any edge, the best out-of-sample E among 153 would be about +0.46R (95%: +0.79R). Observed best: +0.36R. | The top of the leaderboard is what noise alone produces |
| New vs existing vs quant | Mean out-of-sample E: new −0.055R (23/68 positive); existing −0.056R (26/67); quant −0.043R (4/18) | No family class is better than the others |
| Benchmarks | Buy-and-hold over validation → test: XAUUSD +21.5% → −10.9%; BTCUSD −40% → +23%; NAS100 −3% → +30% (Sharpe 2.05); US500 −1.8% → +19.6% (Sharpe 2.4) | Simply holding the indices beat every index strategy in the test period |

## 5. Entry and exit mechanics (every family × config with ≥ 30 out-of-sample trades)

| Exit | Cells | Mean out-of-sample E | Share positive | Mean win rate |
|---|---|---|---|---|
| Trailing stop (1R) | 242 | −0.043R | 32% | 37% |
| 2R | 240 | −0.045R | 35% | 38% |
| Natural target | 133 | −0.047R | 34% | 37% |
| 3R | 238 | −0.047R | 32% | 35% |
| 1.5R | 240 | −0.048R | 33% | 42% |
| Partial (half 1R, half trail) | 240 | −0.049R | 30% | **46%** |
| Time exit | 236 | −0.052R | 33% | 32% |

- **No exit mechanic creates expectancy.** All are within 0.01R of each other.
- **Partial profit-taking produces the highest win rate (46%) without better expectancy.** It is the clearest example of why win rate must not be targeted.

**Timeframes:**

| Timeframe | Mean out-of-sample E | Share positive |
|---|---|---|
| M15 | −0.060R | 24% |
| M30 | −0.038R | 37% |
| H1 | −0.045R | 35% |
| H4 | −0.016R | 33% |

- **Costs bite hardest on M15**, where it is worst.
- **H4 is least negative but has the fewest trades**: too few to validate within 12 months.

## 6. By instrument and family

**Instrument** (mean out-of-sample E across all cells):

| Instrument | Mean E | Share positive |
|---|---|---|
| XAUUSD | **+0.055R** | **70%** |
| GER40 | −0.035R | |
| NAS100 | −0.035R | |
| BTCUSD | −0.032R | |
| US500 | −0.043R | |
| ETHUSD | **−0.186R** | 9% |

- **Gold's positives are not long beta.** Gold longs and shorts did equally well (+0.054R / +0.056R): gold trended strongly in both directions during the period.
- **ETHUSD is hostile to every family tested.**

**Family** (mean out-of-sample E):

| Family | Mean E | Share positive |
|---|---|---|
| Previous-week high/low reaction | +0.017R | 58% |
| Opening-range breakout | +0.008R | 49% |
| Volatility expansion | −0.001R | 47% |
| Stop-hunt at previous-day high/low | −0.095R | 19% |
| Failed Asian breakout | −0.111R | 28% |

- The top three are near zero at best.
- **The "stop-hunt reversal" microstructure ideas are clearly negative.** The worst two families are both microstructure fades.

## 7. Adaptive selector: hypotheses tested

- **Train regime maps:**
  - Gold mapped TRENDING → time-series momentum (consistent with "trending gold → continuation").
  - But gold mapped RANGING → opening-range breakout, not mean reversion (the "ranging → reversion" hypothesis is not supported).
  - BREAKOUT → large-move continuation.
- **Out of sample**, the selector lost on gold (−0.11R validation, −0.04R test) and on 5 of 6 instruments; only ETHUSD was positive (+0.16R, CI −0.38 to +0.89).
- **On the training data the selector looked excellent:** +0.18 to +0.38R per instrument. **This is the largest overfitting effect in the study.**
- **Ensembles and classifiers fared no better:**
  - The 2-of-N ensemble was negative out of sample on 5 of 6 instruments.
  - The logistic classifier was positive on validation for gold only (+0.09R), then −0.05R on test.

## 8. The one lead worth forward-testing (not a validated edge)

**XAUUSD · existing MACD momentum (Strategy Bank #8, H1, own 1.5-ATR stop, 2R):**

| Period | Trades | Expectancy |
|---|---|---|
| Train | 130 | +0.219R |
| Validation | 71 | +0.290R |
| Test | 58 | +0.291R |

- **Strengths:**
  - Out of sample: PF 1.51, 43% win rate, drawdown 8R, CI above zero (+0.03 to +0.55).
  - Positive in 4/4 out-of-sample quarters and at 2× costs (+0.28R).
  - Longs and shorts are equal.
- **Why it is not credible:**
  1. **Holm-adjusted p = 1.0** (raw 0.053); it does not beat the random-control 95th percentile on validation.
  2. **It fails its peers:** ETHUSD is negative in all three periods; XAGUSD is mixed. Across all 16 instruments, MACD momentum is positive in every period only on XAUUSD, BTCUSD and (barely) USDJPY, close to the ~0.7 expected by chance.
  3. **It was picked from a ranked list after the fact.**
- **Recommendation:** keep it running in the Strategy Bank's shadow mode, where it is already recording live signals. Treat it as credible only after ≥ 100 forward signals with expectancy > 0 and PF > 1.3, measured from 2026-11-22 onward.

## 9. What would actually move the needle

1. **Different data, not more indicators.** Every price-only idea at M15–H4 in these markets is consistent with no edge after costs. Realistic sources of edge:
   - real order flow and volume (exchange futures data for indices and gold; exchange order books for crypto);
   - funding rates and basis for crypto;
   - positioning (CFTC COT);
   - an economic calendar, for event-conditioned behaviour.
2. **Longer history.**
   - 26 months gives at most ~12 months of out-of-sample data. That cannot validate H4/D1 strategies, which trade ~100 times a year.
   - Acquiring 5–10 years of M15/H1 data (MT5 history or a vendor) would allow true walk-forward on slower, theoretically stronger strategies (time-series momentum, carry).
3. **Lower costs or longer horizons.** M15 strategies are the most hurt by costs. H4/D1 trend-following on gold and crypto was the least negative, but it cannot be validated without longer data.
4. **Keep using this tournament as the gate.** Any new idea gets a new program version, and its trials are added to the multiple-testing count.

## 10. Rules compliance

| Rule | Status |
|---|---|
| Never optimise on the test set | Kept. Selection used train only; validation was a gate; test was evaluated once. |
| No look-ahead | Every generator is tested to produce identical signals with future bars removed (`backend/tests/test_edge_discovery.py`). |
| Pre-registration | The registry is fingerprinted and the harness refuses edits under the same program version. |
| Survivorship | All 21 existing strategies competed, including retired production replays; no instrument was dropped. |
| Results preserved | All 1,962 trials are recorded in the ledger with parameters and fingerprint. |
| Shadow mode | No live trading was enabled; no strategy was promoted; no execution permission changed. |
