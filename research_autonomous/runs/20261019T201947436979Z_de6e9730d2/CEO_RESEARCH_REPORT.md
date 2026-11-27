# TradeDen autonomous research — first mission report

19 October 2026 · Lead quantitative research work · **Offline, isolated, no deployment**

Run: `20261019T201947436979Z_de6e9730d2`. Full machine evidence and frozen source are in this run directory. No broker orders, production rule changes, production alert permission changes, Telegram sends or scheduled background jobs were performed.

## 1. Executive decision

**No candidate demonstrates a credible positive edge. No strategy is approved for production or promoted to shadow review by the statistical gate.** The work repaired the research foundation, investigated five distinct hypotheses on 16 instruments, built a repeatable competition, and preserved negative findings. The strongest positive final-test cell is worth an independent prospective check, not an allocation or notification stream.

The batch registered **80 hypothesis/instrument cases**, executed **66 supported cases**, documented **14 unsupported cases**, and simulated **11,188 unique standalone trade plans**. Three selection policies were also evaluated. The family-wise testing denominator is conservatively **83** (80 registrations + 3 policies). A correctness rerun is preserved separately; it repeats the same hypotheses and plans and does not create additional independent evidence. There are 2 completed research-run directories; the active run took 19.37 seconds on one foreground process.

## 2. Existing weaknesses and foundation repairs

The prior independent audit found entry timestamps conflated with confirming bar close, skipped entry minutes, uncertain ordering treated as known, missing coverage treated as no-hit, future timestamps accepted, inconsistent cost models, and archived strategies retaining alert rights. These corrections are implemented in a new isolated foundation; the operational platform still uses its existing production behavior.

| Problem | Isolated correction and verification |
|---|---|
| Entry-time semantics | Separate `signal_bar_closed_at` and actual `entry_at`. Historical bank corrections start at detection, not the earlier signal close. Backtests enter at the next H1 open; shadow collection uses the observed quote time. Pre-entry candles cannot decide the result. |
| Entry-minute stop | Exact minute-open entries include that minute. Intraminute touches remain ambiguous without ticks. Explicit regression reproduces the previously missed stop. |
| TP/SL order | One coarse candle touching both barriers needs contiguous M1 coverage; both in one minute stay ambiguous. Conflicting M1/M15 evidence also stays ambiguous. |
| Complete coverage | Missing entry bars, internal M15 gaps, missing intrabar minutes and truncated deadlines remain incomplete. No automatic no-hit from a partial path. Gaps are not assumed to be market closures. |
| Timestamps / candles | Reject invalid, duplicate, out-of-order, nonfinite, future and forming bars; validate OHLC and nonnegative explicit spreads. Reject future quotes/confirming bars and stale confirmation delays. Bars after a historical cutoff are excluded, not evidence of a bad feed clock. |
| Execution | Executable ask/bid entry, ask-side short exits, conservative tick rounding, adverse stop-gap fills, explicit commissions/slippage and financing limitations. Stress doubles entry/exit spreads and adverse costs; all comparisons keep frozen stop/target/planned-risk units. |
| Alert authorization | A pure current-registry delivery gate rejects ARCHIVED/FORWARD_TESTING even if an old spec or signal was alert-approved. Approval reference and current enabled state are required at delivery. This replacement is prepared but not wired into production. |
| Revision integrity | Append-only local corrections have revision IDs, previous-record links, code/data hashes and provenance. Identical reruns append nothing. The original outcome and notification stores are untouched. |

Validation: **37 new independent tests passed**, covering the original adversarial cases, short ask barriers, cost stress, gap fills, timestamp rejection, revisions, causal prefix invariance, authorization revocation and exposure caps. Separate accounting checks verified all **11,188 entry plans** and **18,905 completed normal/stress fill calculations** against stored fills and raw bid-open data. These tests establish implementation properties, not feed accuracy or profitability. The final test evidence is `validation.json`; the frozen run source includes the contemporaneous test file, which was subsequently corrected for a test-fixture scope error only. Research execution code and results did not change after the active run.

### Historical correction evidence

The local correction replay covers **432 frozen priced signals**: SL: 221, TP: 104, INCOMPLETE: 103, AMBIGUOUS: 4. These labels are research-only interpretations of recorded plans. Differences include corrected timing, coverage rules, finite holding horizons and costs; they are not proof that every different original result was a bug. Actual historical executable fills are unverified. All correction revisions, including the earlier resolver revision, remain in `corrections/revisions.jsonl`. The current resolver is `independent-execution-1.0.1`.

## 3. Research architecture

The package has no production imports, MT5 initialization, network data collection or message sender. It reads existing compressed bar caches and writes only inside `research_autonomous/`. Every run gets a unique folder, preregistered configuration before simulation, input hashes, frozen research source, experiment events, individual trade plans/outcomes, rejection counts, data-quality evidence and selection decisions.

