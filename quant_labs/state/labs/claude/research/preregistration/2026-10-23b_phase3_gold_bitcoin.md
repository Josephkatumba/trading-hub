# Pre-registration: Phase 3 gold & bitcoin hypotheses (2026-10-23)

Registered and committed **before** implementation or any data access for these hypotheses. Author: Claude Quant Lab.

## Common protocol (fixed)

* **Evaluator:** frozen shared evaluator v1 via the Claude harness: realistic costs, stress = doubled spreads and slippage, live gate emulated. Dataset `bf130602…`.
* **Gate, one pass, no parameter changes:**
  1. Train (2024-10-15 → 2025-10-01): net > 0, stress > 0, **and better than its baseline**.
  2. Validation (→ 2026-04-01): the same three conditions.
  3. Test (→ 2026-10-01): reported once and **labelled previously exposed data**. It is not used as an independent holdout, because the dataset has been mined by three labs.
* A survivor goes only to **forward paper monitoring**; no Telegram without CEO approval.
* Three hypotheses = three declared trials. The family results are also reported with a Holm adjustment.

## H4 — Regime conditioning of existing momentum candidates (diagnostic, no new model)

* **Prediction:** momentum trades entered while the H1 regime is TRENDING (rule R1 from `backend/market_intel/rules.py`: efficiency ratio over 24 closed H1 candles ≥ 0.35 at entry) have **higher** net expectancy than trades entered otherwise.
* **Strategies:** `crypto_trend_breakout` 0.3.0, Codex `trend_reclaim_r4` (BTCUSD job), `index_trend_day` 0.2.0. Their existing frozen-evaluator trades are used; nothing is re-run or re-tuned.
* **Adoption rule:** a filtered version is created only if TRENDING > non-TRENDING in **both** train and validation, with at least 15 trades in each cell. It would then go to forward monitoring only.

## H5 — Gold session drift (`gold_session_drift` 0.1.0)

* **Mechanism:** intraday momentum. A gold move established from the London open into the first New York hour persists into the US afternoon. This independently replicates the index trend-day mechanism; Claude's FX `london_momentum` test (13:00 London decision) lost, and gold was +0.04R there.
* **Decision:** at the close of the M15 candle **60 minutes after the New York 09:30 open** (DST-aware), XAUUSD only.
* **Condition:** move from the London 08:00 open price to that close ≥ 0.5 × daily ATR(14), where the daily ATR comes from H4 candles grouped into broker days. The close must also be in the outer 25% of the range since the London open.
* **Trade:** follow the move.
  * Stop: 0.35 × daily ATR.
  * Target: 2.2R.
  * Exit: 20:45 UTC (before the daily break) if neither level is hit.
* **Baseline B5:** the same days, decision time, stop, target and exit, **always LONG**, ignoring the condition.

## H6 — Bitcoin weekend momentum (`btc_weekend_momentum` 0.1.0)

* **Mechanism:** thinner weekend liquidity lets the prevailing weekly move extend; information carried from the trading week is absorbed slowly.
* **Decision:** at the close of the first H4 candle opening at or after Saturday 00:00 UTC (after the Friday broker gap), BTCUSD only.
* **Condition:** the move from the week's first H4 open (Monday) to the last close before the Friday gap is ≥ 1.0 × weekly ATR, where weekly ATR = mean of the previous 8 weekly ranges built from H4. The direction is the sign of that move.
* **Trade:** follow the direction.
  * Stop: 0.5 × weekly ATR.
  * Target: 2.0R.
  * Exit: Sunday 20:00 UTC.
* **Baseline B6:** every weekend, same timing and risk, **always LONG**.

## Disclosure

* All splits were previously exposed to Quant Labs research, so no result is an untouched holdout.
* Bitcoin and gold trended strongly over 2024–26. That's why each new hypothesis must beat its always-long baseline.
* H6 has roughly 100 weekends in total. It is low-powered by design, and a pass would be weak evidence.
