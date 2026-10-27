# Gold and Bitcoin Phase 2: validation and readiness

27 October 2026 · Isolated research only · **Production verdict: NOT READY**

## Decision for the CEO

The prototype is more explicit about bad inputs and no longer treats every Gold
closure as missing data. It is **not proven to identify better trades**. Bitcoin's
retained-plan replay remains negative after costs. Gold's small, incomplete cohort
cannot support promotion. Do not deploy, change delivery permissions or activate
any strategy on this evidence.

Three questions have different answers:

| Question | Finding |
|---|---|
| Are market conditions classified more accurately? | Closure classification is better supported; trend/regime prediction accuracy is not established because no independent directional/regime truth labels exist. |
| Are misleading inputs detected? | Yes for the defined faults: 322/322 injected cases were diagnosed on 46 historical prefixes. This is an operational benchmark, not 322 independent market observations or proof of fewer losing trades. |
| Is expectancy better after realistic costs? | Not demonstrated. The recorded-plan cohort is small, historically exposed, mixed-version and incomplete. On the resolved original opportunities, Gold filtering reduced equal-opportunity returns. |

## Broker calendar investigation

Existing evidence in `quant_labs/next_phase/market_sessions.json` identifies IC
Markets Global MT5 and the verified cache clock basis `America/New_York+07:00`.
It records quotes resuming after a published daily break. That is retained
observational evidence, not a newly captured account session table.

