# TRADEDEN signal quality: audit, implementation and walk-forward results (2026-11-22)

**Bottom line:**
- **Weak signals are now identified reliably.** Out of sample, signals the new engine grades REJECTED average −0.148R per trade; everything else averages about −0.03R.
- **Removing them lifts expectancy from −0.096R to about 0.00R per trade** (all instruments, after costs).
- **No configuration showed positive expectancy out of sample.** The 50% win rate and profit factor 1.3 targets were not met.
- **Nothing is promoted to live trading.** The quality gate ships in shadow mode: it grades and records, and changes no alerts.

Labels used below: **LIVE** = recorded live signals, hypothetical R. **HISTORICAL WALK-FORWARD** = simulated on MT5 history, out of sample, net of costs. Neither is an executed trade. No live trading, execution permission, MT5 setting or historical record was changed.

## 1. What was audited

| Source | Content |
|---|---|
| LIVE production confirmations | 685 confirmations, 649 resolved (22 Sep – 18 Nov 2026), from `setup_confirmations`, `signal_outcomes` and 55k lifecycle events |
| LIVE strategy bank | 1,055 signals, 983 resolved (19 Oct – 18 Nov) |
| HISTORICAL | 95,659 raw signals: 16 bank strategies plus the replayed production strategies, 16 instruments, 15 Oct 2024 – 12 Oct 2026. Each signal was simulated under 10 entry/exit variants at 1× and 2× costs: spread, commission, 0.5-spread stop slippage, financing, M1 tie-break, ambiguous bars counted as stops |

Reproduce:

```
python -m research.signal_audit
python -m research.quality_dataset
python -m research.quality_research
```

Archived outputs:
- `docs/signal-quality-live-audit-2026-11-22.json`
- `docs/signal-quality-walk-forward-2026-11-22.json`

**About the quoted dashboard figures** (453 detected / 48 confirmed / 10 TP / 36 SL / −17.98R): they carry no report window, so they could not be reproduced as a unique cohort. The whole-store live record is worse:
- 1,632 resolved signals
- 30.8% win rate
- −0.076R per signal
- −123R in total

## 2. The five biggest causes of poor signal performance

**1. The core production strategies have no edge, and the current trendline version is the main loser.**
- **LIVE:**
  - `trendline_v5` (v5/v5.1): 313 resolved, 20.8% win rate, −80R, PF 0.68.
  - The retired v3 it replaced was +28R. Its REVERSAL setups alone were +84R over 98 signals, but that is small-sample and regime-dependent.
- **HISTORICAL out of sample:**

| Strategy | Trades | Expectancy | Win rate | Average loss |
|---|---|---|---|---|
| trendline_bounce | 6,292 | −0.236R | 23.9% | −1.14R |
| trendline_break_retest | 1,661 | −0.255R | 23.8% | −1.14R |
| support_resistance | 519 | −0.126R | | |

- No strategy has expectancy with a confidence interval above zero.

**2. Stops are too tight for the costs and noise, and targets are too ambitious.**
- **Stop size, HISTORICAL:**

| Stop distance | Expectancy |
|---|---|
| < 0.5 ATR(H1) | −0.26R |
| 0.5–1 ATR | −0.15R |
| ≥ 1 ATR | −0.04 to −0.06R |

- Other stop evidence:
  - 20% of all stops are hit within one hour of entry.
  - Tight-stop strategies lose 1.14R per loss, because spread and slippage are large relative to the risk.
- **Targets:**

| Planned R:R | Historical expectancy | Live win rate |
|---|---|---|
| 2.5–3.5 | −0.21R | 17% at ≥ 3R |
| ≥ 3.5 | −0.25R | 8% at ≥ 5R |

- 24% of stopped trades had first been +1R in profit.

**3. Live R overstates performance, and the lifecycle counts are mostly noise.**
- **LIVE outcomes record SL = exactly −1R** with no spread, slippage or financing. The historical simulation of the same strategies shows −1.14R per loss.
- **Revisions and gaps:**
  - 267 of 685 production outcomes were revised.
  - 25 are UNAVAILABLE.
