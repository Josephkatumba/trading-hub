# Telegram intelligence, signal coverage and Quant Labs optimisation (CEO report, 2026-10-23)

## What was built

| Category | What it sends | Status |
|---|---|---|
| **A · Qualified experimental signals** | Index Trend-Day and Crypto Trend Breakout only, as before. The message now also states the **market regime at entry**. Lifecycle tracking (TP / SL / time exit / final R) is unchanged. | **Live, approved** (no change to permissions) |
| **B · Research observations** | Real-time setups from the other 14 models, headed **"RESEARCH OBSERVATION: NOT A QUALIFIED TRADING SIGNAL"**: condition, directional hypothesis, historical evidence and its limitations, regime, timestamp. **No entry, stop or target.** | **Preview only.** Needs your approval and its own flag. An optional per-model scope is supported. |
| **C · Gold & Bitcoin briefings** | 08:00 EAT morning (gold and bitcoin) and 15:00 EAT New York (gold focus). Covers D1/H4/H1/M15 structure, regime, levels, Asian and London ranges, liquidity events, sessions (DST-aware), USD proxy, the BTC–NAS100 correlation, bullish/bearish/caution conditions, and **what the approved strategies are waiting for**, with the live breakout levels. | **Preview generation** enabled, from the next engine start. Outbound needs approval and a flag. |
| **Telegram Intelligence Center** (dashboard plus `/api/quant-labs/intelligence-center`) | The three categories, each with its approval, flag, mode, last delivery, failures, latest message, next briefing and skipped briefings; engine health; last market data; gold/BTC status; the approval commands | Built. Read-only by design: approvals are recorded through the owner CLI, never from a web page. |

## Quality and reliability

* **No duplicates:**
  * one record per observation and per briefing slot per day;
  * messages mid-send at a crash become DELIVERY_UNKNOWN and are never replayed;
  * one shared Telegram pace across all categories.
* **No stale or misleading content:**
  * a stale or closed market is **withheld**, never described;
  * a briefing with no current data is skipped and logged;
  * a slot missed by more than an hour (engine off) is logged `SKIPPED_LATE` and **never sent late**;
  * the New York briefing is skipped at weekends;
  * observations are recorded only within 15 minutes of a real-time detection, so nothing is replayed after downtime.
* **Nothing invented:** economic releases, yields, funding and open interest are stated as unavailable; there's no authoritative source.
* **A recovery bug was found and fixed:** a single incomplete signal record could abort restart recovery. It's now skipped and logged.
* Broker execution is still **disabled**.

## Previews (genuine records only)

`research/previews/TELEGRAM_CATEGORY_PREVIEWS.md` contains:
* **A** in the new format: a real historical Index Trend-Day signal (GER40, 23 Sep 2026), labelled historical.
* **B:** **no live research event exists yet**, so the examples are real historical frozen-evaluator signals (Compression Escape GER40, Shock Drift ETHUSD). Each was rebuilt from genuine MT5 data with the model's own source and is labelled **HISTORICAL RESEARCH RECORD, not a live detection**. Synthetic data is used only inside tests, labelled as such.
* **C:** morning and New York briefings generated from **live data**:
  * gold is DOWN on every timeframe, trending, high volatility, below its 20-day low;
  * bitcoin's D1 is UP while H4 is DOWN, flagged as caution;
  * Crypto Trend Breakout needs a BTC H4 close above 86,990.66 (baseline rising).

## Phase 3: signal coverage research

* **Coverage isn't the gap; evidence is.** Every instrument and session, including all four gold and all four bitcoin sessions, is already covered. The 16 strategies produced about **203 signals a month** historically, mostly from negative-expectancy models. The two approved strategies produce about 12.7 a month.
* **Duplicate detection:** the six Codex Trend Reclaim variants flag the same opportunities **73–95%** of the time, so they're effectively one strategy.
* **All of your special-focus hypotheses had already been tested:** gold London→NY continuation (rejected at validation against an always-long baseline); gold sweep reversal and continuation (both negative); gold trend pullbacks (significantly negative); BTC failed breakouts (inconclusive); BTC volatility expansion (negative); BTC weekend (underpowered).
  * **Bitcoin trend continuation** is the only consistently positive theme, and is already approved or monitored.
* I deliberately added no near-duplicate strategies. More *qualified* signals need new evidence: forward paper results and the untouched pre-2024 holdout from the MT5 maintenance window.

## Tests

* New: `tests/test_intel_notifications.py` (13 tests) covers:
  * category approval rules;
  * the observation label and no trade levels;
  * preview versus approved send-once across restart;
  * no replay of stale events;
  * per-model scope;
  * EAT slots;
  * stale, late and weekend skips;
  * duplicate prevention;
  * recovery robustness;
  * the Intelligence Center.
* Regression: 102 backend tests (reports, existing Telegram notifier, Strategy Bank and more), quant_live and delivery 35, frontend 187, quant_labs 44. All pass.
* An intermittent timing issue in an existing consumer test was traced to step ordering and fixed: 8 of 8 runs now pass.

## Decisions requiring your authorisation

1. **Engine restart** to activate this work: the regime line, Category B previews, briefing previews and the Intelligence Center.
2. **Category B outbound:** I recommend approving only a narrow scope (Trend Reclaim R4 as the family representative, Turn-of-Month, Range Sweep), about 1 observation a day, or keeping it preview-only. Unscoped, it would send about 6 a day, mostly from rejected models. See `approvals/PENDING_research_observations_request.json`.
3. **Category C outbound:** review the previews and schedule (`approvals/PENDING_intel_briefings_request.json`), then approve and set its flag.
4. Still open: the push (public repository), the MT5 maintenance window (untouched holdout), installing the watchdog, `TRADING_HUB_MT5_TERMINAL_PATH`, and free official calendar and crypto data sources.
