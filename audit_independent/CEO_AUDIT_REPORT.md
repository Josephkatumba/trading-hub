# Independent TradeDen CEO audit — 19 October 2026

Status: initial offline audit and experimental qualification evaluation complete. **No production change or deployment approved or performed.** All market/signal times below are UTC; Nairobi is UTC+3. Synthetic probes are explicitly separated from observed signals.

## 1. Executive summary

The current strategy families have negative performance in the independently verifiable subset. Outcome defects and incomplete evidence mean the exact dashboard loss cannot be accepted as a clean strategy estimate. The largest observed weakness is trendline v5; a simple higher-timeframe filter does not rescue it. There is no convincing evidence that the experimental qualification policy is profitable. Do not promote it. Prioritize trustworthy outcomes, versioned cohorts, and prospective shadow validation before expanding the signal catalogue.

The captured stores contain 413 distinct production confirmations, 413 authoritative outcome rows after revision deduplication, and 49 bank signals. Of 152 priced signals in current families, 95 have conservative, contiguous M1 first-barrier results: -33.62R after assumed execution reserves, expectancy -0.354R. The other signals are explicitly unresolved for this audit, not counted as zero-return trades. The experiment retains 32 current-family signals, resolves 18, and returns -3.17R. These are conditional complete-path results, not a portfolio or all-signal expectancy.

## 2. Scope, provenance and report reconciliation

The directive’s 1,426 setups / 67 confirmations / 2 TP / 24 SL / 2 time exits / 39 active has no supplied report timestamp, population definition or frozen input. Its counts reconcile arithmetically (28 resolved + 39 active), but it cannot be reproduced as a unique cohort from the instruction alone. 2/(2+24)=7.69%; that arithmetic is correct. The reported -19.84R requires per-trade targets and time exits, not win rate alone. The separate 159-resolved figure likewise lacks a report boundary. This audit does not substitute whole-history numbers for those exact claims.

Small input stores were copied into `inputs/` and hashed; the 1.42GB observations log was streamed read-only to retrieve 383 confirmation snapshots. The scan is observational: no engine process, MT5 session, account, reporting scheduler, Telegram client or live configuration was changed. Existing dirty production and research files were preserved. Isolation is the standalone `audit_independent/` directory, with no imports from production back into it; no checkout switch was made in the running engine’s workspace.

The cached M1 history ends around **19 Oct 06:22–06:23 UTC**, before the 49 bank signals and many recent production signals. The analysis clock is the latest captured signal rounded to 15 minutes, **2026-10-19T20:15:00+00:00**, not a guarantee of candle coverage. Missing caches were not downloaded through the running terminal. A 7-day common observation window is used for independent barrier comparisons. Bank-specific time exits are not reproduced by that common-window experiment; all bank results are unverified here anyway. No real-money execution is inferred from a paper signal.

## 3. Critical technical problems

All seven adversarial cases are reproducible with `python audit_independent/probe_outcomes.py`; exact responses are in `probe_results.json`. These establish implementation defects, **not their historical incidence**.

| Priority | Evidence and consequence | Required correction |
|---|---|---|
| P1 | `signal_outcomes.resolve`: at exact 00:00 confirmation, M1 00:00 hits SL, M15 00:15 hits TP; resolver returns +2R TP because `minute_after` always skips the entry minute. Bank confirmation timestamps are exact bar closes, making this especially relevant. | Include the minute when entry is exactly its open; use ticks or classify intraminute entry touches unknown. |
| P1 | A later M15 candle touches both barriers; only minute 00:29 is supplied and touches TP. Resolver declares TP despite missing 00:15–00:28. | Prove contiguous intrabar coverage before deciding first-hit order. |
| P1 | A day-long missing path followed by a TP returns TP. `max_gap_hours` is recorded only on no-hit paths and never prevents certainty. | Validate path coverage against instrument trading sessions before any terminal outcome. |
| P1 | Only two M15 bars are supplied for a seven-day-old signal; resolver returns NO_HIT. | Require end coverage; return incomplete-history status and retry. |
| P1 | Bank records entry from the detection quote but `confirmed_at` from the earlier bar close; resolver starts at `confirmed_at`. USDJPY EMA crossover: bar close 10:00, detection 10:31:20.743 on 19 Oct. | Persist `signal_bar_closed_at` and executable `entry_at` separately; resolve and time alert freshness from actual entry/delivery semantics. |
| P2 | Bank accepts quote age -3600 seconds and a confirming bar one hour in the future. Production `qualification._fresh` already rejects excessive future quote skew. | Shared finite bounded freshness validator for both paths; require 0 <= now-bar_close within tolerance. |
| P2 | Direct resolver accepts a future minute within confirmation candle (00:01 TP when `now` is 00:00:30). Caller normally restricts bar opens, but resolver itself is unsafe and currently forming bar extremes still span a partial interval. | Enforce as-of bounds inside resolver and validate candle completeness at both boundaries. |

