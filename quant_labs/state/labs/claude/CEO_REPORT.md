# Claude Quant Lab — CEO report, first development milestone

Date: 2026-10-20 · Author: Claude Code (claude-opus-5-5) · Workspace: `quant_labs/state/labs/claude/`

## Bottom line

* **Five genuinely different executable models were built** (8 registered versions in total, including failures).
* **Two are historically promising:** *Index Trend-Day Continuation* and *Crypto 20-Day Trend Breakout*. Both are positive after costs and cost stress in train, validation and test.
* **Three were rejected** on their training data and are kept as evidence.
* **None is forward-tested and none is independently verified profitable.** None reaches statistical significance after multiple-testing correction.
* Both promising models pass the live host's restricted-worker execution and the live `qualify()` gate, and both run on genuine MT5 collector data. **After CEO approval on 2026-10-20 they were admitted to live paper scanning** (EXPERIMENTAL, alerts off).

## Status classification (directive §15)

| Category | Models |
|---|---|
| Developed (executable, registered) | index_trend_day 0.1.0/0.2.0, crypto_trend_breakout 0.1.0/0.2.0/0.3.0, hourly_shock_drift 0.1.0, index_turn_of_month 0.1.0, index_gap_fade 0.1.0 |
| Historically promising | index_trend_day 0.2.0, crypto_trend_breakout 0.3.0 |
| Forward-tested | **none yet**. Prospective paper scanning of index_trend_day 0.2.0 and crypto_trend_breakout 0.3.0 began 2026-10-20 |
| Independently verified profitable | **none** |

## Models

| Model | Mechanism | Markets / TF | Planned RR | Verdict |
|---|---|---|---|---|
| **Index Trend-Day Continuation** | Intraday momentum. 2h after the cash open, if the index is ≥0.45 daily ATR from the open and in the outer quarter of the session range, it follows the move. Stop 0.30 daily ATR; flat 15 min before the cash close. | NAS100, US500, GER40 · M15 | 2.2 | **Promising** |
| **Crypto 20-Day Trend Breakout** | Time-series momentum. A fresh 20-day H4 closing breakout aligned with a sloping 50-day baseline. Stop 3 ATR; exits before the Friday broker maintenance gap (max 7 days). | BTCUSD, ETHUSD · H4 | 3.0 | **Promising (small sample)** |
| Hour-Adjusted Shock Drift | Follows H1 candles ≥2.5× the normal range for that hour of day | 6 FX/gold + crypto · H1 | 2.5 | Rejected (−0.10R, 1,257 trades, every market negative) |
| Index Turn-of-Month | Calendar anomaly: long intraday on the last weekday and first 3 weekdays of each month | 3 indices · M15 | 2.2 | Rejected at train (−0.02R); later splits positive. Prospective data only. |
| Index Opening-Gap Fade | Fades 0.5–2 ATR overnight gaps toward the prior close | 3 indices · M15 | ≥2 (variable) | Rejected (−0.19R) |

## Historical performance (frozen shared evaluator, realistic costs)

| | Train | Validation | Test | Pooled | Cost-stressed pooled |
|---|---|---|---|---|---|
| Index Trend-Day: net R/trade (n) | +0.159 (103) | +0.117 (66) | +0.159 (56) | **+0.147 (225)** | +0.134 |
| Crypto Breakout: net R/trade (n) | +0.205 (40) | +0.171 (14) | +0.652 (15) | **+0.295 (69)** | +0.263 |

| Pooled | Win rate | Profit factor | Max DD | Longest losing run | Realized win/loss | Trades/month | 95% CI (R/trade) |
|---|---|---|---|---|---|---|---|
| Index Trend-Day | 52.4% | 1.39 | 8.2R | 6 | 1.26 | 9.7 | −0.01 … +0.31 |
| Crypto Breakout | 47.8% | 1.73 | 6.9R | 8 | 1.89 | 3.0 | −0.10 … +0.68 |