- **"Detected" is inflated by geometry churn:**
  - 87% of 25,755 setups end EXPIRED.
  - 15,068 of those were `EPISODE_REPLACED:LEVEL_CHANGED`.
  - Only 3% ever reach ACTIVE.
  - "Expired" therefore measures redrawn levels, not lost opportunities.

**4. Timing and context filters are missing.**
- **Session (HISTORICAL):**
  - NEW_YORK −0.19R and LATE_US −0.14R.
  - ASIA −0.04R and LONDON −0.05R.
  - The live bank agrees on London being best.
- **Regime:**
  - Reversion setups fading a trend: −0.21R.
  - Reversion setups in ranges: −0.17R.
  - Trend setups in low volatility: +0.06R.
- **Instrument:** XAUUSD is the only target instrument that is positive unfiltered, at +0.057R.

**5. Indicator agreement adds little, and "confluence" is mostly hindsight.**
- Once instrument, strategy, session, stop size and regime are controlled for, RSI, MACD, H4 trend and H1 structure each move expectancy by only ±0.01–0.03R in the fitted model. Adding confirmations does not create edge.
- **Confluence looks strong but is mostly look-ahead.**
  - 57% of signals coincide with another strategy (same symbol and direction).
  - Measured with ±1h, those clustered signals look far better: +0.015R versus −0.22R isolated. The live bank shows the same pattern for merged opportunities.
  - Measured causally (only earlier signals), the effect shrinks and vanishes in 2026: at 3+ agreeing strategies, −0.12R versus −0.16R with none.
  - Later strategies confirm because price has already moved. It was **not** added to the model.

**Answers to the specific questions:**

| Question | Finding |
|---|---|
| Entering too early? | Not the main problem. A confirmation-candle entry raises win rate (32% → 39%) but not expectancy (−0.096 → −0.079R, fewer trades). A pullback-limit entry is worse (−0.17R). |
| Fighting the trend? | Mildly harmful: D1 trend against −0.109R versus with −0.066R. Not decisive. |
| Duplicate signals? | Yes (see cause 5), but the overlap is not an exploitable edge. |
| Recent strategy form? | Not predictive. A strategy's last-40-trade form does not forecast its next trades. |

## 3. What was implemented

| Component | File | What it does |
|---|---|---|
| Regime detection | `backend/signal_quality/regime.py` | TRENDING / RANGING / HIGH_VOLATILITY / LOW_VOLATILITY / BREAKOUT / REVERSAL from closed H1 bars, with H4 context. Fixed a-priori thresholds. |
| Setup features | `backend/signal_quality/features.py` | 22 bucketed, causal features: HTF H4/D1, structure, ADX/DI, RSI, MACD, ATR regime, Bollinger width, extension, stop in ATR, room to next swing level, planned R:R, session, tick activity (labelled as broker ticks, not volume), regime × strategy family |
| Quality scorecard | `backend/signal_quality/model.py` | Additive model of net expectancy fitted by backfitting with empirical-Bayes shrinkage (200 pseudo-trades), so rare buckets cannot create an A+. Fixed grade thresholds: A+ ≥ 0.30R, A ≥ 0.15R, B ≥ 0.05R, C ≥ −0.05R, else REJECTED. Capped at C on regime incompatibility; capped at B with fewer than 300 strategy trades. |
| Strict lifecycle | `backend/signal_quality/lifecycle.py` | Rules can reach only CONFIRMING. CONFIRMED requires A/A+; anything else ends as **NO TRADE** with reasons. |
| Live integration | `backend/signal_quality/live.py`, `strategy_bank/engine.py` | Every bank signal gets `quality` (grade, expected R, supporting/against factors, caps, stage, regime). `TRADEDEN_QUALITY_GATE` = `shadow` (default, annotate only), `enforce` (only A/A+ may alert; NO TRADE is recorded and outcome-tracked and never blocks a later signal) or `off`. |
| Model artifact | `backend/signal_quality/model.json` | Fitted on all 95,659 historical signals. Advisory per-strategy exit suggestions are stored but not applied. |
| Research | `backend/research/signal_audit.py`, `quality_dataset.py`, `quality_research.py` | Live audit, dataset builder and walk-forward harness |
| API | `GET /api/signal-quality` | Live audit, walk-forward comparison, live grading by grade and stage |
| Dashboard | `src/garden/signalQuality.mjs` (Market Radar → "Signal Quality") | Old vs new engine, rejection rate, grade calibration; breakdowns by instrument, strategy, session, regime and month; per-strategy verdicts; live lifecycle; live grading |
| Indicators | `strategy_bank/indicators.py` (`adx`, `rolling_percentile`) | Causal; the live worker's H4/D1 windows were widened to 700/120 bars so EMA200/EMA50 match the full-history values used in research |