Additional code-confirmed risks: `_touch` defaults missing spread to zero for shorts; recorded bar spread is only an approximation to the contemporaneous ask high/low. Real bid/ask ticks are required for precise execution. Barrier R is fixed target-risk or -1R in the production resolver, so it omits stop gaps, commission, slippage and financing. Research simulation has some of these costs, but live outcome statistics do not share that implementation. Bank `time_exit_at` is based on bar close rather than detection; time-exit resolution can use the last available close without proving freshness at exit.

**Qualification governance defect:** `rules.alerting()` immediately allows every EXPERIMENTAL spec, regardless of an ARCHIVED/demoted lifecycle status. `BankAlerts.deliver()` trusts the stored primary-alert flag and does not recheck current qualification. Therefore the registry’s demotion does not reliably revoke experimental alert rights. `qualification.transition()` also exposes an ungated low-level write method; restrict its callers and enforce policy centrally. No demotion or alert change was made in this audit.

## 4. Architecture and entry-quality findings

| Stage | Independent assessment |
|---|---|
| Data ingestion / MT5 | Explicit timeframe requirements and missing-data reporting are good. `fetch_timeframes` includes the forming bar; correctness depends on each strategy removing it. It reports counts rather than validating sorted unique timestamps, OHLC consistency and internal gaps. Short histories may be accepted without marking a timeframe unavailable. Add one canonical validated bar contract. |
| Closed bars / higher timeframe | v5 explicitly removes forming M15/H1 bars; S/R removes forming bars per timeframe; T/M specifies closed H4/H1/M15. Preserve this. Retired v3/v4 use forming inputs and must stay separate. Bank Ctx `last_closed` is causal. |
| Detection / confirmation | Deterministic strategy rules are inspectable, but indicator confluence is not calibrated profitability. Production executable-price gates are materially better than historical bar-close plans. Bank contradiction notes are descriptive, not vetoes. |
| SL / TP | Current production `trade_planning.apply_plan` quantizes levels conservatively and caps T/M targets at intervening H1 swings; this corrects limitations mentioned in an older local audit. Bank levels remain floating point with no tick-size quantization. Timeframe-normalized stops differ by strategy; a universal M15 stop cap can reject legitimate H1 trades. |
| Qualification | Production checks executable R:R and stale quotes; optional commission cost defaults to zero. Bank tolerates spread up to 25% of risk. Neither proves a positive edge. Different qualification paths should share mechanical checks but keep strategy-specific edge tests. |
| Lifecycle / outcomes | Immutable confirmation plans and append-only outcome revisions are strong. Episode expiration is not equivalent to exit of an executed trade. Preserve research-horizon labels separately from authoritative signal outcomes, with explicit denominators and revisions. Final UNAVAILABLE/AMBIGUOUS rows are skipped by normal resolver runs, so new history does not automatically repair them. |
| Ranking | Bank summaries omit ambiguous/unavailable/no-hit rows from expectancy and use realized exits for drawdown. Qualification thresholds (60 resolved, mean >= .05R, PF >= 1.10) lack uncertainty, trial-count correction, overlap controls and regime coverage. |
| Telegram | Separate stores, deduplication, feature switches and explicit experimental disclaimers are good. H1 signals scanned 15–59 minutes after the hour can pass bank freshness yet fail Telegram’s 10-minute age limit because it uses bar close. Alert merging is not portfolio exposure control; cross-symbol USD/risk-on exposures remain unrestricted. |

