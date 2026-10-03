# ROADMAP — TradeDen (trading-hub)

Statuses: **DONE** (in the working tree and tested), **IN REVIEW**, **NEXT**, **PLANNED**
(agreed direction, not started), **OPEN QUESTION**. History is in `PROJECT_LOG.md`.

## Current product state

| Area | Status | Notes |
|---|---|---|
| MT5 market engine (local-only, port 8000, autonomous 30 s scans) | DONE | Verified broker time basis |
| Strategy registry, per-strategy persistence / lifecycle / outcomes | DONE | Scoped by `strategy_id` |
| Trendline `trendline-first-v5.1` | IN REVIEW | Break + rejected retest |
| Support & Resistance `sr-levels-v2` | IN REVIEW | Candle confirmation at the level |
| Trend / Momentum `tm-pullback-v2` | DONE | Unchanged in Phase 1 |
| SMC `smc-confluence-v1` | IN REVIEW | LIVE in TradeDen; signals only |
| Garden UI, Analyst, Strategy Lab, evaluation layer | DONE | Labels for SMC families added |
| 16-instrument universe for every strategy | DONE | 10 official + 6 extras |
| Company HQ bridge (read-only: health, performance, records) | DONE | Lives in Company HQ |

## Next stages

1. **Commit hygiene — NEXT.** Split the uncommitted tree into scoped commits:
   - Phase 11 / T/M v2;
   - the Trendline v5 replacement and S/R level episodes;
   - the Garden command centre;
   - Strategy Upgrade Phase 1.

   Keep `backend/data/` out. Run the full test suite once before the commits.
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

## Company HQ Trading Floor — SMC desk (PLANNED, not implemented)

A future Company HQ Trading Floor desk that consumes TradeDen SMC setups. **Not implemented**:
today SMC setups are TradeDen signals only, `strategy_evidence.scope` is `TRADEDEN_SIGNAL_ONLY`,
and nothing in TradeDen or the HQ bridge routes them to paper or real execution. Preconditions
before any work starts:

- an explicit CEO decision to connect SMC;
- a sufficient verified live SMC sample in Strategy Lab;
- Risk Desk rules defined for the desk;
- implementation in Company HQ (not TradeDen), reading TradeDen's API, with paper execution only.

## Not planned
- TradeDen placing trades (execution stays outside TradeDen).
- Tuning strategy parameters to historical replay results.