**Validation framework** (`research/quality_research.py`):
- **Walk-forward:** expanding window over six quarterly folds, Apr 2025 – Oct 2026.
- **Purging:** training uses only signals whose trade had already exited before the test quarter.
- **No tuning on test data:**
  - Exits and the scorecard are fitted on training rows only.
  - Thresholds were fixed before evaluation.
- **Realism:**
  - Positions are limited after filtering, so a rejected signal never blocks a later one.
  - Every result is repeated at 2× costs.
- **Controls:**
  - A random-selection control (20 seeds).
  - A minimum sample size of 30, with bootstrap 95% confidence intervals.

## 4. Results: old engine vs new engine (HISTORICAL WALK-FORWARD, out of sample, net of costs)

**Six target instruments** (XAUUSD, BTCUSD, ETHUSD, NAS100, US500, GER40):

| Engine | Signals kept | Trades | Win rate | Avg win / loss | Expectancy (95% CI) | PF | Max DD | E at 2× costs |
|---|---|---|---|---|---|---|---|---|
| Old engine (every signal) | 100% | 18,976 | 33.0% | 1.91 / −1.03 | −0.061 (−0.081 to −0.039) | 0.91 | 1,211R | −0.126 |
| **New engine (A/A+ gate)** | **6.4%** | **1,646** | **35.9%** | 1.76 / −0.99 | **−0.004 (−0.072 to +0.062)** | **0.99** | **104R** | −0.030 |
| B and above | 20.4% | 4,891 | 35.0% | | −0.042 (−0.080 to −0.005) | 0.94 | 233R | −0.075 |
| Exit changes only | 100% | 17,950 | 35.5% | | −0.041 (−0.061 to −0.021) | 0.94 | 818R | −0.092 |
| A/A+ gate + exit changes | 6.6% | 1,750 | 36.1% | | −0.047 (−0.111 to +0.014) | 0.93 | 112R | −0.077 |
| Confirmation-candle entry | 100% | 10,993 | 39.3% | | −0.064 | 0.90 | | −0.119 |
| Pullback-limit entry | 100% | 11,990 | 22.1% | | −0.108 | 0.87 | | −0.193 |

**All 16 instruments:**
- Old engine: −0.096R (CI −0.108 to −0.083), 32.4% win rate, PF 0.87.
- New engine: −0.001R (CI −0.054 to +0.052), 36.5% win rate, PF 1.00, on 3.8% of signals.
- A random selection of the same number of signals: −0.056R on average. The new engine beat all 20 random draws (the best draw was −0.012R).

**Grade calibration** (all instruments, every signal):

| Grade | Signals | Expectancy |
|---|---|---|
| A+ | 175 | −0.019R |
| A | 2,657 | +0.025R |
| B | 7,940 | −0.051R |
| C | 23,395 | −0.021R |
| REJECTED | 39,833 | −0.148R |

