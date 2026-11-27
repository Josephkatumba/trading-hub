# Phase 3 — Strategy research (CEO report, 2026-10-23)

## Completed work

* **Engine restart verified** (approved):
  * MT5 connected, broker execution disabled;
  * reports and alerts running;
  * the intelligence API serves current gold and bitcoin analysis;
  * delivery is unchanged: two approved paper candidates only.
* **Pre-registered** three hypotheses before any implementation or data access (commit `862075e`). Each new hypothesis had to beat an **always-long baseline**, because gold and bitcoin rose strongly over 2024–26 and must not pass on market drift alone.

| Hypothesis | Result | Verdict |
|---|---|---|
| **H4** Regime conditioning: does a trending H1 regime at entry improve the momentum candidates? | **Crypto Trend Breakout:** no effect. **Index Trend-Day:** opposite in validation. **Codex BTCUSD Trend Reclaim R4:** trending entries better in every split (TRENDING +0.46 / +0.44 / +0.58R vs OTHER +0.02 / +0.00 / −0.08R). | **Not adopted.** R4 misses the pre-set minimum of 15 trades per cell, so the effect is tracked as a forward diagnostic, not a filter. |
| **H5** Gold session drift (London open → first NY hour momentum, held to 20:45 UTC) | Train +0.213R (n=49, stress +0.203, p=0.014) vs baseline +0.045R. **Validation +0.028R (n=19) vs baseline +0.044R.** | **Rejected at validation:** it no longer beats always-long gold. Test not run. |
| **H6** Bitcoin weekend momentum | The registered 2.0R target is below the live net-RR ≥ 2 gate after costs, leaving 2 trades. It also fires only about 3 weekends a year. | **Invalid as specified; not amended after the fact.** Recorded as a design error. |

## Research findings

1. **The gold session-drift result is a cautionary example.** It was strong in training, beating its baseline with p = 0.014, and faded to below the baseline in validation. Without the always-long baseline it would have looked like a "positive" strategy (+0.028R).
2. **The one consistent conditional pattern is Codex's BTCUSD Trend Reclaim in trending regimes.** It's consistent across all splits but small, and it adds to the crypto-momentum theme. Only forward observation can settle it, and R4 is already in live paper monitoring.
3. **Across Phases 2–3 and Milestones 1–3:** about 28 hypotheses tested by Claude, plus Codex's and Kimi's families. **No strategy has a statistically supported edge after costs.** The surviving theme (crypto and index momentum held to time exits) is consistent but unproven.

## Remaining limitations

* The historical dataset is exhausted as independent evidence: every split has been seen. Genuinely new evidence now comes only from forward paper monitoring, or from deeper M1 history after the maintenance window.
* Macro and crypto-derivatives inputs are unavailable without approved data sources.

## Required CEO decisions

1. Phases 4–5: forward-validation tracking (with the R4 regime diagnostic), engine resilience (§10) and the expanded MT5 maintenance plan (§11). No new strategy qualified for admission in Phase 3.
2. Still open: the push (public repository), free official macro/crypto data sources, and the M1 maintenance window.
