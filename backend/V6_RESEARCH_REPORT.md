# TRADEden V6: strategy research and development report

Prepared for: CEO review. Date: 2026-10-19.
Status: research complete. **No production change, deployment, commit or push was made.** The live engine, the production strategies, the historical data and Telegram were left untouched.

## 1. Conclusion and production-readiness recommendation

**No candidate demonstrated a credible improvement, so no TRADEden V6 strategy is recommended for production.** The brief said to report this rather than force a winner, so that's the conclusion.

- **Scope:** 120 configurations in 14 strategy families (11 new research families and 3 built on the production strategies), plus a regime-aware hybrid and an instrument-selection test (section 6b). Each was selected on a train period, confirmed on a validation period and, if it survived, scored **once** on an untouched test period.
- **Multiple testing:** no candidate is statistically distinguishable from zero after Holm–Bonferroni correction (best: mean reversion, adjusted p ≈ 0.83).
- **Regimes and instruments:** a regime-aware hybrid and instrument-specific selection both failed out-of-sample. trendline_v5 is negative in every one of nine market regimes.
- **The one survivor, H1 Bollinger mean reversion,** is the best evidence found:
  - test **+0.07R per trade** after costs, PF 1.16, 193 trades, 58% win rate
  - but its 95% CI is -0.07R to +0.21R, it turns negative at double costs in development, and only 3 of 6 folds are positive
  - "Promising, not proven": it should be forward-tested in shadow, not deployed.
- **The current live engine is not production-ready as a source of trade signals:**
  - trendline_v5, which generates almost all alerts, is worse than every one of 20 random-entry twins with identical geometry and costs.
  - Trend/Momentum, S&R and SMC are negative or statistically indistinguishable from zero.
- **The binding constraint is data, not ideas.** At this signal frequency, a realistic edge of +0.05–0.10R per trade needs **12–50 months** of trades to confirm. The 6-month test window can only detect edges larger than about ±0.14R, so a "materially better" engine cannot be *proven* from two years of M15 history.

Recommended actions (all need CEO approval):

| # | Action | Why |
|---|---|---|
| 1 | Move **trendline_v5** and **Trend/Momentum** to SHADOW (no Telegram alerts) | Negative expectancy on every period, live and replay; trendline is below the random-entry control |
| 2 | Label S&R and SMC alerts "research signal, unproven" or pause them | Not distinguishable from zero after costs |
| 3 | Run **H1 Bollinger mean reversion (z=2.5, target = 20-bar mean)** as a SHADOW research strategy with pre-registered forward criteria (section 7) | The only family positive on train, validation and test |
| 4 | Acquire longer, higher-quality history: tick or M1 with real spreads, 5+ years | Needed to detect realistic edges (section 9) |
| 5 | Keep the authoritative outcome resolver and reports (T-032) | They are how forward evidence will be measured |

## 2. Baseline performance (production strategies, current code)

The lab replays the production strategy classes unchanged, bar by bar, with production `apply_plan` and executable-price qualification:
- BUY fills at the ask, SELL exits at the ask
- recorded spread, 0.5-spread stop slippage, commission
- M1 tie-break; ambiguous ties count as stops

**Train** 15 Oct 2024 – 1 Oct 2025, **validation** 1 Oct 2025 – 1 Apr 2026, **test** 1 Apr – 12 Oct 2026. Figures are expectancy in R per trade, with the 95% CI and n:

| Strategy | Train | Validation | Test | Trades/month | Dev. max drawdown |
|---|---|---|---|---|---|
| trendline_v5 | -0.18 (-0.23, -0.12), 4,264 | -0.22 (-0.30, -0.14), 2,401 | -0.26 (-0.33, -0.19), 2,501 | ~390 | **1,292R** |
| support_resistance | -0.17 (-0.32, -0.00), 342 | -0.12 (-0.35, +0.13), 180 | -0.02 (-0.24, +0.21), 175 | ~29 | 82R |
| trend_momentum | -0.34 (-0.69, +0.04), 47 | -0.15 (-0.63, +0.34), 29 | -0.13 (-0.64, +0.46), 28 | ~4 | 22R |
| smc | +0.04 (-0.29, +0.37), 78 | +0.08 (-0.33, +0.52), 55 | -0.23 (-0.68, +0.27), 51 | ~8 | 16R |

Live cross-check, using the authoritative outcomes from 25 Sep to 12 Oct:
- trendline_v5: 90 resolved, 21% win rate, -0.32R per signal, against a replay of -0.19R. Both are negative. Most live signals came from the looser pre-12-Oct v5 pipeline.
- The other strategies have too few live signals to compare.

