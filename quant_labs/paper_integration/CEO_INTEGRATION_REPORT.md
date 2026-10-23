# Seven-model Codex experimental paper integration

**23 October 2026 · Africa/Nairobi**

All seven original 0.1.0 executables are now separately registered and executing in the existing experimental paper scanner. They remain EXPERIMENTAL. No source parameters, manifests, stop/target calculations or horizons were changed. No engine restart, production-strategy change, dashboard-code change, delivery activation, broker execution, push or deployment occurred.

## Actual scanner executions

| Model | Supported instruments | Actual completed executions after enrollment | Detections | Scan / Telegram |
|---|---|---:|---:|---|
| trend_reclaim_r2 0.1.0 | EURUSD, XAUUSD, BTCUSD | 3 | 0 | enabled / disabled |
| trend_reclaim_r3 0.1.0 | EURUSD, XAUUSD, BTCUSD | 3 | 0 | enabled / disabled |
| trend_reclaim_r4 0.1.0 | EURUSD, XAUUSD, BTCUSD | 3 | 0 | enabled / disabled |
| trend_reclaim_r5 0.1.0 | EURUSD, XAUUSD, BTCUSD | 3 | 0 | enabled / disabled |
| trend_reclaim_r7 0.1.0 | EURUSD, XAUUSD, BTCUSD | 3 | 0 | enabled / disabled |
| trend_reclaim_r9 0.1.0 | EURUSD, XAUUSD, BTCUSD | 3 | 0 | enabled / disabled |
| range_sweep_reversion 0.1.0 | EURUSD, XAUUSD, BTCUSD | 3 | 0 | enabled / disabled |

Registration completed at 03:05:30 EAT. Genuine executions were recorded between 03:05:56 EAT and 03:06:31 EAT, covering all 21 model/market combinations on the completed 03:00 EAT M15 candle. Zero detections and zero qualified new paper signals occurred; forward expectancy and win rate are unavailable, not zero. No historical or synthetic opportunity was inserted into the live signal ledger.

## Frequency and scheduling

Each model uses closed M15 features and H1 context: **at most one worker claim per model/version/instrument/completed M15 bar**, normally one decision opportunity every 15 minutes. Enrollment may evaluate the already completed latest candle. Repeated collector handoffs use the same durable claim and cannot count that candle twice.

The existing market worker waits 30 seconds after each complete scan. The paper consumer rotates at most eight model slots per market handoff within a ten-second budget across all laboratories. Thus 30 seconds is a collector polling interval plus scan duration, not a promise of every model running every 30 seconds. Rotation needed approximately two collector passes for some initial model/market pairs. Under overload or invalid/stale input a bar may be missed; it must remain missing coverage, not an invented evaluation.

## Shared evaluator and source preservation

All **21 exact historical requests** were re-run through the unchanged frozen shared evaluator. Train, validation and final-test statistics matched their preserved originals exactly for every case. Original canonical outcomes remain 18 COMPLETE and three FAILED; their separately preserved successful recoveries supplied comparison evidence. This validation was not a new hypothesis search and did not overwrite the original queue or results. No candidate was certified profitable.

Original raw source and manifest hashes for every candidate are preserved in the source inventory (normalized registered-source hashes are separate from Windows line-ending hashes). The original six Trend Reclaim net targets 2/3/4/5/7/9 and horizons 6/8/12/18/24/36 hours remain unchanged. Range Sweep retains its opposite-range target, 9 gross R cap, minimum 2 net planned R, and 12-hour horizon. The existing common conservative tick rounding and entry-quality gates still apply.

## MT5 input sufficiency

All 21 read-only genuine-cache executable probes completed successfully. Every probe received 300 completed M15 bars, 160 H1 bars and 120 cached M1 bars, current actual bid/ask, spread, tick size and instrument metadata. Quote ages at probe were inside the existing 30-second gate. No extra MT5 connection was created and timestamps were never refreshed artificially.

Final existing-collector diagnostics show 1,199 completed M15 bars and 599 H1 bars on each supported market, exceeding the actual implementation minimums of 80 M15 and 64 H1. The current M1 handoff contains 119 completed bars after excluding its forming minute; the read-only cache can supply 120. M1 is optional outcome refinement, not an entry feature in these seven models.

Therefore **current data is sufficient for their entry evaluation** on EURUSD, XAUUSD and BTCUSD. It does not guarantee complete future path resolution: missing minute coverage, gaps, conflicting bars or ambiguous TP/SL ordering remain unresolved. Longer 24/36-hour BTC variants rely on continuing capture and the existing bounded history recovery; they are not resolved immediately from the short recent M1 window. No outcome or stale-input requirement was weakened.

## Duplicates, overlap and independent forward accounting

Existing durable run and economic signal identity constraints prevent repeated same-bar signals. Scoped SQLite guards were added only for these seven identities, inside the experimental database, so the running consumer gains overlap/instrument protection without loading other sessions’ pending engine changes. Same-model/version/instrument opportunities cannot overlap: known latest exits release the reservation, while missing/ambiguous outcomes reserve the original deadline, as in the shared historical evaluator. Rejected overlaps are separately recorded and excluded from confirmed signals. These rules do not change model exits.

Each forward cohort records its own enrollment time, source hash and instrument scope. `forward_performance.json` uses only genuine post-enrollment records, latest outcome revisions, and chronological overlap exclusion; it also recomputes exclusions after late ambiguity revisions. Different target variants are tracked separately and are never pooled into a claim of independent portfolio performance. Historical and forward results remain in distinct stores/files. Existing dashboard summaries were not altered.

Priority BTC Trend Reclaim variants and Range Sweep on EURUSD/BTCUSD all have actual COMPLETE executions. Their research priority did not alter their rules or grant any approval.

## Safety and verification

- All seven: EXPERIMENTAL, scan_enabled=1, alert_enabled=0.
- Global experimental Telegram remains DRY_RUN, outbound approval false. No new approval or external message was created.
- Broker execution remains disabled. Existing production strategy identities, alerts, reports, outcomes and Strategy Bank permissions match the recorded baseline; existing laboratory registrations are unchanged.
- The engine retains its original uptime start, 19 October 2026 21:44:24 UTC. It continues independently of this research session.
- Regression suite: 652 tests passed. The final focused admission suite: six tests passed, including duplicate/overlap admission, unknown/revised outcomes, unsupported symbols, immutable registration and per-model separation.
- Sandbox temporary-file restrictions interrupted an initial validation/test attempt; the bounded tasks were retried successfully with functioning local permissions. No live registration occurred until historical/probe/admission checks passed.

## Evidence and continuation

`README.md` explains the scoped guards and read-only forward refresh command. `shared_evaluator_validation.json`, `genuine_provider_probes.json`, `preserved_sources.json`, `admission.json`, `post_admission_health.json`, `forward_performance.json`, and test logs preserve the evidence. The consistent pre-admission SQLite backup is private and Git-ignored. Original model files and historical records remain in place.

The scanner independently persists outcomes and forward records. To refresh the full independent cohort report without changing models or delivery permissions:

```powershell
python -m quant_labs.paper_integration.manage forward
```

No additional research or deployment approval is implied by registration.
