# TRADEden Gold and Bitcoin: audit and isolated development

27 October 2026 · CEO review · No deployment or production activation

## CEO decision

The existing platform has substantial engineering safeguards and useful descriptive
market context. Historical research does **not** establish a general profitable
Gold/Bitcoin scanner. This work adds a tested offline quality overlay and a
reproducible comparison, not a new approved strategy. Better trading opportunities
have **not** been demonstrated. Do not activate this overlay in production yet:
its strict gap rule blocks all sampled Gold contexts and needs a broker calendar.

The highest-value next step is verified session-aware data continuity and prospective
quote collection, followed by a frozen, cost-aware comparison of one narrowly
specified strategy. More indicators or ML are lower priority.

## Scope and baseline

The working tree was clean at initial inspection. Repository areas inventoried:
backend, frontend, MT5 integration, operational/deployment controls, strategy bank,
Quant Labs, autonomous research, tests, audit artifacts and existing reports.
This is a source-and-artifact audit of relevant paths, not independent certification
of every historical record or a live operational health check. No terminal was
started and no running service or production configuration was changed.

| Responsibility | Existing implementation | Assessment |
|---|---|---|
| FastAPI collection and worker lifecycle | `backend/main.py` | Shared MT5 session, background scanner, disabled execution responses; retains owner intent |
| Data ingestion | `backend/market_data.py`, `market_time.py`, `quant_live/adapter.py` | Explicit timeframe requirements and normalized closed-bar handoff; broker provenance matters |
| General scanners | `backend/scanner.py`, `strategies/{trendline,support_resistance,trend_momentum,smc}.py` | Real implemented rules; descriptive confirmation is not statistical qualification |
| Strategy isolation | `backend/strategies/registry.py` | LIVE/SHADOW separation, missing-data checks, immutable shared inputs |
| Gold/BTC intelligence | `backend/market_intel/{rules,engine,live,readiness}.py` | D1/H4/H1/M15 context, session levels, pivots, volatility/regime and explainable scenarios |
| Executable qualification | `backend/qualification.py`, `quant_live/runtime.py` | Bid/ask geometry, freshness, cost/RR checks; model approval remains separate |
| Paper monitoring | `backend/signal_outcomes.py`, `outcomes.py`, `quant_live/{execution,runtime,store}.py` | Established lifecycle/outcome infrastructure; retain unknown/ambiguous outcomes |
| Research and performance | `backend/research/`, `quant_labs/`, `research_autonomous/`, `backend/performance.py` | Existing replay, costs, train/test, uncertainty and failed research; avoid a competing backtester |
| Telegram | `backend/telegram_notifier.py`, `quant_live/{telegram,intel_center,research_observations}.py`, `market_intel/briefings.py` | Independent categories and approvals; C uses 08:00 and 15:00 EAT slots |
| Dashboard | `src/marketRadar.js`, `src/quantLabs.mjs`, `src/garden/` | Existing identity and Gold/BTC panel already display context, levels and unavailable feeds |
| Process safety | `backend/ops/{control,engine,watchdog}.py`, `main.ensure_mt5`, root launchers | RUNNING/PAUSED/STOPPED; terminal disappearance pauses rather than silently reinitializing |

No evidence justified rebuilding the dashboard, replacing lifecycle states, adding
another MT5 collector, or expanding Telegram delivery. The experimental overlay
has no dependency on those workers and is not exposed through a live route.

## Gold assessment

Existing intelligence supplies DST-aware Asia/London/New York windows,
previous broker-day/week levels, confirmed H4 swings, D1 outer ranges, H1 efficiency,
ATR percentile and shock context. Gold compression readiness is explicitly
Category B research. The equal-weight broker FX basket is labeled a USD proxy,
not DXY. Treasury yields, inflation expectations and authoritative news/calendar
are explicitly unavailable. These are useful honesty boundaries.

Weaknesses: fixed bar-count windows span market closures; session completeness
currently depends on elapsed clock time rather than proof of every expected bar.
The broker-calendar/session provenance must be verified before calling a range
complete or interpreting a missing interval as an outage. This iteration diagnoses
that uncertainty; it does not invent a closure calendar or macro veto.

## Bitcoin assessment

Existing Bitcoin context includes weekend state, synchronized NAS100 H1 return
correlation and explicit unavailability of funding, OI and liquidations. Existing
readiness describes Crypto Trend Breakout v0.3.0 as Category A, whereas Gold's
compression model remains Category B. This source label is not independent proof
of current delivery approval or edge; current stored approval must still govern.