## 3. The actual causes of poor performance

Several hypotheses were tested; the evidence points to three causes.

1. **No predictive edge in the entries.**
   - Random-entry control: each signal gets 20 random twins (same instrument, ±15 days, random direction, same stop distance in ATR, same R target, same costs).
   - **trendline_v5: -0.19R vs a random median of -0.17R, below all 20 draws.**
   - S&R is at the 15th percentile and Trend/Momentum at the 5th. SMC reaches the 90th, but on only 133 trades.
   - Before costs, trendline_v5 is -0.02R (CI -0.07 to +0.02): random-like.
2. **Costs are large relative to the risk taken.**
   - Stops of about 1 M15 ATR mean spread, commission and slippage cost about 0.15–0.17R per trade.
   - With no edge, expectancy is roughly minus that cost, which is exactly what is observed.
   - Every widening of stops moved results towards zero (T-032) but never above it.
3. **Volume amplifies the damage.** About 390 trendline trades a month across 16 instruments turns a small negative expectancy into a 1,292R drawdown over 17.5 months, and floods Telegram with low-quality alerts.

Hypotheses examined and *not* supported as the main cause:
- **Outcome tracking errors:** the authoritative resolver changed totals only slightly.
- **Target placement alone:** target caps and realistic-R variants were all negative.
- **Contradictory evidence:** see section 4.
- **Session timing:** London/NY filters moved trendline only from -0.19R to -0.15R.
- **Confirmation lateness:** late confirmations did no worse (audit).

## 4. Contradictory evidence: are the conflicts predictive?

A conflict uses the T-031B definition: an opposing H1 bias, opposing structure, opposing momentum, or price within 0.5 ATR of the opposing level. trendline_v5 history, train and validation only:

| Group | Train E (n) | Validation E (n) |
|---|---|---|
| All signals | -0.18 (4,264) | -0.22 (2,401) |
| 0 conflicts | -0.12 (447) | **-0.31** (302) |
| 1 conflict | -0.29 (1,674) | -0.19 (922) |
| 2+ conflicts | -0.10 (2,143) | -0.22 (1,177) |
| Opposing H1 bias: present / absent | -0.13 / -0.23 | -0.26 / -0.18 |
| Opposing structure: present / absent | -0.22 / -0.17 | -0.34 / -0.21 |
| Opposing momentum: present / absent | -0.16 / -0.19 | -0.13 / -0.27 |
| Opposing level < 0.5 ATR: present / absent | -0.16 / -0.20 | -0.20 / -0.25 |
| H1 bias and momentum both aligned | -0.17 (372) | -0.22 (233) |

Findings:
- About 90% of trendline signals carry at least one conflict, matching the live 78 of 94.
- **No conflict type is consistently predictive.** The H1-bias and momentum effects flip sign between train and validation. Conflict-free signals were the *worst* group in validation.
- Filtering conflicts did not improve expectancy (the "Trendline + conflict filters" family was rejected on train).
- Interpretation: the conflicts are a *symptom*. When entries carry no information, the indicators around them are as likely to disagree as to agree. They are worth showing in alerts as context, as T-031B now does, but not worth filtering on.

## 5. Testing environment

- **Data:** MT5 (IC Markets) history cached locally for 16 instruments: M15/H1/H4 from Aug 2024, D1 from Aug 2023, M1 from Jul 2026. Times are normalised through the verified broker clock basis.
- **No look-ahead:**
  - Production strategies are replayed at each M15 bar open with only closed bars and the open price.
  - New generators decide on closed bars and enter at the next bar's open.
  - Trailing stops update only after a bar closes.
  - Tests corrupt every value after the decision point and require identical signals; an injected leak is caught.