The current [broker trading-hours page](https://www.icmarkets-global.com/en/trading-pricing/trading-hours)
was reviewed. Gold's prose and table disagree about the weekday close. The page
also lists broker-specific Bitcoin maintenance, so broker BTC is not assumed to
quote continuously like a spot venue. The terminal Specification remains the
account authority. No account-specific quote/trade session export was available;
MT5 was not initialized to obtain one. Current published hours do not certify
historical schedules or holidays.

`backend/research/broker_sessions.json` stores the source, review date, clock,
weekly sessions, disputed intervals and verification limits. Scanner code has
no assumed Gold-hour constants. `BrokerCalendar` accepts an injected versioned
profile and dated overrides. Disputed closing minutes remain UNKNOWN; holiday
overrides require external evidence rather than inference from an absent candle.

Implementation distinctions:

- Known scheduled breaks/weekends are separated from expected-but-missing bars.
- Partial H1/H4/D1 buckets are expected when a session overlaps any portion.
- Broker-wall-clock alignment and NY DST are used; ambiguous clock boundaries
  are rejected rather than silently assigned an offset.
- Freshness uses the latest *expected completed* context bar, allowing normal
  closures without accepting an absent expected bar after reopening.
- Stale, absent and future quotes remain unavailable even during a closure.
  Trade hours do not prove quote availability; no quote-freshness waiver exists.

The calendar is labeled `PUBLISHED_INDICATIVE_NOT_ACCOUNT_VERIFIED`. This is an
offline compatibility model, not certified account availability.

Historical transitions were audited on the retained content-addressed MT5 snapshot:

| Gold timeframe | Gaps compatible with published closures | Unexpected or unverified gaps |
|---|---:|---:|
| M15 | 538 | 27 |
| H1 | 539 | 24 |
| H4 | 113 | 9 |
| D1 | 159 | 9 |

These are interval counts, not independent outages. A holiday, a changed session
or an interruption can each produce an unverified gap. The new logic does not
invent which explanation is correct. Bitcoin gap counts and examples are in
`phase2-session-transitions-final-2026-10-27.json`.

## Backend stall: root cause and regression

A 20-second diagnostic timeout captured the API test waiting in Python 3.14's
`socket._fallback_socketpair` accept call while constructing the asyncio event
loop for Starlette TestClient. It stalled before the application handled the
request. The same API test passed in 0.401 seconds with approved local socket
access. This supports restricted loopback access as the cause, not an MT5 call,
network service dependency, SQLite deadlock or background worker in that trace.

The calendar restart test separately hit denied access to its temporary SQLite
file under restricted execution and passed with temporary-database access.
These environmental failures are recorded, not converted into skipped tests.

`backend/tests/run_suite.py` now isolates `TRADEDEN_CONTROL_FILE` before importing
the application, as well as isolating the data directory. It creates RUNNING intent
only in that disposable fixture. Optional verbose output identifies the current
test; a configurable 120-second per-test/discovery timeout emits all thread stacks
and exits nonzero. No production event-loop policy was changed.

Completed runs before the final consolidated run:

- 707 backend tests: no failures, one skip, 114.839 seconds.
- 717 backend tests including calendar/H4 checks: no failures, one skip,
  113.360 seconds.
- Four additional statistical checks: all pass.
- 187 frontend tests: all pass; no skips.

The one backend skip reports an already-running watchdog; it was left untouched.
The default backend runner explicitly excludes opt-in RealStoreEquivalence tests.
Those live-store comparisons were not run and are distinct from unittest skips.
The final consolidated backend run completed **721 tests in 115.635 seconds:
720 passed, one skipped, zero failures/errors/timeouts**. Counts and local commit hashes are recorded in
`PHASE2_COMMITS_2026-10-27.md` after the tested implementation is committed.

## Expanded chronological validation

Authoritative evidence: `phase2-validation-final-2026-10-27.json`.
The earlier `phase2-validation-2026-10-27.json` is retained as an intermediate
run; use the final artifact, which sorts drawdown inputs chronologically and
withholds bootstrap intervals with fewer than eight weekly clusters.

Protocol: unchanged baseline `market_intel.engine.build`, strict Phase 1 policy,
and the calendar overlay receive identical trailing M15/H1/H4/D1 windows. Six
broker-hour sampling positions per day use only completed history. Periods:
train 15 Oct 2024–1 Oct 2025, validation to 1 Apr 2026, chronological test to
12 Oct 2026. No thresholds were fitted or selected on these results. The historical
cache has been used in prior research, so the test is not a pristine firm-wide holdout.

| Context measure | Gold | Bitcoin |
|---|---:|---:|
| All observations | 3,060 | 4,354 |
| Strict Phase 1 blocked | 3,060 | 3,336 |
| Calendar overlay blocked | 2,541 | 3,209 |
| Baseline directional scenario flags | 39 | 36 |
| Calendar overlay directional flags | 22 | 26 |
| Chronological test observations | 818 | 1,161 |
| Test reduction in block rate | 14.18 percentage points | 5.17 percentage points |
| Weekly-block 95% interval for reduction | 7.71–21.43 points | -0.17–11.22 points |

The intervals describe paired changes in context blocking, using 28 UTC weekly
clusters and a fixed bootstrap seed. They do not measure forecasting or profitability.
Reduced directional flags are not labeled false positives: the overlay also
withholds conflict/range/shock conditions whose predictive value is unproven.

Coverage includes Gold Asia 850, London 1,026, New York 513 and other periods;
Gold regimes: 697 trending, 836 mixed, 1,527 ranging. Bitcoin includes 1,240 UTC
weekend and 3,114 weekday contexts; regimes: 816 trending, 1,176 mixed, 2,362 ranging.
Low/normal/high volatility groups and per-split counts are retained in the artifact.
There are 100 Gold and 140 Bitcoin price-shock observations. No authoritative
historical news calendar is connected, so none is asserted to be news-caused.

Context replay uses explicitly synthetic fresh zero-spread quotes at the latest
M15 close. It cannot validate historical tick freshness or execution feasibility.
Closure samples and transition tests cover daily breaks/weekends/reopening; they
are not a continuous tick-by-tick quote availability audit.

## Actual cost replay: narrow conditional evidence

The 50 frozen Gold/BTC plans in `audit_independent/signal_evidence.json` were
re-evaluated with `quant_live.execution.simulate`. Original and filtered plans
keep identical entry, stop, target, prices, time horizon and costs. The filter
adds only the offline context/quality eligibility check. Plans include mixed
strategy versions and sources, not a complete replay of today's strategy registry.
They are retained original opportunities, not newly generated signals.

Spread is recorded or reconstructed from the retained spread/risk feature; missing
spread is not replaced with zero. Quote sides are reconstructed from entry/direction;
historical tick receipt time is unavailable. The fill model uses bid/ask sides,
adverse slippage, explicit commission assumptions (Gold 0.07 price units, Bitcoin
zero), current broker financing as a historical proxy, unresolved intrabar ties
and data gaps. Double-cost stress retains planned risk/geometry. A fixed seven-day
deadline is used unless a recorded time exit exists. No actual broker fill is claimed.

| Normal costs, resolved-only | Original Gold | Filtered Gold | Original BTC | Filtered BTC |
|---|---:|---:|---:|---:|
| Attempts | 25 | 15 | 25 | 10 |
| Resolved | 16 | 9 | 22 | 10 |
| Unknown/invalid | 9 | 6 | 3 | 0 |
| Mean net R | +0.350 | +0.416 | -0.260 | -0.246 |
| Win rate | 43.75% | 44.44% | 27.27% | 30.00% |
| Profit factor | 1.623 | 1.760 | 0.651 | 0.657 |
| Realized drawdown R | 3.039 | 2.038 | 7.723 | 3.101 |
| Longest losing streak | 3 | 2 | 4 | 3 |

Stress mean R is +0.312/+0.368 Gold original/filtered and -0.295/-0.276 BTC.
Average winners/losers, status counts and individual outcomes are stored in the
JSON. There are only three or four independent weekly clusters, so inferential
confidence intervals are withheld; the earlier intermediate bootstrap intervals
must not be used to claim significance.

Per-resolved-trade means conceal the effect of abstention. On each resolved
original opportunity, taking zero R when filtered changes Gold by **-0.117R**
and Bitcoin by **+0.148R** on average. These tiny retrospective, overlapping
streams are not a portfolio or independent prospective test. Reducing drawdown
by trading less does not establish more accurate entries. The no-trade control
is zero R. Assigning -1.5R per unknown turns Gold's original/filtered averages
to -0.316/-0.351R; this is sensitivity analysis, not a lower bound on gap losses.
**No market earns trading-edge approval.**

## H4 validation

Tests cover absent/stale H4, broker-grid misalignment, incomplete and future
candles, expected gaps, restart reloads and revision exclusion from the existing
SQLite reader. Genuine historical prefix tests and the injected-fault benchmark
exercise chronology. No M15/H1 fallback is substituted for absent H4.
The evaluator is stateless: every call validates its provided snapshot; restarting
does not reuse a previously trusted in-memory H4 result.

Known-fault benchmark: 46 prefixes across both markets, one prefix per 30-day
epoch bucket, with seven faults each. All 46 cases per fault were diagnosed:
missing H4, stale H4, misaligned H4, a deleted H4 candle, future quote, stale
quote and absent quote. Baseline's generic stale flag catches the stale quotes,
but is not a general H4 fault detector. Baseline also reports UNAVAILABLE for
missing H4; the defect is allowing that context to satisfy scenario conditions.
This benchmark does not estimate a population false-positive rate.

## Remaining defects and risks

1. No account-specific quote/trade schedule or historically dated holiday table.
   Published schedules are insufficient authority for activation.
2. Gold's nine unverified D1 gaps can propagate through the required 60-bar window;
   1,475 contexts still flag missing expected D1 history. Investigate holidays and
   source coverage rather than loosening thresholds to improve results.
3. Crypto DST clock ambiguity still blocks affected windows. The first run found
   400 contexts with invalid H4 history, 602 with invalid H1 and 102 with invalid
   M15, with overlap. Diagnostic inspection reproduced ambiguous broker-clock
   boundaries. Do not silently repair these timestamps without provenance.
4. The live intelligence builder retains its legacy freshness/H4 behavior because
   production integration is unapproved. Nested `analysis` is descriptive legacy
   output; the overlay's top-level status, blockers and quote/data quality are the
   authoritative research eligibility result.
5. Macro/news and exchange order-flow inputs remain unavailable. Zero-variance
   optional equity correlation remains a separate legacy follow-up.
6. No complete current-registry strategy replay, independent prospective quotes,
   sufficiently large return cohort or calibrated directional accuracy labels.
7. Existing loader/build closed-bar handling uses fixed timeframe durations;
   the calendar adds broker-wall-clock closure checks. DST ambiguity remains
   fail-closed and needs verified source-clock/session evidence before live use.

## Resource use and operational impact

The final 7,414-context comparison completed in 152.4 seconds on one foreground
process; no background research job was installed. A bounded-window Gold probe
with allocation tracing measured 0.674 seconds cold and 0.0517 seconds mean warm
over 20 repeats, with 525,860 bytes peak incremental traced Python allocation.
This excludes historical input loading and is not whole-process RSS or a live
latency guarantee. The calendar cache is bounded to 8,192 day/timeframe entries;
its maximum-memory behavior still needs a long-running soak before integration.

Current production resource impact is zero: no route, worker, strategy, collector
or dashboard imports these research modules. No production service was restarted;
broker execution and Telegram permissions were unchanged.

## Deployment recommendation and rollback

Recommended approach: remain offline. Obtain the account Specification/session
export and historical exceptions; reconcile unresolved gaps and DST provenance;
rerun the frozen protocol; collect unseen prospective paper evidence with receipt
timestamps. Only then request CEO approval for a default-off, preview-only API
adapter beside the current dashboard panel. Retain legacy output for comparison;
require explicit approval for any later activation or delivery change.

Rollback now: stop only the foreground research command if one is running; no
production rollback is needed. Restore research code from the prior local commit
or revert the validation commit on its branch while preserving evidence artifacts.
Do not reset or delete live history. A future integration must have its own
default-off flag, versioned profile and tested rollback before approval.

## Reproduction and local version control

From the repository root, choose new output names; research commands use exclusive
creation to retain existing evidence:

```powershell
python -m backend.research.phase2_validation --output docs/phase2-validation-rerun.json
python -m backend.research.phase2_faults docs/phase2-faults-rerun.json
python -m backend.research.phase2_sessions docs/phase2-sessions-rerun.json
python -m backend.research.phase2_resources docs/phase2-resources-rerun.json
python backend/tests/run_suite.py --verbose --timeout 120
npm test
```

The backend suite requires local socket and temporary-file access. It does not
require production MT5 startup. Source hashes, dataset manifest/blob verification,
fixed periods, recorded observations and explicit quote/cost assumptions accompany
the final evidence. Commit references are recorded in the companion commit record.
