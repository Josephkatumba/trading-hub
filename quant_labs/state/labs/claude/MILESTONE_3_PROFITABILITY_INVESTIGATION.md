# Milestone 3 — Profitability investigation (CEO report, 2026-10-23)

## 1. Crypto momentum, treated as one theme

* My Crypto Trend Breakout 0.3.0 and Codex's BTCUSD Trend Reclaim R4 are **largely independent evidence**:
  * about 31% of either strategy's BTCUSD trades overlap a same-direction trade of the other;
  * they traded in the same week 14 times out of 54;
  * weekly net-R correlation is 0.22.
* **Combined: +0.272R over 150 trades, weekly-clustered two-sided p = 0.16.**
* It's the most consistent positive theme in Quant Labs: two independent implementations, positive in every split. It's still **not statistically established**.
* Status: Category B. Both strategies are in live paper monitoring. Crypto Trend Breakout has Telegram enabled; Codex R4 is internal only.
* Evidence: `research/audit/crypto_momentum.json`.

## 2. Kimi failure-inverse hypotheses: pre-registered, all rejected

The specification was committed before implementation (`674ab1e`) and evaluated once on the train split, as registered.

| Hypothesis | Train net R (n) | Stress | Outcome |
|---|---|---|---|
| London sweep **continuation** | −0.046 (115) | −0.129 | Rejected at train |
| Volatility climax **acceleration** in trend | −0.181 (406) | −0.248 | Rejected at train |
| **Failed** London ORB reversal | −0.095 (428) | −0.131 | Rejected at train |

**Interpretation:** each of Kimi's patterns now loses in **both** directions:
* sweep fade and sweep continuation;
* climax fade and climax acceleration;
* ORB drive and ORB failure.

These M15 session and volatility patterns carry no tradeable direction after costs; they are not edges pointing the wrong way. This matches the earlier finding that tight-stop M15 pattern entries lose to noise plus spread and commission. Per the protocol, validation and test were **not** run. The three models are registered in the research ledger for trial accounting and not admitted to live.

## 3. Range Sweep Reversion: regime diagnostic

* No stable conditional edge.
* BTCUSD's test gains come from range-bound / mid-volatility (+0.48R, n=12), the same regime that lost in train (−0.07R) and validation (−0.82R).
* EURUSD's test gains rest on 9 low-volatility trades plus 3 trending trades.
* The only consistent pattern is a **loss**: range-bound / high-volatility is negative in every split on BTCUSD and EURUSD.
* A "Range Sweep excluding high volatility" variant could be tested **prospectively only**, because it was derived from exposed data.
* Status: Category C. Evidence: `research/audit/range_sweep_regimes.json`.

## Overall conclusion

* No strategy has demonstrated a statistically supported edge after realistic costs.
* The research narrows where to look:
  * **multi-hour to multi-day drift** captured with wide stops and time exits (index trend days, crypto momentum) is the only family that has stayed positive;
  * **M15 pattern entries with tight stops** have now failed across about 25 independent hypotheses from three labs.
* Further historical mining of the same exposed 2024–26 data has diminishing honest value. The best next evidence is **prospective**: the live paper signals now accumulating, and the extended M1 history from the pending maintenance window.

## Tested

* All evaluations used the frozen shared evaluator with realistic and stressed costs.
* The pre-registration commit predates the implementation.
* Nothing was tuned on the test split.

## Requires your approval

* Pushing commits `7afd025` and `674ab1e`, plus the Milestone 2–3 commit to follow.
* The M1 maintenance window, which is the main lever for genuinely new historical evidence.

## Next

* **Milestone 4:** keep the B-category candidates in live paper monitoring, already active. Add Codex BTCUSD R4 as the single representative of its family in reporting.
* **Milestone 5:** unified Quant Labs leaderboard (historical / validation / test / forward, separated) and the 23:00 EAT daily / Friday weekly Telegram research report.