The lifecycle is IDEA → RESEARCH → IMPLEMENTATION → BACKTEST → OUT_OF_SAMPLE_VALIDATION → SHADOW_FORWARD_TEST → QUALIFICATION_REVIEW → CEO_APPROVAL → PRODUCTION_SIGNALS. REJECTED, NEEDS_DATA and ARCHIVED remain documented. The pure transition validator prevents skipping forward evidence and CEO deployment approval; current results stop at research evaluation. No historical candidate is silently renamed or recycled.

`strategy_catalog.json` contains IDs, versions, entry/exit/SL/TP rules, risk model, intended regimes, limitations, historical/OOS results and explicitly unavailable forward performance. `experiments.jsonl` preserves failed and unsupported ideas. Existing TradeDen production/research components remain intact. This is an independent reference implementation and competition, not a production replacement.

## 4. New strategy families investigated

Rules were fixed for this batch; there was no grid search, optimizer, model fitting to final-test results, or parameter adjustment to create a winner. Slow lookbacks count observed closed H1 bars, not fabricated weekend candles; entries require 12 recent consecutive H1 intervals. All entries use only completed H1 information, with execution at the next bid/ask open.

| ID / version | Hypothesis | Entry | Stop / target / maximum hold | Limitation |
|---|---|---|---|---|

| drift48 / 1.0.0 | A coherent two-day directional move may persist beyond trading costs. | H1 at 00/06/12/18 UTC: 48-return log drift / sqrt(sum squared returns) >= 1.5 in magnitude; efficiency >= .25; enter next H1 open. | 2 prior H1 ATR(24) from executable entry. 1.5R fixed. 24h. | Intraday hypothesis inspired by momentum, not a replication of monthly futures literature. |

| robust_revert / 1.0.0 | Extreme deviation from the rolling median may revert when its first reversal starts. | Previous H1 close >2.5 scaled MAD(48) from prior median; current H1 moves toward median; same signed deviation; enter next open. | 1.5 prior H1 ATR(24). Frozen median of 48 closes before trigger; >=1R executable reward. 12h. | Median is not intrinsic value; persistent trends can defeat reversion. |

| compression_release / 1.0.0 | A first range escape after narrow trading may persist. | Prior 12 H1 high-low range <=2.5 prior ATR(24); first close beyond it by .1 ATR; enter next open. | 1.5 prior H1 ATR(24). 2R fixed. 12h. | Few compressions may meet fixed rule; no thresholds retuned to increase count. |

| shock_fade / 1.0.0 | A large directional shock followed by a reversal may reflect temporary dislocation. | Prior H1 range >2.5 prior ATR(24), body >=70% range; current close crosses shock midpoint in opposite direction; enter next open. | Beyond shock extreme by .2 prior ATR(24). Shock open; >=1.2R executable reward. 6h. | No news feed; shocks can be permanent information, not temporary liquidity. |

| relative_lag / 1.0.0 | BTC/ETH relative return shocks may mean-revert conditionally. | BTC/ETH only: rolling prior 48 H1 returns OLS beta; current residual >2.5 prior residual SD; fade residual next H1 open. | 1.5 prior H1 ATR(24). 1.5R fixed. 6h. | Unhedged single-leg residual signal; not market-neutral arbitrage. Both CFDs share crypto risk. |


The residual strategy is an **unhedged directional BTC/ETH signal**, not statistical arbitrage or market neutrality. It is unsupported for the other 14 markets. No centralized-volume, order-flow or order-book strategies were fabricated from MT5 tick volume. ML was deferred because data contracts and weak simpler candidates do not yet justify its added search space.