### Observed failure examples

Prices below are the stored confirmation plans, not new order recommendations. ATR is an independently computed 14-bar mean true range on completed M15 bars, not claimed to equal each strategy’s internal Wilder/H1 ATR. H1 EMA alignment is independently computed EMA50/EMA200; it can disagree with the original snapshot’s different bias definition.

| Strategy / instrument / time UTC | Entry / SL / TP | Market context and independent result |
|---|---|---|

| trendline_v5 / EURJPY / 2026-09-25T18:45:06.231453+00:00 | 179.121 / 179.2257964 / 178.917 | H1 EMA aligned=False; stop 1.062 M15 ATR; target 2.068 ATR; spread/risk 0.048; snapshot RSI 30.828; SL -1.181R. |

| trendline_v5 / USDCAD / 2026-09-28T00:00:32.198395+00:00 | 1.41549 / 1.41583136 / 1.41401 | H1 EMA aligned=False; stop 0.900 M15 ATR; target 3.902 ATR; spread/risk 0.088; snapshot RSI 65.734; SL -1.220R. |

| trendline_v5 / XAGUSD / 2026-09-28T00:00:32.198395+00:00 | 63.726 / 63.5964 / 64.036 | H1 EMA aligned=False; stop 0.900 M15 ATR; target 2.153 ATR; spread/risk 0.116; snapshot RSI 20.294; SL -1.042R. |

| trend_momentum / XAUUSD / 2026-09-25T00:00:00.703324+00:00 | 4265 / 4293.058571 / 4185.45 | H1 EMA aligned=True; stop 5.703 M15 ATR; target 16.169 ATR; spread/risk 0.002; snapshot RSI N/A; SL -1.004R. |

| trend_momentum / GBPJPY / 2026-09-28T00:00:32.198395+00:00 | 208.283 / 208.7535714 / 206.288 | H1 EMA aligned=True; stop 3.233 M15 ATR; target 13.705 ATR; spread/risk 0.015; snapshot RSI N/A; SL -1.018R. |


The EURJPY short has snapshot RSI near 31 (momentum exhaustion risk); XAGUSD long has snapshot bearish HTF and RSI near 20 (countertrend risk); USDCAD short has snapshot bullish HTF. These are examples, not proof that an RSI or HTF veto improves results. T/M XAUUSD and GBPJPY targets are roughly 16.2 and 13.7 M15 ATR away; horizon mismatch and target reachability deserve explicit testing. Their stops are on the H1 model, so M15 distance alone does not prove a placement bug.

Early/late entry: bar-close to detection mismatches are established in the bank, but no causal early-versus-late edge conclusion is possible from this fixed-entry observational replay. Consolidation, liquidity and news impact are not independently measured by the available quote history. Do not assert these as proven causes. Session gaps are marked unknown, including legitimate weekend/daily closures, until an independent calendar is supplied. This deliberately sacrifices sample size rather than inventing a first hit.


**Overlapping signals:** 207 of 432 priced records have a previous same-symbol, same-direction confirmation within four hours. This counts potential dependence, not duplicate executed orders. Examples: AUDUSD bank Donchian Channel Breakout and ATR Volatility Breakout at 19 Oct 11:00:08.754 UTC; NZDUSD and GBPJPY have similar bank clusters. `results.json.correlated` contains paired IDs and time differences. Existing opportunity merging reduces duplicate alerts, but per-strategy statistics still count each signal and cross-symbol economic correlation is not controlled.

## 5. Strategy-by-strategy assessment

No strategy has a convincing independently established positive edge in this audit. S/R is the most credible candidate for continued controlled investigation, but the sample is small and missingness is selective. Strategy families and versions must not be pooled into a single promotion decision.

| Family | Priced signals | Independently resolved | Net R | Expectancy R | Decision recommendation (requires CEO approval for production changes) |
|---|---:|---:|---:|---:|---|