MT5 prices are broker CFD observations. No centralized volume, actual delta,
depth or liquidation metric is available here. An exchange feed could later be
joined by timestamp and venue, but its spot/perpetual provenance must stay separate
from broker execution prices. No external subscription or exchange connector was
introduced. The correlation helper also deserves an unavailable result for zero
variance rather than allowing a statistics exception; this remains a live-code
follow-up, not a change made in this isolated iteration.

## Prior research findings: evidence, not a new backtest

`backend/V6_RESEARCH_REPORT.md` reports 120 configurations across 14 families.
Its pooled production-strategy test expectancy is -0.26R for trendline_v5
(2,501 trades), -0.02R S/R (175), -0.13R Trend/Momentum (28), -0.23R SMC (51).
These are **pooled markets**, not Gold/BTC-specific numbers. Do not relabel them.
The reported H1 Bollinger survivor is +0.07R on 193 test trades, CI [-0.07,+0.21],
and not significant after multiple comparisons. It is not a qualified edge.

That report attributes the dominant failures to random-like entries, roughly
0.15–0.17R execution drag, and excessive frequency. Session/conflict filters,
larger stops and target changes did not establish positive expectancy. Outcomes
were investigated; changing their resolver alone did not explain away losses.

`research_autonomous/CEO_RESEARCH_REPORT.md` reports 80 hypothesis/market cases,
66 supported, 11,188 standalone plans and no qualified winner. Its illustrative
BTC drift final-test cell is +0.098R on 37 resolved of 40 attempts, but -0.070R
under stress and CI [-0.387,+0.529]. Gold drift is +0.664R on only six resolved
of 26 attempts: the 20 unknowns prevent a credible positive conclusion. Historical
cache reuse means chronological splits are not untouched firm-wide evidence.
These figures were read from retained reports, not independently recomputed here.

Do not optimize another set of indicators against these already-exposed test
periods and call it independent validation. No incremental predictive value for
M5/M30, RSI/ADX, order flow, new regime filters or ML was established in this work.

## Confirmed quality defects and prepared implementation

`market_intel.engine.build` can mark missing quotes or future quotes as non-stale
when candles are fresh. Scenario confirmation only excludes an opposing H4 state,
so `UNAVAILABLE` can pass. New regression fixtures reproduce both behaviors.
These are analysis-layer findings; the separate paper-signal qualification gates
must not be described as having the same bypass.

`backend/research/intelligence_preview.py` prepares a pure offline overlay:

- Validate finite positive OHLC and consistent bounds; reject observed duplicate
  or unordered history without silently sorting or deduplicating it.
- Use only bars closed by the evaluation cutoff; retain input objects unchanged.
- Report each timeframe's count, last-close age, malformed history and recent gaps.
- Require 60 bars per existing context timeframe; freshness at most one timeframe
  since the latest close. These are conservative policy assumptions, not fitted thresholds.
- Require a positive ordered bid/ask with quote age 0–120 seconds. No quote means
  unavailable execution conditions, even when descriptive candles are current.
- Report spread/H1 ATR(24), with a research ceiling of 0.10. Zero/unavailable ATR
  fails closed. This is a diagnostic, not a full commission/slippage cost model.
- Suppress both scenario-met flags when any blocker exists. Always return
  `NO QUALIFIED OPPORTUNITY`, `qualified=False`, `production_enabled=False`.

No entry/stop/target, confidence percentage, trade quota, signal promotion,
notification sender, model training or stop adjustment was added. Existing
strategies, approvals, history and lifecycle remain unchanged.

## Same-data context comparison

Evidence: `docs/gold-bitcoin-context-comparison-2026-10-27.json`.
Runner: `backend/research/intelligence_compare.py`. Both implementations receive
the same trailing M15/H1/H4/D1 windows at the last 120 available D1 closes for
each market. The content-addressed dataset manifest and blobs are verified by
`SharedData`; the output records dataset and source hashes and every observation.

| Metric | Gold | Bitcoin |
|---|---:|---:|
| Context observations | 120 | 120 |
| Existing stale flag | 4 | 0 |
| Existing directional scenario met | 0 | 0 |
| Overlay directional scenario met | 0 | 0 |
| Overlay blocked contexts | 120 | 91 |

All Gold samples include recent H1/H4/D1 gaps under a strict uniform clock.
Many are expected closures, which this overlay deliberately refuses to classify
without a verified calendar. **This policy is too restrictive for live Gold use.**
Bitcoin has 71 ranging/inside-prior-range observations, 33 D1/H4 conflicts, six
shock observations, seven H1-gap and three M15-gap observations; categories overlap.
More blocking does not establish better selection.