Research context: the [original momentum authors’ publication list](https://faculty.som.yale.edu/tobymoskowitz/research/) documents time-series momentum research, but this short-horizon CFD hypothesis is not a replication and inherits no profitability claim. The [backtest-overfitting paper](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf) motivates preserving trial counts and resisting repeated parameter searches; this implementation uses chronological folds and explicit family-wise correction, not that paper’s full CSCV/PBO estimator.

## 5. Data, chronology and realistic-execution boundaries

Input: 48 hashed H1/M15/M1 files across XAUUSD, XAGUSD, BTCUSD, ETHUSD, nine FX/JPY pairs, NAS100, US500 and GER40. The broker-cache timezone basis is recorded as `America/New_York+07:00`; its original provenance is retained, not independently re-certified with ticks. H1/M15 histories extend back before the 15 Oct 2024 research start. M1 exists mainly from July/August 2026. It is used only to resolve coarse-bar ambiguity/partial entries where available. A one-bar single-barrier result can be established with M15; within-bar ordering for ties cannot.

Training: **15 Oct 2024–1 Oct 2025**. Validation: **1 Oct 2025–1 Apr 2026**. Final historical test: **1 Apr–1 Oct 2026**. Expanding selection refits at 1 Oct 2025, 1 Jan 2026, 1 Apr 2026 and 1 Jul 2026, using completed trades whose deadlines precede the fold by 48 hours. Entries whose deadlines approach the next fold within 48 hours are excluded. Maximum candidate hold is 24 hours. Parameters remain fixed; only selection maps can change from past evidence.

The historical cache has already been exposed to other research in this repository. Therefore “out of sample” here means **chronologically separated from this batch’s fitting**, not a previously untouched firm-wide dataset. The report explicitly requires prospective evidence before any promotion.

Execution costs are assumptions: round-trip FX commission .00007 price units (.007 JPY), gold .07, silver .0014, others zero; .25 exit-bar spread adverse entry/TP/time-exit slippage and .5 spread on stops. Normal fills use correct bid/ask sides and fixed plans, with no favorable target-gap improvement. Financing uses the broker’s **current** snapshot as a proxy for historical charges, supporting point-based and annual-percent modes; unavailable money-currency conversion fails closed for positions crossing rollover. These assumptions may differ from the actual account. Swap credits are removed in stress; positive financing, spreads, slippage and commissions are doubled.

Incomplete paths are excluded from resolved-only return statistics and separately counted. A -1.5R-per-unknown sensitivity scenario is stored, but **it is not a lower bound**: gaps can lose more. Missingness may depend on market, horizon and outcome. Realized drawdown ignores unknown and floating losses and is not account drawdown. “Weekly P&L mean/SD” is a descriptive ratio on equal-risk cash outcomes, not a certified annualized Sharpe ratio. Risk-percent leverage, tick latency, borrow limits, news, historical spread extrema and historical financing remain unverified.

## 6. Competition results and rejected ideas

Provisional coverage/sample classification: {'NEEDS_DATA': 57, 'UNSUPPORTED': 14, 'REJECTED': 8, 'REVIEW_ONLY': 1}. These labels precede the final statistical gate; **all 66 supported cases are NOT_QUALIFIED**. NEEDS_DATA is not a recommendation to collect more data for every weak idea. Negative, redundant and infeasible cases should be deprioritized rather than automatically expanded.

Family totals below aggregate standalone streams and therefore include overlapping opportunities; they are **not a portfolio**. Use the exposure-constrained policy comparison for portfolio-like overlays.

| Experiment | Attempts | Resolved | Unknown | Net R | E[R] | PF | Realized DD R | Stress E[R] | Weekly 95% CI | Holm p |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|

| drift48 | 423 | 303 | 120 | -30.178 | -0.100 | 0.831 | 44.832 | -0.190 | [-0.27, 0.066] | N/A |

| robust_revert | 1125 | 922 | 203 | -180.117 | -0.195 | 0.668 | 185.810 | -0.320 | [-0.3, -0.093] | N/A |

| compression_release | 895 | 803 | 92 | -103.892 | -0.129 | 0.795 | 140.261 | -0.203 | [-0.262, 0.008] | N/A |

| shock_fade | 0 | 0 | 0 | 0.000 | N/A | N/A | 0.000 | N/A | N/A | N/A |

| relative_lag | 207 | 204 | 3 | -17.789 | -0.087 | 0.811 | 24.181 | -0.150 | [-0.215, 0.065] | N/A |


**Rejected/deprioritized:** no broad family supports production expansion. Shock fade produced no executable trades: the midpoint reversal plus far-side structural stop and return-to-origin target generally leaves insufficient reward relative to risk. Preserve that failure rather than changing the target or threshold after viewing results. Residual reversal is not promoted as crypto arbitrage. High missingness makes many metal/index drift results non-credible despite occasionally positive resolved-only returns. A lifecycle state of NEEDS_DATA does not override negative validation or cost stress.

### Highest descriptive final-test cells

These are post-test rankings for diagnosis, not selection rules or market recommendations. The Holm denominator includes every registered market hypothesis and the three selection policies.

| Experiment | Attempts | Resolved | Unknown | Net R | E[R] | PF | Realized DD R | Stress E[R] | Weekly 95% CI | Holm p |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|

| compression_release@1.0.0:EURJPY | 65 | 62 | 3 | 7.497 | 0.121 | 1.227 | 6.477 | 0.063 | [-0.197, 0.418] | 1.000 |

| drift48@1.0.0:XAUUSD | 26 | 6 | 20 | 3.985 | 0.664 | 2.988 | 1.003 | 0.661 | [-0.17, 1.498] | 1.000 |

| drift48@1.0.0:BTCUSD | 40 | 37 | 3 | 3.639 | 0.098 | 1.197 | 5.998 | -0.070 | [-0.387, 0.529] | 1.000 |

| robust_revert@1.0.0:GBPJPY | 76 | 69 | 7 | 3.441 | 0.050 | 1.098 | 6.327 | -0.199 | [-0.205, 0.351] | 1.000 |

| drift48@1.0.0:NAS100 | 27 | 12 | 15 | 2.959 | 0.247 | 1.491 | 2.517 | 0.239 | [-0.504, 0.92] | 1.000 |

| drift48@1.0.0:GER40 | 22 | 3 | 19 | 1.992 | 0.664 | 2.987 | 1.002 | 0.661 | [-1.002, 1.497] | 1.000 |

| drift48@1.0.0:EURUSD | 23 | 21 | 2 | 1.805 | 0.086 | 1.170 | 4.263 | 0.026 | [-0.429, 0.469] | 1.000 |

| drift48@1.0.0:GBPJPY | 30 | 25 | 5 | 0.610 | 0.024 | 1.049 | 4.386 | -0.037 | [-0.453, 0.328] | 1.000 |

| drift48@1.0.0:XAGUSD | 18 | 2 | 16 | 0.467 | 0.234 | 1.457 | 1.021 | 0.204 | [-1.021, 1.488] | 1.000 |

| shock_fade@1.0.0:XAUUSD | 0 | 0 | 0 | 0.000 | N/A | N/A | 0.000 | N/A | N/A | 1.000 |


**Most interesting but unqualified:** EURJPY compression release has 62 resolved final-test trades from 65 attempts, +7.50R, expectancy +0.121R, PF 1.227; doubled-cost expectancy +0.063R. Its weekly bootstrap 95% expectancy interval is **[-0.197, +0.418]R**, unadjusted sign-flip p≈0.232, Holm p=1.0. Training expectancy is -0.005R and validation is -0.222R. That instability and uncertainty rule out qualification. A new chronological forward interval could investigate it without re-optimizing parameters; it is not a selected winner.

## 7. Market-specific evidence

The table shows the highest resolved-only final-test net R among the registered hypotheses per market. This is a **diagnostic maximum after multiple comparisons**, not a tradable best-strategy assignment. Zero-trade hypotheses cannot win the ranking. All market choices remain unqualified.

| Experiment | Attempts | Resolved | Unknown | Net R | E[R] | PF | Realized DD R | Stress E[R] | Weekly 95% CI | Holm p |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|

| AUDUSD / robust_revert | 87 | 81 | 6 | -5.721 | -0.071 | 0.863 | 10.966 | -0.158 | [-0.333, 0.232] | 1.000 |

| BTCUSD / drift48 | 40 | 37 | 3 | 3.639 | 0.098 | 1.197 | 5.998 | -0.070 | [-0.387, 0.529] | 1.000 |

| ETHUSD / drift48 | 25 | 18 | 7 | -2.990 | -0.166 | 0.731 | 4.502 | -0.311 | [-0.918, 0.437] | 1.000 |

| EURJPY / compression_release | 65 | 62 | 3 | 7.497 | 0.121 | 1.227 | 6.477 | 0.063 | [-0.197, 0.418] | 1.000 |

| EURUSD / drift48 | 23 | 21 | 2 | 1.805 | 0.086 | 1.170 | 4.263 | 0.026 | [-0.429, 0.469] | 1.000 |

| GBPJPY / robust_revert | 76 | 69 | 7 | 3.441 | 0.050 | 1.098 | 6.327 | -0.199 | [-0.205, 0.351] | 1.000 |

| GBPUSD / drift48 | 24 | 22 | 2 | -2.528 | -0.115 | 0.798 | 6.624 | -0.171 | [-0.574, 0.247] | 1.000 |

| GER40 / drift48 | 22 | 3 | 19 | 1.992 | 0.664 | 2.987 | 1.002 | 0.661 | [-1.002, 1.497] | 1.000 |

| NAS100 / drift48 | 27 | 12 | 15 | 2.959 | 0.247 | 1.491 | 2.517 | 0.239 | [-0.504, 0.92] | 1.000 |

| NZDUSD / compression_release | 44 | 42 | 2 | -0.125 | -0.003 | 0.995 | 6.322 | -0.074 | [-0.37, 0.387] | 1.000 |

| US500 / drift48 | 25 | 11 | 14 | -1.129 | -0.103 | 0.841 | 4.590 | -0.129 | [-0.763, 0.567] | 1.000 |

| USDCAD / compression_release | 82 | 78 | 4 | -2.741 | -0.035 | 0.943 | 14.533 | -0.106 | [-0.338, 0.267] | 1.000 |

| USDCHF / drift48 | 21 | 19 | 2 | -5.243 | -0.276 | 0.559 | 7.515 | -0.538 | [-0.738, 0.203] | 1.000 |

| USDJPY / compression_release | 55 | 54 | 1 | -1.473 | -0.027 | 0.953 | 8.631 | -0.077 | [-0.293, 0.241] | 1.000 |

| XAGUSD / drift48 | 18 | 2 | 16 | 0.467 | 0.234 | 1.457 | 1.021 | 0.204 | [-1.021, 1.488] | 1.000 |

| XAUUSD / drift48 | 26 | 6 | 20 | 3.985 | 0.664 | 2.988 | 1.003 | 0.661 | [-0.17, 1.498] | 1.000 |


Data gaps, sample sizes and execution costs vary strongly by instrument. The strict no-calendar path policy censors scheduled closures as well as outages. Do not interpret an instrument with many unknown outcomes as safer or more profitable. `data_quality.json` lists all counts; complete broker session and holiday schedules are a priority for gold and equity-index CFDs.

## 8. Regime selection, overlapping opportunities and uncertainty

Three causal regimes use past H1 efficiency and short/long volatility ratio: TREND, RANGE and VOLATILE. Their economic value is tested rather than assumed. `static_diverse` consumes all fixed candidate streams; `train_market` selects a strategy per market; `train_regime` selects per market/regime. Selection needs at least 30 known past trades, >=95% known outcomes, positive stressed training expectancy and positive approximate one-sided 90% weekly-cluster training score. This is a research selector, not a production qualification model.

Each policy applies one symbol and one broad FX/crypto/metals/equity-index risk group at a time, with at most three concurrent one-R units. Standalone strategy/instrument simulations also forbid overlapping positions. For a fair matched opportunity stream, normal/stress runs share conservative holding locks; unknown paths lock to deadline. Lexical tie breaking is deterministic. Policy overlays use standalone opportunities and do not regenerate all foregone signals after a rejected portfolio entry, so they are not a complete path-dependent trading-engine simulation.

| Experiment | Attempts | Resolved | Unknown | Net R | E[R] | PF | Realized DD R | Stress E[R] | Weekly 95% CI | Holm p |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|

| static_diverse / validation | 851 | 691 | 160 | -64.604 | -0.093 | 0.841 | 94.998 | -0.136 | [-0.187, 0.001] | N/A |

| static_diverse / test | 796 | 659 | 137 | -112.310 | -0.170 | 0.720 | 116.374 | -0.251 | [-0.24, -0.101] | 1.000 |

| train_market / validation | 0 | 0 | 0 | 0.000 | N/A | N/A | 0.000 | N/A | N/A | N/A |

| train_market / test | 0 | 0 | 0 | 0.000 | N/A | N/A | 0.000 | N/A | N/A | 1.000 |

| train_regime / validation | 0 | 0 | 0 | 0.000 | N/A | N/A | 0.000 | N/A | N/A | N/A |

| train_regime / test | 0 | 0 | 0 | 0.000 | N/A | N/A | 0.000 | N/A | N/A | 1.000 |


Both trained selectors **abstain in every fold**: no training cell met the fixed admission score. Their zero P&L is absence of exposure, not a discovered edge or evidence that regime selection improves active returns. The static diverse overlay loses -112.31R on 659 resolved test positions, with 137 unknown outcomes; stress loses -165.34R. Merely combining weak strategies does not make a robust portfolio.

Uncertainty uses 2,500 entry-week block bootstrap draws, preserving same-week cross-market dependence; 5,000 weekly sign flips provide one-sided exploratory p-values under symmetric weekly outcomes. Holm step-down correction covers 83 registered hypotheses/policies, including unsupported/inactive cases conservatively. It does **not** correct the unknown number of prior firm-wide research trials, invalid sign-symmetry assumptions or regime changes. Cross-week dependence and censoring remain limitations. Family weekly-correlation diagnostics are saved; zero-variance families are reported as undefined, not assigned zero correlation.

## 9. Forward-testing requirements

No actual prospective performance was collected. `forward.py` is a bounded, file-driven SHADOW_ONLY collector with no sender or trading capability. It checks observed quote time, actual entry time, completed H1 history and future/stale data, and rejects historical snapshots presented as current. A separately approved read-only feed capture would be needed for ongoing operation; this task has not connected a new loop to the running scanner.

For an unchanged candidate, pre-register the future start date, code/data/cost versions, instrument, opportunity unit, stopping rules and sample target. Capture actual bid/ask quotes, signal-bar close, detection and delivery timestamps, tick size, spread, session calendar and every rejection. Resolve through the corrected coverage contract and retain ambiguous paths. Require adequate independent opportunities and regime coverage, positive cost-stressed uncertainty bounds after the full experiment inventory, and acceptable realized/floating drawdown before qualification review. Then obtain explicit CEO approval and an approved deployment. Do not relax thresholds to force a winner.

## 10. Proposed production improvements — prepared, not deployed

1. Integrate the independently tested entry-time, coverage, tie and current-status authorization contracts behind an approved isolated change; review compatibility with existing stores and API consumers.
2. Re-resolve prior outcomes as appended revisions with input/code/version provenance. Present original and revised cohorts without erasing history; keep simulated signals distinct from actual execution.
3. Centralize delivery-time authorization across existing bank and production Telegram paths. Static experimental labels must not bypass later archive/demotion.
4. Add validated bid/ask and complete-path contracts, known/unknown outcome denominators, broker-session calendars and an explicit costs evidence source.
5. Version every strategy and selection model; keep the original four families and legacy records only where evidence and reproducibility require them. Do not auto-activate research predictions.

The isolated code is a reference implementation, not a drop-in deployment patch: schema migration, production regression, API/UI compatibility, notification-state migration and rollback need review on a separate branch before CEO approval. No production route, configuration or historical data was edited.

## 11. Resources and repeatable operations

Active batch runtime: **19.37s**; one foreground process; 16 markets sequentially; default **240s wall-clock budget**, configurable maximum 600s; default cap 2,000 attempts per supported strategy/market. No cap was reached. There is no polling daemon, cron job or scheduled automation. Windows priority is lowered for research. Active run artifacts occupy about **14.3 MiB** before this report. Peak process memory was not measured and no hard memory cap is claimed; full M1/M15 histories are handled one instrument at a time, while H1 context is retained across markets for cross-market research.

The runner is repeatable and logs failed/partial runs. Any source/cache change during a run invalidates its identity checks. Threshold choices are preregistered; future revisions must get new versions and retain all old attempts. Avoid unbounded searches and use a fresh future period for any changes inspired by these results.

Reproduce from repository root:

```text
python -m research_autonomous.validate
python -m research_autonomous.experiment --max-seconds 240
python -m research_autonomous.verify_run
python -m research_autonomous.replay_corrections
python -m research_autonomous.report
```

Each experiment run writes a new immutable directory; no result directory is overwritten. The correction ledger appends and deduplicates revisions. Report generation writes the human-readable latest report/catalog, retaining underlying run evidence. Tests use temporary files only inside the research directory.

## 12. Prioritized next development plan

| Priority | Work | Success criterion |
|---|---|---|
| 1 — correctness | Review isolated resolver/authorization fixes, add production-adapter tests, and prepare an auditable migration diff. | Exact old defect cases fixed; no skipped entry minutes, false no-hit, future timestamps or archived alerts; CEO approval before live integration. |
| 2 — data | Obtain complete broker session/holiday calendar and timestamped bid/ask/cost history; verify normalization and cross-timeframe aggregation. | Previously incomplete paths become verifiable without guessing closures; quantify coverage by market and holding horizon. |
| 3 — independent replication | Pre-register unchanged EURJPY compression release for an untouched period; deprioritize shock fade and weak broad families. | Enough independent opportunities, positive cost-stressed uncertainty after all trials, stability beyond one favorable half-year. |
| 4 — selection | Retest static versus causal market/regime selection only after base candidates have evidence. | Active out-of-sample improvement with matched risk/exposure, not a zero-trade selector beating losing exposure. |
| 5 — diversification | With appropriate data, investigate genuinely different session/relative-value mechanisms; require a true hedge for arbitrage claims. | Economic rationale, known fills/financing and independent opportunity diversity. No order-book/central-volume claims from tick counts. |
| 6 — operations | Add an approved read-only snapshot feed and monitored shadow evidence collection; keep experiment budgets. | Reproducible prospective records, no Telegram or execution rights, bounded laptop load. |

The immediate recommendation is **repair measurement before expanding notifications**. No credible positive-edge winner was found, and the standards were not lowered to manufacture one.

## Evidence index

- `preregistered.json`: fixed rules, execution/cost assumptions, bounds and fold definitions.
- `source/`: frozen source for the active batch.
- `data_manifest.json` and `data_quality.json`: hashed data, provenance and exclusions/gaps.
- `experiments.jsonl`: complete lifecycle/rejection record.
- `trades.jsonl` and `policy_trades.jsonl`: individual planned opportunities and outcomes.
- `results.json`: all train/validation/test metrics, selectors, multiple testing and correlation diagnostics.
- `independent_verification.json`: separate accounting checks.
- `strategy_catalog.json`: strategy rules, results, known limits and explicitly absent forward evidence.
- `corrections/revisions.jsonl`: append-only research corrections, outside backend stores.
- `validation.json`: final independent regression evidence.

All local links and file names refer to the isolated workspace; historical outcomes and strategies are simulated research evidence, never guaranteed future returns.

## Appendix: complete supported experiment inventory

REJECTED means adequate final-test sample/coverage but nonpositive resolved-only expectancy under the provisional classifier. NEEDS_DATA means insufficient sample or coverage, even if observed returns are already poor. REVIEW_ONLY means a positive point estimate with enough sample/coverage before uncertainty and prior-period checks; it still fails final qualification. These labels do not authorize forward collection or production alerts.

| ID / market | Classification | Train E[R] | Validation E[R] | Test N | Test unknown | Test E[R] | Stress E[R] | Holm p |
|---|---|---:|---:|---:|---:|---:|---:|---:|

| compression_release / AUDUSD | NEEDS_DATA | -0.099 | -0.021 | 55 | 3 | -0.165 | -0.240 | 1.000 |

| compression_release / BTCUSD | REJECTED | -0.020 | 0.275 | 91 | 3 | -0.148 | -0.204 | 1.000 |

| compression_release / ETHUSD | NEEDS_DATA | 0.010 | -0.097 | 23 | 2 | -0.263 | -0.478 | 1.000 |

| compression_release / EURJPY | REVIEW_ONLY | -0.005 | -0.222 | 62 | 3 | 0.121 | 0.063 | 1.000 |

| compression_release / EURUSD | REJECTED | 0.156 | -0.244 | 86 | 2 | -0.234 | -0.291 | 1.000 |

| compression_release / GBPJPY | REJECTED | -0.055 | -0.318 | 66 | 1 | -0.062 | -0.151 | 1.000 |

| compression_release / GBPUSD | REJECTED | 0.098 | -0.057 | 81 | 2 | -0.098 | -0.178 | 1.000 |

| compression_release / GER40 | NEEDS_DATA | -0.645 | -1.005 | 6 | 3 | -0.003 | -0.008 | 1.000 |

| compression_release / NAS100 | NEEDS_DATA | -0.142 | 0.267 | 33 | 11 | -0.186 | -0.195 | 1.000 |

| compression_release / NZDUSD | NEEDS_DATA | -0.155 | 0.014 | 42 | 2 | -0.003 | -0.074 | 1.000 |

| compression_release / US500 | NEEDS_DATA | -0.186 | -0.106 | 46 | 25 | -0.164 | -0.186 | 1.000 |

| compression_release / USDCAD | REJECTED | -0.088 | -0.280 | 78 | 4 | -0.035 | -0.106 | 1.000 |

| compression_release / USDCHF | NEEDS_DATA | 0.084 | 0.071 | 57 | 3 | -0.270 | -0.462 | 1.000 |

| compression_release / USDJPY | NEEDS_DATA | 0.157 | -0.243 | 54 | 1 | -0.027 | -0.077 | 1.000 |

| compression_release / XAGUSD | NEEDS_DATA | -0.196 | -1.022 | 13 | 16 | -0.790 | -0.821 | 1.000 |

| compression_release / XAUUSD | NEEDS_DATA | -0.010 | 0.056 | 10 | 11 | -0.704 | -0.708 | 1.000 |

| drift48 / AUDUSD | NEEDS_DATA | -0.136 | 0.371 | 24 | 3 | -0.351 | -0.410 | 1.000 |

| drift48 / BTCUSD | NEEDS_DATA | 0.069 | 0.007 | 37 | 3 | 0.098 | -0.070 | 1.000 |

| drift48 / ETHUSD | NEEDS_DATA | 0.127 | -0.037 | 18 | 7 | -0.166 | -0.311 | 1.000 |

| drift48 / EURJPY | NEEDS_DATA | -0.562 | 0.059 | 20 | 3 | -0.104 | -0.150 | 1.000 |

| drift48 / EURUSD | NEEDS_DATA | -0.089 | -0.056 | 21 | 2 | 0.086 | 0.026 | 1.000 |

| drift48 / GBPJPY | NEEDS_DATA | -0.343 | -0.087 | 25 | 5 | 0.024 | -0.037 | 1.000 |

| drift48 / GBPUSD | NEEDS_DATA | 0.067 | -0.109 | 22 | 2 | -0.115 | -0.171 | 1.000 |

| drift48 / GER40 | NEEDS_DATA | 0.067 | -0.170 | 3 | 19 | 0.664 | 0.661 | 1.000 |

| drift48 / NAS100 | NEEDS_DATA | -0.265 | -0.417 | 12 | 15 | 0.247 | 0.239 | 1.000 |

| drift48 / NZDUSD | NEEDS_DATA | 0.050 | 0.390 | 31 | 4 | -0.294 | -0.414 | 1.000 |

| drift48 / US500 | NEEDS_DATA | -0.482 | 0.550 | 11 | 14 | -0.103 | -0.129 | 1.000 |

| drift48 / USDCAD | NEEDS_DATA | 0.004 | 0.233 | 33 | 3 | -0.218 | -0.276 | 1.000 |

| drift48 / USDCHF | NEEDS_DATA | -0.205 | 0.171 | 19 | 2 | -0.276 | -0.538 | 1.000 |

| drift48 / USDJPY | NEEDS_DATA | -0.089 | 0.052 | 19 | 2 | -0.363 | -0.421 | 1.000 |

| drift48 / XAGUSD | NEEDS_DATA | -0.437 | 0.490 | 2 | 16 | 0.234 | 0.204 | 1.000 |

| drift48 / XAUUSD | NEEDS_DATA | -0.173 | -0.320 | 6 | 20 | 0.664 | 0.661 | 1.000 |

| relative_lag / BTCUSD | REJECTED | -0.003 | 0.029 | 158 | 2 | -0.062 | -0.100 | 1.000 |

| relative_lag / ETHUSD | NEEDS_DATA | -0.097 | -0.208 | 46 | 1 | -0.175 | -0.324 | 1.000 |

| robust_revert / AUDUSD | NEEDS_DATA | -0.030 | -0.186 | 81 | 6 | -0.071 | -0.158 | 1.000 |

| robust_revert / BTCUSD | REJECTED | -0.064 | -0.167 | 123 | 6 | -0.039 | -0.072 | 1.000 |

| robust_revert / ETHUSD | NEEDS_DATA | -0.180 | -0.298 | 44 | 5 | -0.164 | -0.376 | 1.000 |

| robust_revert / EURJPY | NEEDS_DATA | -0.087 | -0.167 | 70 | 9 | -0.110 | -0.288 | 1.000 |

| robust_revert / EURUSD | NEEDS_DATA | -0.121 | -0.150 | 64 | 5 | -0.185 | -0.266 | 1.000 |

| robust_revert / GBPJPY | NEEDS_DATA | 0.061 | -0.183 | 69 | 7 | 0.050 | -0.199 | 1.000 |

| robust_revert / GBPUSD | NEEDS_DATA | -0.160 | -0.132 | 67 | 5 | -0.171 | -0.239 | 1.000 |

| robust_revert / GER40 | NEEDS_DATA | -0.740 | -0.730 | 21 | 25 | -0.681 | -0.707 | 1.000 |

| robust_revert / NAS100 | NEEDS_DATA | -0.528 | -0.444 | 18 | 30 | -0.609 | -0.616 | 1.000 |

| robust_revert / NZDUSD | REJECTED | -0.006 | 0.038 | 69 | 3 | -0.161 | -0.238 | 1.000 |

| robust_revert / US500 | NEEDS_DATA | -0.250 | -0.393 | 21 | 22 | -0.649 | -0.675 | 1.000 |

| robust_revert / USDCAD | NEEDS_DATA | -0.191 | -0.126 | 77 | 11 | -0.209 | -0.320 | 1.000 |

| robust_revert / USDCHF | NEEDS_DATA | -0.236 | -0.227 | 75 | 6 | -0.357 | -0.661 | 1.000 |

| robust_revert / USDJPY | NEEDS_DATA | -0.007 | -0.197 | 76 | 7 | -0.037 | -0.239 | 1.000 |

| robust_revert / XAGUSD | NEEDS_DATA | -0.479 | -0.651 | 21 | 28 | -0.749 | -0.780 | 1.000 |

| robust_revert / XAUUSD | NEEDS_DATA | -0.550 | -0.658 | 26 | 28 | -0.902 | -0.907 | 1.000 |

| shock_fade / AUDUSD | NEEDS_DATA | N/A | N/A | 0 | 0 | N/A | N/A | 1.000 |

| shock_fade / BTCUSD | NEEDS_DATA | -0.148 | N/A | 0 | 0 | N/A | N/A | 1.000 |

| shock_fade / ETHUSD | NEEDS_DATA | N/A | N/A | 0 | 0 | N/A | N/A | 1.000 |

| shock_fade / EURJPY | NEEDS_DATA | N/A | N/A | 0 | 0 | N/A | N/A | 1.000 |

| shock_fade / EURUSD | NEEDS_DATA | N/A | N/A | 0 | 0 | N/A | N/A | 1.000 |

| shock_fade / GBPJPY | NEEDS_DATA | N/A | N/A | 0 | 0 | N/A | N/A | 1.000 |

| shock_fade / GBPUSD | NEEDS_DATA | N/A | N/A | 0 | 0 | N/A | N/A | 1.000 |

| shock_fade / GER40 | NEEDS_DATA | N/A | N/A | 0 | 0 | N/A | N/A | 1.000 |

| shock_fade / NAS100 | NEEDS_DATA | N/A | N/A | 0 | 0 | N/A | N/A | 1.000 |

| shock_fade / NZDUSD | NEEDS_DATA | N/A | N/A | 0 | 0 | N/A | N/A | 1.000 |

| shock_fade / US500 | NEEDS_DATA | N/A | N/A | 0 | 0 | N/A | N/A | 1.000 |

| shock_fade / USDCAD | NEEDS_DATA | N/A | N/A | 0 | 0 | N/A | N/A | 1.000 |

| shock_fade / USDCHF | NEEDS_DATA | N/A | N/A | 0 | 0 | N/A | N/A | 1.000 |

| shock_fade / USDJPY | NEEDS_DATA | N/A | N/A | 0 | 0 | N/A | N/A | 1.000 |

| shock_fade / XAGUSD | NEEDS_DATA | N/A | N/A | 0 | 0 | N/A | N/A | 1.000 |

| shock_fade / XAUUSD | NEEDS_DATA | N/A | N/A | 0 | 0 | N/A | N/A | 1.000 |