| trendline_v5 | 107 | 68 | -31.139 | -0.458 | Suspend qualified generation pending redesign and version-specific forward evidence. |

| support_resistance | 30 | 22 | 2.692 | 0.122 | Needs more data; retain shadow/controlled research, no positive-edge certification. |

| trend_momentum | 13 | 4 | -4.117 | -1.029 | Suspend qualified generation pending target/horizon validation. |

| smc | 2 | 1 | -1.060 | -1.060 | Experimental only; insufficient sample. |

| trendline | 231 | 169 | 14.424 | 0.085 | Retired; preserve for reproducibility, never merge with v5. |


Version-specific results (same conditional coverage and cost assumptions):

| Version | Signals | Resolved | Net R | Expectancy R | PF | Realized DD R | Day-block 95% interval |
|---|---:|---:|---:|---:|---:|---:|---|

| smc-confluence-v1 | 2 | 1 | -1.060 | -1.060 | 0.000 | 1.060 | [-1.06, -1.06] |

| sr-levels-v1 | 21 | 17 | 5.364 | 0.316 | 1.584 | 3.586 | [-0.472, 1.225] |

| sr-levels-v2 | 9 | 5 | -2.672 | -0.534 | 0.368 | 2.672 | [-1.005, -0.417] |

| tm-pullback-v1 | 1 | 1 | -1.004 | -1.004 | 0.000 | 1.004 | [-1.004, -1.004] |

| tm-pullback-v2 | 12 | 3 | -3.113 | -1.038 | 0.000 | 3.113 | [-1.059, -1.018] |

| trendline-first-v5 | 63 | 46 | -21.582 | -0.469 | 0.479 | 21.582 | [-0.816, -0.284] |

| trendline-first-v5.1 | 44 | 22 | -9.557 | -0.434 | 0.490 | 13.446 | [-0.994, 0.433] |


### Bank catalogue: existing historical claims, independently unverified

The pre-existing `backend/data/strategy_bank/historical.json` contains a two-year backtest with chronological train/validation/test periods. Its figures below are **secondary codebase evidence, not rerun or certified results**. Several strategies share trend/breakout exposure. Retain source provenance and adjust for all attempted variants before making promotion claims. No new near-identical strategies were added.

| Strategy | Existing test trades | Existing test expectancy R | Assessment |
|---|---:|---:|---|

| trendline_break_retest | 575 | -0.244 | Experimental; negative or absent historical evidence, no qualified promotion. |

| trendline_bounce | 2221 | -0.314 | Experimental; negative or absent historical evidence, no qualified promotion. |

| support_resistance | 175 | -0.042 | Experimental; negative or absent historical evidence, no qualified promotion. |

| breakout | 516 | -0.132 | Experimental; negative or absent historical evidence, no qualified promotion. |

| ema_crossover | 640 | -0.079 | Experimental; negative or absent historical evidence, no qualified promotion. |

| ema_pullback | 1393 | -0.168 | Experimental; negative or absent historical evidence, no qualified promotion. |

| rsi_divergence | 218 | -0.174 | Experimental; negative or absent historical evidence, no qualified promotion. |

| macd_momentum | 1091 | -0.029 | Experimental; negative or absent historical evidence, no qualified promotion. |

| bollinger_reversion | 204 | 0.077 | Candidate for independent retest only; no promotion. |

| donchian | 1755 | -0.094 | Experimental; negative or absent historical evidence, no qualified promotion. |

| london_breakout | 1122 | 0.083 | Candidate for independent retest only; no promotion. |

| opening_range_breakout | 379 | -0.132 | Experimental; negative or absent historical evidence, no qualified promotion. |

| vwap_reversion | N/A | N/A | Unsupported: preserve explicit missing-volume restriction. |

| liquidity_sweep | 790 | -0.099 | Experimental; negative or absent historical evidence, no qualified promotion. |

| fair_value_gap | 198 | -0.222 | Experimental; negative or absent historical evidence, no qualified promotion. |

| order_block_retest | 177 | 0.025 | Candidate for independent retest only; no promotion. |

| market_structure_break | 375 | 0.050 | Candidate for independent retest only; no promotion. |

