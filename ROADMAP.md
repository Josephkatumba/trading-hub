# ROADMAP — TradeDen (trading-hub)

Statuses: **DONE** (in the working tree and tested), **IN REVIEW**, **NEXT**, **PLANNED**
(agreed direction, not started), **OPEN QUESTION**. History is in `PROJECT_LOG.md`.

## Current product state

| Area | Status | Notes |
|---|---|---|
| MT5 market engine (local-only, port 8000, autonomous 30 s scans) | DONE | Verified broker time basis |
| Strategy registry, per-strategy persistence / lifecycle / outcomes | DONE | Scoped by `strategy_id` |
| Trendline `trendline-first-v5.1` | DONE | Break + rejected retest (committed 2026-10-03) |
| Support & Resistance `sr-levels-v2` | DONE | Candle confirmation at the level |
| Trend / Momentum `tm-pullback-v2` | DONE | Unchanged in Phase 1 |
| SMC `smc-confluence-v1` | DONE | LIVE in TradeDen; consumed by Company HQ desk P04 (paper only) |
| Garden UI, Analyst, Strategy Lab, evaluation layer | DONE | Labels for SMC families added |
| 16-instrument universe for every strategy | DONE | 10 official + 6 extras |
| Company HQ bridge (read-only: health, performance, records) | DONE | Lives in Company HQ |
| Company HQ Trading Floor V2 (16-symbol universe, P04 SMC desk) | DONE | Lives in Company HQ; paper only |

## Next stages

1. **Commit hygiene — DONE (2026-10-03).** The uncommitted tree was split into scoped commits and
   pushed to `main`. `backend/data/` is ignored.
2. **Live observation of Phase 1 — NEXT.** Let S/R v2, Trendline v5.1 and SMC accumulate verified
   live outcomes and compare them with the replay in Strategy Lab, per strategy and version. No
   parameter changes until there is a verified sample.
3. **Replay realism — PLANNED.** Add spread/commission assumptions per instrument to the replay
   tools (`stop_ab.py`, `tests/tools/strategy_upgrade_report.py`), reported separately from the
   cost-free detection comparison.
4. **S/R pattern review — OPEN QUESTION.** Whether a strong-bodied candle launched from the level
   should count as a fourth pattern. To be decided on reasoning, not on replay results.
5. **Trend / Momentum refinements — OPEN QUESTION.** EMA50 at the pullback bar for the hold check;
   trigger-candle proximity to the pullback extreme. Only if live evidence justifies it.
6. **SMC evidence in the Garden — PLANNED.** Show the structure break, FVG, order block, sweep and
   reaction candle from `strategy_evidence` on setup cards and in the Analyst.

## Company HQ Trading Floor — SMC desk P04 (IMPLEMENTED 2026-10-03, paper only)

Built in Company HQ on the CEO's explicit instruction (Trading Floor V2):
- P04 is a `prop_conservative` paper account with USD 10,000. It consumes only CONFIRMED,
  `strategy_valid` TradeDen `smc` observations through the existing read-only JSONL bridge.
- Every proposal goes through the Central Risk Desk and the paper executor. There is no live
  execution path.
- TradeDen remains the only SMC detector; nothing was reimplemented in HQ.
- Lifecycle evidence uses genuine historical SMC observations, produced by TradeDen's own
  recorder on real MT5 history (`backend/tests/tools/smc_hq_replay_fixture.py`).
- No live SMC trade is claimed yet.

Still open:
- A verified live SMC sample in Strategy Lab. Until there is one, P04's results are observation,
  not evidence of edge.
- `strategy_evidence.scope` on TradeDen SMC records still reads `TRADEDEN_SIGNAL_ONLY`, the
  Phase 1 label. Updating that metadata is a TradeDen change to schedule separately; HQ
  consumption is governed by the CEO decision, not by this field.

## Not planned
- TradeDen placing trades (execution stays outside TradeDen).
- Tuning strategy parameters to historical replay results.