**On the 60–70% win-rate aspiration:** neither model reaches it, and I did not force it. Planned RR is 2.2R and 3R, but most trades close at the time limit. Realized win/loss is 1.26 and 1.89, well below the planned RR, and I report it separately as the directive asks.

**Caveats.** Both confidence intervals include zero. The index model's best result depends on the decision time (judging the day at 60 or 90 minutes is flat or negative). The three indices are highly correlated. The crypto test split has only 15 trades. All historical splits were previously exposed to other research.

## Genuine-data compatibility and integration

* All sources pass the live `validate_source`. Direct execution and the live restricted host's `execute()` agreed on 36/36 historical decision snapshots.
* The live `qualify()` gate admitted 24/24 snapshots for the two promising models.
* `provider_bridge probe` on genuine MT5 collector data (NAS100, US500, GER40, BTCUSD, ETHUSD): status COMPLETE in the bounded worker, about 14 MB and under 0.1 s CPU, with zero live writes. No signals at probe time, which is expected.
* A dry-run admission to a throwaway live registry (scratchpad, not production) was accepted as EXPERIMENTAL, scan on, alerts off.
* All 8 versions are registered in the research ledger under `claude`, and 7 evaluation jobs are queued. The index 0.2.0 job was correctly deduplicated against 0.1.0. **The queue needs the owner's operator to run `run-one`; I did not use operator credentials.**

### Integration issues found (relevant to all labs)

1. **Live cache depth ≈ 200 bars per timeframe.** Crypto 0.2.0 needed 332 H4 bars and would never have fired live. Fixed in 0.3.0.
2. **The live gate rejects D1 context on Mondays** (the last D1 bar closed Friday, which is more than 48h old). About 20% of index signals would have been silently dropped. Fixed in my lab with index 0.2.0 (H4-derived daily ATR). A shared fix (session-aware staleness) is **recommended for owner review and not applied**.
3. **Crypto has a weekly maintenance gap every Friday 21:00/22:00 UTC.** The evaluator marks straddling trades INCOMPLETE. Fixed in crypto 0.2.0+.

## Not done (approval boundaries respected)

* No Telegram activation, broker orders, engine restart, push or public deployment.
* No shared infrastructure, evaluator, Codex or Kimi file was modified.
* Live paper-scanning admission was executed **only after explicit CEO approval** (2026-10-20). Registered in `backend/data/quant_live` as EXPERIMENTAL with scan on and alert off. The running engine picked both up without a restart: Claude lab READY, Telegram DRY_RUN, outbound not approved, scan cycle running with no errors.

## Recommended next actions

1. ~~CEO decision: admit to live paper scanning~~ **Done 2026-10-20.** Commands used, run from `backend/`:
   ```
   python -m quant_live --store data/quant_live register --manifest ../quant_labs/state/labs/claude/strategies/index_trend_day/manifest.json --source ../quant_labs/state/labs/claude/strategies/index_trend_day/model.py --session-reference "Claude Code (claude-opus-5-5) desktop session 14e835e0-e7e8-43cf-b286-855a18365bd7, 2026-10-20"
   python -m quant_live --store data/quant_live register --manifest ../quant_labs/state/labs/claude/strategies/crypto_trend_breakout/manifest.json --source ../quant_labs/state/labs/claude/strategies/crypto_trend_breakout/model.py --session-reference "Claude Code (claude-opus-5-5) desktop session 14e835e0-e7e8-43cf-b286-855a18365bd7, 2026-10-20"
   ```
2. Owner/operator: run the queued Claude jobs through `run-one` to produce the official ledger results.
3. Owner review of the Monday D1-staleness behaviour in `backend/quant_live/runtime.py`. It affects every lab's D1-dependent model.
4. Collect at least 3 months of prospective paper outcomes before any qualification claim. The index model generates about 10 signals per month and crypto about 3.

Evidence: `notes/RESEARCH_JOURNAL.md`, `research/results/` (all per-version JSON, intents and sensitivity runs), `research/probes/`, source under `strategies/` (prior versions preserved in `v0.x.0/` subfolders).
