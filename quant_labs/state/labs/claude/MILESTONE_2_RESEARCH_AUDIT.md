# Milestone 2 — Research audit (CEO report, 2026-10-23)

## Milestone 1 closure (verified after restart)

* The engine restarted with your approval. Only the engine restarted; the dashboard stayed up. MT5 is connected, the scanner is READY and execution is disabled.
* The new delivery code is live: `telegram_mode` is `EXPERIMENTAL_APPROVED` and the approval is recorded. Alerts are on **only** for Index Trend-Day 0.2.0 and Crypto Trend Breakout 0.3.0, there are no production models, diagnostics are live, all 16 markets are flowing, and there are no errors.
* Signal state was preserved across the restart.
* **Live delivery of a real signal is not yet verified.** No qualifying signal has occurred since the restart.

## Completed

* Processed Kimi's 6 queued evaluation jobs: 5 completed, and 1 recovered from the OneDrive lock by exact-request re-run with Kimi's records untouched.
* Audited **every** evaluated strategy across all three labs: 87 instrument cells. Sources are official results, recoveries, Codex's retry file, and a frozen-evaluator replay of Compression Escape (never queued by Codex). Per cell and split, the audit reports:
  * net expectancy and stress expectancy;
  * bootstrap 95% CI and sign-flip p;
  * expectancy without the best trade, and the best trade's share of gains;
  * a Holm correction across all 87 cells;
  * entry overlap between variants.
* Evidence files: `research/audit/analyze.py`, `research/audit/evidence.json` and `research/audit/classification.json`.

## Findings

1. **Category A (promising) is empty.** No positive result survives multiple-testing correction, so nothing is promoted.
2. **The only statistically significant results are losses.** Trend Reclaim on EURUSD (R5, R7, R9: Holm p = 0.04) and on XAUUSD lose reliably. Trend-pullback reclaim in FX and gold is rejected.
3. **Codex's positive cells are one hypothesis, not seven.**
   * The BTCUSD Trend Reclaim variants share 54–94% of their entries; they differ only in target size.
   * Only R4 is positive in all three splits: +0.195 / +0.265 / +0.330R over 81 trades, and still +0.14R on test without its best trade.
   * R7's +0.817R and R9's +0.636R are negative or flat in training and depend on single trades: R9 falls to +0.06R without its best trade.
   * Do not select R7.
4. **Range Sweep Reversion is positive only in the test split.** EURUSD and BTCUSD lose in train and validation, the test gains halve without the best trade, and XAUUSD loses −1.01R per trade on test. Not stable.
5. **The one recurring positive theme is crypto time-series momentum.** My Crypto Trend Breakout and Codex's BTCUSD Trend Reclaim (R4) are independent implementations that are both positive across all splits. Neither is significant on its own.
6. **Kimi's three families fail out of sample.** Vol Exhaustion Fade is a textbook in-sample overfit: positive in training, negative after. London Sweep Reversal loses significantly in v0.1.0 (test p = 0.004). Opening Range Drive is flat before costs.

## Classification

| Category | Strategies |
|---|---|
| **A Promising** | none |
| **B Inconclusive** (continue paper) | Index Trend-Day 0.2.0 ✉️, Crypto Trend Breakout 0.3.0 ✉️, Codex BTCUSD Trend Reclaim (one hypothesis, prefer R4), Index Turn-of-Month (prospective only) |
| **C Underperforming** (investigate) | Range Sweep Reversion, Hourly Shock Drift, Kimi London Sweep Reversal, Kimi Vol Exhaustion Fade, Kimi Opening Range Drive |
| **D Rejected** (preserved, deprioritised) | Trend Reclaim EURUSD and XAUUSD cells, Compression Escape, Index Gap Fade, Index First-Candle Drive, my 8 phase-2 models |

✉️ = Telegram delivery enabled. Everything else is monitored internally only. Nothing was deleted or demoted in the live registry; all 15 models keep scanning.

## Requires your approval

* The research-only Telegram request is still pending. I now also recommend declining it for Compression Escape, which is in Category D.
* Pushing commit `7afd025`. The audit files will be committed with Milestone 3.

## Next (Milestone 3: profitability investigation)

1. **Crypto momentum, as one theme.** Test whether my breakout and Codex's BTCUSD reclaim capture the same moves: signal overlap and return correlation. Pool them only if they're independent. Collect prospective data.
2. **Failure mechanisms as new hypotheses.** Each one gets a single pre-registered specification, evaluated once, with no tuning on exposed test data:
   * London sweeps followed by **continuation** (inverting Kimi's reversal);
   * volatility climax followed by **acceleration**;
   * **failed** opening-range breakouts.
3. **Range Sweep Reversion regime check.** Look for whether a regime condition explains the test-only behaviour. Diagnostic only, no parameter selection.