**What improved (measured):**
- Rejecting the worst ~40% of signals is robust:
  - REJECTED is clearly the worst group out of sample, in every view.
  - The gate removes most of the old engine's losses: drawdown falls from 1,211R to 104R on the target instruments.
  - Expectancy moves from clearly negative to roughly break-even.
- Per-quarter results, all instruments:
  - The gate was positive in 3 of 6 quarters: Q3 2025 +0.02, Q4 2025 +0.14, Q1 2026 +0.06.
  - It was negative in the other 3: Q2 2025 −0.06, Q2 2026 −0.09, Q3 2026 −0.05.

**What did not improve:**
- **Positive expectancy:** none of the configurations has a confidence interval above zero.
- **Targets:** none reaches the 50% win rate or PF 1.3 targets.
- **Grade separation:** the model separates REJECTED from the rest, but A+ is not better than A, and A barely beats B/C. It is a good *rejector*, not yet a *selector*.
- **Instruments:** ETHUSD, NAS100 and US500 remain negative even after gating.
- **Regime caps:** removing them slightly improved the out-of-sample result (−0.005R versus −0.028R, within noise). They are kept as the pre-registered design, but are not shown to help.
- **Exit changes:** these help the unfiltered engine (+0.03R) but not the gated one, so they stay advisory.
- **Entries:** the confirmation-candle entry is a clear example of a higher win rate without higher expectancy.

## 5. Strategy verdicts (out of sample; records are never deleted)

The gated figures below are the A/A+ subset of each strategy's out-of-sample signals.

| Verdict | Strategies (gated trades, gated expectancy) |
|---|---|
| Disable (keep records) | trendline_break_retest (63, −0.27R), support_resistance (7), opening_range_breakout (134, −0.17R), fair_value_gap (24), order_block_retest (9), smc* (0 gated) |
| Improve, quality-gated only (positive but not significant) | breakout (165, +0.14R), market_structure_break (64, +0.15R), ema_pullback (78, +0.12R), ema_crossover (31, +0.13R), macd_momentum (97, +0.09R), ichimoku (145, +0.07R), bollinger_reversion (51, +0.06R), donchian (443, +0.04R), london_breakout (427, +0.02R) |
| Restrict to instruments (not significant) | atr_breakout, inside_bar_breakout, liquidity_sweep, rsi_divergence, trendline_bounce (only 6 gated trades) |
| Insufficient evidence | trend_momentum (76 trades) |
| Promote | **none** |

\* SMC is positive unfiltered (+0.056R over 149 trades), but its confidence interval includes zero and the gate selects none of its signals.

Read the "improve" group with caution. These are subsets chosen per strategy, with small samples, and the walk-forward as a whole is break-even. They are leads for forward shadow validation, not results.

The full per-strategy figures are in `strategy_status` in the JSON: win rate, average win and loss, expectancy, PF, drawdown, sample size and by instrument.

## 6. What remains experimental, and recommended next steps

1. **Keep the gate in `shadow`.**
   - Turn on `enforce` only for bank Telegram alerts, and only after at least 3 months of forward graded signals show REJECTED < others and A/A+ ≥ 0.
   - The production scanner strategies (trendline_v5, S/R) are not yet graded live, because they run in a separate pipeline. Wiring them in is the next step.
2. **Fix live R.** Record cost-aware R (spread, slippage) in `signal_outcomes`, so live statistics match research.
3. **Fix detection churn.** Stop counting `EPISODE_REPLACED` as a new detected setup in dashboard totals.
4. **Stop and target design for the trendline family.**
   - The walk-forward repeatedly chose a 1.5×ATR stop with a 2R target for trendline and liquidity strategies.
   - Test this as a versioned strategy (trendline_v6) in shadow, not as a silent change.
5. **Replay trendline v3 historically** before considering reinstating it. Its live REVERSAL result (+84R over 98 signals) is the largest positive signal in the record, but it is unverified.
6. **Retrain the scorecard quarterly**, with the same walk-forward gate. The model must beat both the old engine and random selection out of sample before any version is promoted.