| inside_bar_breakout | 1523 | -0.155 | Experimental; negative or absent historical evidence, no qualified promotion. |

| atr_breakout | 1540 | -0.180 | Experimental; negative or absent historical evidence, no qualified promotion. |

| ichimoku | 1388 | -0.097 | Experimental; negative or absent historical evidence, no qualified promotion. |


Expansion/discovery strategies already present in the dirty workspace are not independently validated by this audit. Keep them in research until their exact code, data and forward outcomes are frozen and reproduced. Existing positive backtests for Bollinger reversion, London breakout, order-block retest and market-structure break are hypotheses; the bank’s 49 recent forward records have no cached M1 coverage here.

## 6. Outcome-tracking accuracy and R accounting

Entry is modeled as immediate market entry at the recorded executable quote. There is no evidence of actual broker fills or pending-order activation; a paper confirmation is not an executed order. Ties remain ambiguous; no SL-first or TP-first assumption is used to manufacture certainty. Missing first minutes and gaps remain unknown. Independent stop-gap fills use the worse of planned stop and bar open; TP improvement is conservatively ignored. R denominator is the stored planned risk; costs reduce the numerator.

Spread is already reflected in stored entry and exit-side barriers. The additional reserve is assumed FX commission .00007 price units (.007 for JPY), gold .07, silver .0014; indices/crypto zero commission; plus half the exit-bar spread on either resolved outcome. These are transparent sensitivity assumptions, **not verified historical account charges**. A second run doubles that additional reserve. This is not full spread doubling, variable intraminute slippage or financing stress. Financing is unavailable and omitted.

Calendar gaps and incomplete histories can remove slow trades preferentially, so resolved-only comparisons may be biased. The results do not identify the counterfactual performance of omitted signals. No-hit is censored, not zero P&L; a seven-day market exit would require a verified executable closing quote. Realized-exit drawdown assumes additive equal planned-risk units; it excludes floating exposure and is not account drawdown. The bootstrap resamples entry UTC days to preserve same-day dependence, but multi-day/cross-asset dependence and very few days make its intervals exploratory. A single all-winning five-trade subset cannot establish certainty even when a bootstrap returns positive bounds.

## 7. Experimental system and test results

The standalone experiment changes qualification only, preserving original entries, stops and targets: (1) last fully closed H1 EMA50/EMA200 direction alignment with >=200 bars, (2) stop 0.5–3 independent M15 ATR and target <=4 M15 ATR, (3) known spread <=10% planned risk, (4) at most one retained symbol/direction signal per four hours. Unknown features fail closed. These thresholds are research hypotheses fixed before the final cohort results, not validated recommendations. The generic location rule is deliberately challenged because H1 strategies may require different horizons.

Original and experimental use the same captured signals, independent resolver, candles, observation clock and cost model. The primary comparison excludes retired trendline and separates the bank. Cooldown is applied independently within each cohort.

| Population / system | Signals | Resolved | Net R | Expectancy R | PF | Realized DD R | Day-block 95% interval |
|---|---:|---:|---:|---:|---:|---:|---|

| Current strategy families / original | 152 | 95 | -33.624 | -0.354 | 0.573 | 38.844 | [-0.541, -0.149] |

| Current strategy families / experimental | 32 | 18 | -3.166 | -0.176 | 0.751 | 5.470 | [-0.592, 0.237] |

| Retired trendline / original | 231 | 169 | 14.424 | 0.085 | 1.131 | 23.226 | [-0.335, 0.139] |

| Retired trendline / experimental | 32 | 25 | 2.577 | 0.103 | 1.163 | 8.484 | [-0.07, 1.013] |

| Strategy Bank / original | 49 | 0 | 0.000 | N/A | N/A | 0.000 | N/A |

| Strategy Bank / experimental | 0 | 0 | 0.000 | N/A | N/A | 0.000 | N/A |

| Training before Oct 1 / original | 69 | 51 | -13.618 | -0.267 | 0.669 | 19.938 | [-0.392, -0.06] |

| Training before Oct 1 / experimental | 16 | 10 | 0.202 | 0.020 | 1.032 | 2.542 | [-0.493, 0.842] |