- **Execution:**
  - BUY at the ask, SELL exits at the ask.
  - Gaps fill at the open.
  - Stops slip 0.5 × spread.
  - Commission follows an IC-Markets-Raw-style table.
  - Same-candle TP/SL is settled on M1 or counted as a stop (pessimistic).
  - One position per strategy and instrument.
  - The stress test doubles all costs, now including the BUY entry spread. (The T-032 report's ×2 figures understated this slightly; all V6 figures use the corrected simulator.)
- **Selection protocol, fixed before results were seen:**
  1. Rank on train: at least 60 trades, positive expectancy, and at least half of the one-parameter neighbours also positive.
  2. Choose one configuration per family on validation: at least 30 trades and the best expectancy, which must be positive.
  3. Score test once.
  - Credible improvement requires all of: test E > 0 with the CI lower bound above 0, positive at ×2 costs in development and test, and at least 4/6 positive walk-forward folds.
- **Record:** every configuration, failed or not, is in `data/research/ledger.jsonl` (kinds `v6-train`, `v6-test`).
- **Protocol correction, disclosed:** the neighbour-robustness rule initially treated named variants (e.g. "as deployed") as parameter neighbours, which wrongly excluded the S&R session/stop variant. After the fix it went to validation and was rejected there (-0.05R), so it never reached test.

## 6. Ranked comparison of experimental strategies

| Rank | Family | Configs | Best train config: E (CI), n | Shortlisted | Chosen on validation: E, n | Test (scored once): E (CI), n, PF | Verdict |
|---|---|---|---|---|---|---|---|
| 1 | H1 Bollinger mean reversion | 4 | z=2.5, target 1.5R: +0.021 (-0.08, +0.13), n=489 | 2 | z=2.5, target mean: +0.067, n=174 | +0.068 (-0.07, +0.21), n=193, PF 1.158 | Promising, not proven |
| 2 | D1 time-series momentum (weekly) | 8 | lookback 60d, stop 1.5 ATR, trail3: +0.174 (-0.00, +0.35), n=291 | 5 | lookback 20d, stop 3.0 ATR, week: +0.011, n=339 | -0.043 (-0.10, +0.01), n=352, PF 0.798 | Failed on test |
| 3 | SMC (production) | 1 | as deployed: +0.036 (-0.29, +0.37), n=78 | 1 | as deployed: +0.083, n=55 | -0.231 (-0.68, +0.27), n=51, PF 0.722 | Failed on test |
| 4 | S&R (production) + session/stop | 3 | London/NY + no rollover + 2 ATR stop: +0.017 (-0.20, +0.23), n=207 | 1 | same: -0.046, n=110 | not scored | Rejected on validation |
| 5 | Donchian H1 trend breakout | 48 | N=20, stop 3 ATR, fixed 2R, no EMA filter: +0.018 (-0.04, +0.08), n=1,967 | 0 | – | not scored | Rejected on train (isolated spike) |
| 6 | H1 volatility squeeze breakout | 4 | width pct 0.1, trail3: -0.001 (-0.09, +0.09), n=1,736 | 0 | – | not scored | Rejected on train |
| 7 | London opening-range breakout | 16 | target 3R, far stop, range ≤ 1.5 ATR: -0.011 (-0.07, +0.05), n=2,687 | 0 | – | not scored | Rejected on train |
| 8 | H4 Donchian + D1 trend | 8 | N=20, stop 2 ATR, trail3: -0.013 (-0.14, +0.13), n=400 | 0 | – | not scored | Rejected on train |
| 9 | H1 trend pullback | 12 | stop 2 ATR, trail2: -0.059 (-0.10, -0.02), n=2,464 | 0 | – | not scored | Rejected on train |
| 10 | Trendline (production) + conflict filters | 4 | no conflicts + 2 ATR stop: -0.089 (-0.23, +0.05), n=601 | 0 | – | not scored | Rejected on train |
| 11 | Trend/Momentum (production) | 1 | as deployed: -0.335 (-0.69, +0.04), n=47 | 0 | – | not scored | Rejected on train |

Each family's rationale is in its docstring in `research/v6.py` and in the ledger.

Notable observations:
- **Trend following (H1 and H4 Donchian, H1 pullback, squeeze) sits at about zero after costs.** It's cheaper than the production strategies but carries no edge on these instruments over this period.
- **Weekly time-series momentum is a regime effect.** The 60-day versions were strong in train (2024–25), negative in all validation configurations, and the validation choice failed on test.
- **Mean reversion was positive in all three periods,** though weakly in train (+0.01R in development years 2024–25, +0.07R since). That's consistent with a modest, regime-dependent effect or with noise; the data cannot tell which (section 9).

## 6b. Expanded mandate (round 3): regimes, hybrid, new families, instruments, multiple testing

The CEO's expanded mandate asked for approaches beyond the four production strategies, regime-aware systems, instrument- and regime-level analysis, and control for multiple testing. Four hypotheses were registered before running (`research/v6_round3.py`), using the same protocol.

### Market-regime performance (train period)

Regime at each signal, from H1 bars already closed:
- **Trend:** |EMA50 change over 10 bars| / ATR above 0.5 is TREND, below 0.25 is RANGE, otherwise MIXED.
- **Volatility:** ATR / its 100-bar median above 1.25 is HIGH, below 0.8 is LOW.

Each cell shows expectancy in R per trade and (n). Cells with fewer than 20 trades are omitted.

| Stream (train) | TREND / HIGH | TREND / NORMAL | TREND / LOW | MIXED / HIGH | MIXED / NORMAL | MIXED / LOW | RANGE / HIGH | RANGE / NORMAL | RANGE / LOW |
|---|---|---|---|---|---|---|---|---|---|
| trendline_v5 | -0.10 (721) | -0.21 (1750) | -0.14 (527) | -0.03 (147) | -0.06 (400) | -0.24 (137) | -0.09 (98) | -0.32 (338) | -0.37 (146) |
| support_resistance | -0.23 (73) | -0.28 (156) | +0.06 (62) | – | +0.29 (22) | – | – | – | – |
| trend_momentum | – | -0.23 (27) | – | – | – | – | – | – | – |
| smc | – | -0.07 (30) | – | – | – | – | – | – | – |
| Donchian H1 (N=20, 3 ATR, 2R) | -0.03 (279) | -0.01 (583) | -0.03 (131) | -0.02 (144) | +0.04 (240) | +0.15 (59) | +0.05 (166) | +0.04 (296) | +0.26 (69) |
| H1 pullback (2 ATR, trail2) | +0.01 (207) | -0.10 (699) | -0.04 (268) | +0.06 (91) | -0.03 (396) | -0.01 (98) | -0.16 (115) | -0.07 (448) | -0.02 (142) |
| London ORB (3R, far, ≤1.5 ATR) | +0.14 (206) | -0.00 (780) | -0.05 (628) | +0.04 (45) | +0.14 (268) | -0.15 (197) | +0.11 (52) | -0.14 (319) | +0.01 (187) |
| H1 mean reversion (z=2.5, mean) | – | – | – | – | -0.15 (38) | – | +0.04 (84) | +0.06 (168) | -0.12 (48) |
| H1 squeeze (0.1, trail3) | -0.48 (23) | +0.02 (391) | +0.02 (330) | -0.12 (30) | -0.18 (256) | +0.07 (161) | +0.07 (37) | +0.02 (331) | +0.14 (177) |
| D1 TS momentum (60d, 3 ATR, trail3) | +0.10 (41) | +0.22 (78) | +0.10 (27) | – | +0.05 (38) | – | – | -0.11 (27) | – |

What the table shows:
- **trendline_v5 is negative in all nine regimes.** No market condition rescues it.
- Mean reversion lives where intended: only RANGE regimes are positive.
- Most other cells are within noise of zero, and the sign pattern is not coherent across neighbouring regimes.

### Results by hypothesis

| Hypothesis | Train | Validation | Test (once) | Verdict |
|---|---|---|---|---|
| **H-R1 regime-aware hybrid** (each family only in train-positive regimes; strict cell rule: n ≥ 40, CI lower bound > -0.05R). The rule selected only London ORB in MIXED/NORMAL and TS momentum in TREND/NORMAL. | +0.12R (CI -0.01, +0.25), n=412. In-sample by construction | **-0.01R** (CI -0.17, +0.16), n=243 | not scored | **Rejected**: regime selection does not generalise |
| **H-R2 cross-sectional momentum** (weekly; long the 3 strongest / short the 3 weakest of 16 by ATR-normalised 20/60-day return) | +0.00 to +0.07R in all 4 configurations | **negative in all 4** (-0.05 to -0.01R) | not scored | **Rejected on validation** |
| **H-R3 H4 inside-bar breakout** (pure price action, 6 configurations) | 3 shortlisted | target 3R + D1 trend chosen | **-0.17R** (CI -0.35, +0.02), n=272, PF 0.78 | **Failed on test** |
| **H-R4 instrument selection** (mean reversion only on the 8 instruments positive on train: BTCUSD, EURJPY, GBPJPY, GBPUSD, GER40, USDCAD, USDCHF, XAUUSD) | (selection set) | **+0.23R** (CI +0.03, +0.42), n=94, against -0.12R for the other 8 | selected **+0.04R** (CI -0.15, +0.23), n=98; **others +0.10R**, n=95 | **Rejected**: the instrument advantage reversed on test |

Notes:
- **H-R4 disclosure:** it was applied to mean reversion *because* that was the best family, after its aggregate test score was known. Its instrument set was fixed on train only.
- **What H-R4 shows:** the validation result looked convincing (CI above zero) and still did not hold. That is a concrete demonstration of why instrument-specific tuning on two years of data is not trustworthy.

### Multiple-testing control

- **Configurations evaluated in all rounds:** 120, plus the hybrid and the instrument analysis.
- **Test-scored candidates:** each was scored once. Below is its one-sided p-value for expectancy > 0, and the Holm–Bonferroni adjustment across all of them:

| Test-scored candidate | Test E | Raw p | Holm-adjusted p |
|---|---|---|---|
| H1 Bollinger mean reversion (z=2.5, mean), all instruments | +0.068 | 0.166 | 0.83 |
| H1 mean reversion, train-selected instruments (H-R4) | +0.039 | 0.349 | 1.00 |
| SMC (production) | -0.231 | 0.84 | 1.0 |
| D1 time-series momentum (20d, 3 ATR, week) | -0.043 | 0.94 | 1.0 |
| H4 inside-bar breakout (3R, D1 trend) | -0.174 | 0.96 | 1.0 |

**No candidate is statistically distinguishable from zero expectancy, even before the multiple-testing adjustment.** Given 120+ configurations, a single positive point estimate like mean reversion's +0.07R is well within what selection luck produces.

### Updated ranked comparison of the strongest candidates

All 14 families plus the hybrid are ranked by out-of-sample evidence:

1. **H1 Bollinger mean reversion, all instruments.** Positive on train, validation and test (+0.01 / +0.07 / +0.07R), but not significant, fails ×2 costs in development, and 3/6 folds. **Best available, unproven.**
2. **H1 mean reversion, instrument-selected.** Validation +0.23R, test +0.04R; selection did not persist.
3. **D1 time-series momentum.** Strong in train, negative on validation and test: a regime effect.
4. **Cross-sectional momentum.** About zero on train, negative on validation.
5. **Regime-aware hybrid.** In-sample +0.12R, validation -0.01R.
6. **Donchian H1 / H4, London ORB, H1 squeeze.** About zero after costs on train; isolated positive cells only.
7. **SMC (production).** Positive on train and validation, -0.23R on test.
8. **H4 inside-bar breakout.** -0.17R on test.
9. **H1 trend pullback; S&R (production) and its variants.** Negative to zero.
10. **Trend/Momentum (production); Trendline (production) and its conflict filters.** Clearly negative; trendline is below the random-entry control.

**Recommendation after the expanded mandate: unchanged.**
- No approach demonstrated a credible, repeatable edge on the available data.
- The only defensible next step is a **forward shadow test of H1 mean reversion on all 16 instruments, with frozen parameters** (section 7). Instrument selection and regime switching are not supported by the evidence.
- Longer, better data is needed before any production promotion.

## 7. Shadow candidate: research configuration

This is **not** a production configuration.

```
Family:      H1 Bollinger mean reversion ("Reversion V6-R1")
Instruments: all 16 TRADEden instruments (7 of 16 positive in development: no instrument selection applied)
Regime gate: H1 EMA50 slope over 10 bars < 0.3 x H1 ATR(14)       (quiet / ranging market only)
Trigger:     previous H1 close outside the 20-period 2.5-sigma band, current H1 close back inside
Entry:       next H1 open (BUY at ask, SELL at bid)
Stop:        1.0 x H1 ATR beyond the extreme of the two trigger bars
Target:      the 20-bar mean (trade skipped if the mean is < 0.5R away)
Time exit:   48 hours
Frequency:   ~31 trades/month across 16 instruments
```

Out-of-sample statistics (after costs):

| Period | Trades | Win rate | Expectancy (95% CI) | PF | Max DD | ×2 costs |
|---|---|---|---|---|---|---|
| Train | 370 | 53% | +0.007 (-0.09, +0.11) | 1.01 | – | – |
| Validation | 174 | 56% | +0.067 (-0.08, +0.22) | 1.15 | – | – |
| Development (train+validation) | 544 | 54% | +0.026 (-0.06, +0.11) | 1.06 | 23.4R | **-0.024** |
| **Test (once)** | 193 | 58% | **+0.068 (-0.07, +0.21)** | 1.16 | 16.1R | +0.035 |

Further detail:
- **Walk-forward folds:** -0.08, -0.09, +0.05, +0.13, +0.18, -0.05 (3/6 positive).
- **Test equity:**
  - monthly R: Apr -2.6, May +1.2, Jun -1.9, Jul -4.3, Aug +7.6, Sep +7.1, Oct (to 12th) +6.1
  - 4 of 7 months positive, longest losing streak 7 trades, max drawdown 16.1R
- **Proposed forward criteria,** pre-registered now, before any forward data:
  - after at least 120 forward shadow trades (about 4 months), promote only if expectancy is at least +0.05R after costs with PF of at least 1.10
  - expectancy must still be positive with costs doubled
  - no single instrument may contribute more than 30% of total R
  - otherwise retire the configuration
  - parameters stay frozen during the forward test.

## 8. Risk and drawdown analysis

- **trendline_v5 as deployed:** a 1,292R development drawdown. At even 0.25% account risk per trade, that is more than a 100% loss. Its live alert stream should not be used for trading.
- **Shadow candidate:**
  - development max drawdown 23.4R, test 16.1R
  - at 0.5% risk per trade, about an 8–12% equity drawdown, with no edge proven to pay for it
  - holding time about 15 hours; at most 16 positions open at once (one per instrument)
  - instruments are correlated (USD pairs, the indices), so drawdowns cluster.
- **Ambiguous same-candle outcomes:** 2 of 544 development trades, both counted as stops.

## 9. Remaining limitations

- **Statistical power is the binding constraint:**

| Stream | R dispersion per trade | Trades/month | Trades (months) to detect +0.05R | +0.10R | +0.20R | 6.4-month test CI half-width |
|---|---|---|---|---|---|---|
| Mean reversion | 1.0R | 31 | 1,542 (~50) | 386 (~12) | 96 (~3) | ±0.14R |
| trendline_v5 | 1.9R | 381 | 5,374 (~14) | 1,343 (~4) | 336 (~1) | ±0.07R |

  Realistic retail-scale edges (+0.05–0.10R) are invisible in a two-year sample at these frequencies. Longer history, ideally 5+ years with tick spreads, is the most valuable next investment.
- **One market history:** Oct 2024 – Oct 2026, dominated by a few regimes. The momentum results show how regime-dependent effects can look.
- **Spread data:** MT5 bar spread fields can understate real spreads at rollover and news, and commission is an assumption. Both are covered only partly by the ×2-cost stress.
- **M1 coverage:** only about 3 months, so older same-candle ties are AMBIGUOUS and counted pessimistically. They are rare.
- **Intra-bar decisions:** the production S&R and SMC strategies check reward/risk at the live intra-bar price. The bar-open replay reproduces 30/31 trendline and 10/11 Trend/Momentum live decisions, but only 2/6 S&R and 0/1 SMC.
- **Earlier look at the test window:** T-032 scored S&R V2, a near-identical variant, on the same window. No V6 choice used test data.
- **Multiple testing:** 120 configurations were evaluated. The shortlist and robustness rules reduce, but don't eliminate, selection luck. Holm-adjusted test p-values are all ≥ 0.8 (section 6b): the single "promising" result is consistent with luck.

## 10. Changes requiring CEO approval

1. Move trendline_v5 and Trend/Momentum to SHADOW, and pause or relabel the S&R and SMC alerts.
2. Implement "Reversion V6-R1" as a SHADOW strategy, frozen parameters, no alerts, with the forward criteria in section 7. It needs a production `Strategy` class; it is currently research code only.
3. Enable the authoritative outcome resolver and the reports (T-032 G1–G2) so forward evidence accumulates.
4. Approve sourcing longer history (5+ years, tick/M1 with spreads).
5. Commit the research code. It is uncommitted, nothing is pushed; files are listed below.

## Files and reproduction

- **New:** `research/v6.py`, `research/v6_round3.py` (expanded mandate)
- **Updated:**
  - `research/simulate.py`: trailing exits; BUY entry cost scales under stress
  - `research/metrics.py`: a win is a positive-R exit
  - `research/lab.py`: per-signal trail and holding limits
  - `tests/test_research_lab.py`: 4 new tests (trailing, costs, generator look-ahead)
- **Verification:** `python tests/run_suite.py` → **568 tests, OK**.
- **Results (git-ignored):**
  - `data/research/v6_results.json`, `data/research/v6_round3_results.json`
  - `data/research/ledger.jsonl` (all 109 V6 configurations plus finalists)
- **Reproduce:**
  - `python -m research.v6 baseline`
  - `python -m research.v6 conflicts`
  - `python -m research.v6 families`
  - `python -m research.v6 round2`
  - `python -m research.v6_round3`

  It requires the cached MT5 history (`python -m research.lab generate` for the production signals).