Historical quote receipt times are unavailable in this dataset. The comparison
explicitly supplies synthetic fresh zero-spread quotes at the last M15 close to
isolate candle-context behavior. They are **not executable quotes**. It measures
context eligibility, not returns; win rate, expectancy, PF, drawdown, losing streaks
and trade performance differences are **not evaluated**, rather than fabricated.
No claim of better opportunities follows from 240 daily context samples with no
directional scenarios met. Daily sampling does not cover all intraday opportunities.

Reproduce from the repository root, choosing a new output path (exclusive creation
protects existing evidence):

```powershell
python -m backend.research.intelligence_compare --output docs/gold-bitcoin-context-comparison-rerun.json
python -m unittest discover -s backend/tests -p test_intelligence_preview.py
```

## Architecture and ranked next work

Retain the shared collector → normalized immutable snapshot → descriptive
intelligence → separate approved strategy → executable paper plan → durable
lifecycle → authorized delivery architecture. The overlay belongs between
normalized inputs and contextual display, after its calendar policy is validated.

| Rank | Work | Expected practical value | Cost / risk |
|---|---|---|---|
| 1 | Broker-verified weekly/holiday/DST session calendar, expected-bar coverage, quote receipt capture | Distinguish legitimate closures from missing observations; remove overblocking | Medium / low in offline research |
| 2 | Prepare targeted live intelligence freshness/H4 fixes and zero-variance correlation fallback for approval | Correct demonstrable misleading context states | Low / behavior change requires approval |
| 3 | Freeze one existing Gold and one Bitcoin hypothesis, compare against unchanged strategy and no-trade/random controls | Establish whether selection adds value after realistic fills | Medium / statistical uncertainty high |
| 4 | Prospective paper-only evaluation with stable identifiers and deduplicated lifecycle notifications in preview | Independent evidence from previously unseen conditions | Medium / preserve category approvals |
| 5 | Reuse execution foundation for targets 2R/3R/4R, costs normal/double, chronological embargoed walk-forward folds | Compare expectancy, unknowns, weekly block CIs, drawdown and regime/session breakdown | Medium / must count all trials and avoid test-set tuning |
| 6 | Dashboard additions using existing panel: blockers, per-timeframe freshness, evidence link | Clearer interpretation after reviewed API contract | Low / production display change |
| 7 | Timestamped macro calendar or independent venue data; only then feature ablation or calibrated simple models | Potential context value, unproven incremental edge | Medium–high / provenance and maintenance |

Future trade comparisons must keep entry times, stop geometry, costs, coverage
and periods identical; show unresolved paths separately and stress their effects;
retain all rejected configurations; avoid presenting an indicator score as a
calibrated probability. ML is deferred until a simpler baseline earns promotion.

## Validation and approval boundary

Nine focused tests pass: actual baseline defect reproductions, future-prefix
invariance, input immutability, each timeframe's staleness, gaps, malformed data,
invalid quotes, cost and zero-ATR blocking. The historical comparison completed
240 observations. Seven existing RuleTests/EngineTests/NoLookAheadOnGenuineData
tests pass, including genuine historical prefix invariance. All 187 frontend
tests pass. The full backend runner and a separate existing intelligence API test
did not complete and were interrupted after stalling; no full-backend regression
pass is claimed. The separate invocation reached the Starlette TestClient import
warning without completing the API guard test; its root cause is undiagnosed.
These incomplete integration checks are another prerequisite before activation.

This iteration completes the audit and highest-priority isolated quality prototype,
not every research direction in the assignment. Dashboard wiring, live scanner
replacement, new strategies, historical strategy-return comparison, exchange/macro
feeds and ML remain explicitly deferred until their evidence/data prerequisites
are met. Nothing was deployed, promoted, sent to Telegram or enabled for execution.
Category C retains the existing 08:00/15:00 EAT schedule and approval gate.

CEO approval is required before any production wiring, deployment, strategy
promotion or delivery-permission change. The present overlay is **not recommended
for activation** until session-calendar overblocking is resolved and evaluated.

## External method references

The official [MT5 rates documentation](https://www.mql5.com/en/docs/python_metatrader5/mt5copyratesfrompos_py)
defines bar zero as the current bar and exposes tick volume and real volume as
separate fields; closed-bar filtering is necessary. The original
[Probability of Backtest Overfitting paper](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf)
supports treating selection across many backtests as a source of false discoveries.
Neither source validates these strategies or thresholds.
