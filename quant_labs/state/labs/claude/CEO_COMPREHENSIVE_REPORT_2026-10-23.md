# TradeDen Quant Labs — comprehensive CEO report

**Date:** 2026-10-23 · **Author:** Claude Code (claude-opus-5-5) · **Scope:** the final CEO directive, Phases 1–5

## Executive summary

* TradeDen is now a **working research and signal-intelligence platform**:
  * 17 strategies are monitored live in paper mode;
  * Telegram delivery is approved for exactly two experimental paper candidates;
  * every signal has a durable lifecycle, with outcomes after estimated costs;
  * a unified leaderboard, a daily and weekly research report, explainable gold and bitcoin intelligence, engine health monitoring and a tested watchdog are in place.
* **Operational success is not trading profitability.**
  * About 30 hypotheses from Claude, plus every Codex and Kimi family, were tested on the frozen evaluator with realistic costs.
  * **None has a statistically supported edge.** The audit's Category A (promising) is empty.
  * The one consistent positive theme is **momentum held to a time exit**: crypto trend (two independent implementations, combined +0.27R over 150 trades, p = 0.16) and the index trend day (+0.15R over 225 trades). Both are consistent, and both are unproven.
* The historical data is exhausted as independent evidence. The fastest route to one genuinely validated edge is the **untouched pre-sample holdout** (2022 → Aug 2024) unlocked by the MT5 maintenance window, followed by forward paper results.

## Status classification

| Category | Strategies |
|---|---|
| Independently verified profitable | **none** |
| Production | **none** |
| Forward-tested | **none yet.** Paper monitoring has run for under 4 days; no qualifying signal has fired. |
| Paper candidates (Telegram on) | Index Trend-Day 0.2.0, Crypto Trend Breakout 0.3.0 |
| Category B, inconclusive (internal paper) | + Codex BTCUSD Trend Reclaim R4 (trending-regime effect tracked), Index Turn-of-Month |
| Category C, underperforming | Range Sweep Reversion, Hourly Shock Drift, Kimi London Sweep Reversal, Vol Exhaustion Fade, Opening Range Drive |
| Category D, rejected (preserved) | Trend Reclaim EURUSD/XAUUSD cells (significantly negative), Compression Escape, Index Gap Fade, First-Candle Drive, plus Claude's rejected phase-2 and phase-3 models |

## Phase results

| Phase | Completed | Verified | Report |
|---|---|---|---|
| 1. Operations | Engine verified; delivery scope confirmed; zero-detection audit (80/80 replays agree with live; zero signals expected in Asian hours, P≈91%); pre-push security review | 300+ tests | `PHASE_1_OPERATIONAL_VERIFICATION.md` |
| 2. Gold & Bitcoin intelligence | Rule-based, explainable structure, levels, sessions, regime and scenarios; unavailable data marked, never estimated; API, dashboard and internal previews | No look-ahead on genuine data; 2 real defects found and fixed | `PHASE_2_GOLD_BITCOIN_INTELLIGENCE.md` |
| 3. Strategy research | Pre-registered H4–H6 with always-long baselines | H5 (gold session drift) beat its baseline in train and **failed in validation**; H4 not adopted; H6 mis-specified, not amended | `PHASE_3_STRATEGY_RESEARCH.md` |
| 4. Forward validation | Live signals tagged REAL_TIME with entry regime; all Category B candidates monitored; leaderboard frequency and forward-by-regime | Tests pass | this report |
| 5. Reliability and plans | Health OK/DEGRADED/DOWN; conservative watchdog (tested, not installed); MT5 plan with untouched holdout | Tests pass; watchdog live diagnostic OK | `docs/ENGINE_RESILIENCE.md`, `docs/M1_MAINTENANCE_RUNBOOK.md` |

## Remaining limitations

* No real Telegram signal has passed through the full pipeline yet. It will at the first qualifying paper-candidate signal: about 2–3 a week if historical rates hold.
* Macro data (yields, calendar) and crypto-derivatives data (funding, open interest, liquidations) are unavailable.
* Overnight index trades can't be scored: no session calendar, historical swaps or dividend data.
* The research queue still loses jobs to OneDrive file locks, recoverable with the documented pattern. The runtime relocation tool is ready.
* Phase 4–5 code (regime tagging, health, frequency) is **inactive until the next engine restart**.

## Required CEO decisions

1. **Engine restart** to activate the Phase 4–5 code (engine only).
2. **The MT5 maintenance window**, at a weekend: it unlocks the untouched holdout and deeper M1.
3. **Install the watchdog** as a logon task (persistent config), and **set `TRADING_HUB_MT5_TERMINAL_PATH`**.
4. **Push:** the repository is public, and pushing publishes six or more commits, including Codex's and Kimi's.
5. Free official data sources: the Fed and BLS calendars, and exchange funding and open-interest APIs.
6. Keep research-only Telegram delivery **off**, as recommended.
7. Scheduled gold and bitcoin intelligence messages (currently internal previews only).
