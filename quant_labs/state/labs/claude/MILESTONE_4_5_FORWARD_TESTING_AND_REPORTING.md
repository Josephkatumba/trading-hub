# Milestones 4–5 — Forward testing, leaderboard and research reports (CEO report, 2026-10-23)

## Completed

**Milestone 4: forward testing.** All four Category B candidates are in live paper monitoring:

| Strategy | Monitoring | Telegram |
|---|---|---|
| Claude Index Trend-Day 0.2.0 | live paper | **on** (approved) |
| Claude Crypto Trend Breakout 0.3.0 | live paper | **on** (approved) |
| Codex Trend Reclaim R4 (BTCUSD family representative) | live paper | off |
| Claude Index Turn-of-Month 0.1.0 (registered today; source hash matches research) | live paper | off |

* All 16 models keep scanning, including categories C and D, so forward evidence also accrues for the rejected ones. Nothing was deleted or demoted.
* **Scanner fix:** models received one closed candle fewer than they declared (e.g. 119 of 120), because the forming candle is fetched and correctly discarded. The fetch plan now requests one extra candle. This changes no strategy rule; no model needed the missing candle.

**Milestone 5: unified leaderboard.** It's part of the existing Quant Labs dashboard view and the `/api/quant-labs/live` payload. Each strategy row shows:
* researcher, name, version, instruments and timeframe;
* A/B/C/D category and status, and Telegram on/off;
* **historical train / validation / test** expectancy with n, plus test stress and per-instrument test results;
* **forward** signals, resolved, win rate, average R, net R, drawdown and estimated costs;
* last successful evaluation.

Historical and forward results are never pooled. A ⚠ small-sample flag appears under 30 trades. Correlated variants (Trend Reclaim R2–R9) are marked as one family. Example: R4 test is BTCUSD +0.33R, EURUSD −0.82R, XAUUSD −0.81R.

**Milestone 5: daily and weekly Telegram research report.** A "QUANT LABS (experimental research · separate from production)" section is added to the **existing** 23:00 EAT daily and Friday 23:00 EAT weekly reports: same scheduler, same delivery ledger, no new bot. It reports:
* active strategies;
* evaluations completed;
* setups detected;
* confirmed paper signals and quality-gate rejections;
* resolved outcomes (TP / SL / time exit) and net R;
* all-time forward expectancy;
* best and worst strategy;
* scanner errors, stale input and missing data;
* Telegram delivery states.

It reports **zero** when nothing happened.

## Tested

* New: `tests/test_quant_labs_reporting.py` (5 tests), covering:
  * historical and forward kept separate;
  * zero reported without fabrication;
  * window counts;
  * the section present in both daily and weekly reports;
  * the unavailable-store message;
  * the fetch-plan fix.
* Frontend: 185 tests pass, including the new leaderboard test for separation, the small-sample flag, escaping and the approved/dry-run notice.
* Regression: reports, Telegram notifier, Strategy Bank, financing, provider bridge, Codex paper integration, quant_live and delivery suites all pass.
* The leaderboard and report section were built against the **real live store**. Today's section reads 16 active strategies, 501 evaluations, 0 setups, 0 signals and 0 scanner errors.

## Operational now / blocked

* **Running now:** the engine and Milestone 1 delivery code, and monitoring of all four B candidates. Turn-of-Month is picked up live from the registry.
* **Blocked: needs an engine restart.** The leaderboard, the report section and the fetch-plan fix live in engine code, so they take effect only after a restart. Tonight's 23:00 EAT report includes the Quant Labs section only if the engine restarts before then.
* **Still unverified:** live delivery of a real signal. No qualifying paper-candidate signal has occurred yet.

## Requires your approval

1. **Engine restart** to activate Milestone 4–5 code (engine only; the dashboard stays up).
2. Pushing commits `7afd025`, `674ab1e`, `6d97c60` and the Milestone 4–5 commit (local only).
3. The pending research-only Telegram request (recommended: decline).
4. The M1 maintenance window (deeper history).