| Test Oct 8 onward / original | 24 | 6 | 1.966 | 0.328 | 1.616 | 2.129 | [-1.064, 1.581] |

| Test Oct 8 onward / experimental | 3 | 0 | 0.000 | N/A | N/A | 0.000 | N/A |


### Individual filters on current families

| Policy | Signals | Resolved | Net R | Expectancy R | PF | Realized DD R | Day-block 95% interval |
|---|---:|---:|---:|---:|---:|---:|---|

| htf | 65 | 33 | -19.511 | -0.591 | 0.328 | 20.118 | [-0.888, -0.199] |

| location | 106 | 76 | -23.055 | -0.303 | 0.626 | 30.390 | [-0.528, 0.015] |

| cost | 128 | 78 | -19.419 | -0.249 | 0.679 | 24.016 | [-0.409, -0.09] |


### Twice the additional execution-cost reserve

| System | Signals | Resolved | Net R | Expectancy R | PF | Realized DD R | Day-block 95% interval |
|---|---:|---:|---:|---:|---:|---:|---|

| original | 152 | 95 | -43.085 | -0.454 | 0.501 | 47.896 | [-0.65, -0.236] |

| experimental | 32 | 18 | -4.110 | -0.228 | 0.693 | 6.144 | [-0.657, 0.174] |


### Sequential fixed-policy windows

These are retrospective stability diagnostics, **not fresh walk-forward validation**: the code and dataset were already visible during the audit. No thresholds are refit.

| Window start / system | Signals | Resolved | Net R | Expectancy R | PF | Realized DD R | Day-block 95% interval |
|---|---:|---:|---:|---:|---:|---:|---|

| 2026-09-23 / original | 62 | 46 | -11.205 | -0.244 | 0.696 | 19.938 | [-0.374, -0.0] |

| 2026-09-23 / experimental | 15 | 9 | 1.213 | 0.135 | 1.228 | 2.542 | [-0.364, 1.611] |

| 2026-09-30 / original | 56 | 37 | -17.392 | -0.470 | 0.451 | 19.285 | [-0.623, -0.392] |

| 2026-09-30 / experimental | 10 | 8 | -3.359 | -0.420 | 0.471 | 3.359 | [-1.036, 0.039] |

| 2026-10-07 / original | 14 | 10 | -2.899 | -0.290 | 0.640 | 8.054 | [-1.166, 1.581] |

| 2026-10-07 / experimental | 4 | 1 | -1.020 | -1.020 | 0.000 | 1.020 | [-1.02, -1.02] |

| 2026-10-14 / original | 20 | 2 | -2.129 | -1.064 | 0.000 | 2.129 | [-1.064, -1.064] |

| 2026-10-14 / experimental | 3 | 0 | 0.000 | N/A | N/A | 0.000 | N/A |


The chronological diagnostic split is 8 Oct, with a seven-day purge: training entries before 1 Oct, testing entries from 8 Oct. The experiment has **no independently resolved test trades** because of cached-history truncation. Therefore unseen-data improvement is unestablished. Lower aggregate losses or drawdown can merely reflect lower signal frequency. Individual filter ablations do not justify blind indicator additions. The S/R retained subset is only five independently resolved targets; the retained v5 subset still loses heavily. Do not deploy this generic policy. A true walk-forward study must use version-frozen historical detectors, training-only choices, untouched future folds, complete execution paths and portfolio exposure rules.

## 8. Root causes and assessment of the implementation

**Evidence-supported root causes:** weak v5 expectancy in the verifiable current-family subset; stale/overdistant plans in historical T/M; dependence from clustered signals; materially different legacy/current versions and reporting denominators; incomplete histories; and inconsistent entry timing, outcome certainty and execution costs. These effects cannot be decomposed into exact percentages of the reported -19.84R without the original report cohort.

**Implemented correctly and worth preserving:** deterministic inspectable strategy rules, closed-bar v5 handling, causal higher-timeframe selection, isolated registry evaluation, explicit missing-volume VWAP restriction, executable bid/ask qualification, current conservative production quantization, immutable confirmation evidence, append-only revisions and independent Telegram deduplication.

