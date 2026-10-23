# Pre-registration: overnight crypto hypotheses H7–H9 (2026-10-23, written before implementation)

## Context

* Overnight statistics (`research/audit/intel_studies.json`):
  * Gold London moves carry no directional information about New York.
  * Gold multi-day holds can't be scored because of the daily break.
  * BTC volatility clusters strongly, but post-shock direction is unpredictable.
* So the overnight budget goes to three distinct **crypto** mechanisms. ETHUSD is included as **independent replication**: a mechanism must work on both BTCUSD and ETHUSD, net of costs.

## Common protocol (fixed)

* **Evaluator:** frozen v1 via the Claude harness: realistic costs, stress, live gate emulated. H4 primary timeframe.
* **Holding period:** exit by min(72h, Friday 20:45 UTC); no entry with less than 24h before that broker gap.
* **Gate, one pass:**
  1. Train: net > 0, stress > 0, **better than the always-long baseline at the same decision times**, and positive on **both** BTCUSD and ETHUSD individually.
  2. Validation: the same.
  3. Test: reported once, labelled as previously exposed data.
* **Early rejection:** a failed train gate ends the hypothesis. No parameter changes.
* A survivor goes only to internal forward paper monitoring: no Telegram, no promotion.

## H7 — D1-trend H4 pullback continuation (`crypto_pullback_continuation` 0.1.0)

* **Mechanism:** within an established daily trend, pullbacks are absorbed by trend-following flows. Resumption after a pullback is a different entry from breakout chasing.
* **Rules:**
  * D1 trend UP (rule T1 on D1: close > EMA50, EMA20 > EMA50, EMA50 rising over 5 days);
  * within the last 6 H4 candles at least one closed below the H4 EMA20 (the pullback);
  * the latest H4 candle closes above the previous H4 candle's high (resumption) → **BUY**. DOWN trend mirrored → **SELL**.
* **Risk:**
  * Stop: lowest low of the last 6 H4 candles − 0.5 × ATR(H4, 14) (highest high + 0.5 ATR for sells).
  * Target: 2.5R.

## H8 — Volatility-regime transition breakout (`crypto_vol_transition` 0.1.0)

* **Mechanism:** volatility clusters, so a compressed regime precedes expansion. The first break of the compressed range marks the transition, and the expansion tends to persist.
* **Rules:**
  * ATR(H1, 24) is in the lowest 20% of its values over the prior 20 days (compression), measured at the decision;
  * the latest H4 candle closes beyond the high (BUY) or low (SELL) of the previous 18 H4 candles (3 days).
* **Risk:**
  * Stop: opposite side of that 3-day range, capped at 3 × ATR(H4, 14) from entry.
  * Target: 2.5R.

## H9 — Conditional mean reversion after an extreme 24h move (`crypto_extreme_reversion` 0.1.0)

* **Mechanism:** extreme short-horizon moves overshoot through forced or liquidity-driven flow, then partially revert once the flow is absorbed.
* **Rules:**
  * the move over the last 6 H4 candles (24h) is ≥ 3 × the average daily range of the prior 14 days;
  * the latest H4 candle closes **against** that move (first counter-close) → trade the reversal.
* **Risk:**
  * Stop: the 24h extreme + 0.25 × ATR(H4, 14).
  * Target: 2.0R.
* **Prior evidence disclosed:** BTC post-shock 4h direction showed no reversal tendency, so this is a weak prior.

## Baselines

The same decision times, risk and exit as the hypothesis, **always LONG**. A mechanism has to beat 2024–26 crypto drift, not just be positive.
