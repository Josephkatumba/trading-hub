# Pre-registration: failure-inverse hypotheses from Kimi's research (2026-10-23)

Registered **before** implementation or any data access, and committed to git before evaluation.
Author: Claude Quant Lab. Kimi's implementations and records are untouched; these are independent Claude implementations.

## Common protocol (fixed)

* **Instruments** (Kimi's universe): EURUSD, GBPUSD, GBPJPY, XAUUSD, BTCUSD, ETHUSD. M15 primary timeframe.
* **Evaluation:** frozen shared evaluator v1 through the Claude harness (realistic costs, live qualification gate emulated), dataset `bf130602…`.
* **Sequential gate, one pass each, no parameter changes at any step:**
  1. **Train** (2024-10-15 → 2025-10-01): reject unless net expectancy > 0 **and** stress expectancy > 0.
  2. **Validation** (→ 2026-04-01): run only if train passes; reject unless net > 0 and stress > 0.
  3. **Test** (→ 2026-10-01): run only if validation passes; reported as-is.
* **Disclosure:** all splits were previously exposed to other labs' research; none is an untouched holdout. Any survivor would still need prospective paper evidence. Three hypotheses = three declared trials.
* **Exits:** before broker data gaps (metals 20:45 UTC daily; FX/crypto Friday 20:45 UTC). One position per symbol, enforced by the evaluator lock.

## H1 — London sweep **continuation** (`london_sweep_continuation` 0.1.0)

* **Question:** Kimi faded Asian-range sweeps during London and lost (v0.1.0 test −0.614R, p = 0.004). Does the sweep instead predict continuation in the sweep direction?
* **Asian range:** M15 candles opening 00:00–05:45 UTC (at least 20 present); width ≤ 4 × ATR(M15, 14).
* **Trigger** (candle closing 07:15–10:00 UTC, first sweep of the day only): the candle's low < Asian low − 0.05 ATR **and** it closes back above the Asian low. That is Kimi's sweep; the mirror applies for highs.
* **Trade:** in the **sweep direction** (low swept → SELL, high swept → BUY).
  * Stop: beyond the trigger candle's opposite extreme + 0.15 ATR.
  * Target: 2.5R.
  * Time limit: 16:00 UTC or the next data gap.

## H2 — Volatility climax **acceleration** (`vol_climax_acceleration` 0.1.0)

* **Question:** Kimi faded volatility climaxes. In-sample it was positive (+0.20 / +0.32R); out of sample it was negative. Do climaxes in an established trend mark acceleration rather than exhaustion?
* **Climax candle:**
  * range ≥ 1.6 × ATR(M15, 14);
  * close in the outer 20% of its range;
  * close beyond the prior 20-candle high (BUY) or low (SELL).
* **Regime:** H1 efficiency ratio over 24 candles ≥ 0.35, and the climax direction equals the sign of that 24-candle H1 move.
* **Trade:** in the climax direction.
  * Stop: the climax candle midpoint.
  * Target: 2.5R.
  * Time limit: 8h or the next data gap.
* **Prior evidence disclosed:** Claude's `hourly_shock_drift` (H1 shock continuation, no trend filter) lost −0.10R. H2 differs in timeframe and trend conditioning but is a related mechanism. A negative result is the expected default.

## H3 — Failed London opening-range breakout (`failed_orb_reversal` 0.1.0)

* **Question:** Kimi traded London opening-range breakouts and was flat before costs. Are **failed** breakouts informative?
* **Opening range:** the four M15 candles from 08:00 London local time (DST-aware), all present.
* **Breakout:** within the next 12 candles, a candle closes beyond the range by ≥ 0.1 ATR(M15, 14).
* **Failure:** within the following 4 candles, a candle closes back inside the range. That close is the signal; first failure per day only.
* **Trade:** opposite to the breakout.
  * Stop: the breakout extreme + 0.15 ATR.
  * Target: 2.2R.
  * Time limit: 16:00 London or the next data gap.