**Incorrectly implemented:** the reproduced boundary/coverage/freshness cases, bank entry timestamp semantics and lifecycle-alert revocation inconsistency. **Technically functional but statistically weak:** heuristic scores, strategy proliferation, point-estimate promotion gates, and bar-only paper R presented without execution uncertainty. **Requires redesign:** shared outcome/execution contract, central alert authorization, version/cohort reporting and portfolio risk qualification. This assessment concerns inspected implementation evidence, not claims about which person or model authored each line.

## 9. Recommended qualification architecture

Use separate mechanical-validity, statistical-admission and portfolio-risk decisions. Mechanical validity must verify closed bars, timestamps, session-aware coverage, finite quotes and costs, executable rounded levels, actual entry time, plan reachability and spread-to-risk; it never proves profitability. Statistical admission is strategy- and version-specific: pre-register rules, minimum independent opportunity count, net expectancy interval, drawdown limits, regime/session coverage and all research trials; use block-based uncertainty and prospective shadow outcomes. Portfolio admission applies instrument/currency/risk-factor exposure limits and a shared opportunity ID across strategies and alert channels.

Do not adopt universal HTF/RSI/session/volatility filters on intuition. HTF alignment did not establish an improvement here. Test target reachability and time exits by strategy horizon; test session and volatility filters only after obtaining complete calendars and broker histories. Score should be called pattern strength unless calibrated prospectively against a precisely defined outcome. Keep experimental approval distinct from statistically qualified status. Every alert must recheck current authorization at send time.

Suggested admission criteria are proposals, not proven thresholds: a positive lower bound for cost-stressed expectancy across independent opportunity blocks, adequate event and regime coverage, stable untouched folds, acceptable floating/realized drawdown, and documented CEO approval. A fixed 60-record count alone is insufficient. No real-money permissions should follow automatically from paper qualification.

## 10. Implementation roadmap and reproducibility

1. **Before changing signals:** freeze the exact original report inputs, code revision, settings and cohort query; surface missing/ambiguous outcomes and version-specific denominators. Preserve all historical rows.
2. **Correctness work after approval:** implement entry-time and contiguous-coverage fixes in an isolated branch, add the adversarial cases as expected-correct regressions, re-resolve historical rows as auditable revisions, and unify central alert authorization. Do not overwrite prior performance.
3. **Research data:** obtain complete bid/ask ticks or contiguous M1 plus broker trading sessions, timestamped cost specifications, full entry/delivery timestamps and a frozen data manifest. Close gaps before comparing strategies.
4. **Validation:** rerun exact current versions over several regimes; perform chronological purged walk-forward tests, cost stress, dependence-aware uncertainty and currency-factor exposure simulation. Report all tried candidates. Preserve an untouched future period.
5. **Forward shadow:** register the best supported strategy-specific candidate with no public alerts; compare matching opportunities prospectively. Recommend suspension/restriction of v5 and T/M qualified generation for CEO review, without changing their configuration here.
6. **Deployment:** submit concrete production diff, migration/revision plan, tests and rollback for CEO approval. This report supplies no deployment authorization.

Reproduce offline from repository root:

```text
python audit_independent/probe_outcomes.py
python -m unittest discover -s audit_independent -p test_replay.py
python audit_independent/check_existing.py
python audit_independent/run_audit.py
python audit_independent/build_report.py
```

`run_audit.py` captures a new read-only snapshot from the evolving source stores on every run; exact old evidence is retained in the delivered input copies until rerun. `signal_evidence.json` contains all priced plans, computed features and independent outcomes. `results.json`, `cohort_results.json`, `probe_results.json` and `source_manifest.json` provide machine-readable supporting evidence. The experiment is not imported or enabled by the application.

Validation: **7 independent replay tests passed; 49 relevant existing outcome/bank/market-data/source-quality tests passed.** The initial existing-test run hit sandbox temporary-directory permission errors; the authorized rerun outside that restriction passed all 49. Seven adversarial probes expose behavior absent from those passing regressions. This is targeted validation, not a full-suite certification. No profitability claim or production change is warranted.
