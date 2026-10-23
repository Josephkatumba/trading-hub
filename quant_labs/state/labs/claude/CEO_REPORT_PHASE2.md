# Claude Quant Lab — CEO report, phase 2: increasing trading opportunities

Date: 2026-10-20 · Author: Claude Code (claude-opus-5-5) · Workspace: `quant_labs/state/labs/claude/`

## Bottom line

* **I built and tested 9 new executable models** (8 genuinely different mechanisms plus 1 declared train-selected subset) on M15 and M5 across gold, FX, crypto and indices.
* **None shows credible positive expectancy.** Several would easily deliver the requested 3–10 signals per day, but they lose money after costs. Per the directive, I rejected them rather than admitting them.
* **No new model was admitted to live paper scanning.** The two live models (Index Trend-Day 0.2.0, Crypto Trend Breakout 0.3.0) are unchanged. They are still scanning with alerts off and Telegram in DRY_RUN.
* The credible portfolio is still about **0.55 qualified signals per weekday (~12/month)**. I did not reach the 3–10/day target without giving up signal quality, and I did not force it.

## What was tested (all costs and gates as in production)

Frequency is gate-qualified signals per weekday over 2024-10 → 2026-10. Net R/trade uses normal costs; the stress column doubles spreads and adverse fills.

| Model | Mechanism | Signals/weekday | Train | Validation | Test | Stress (train) | Verdict |
|---|---|---|---|---|---|---|---|
| Fair-Value-Gap Retest | Imbalance first-retest continuation, H1 trend | **6.7** | −0.082 (1,666) | −0.090 (812) | −0.102 (754) | −0.167 | Rejected: frequent but consistently unprofitable |
| 24h Channel Trend 0.1.0 | Fresh 24h breakout + H4 trend, wide stop | **28.9** (13.0 non-overlapping) | −0.057 (3,186) | −0.034 | −0.065 | −0.112 | Rejected: frequent but consistently unprofitable |
| 24h Channel Trend 0.2.0 | Same, gold+crypto only (**train-selected**) | 5.4 | +0.134 (673) | −0.029 (358) | −0.005 | +0.100 | Rejected at validation |
| Index Opening-Candle Drive | First 15-min cash candle direction, 6R or close | **2.2** | +0.186 (550), p=0.02 | +0.066 (284) | −0.002 (287) | +0.163 | Rejected: edge decays to zero out of sample |
| Index 5-min Opening Range (M5) | Canonical Zarattini-Aziz spec | 2.4 | — | — | −0.026 (145, Jul–Oct 2026 only) | −0.051 | Rejected (exploratory: M5 data only 3 months) |
| Session-Mean Reversion | 2.5σ stretch from day mean, range regime | 1.3 | −0.360 (327) | −0.051 | −0.256 | −0.475 | Rejected |
| London Momentum | FX/metal London-morning trend into the fix | 0.7 | −0.164 (186) | −0.291 | (+0.169) | −0.194 | Rejected at train |
| London Fix Reversal | Fade pre-fix price pressure | 0.6 | −0.107 (162) | −0.081 | −0.133 | −0.153 | Rejected |
| Prior-Day Acceptance | Break and held retest of PDH/PDL | 0.2 | +0.030 (56) | −0.258 | −0.426 | −0.034 | Rejected (negative after stress) |

Rejection decisions were made at the protocol step shown. Later-split numbers were generated afterwards for completeness and were not used to tune anything.

## What the evidence says

1. **Tight-stop M15 pattern entries lose to noise plus costs.** At M15, FX majors pay about 0.15 M15-ATR in commission per round trip. Planned 2.5R targets rarely get hit before structural stops.
2. **My only robust edge so far is held intraday drift, not pattern precision.** Index Trend-Day (live) wins mostly through time exits. Mechanisms that rely on precise M15 levels (gaps, retests, stretches, fixes) did not survive.
3. **More frequency came with worse expectancy in every case.** The two highest-frequency candidates (FVG retest at 6.7/day, channel at 13–29/day) were also the most consistently negative.

## Infrastructure limits that block honest higher-frequency research

| Limit | Effect | Proposed owner action (not applied) |
|---|---|---|
| M5 is not a supported research-ledger/evaluator timeframe, and shared M1 history starts in Jul 2026 | M5 models cannot be registered or validated; only about 3 months of exploratory data | Extend the collector's M1 history (or snapshot more M1) and add M5 to the evaluator in a reviewed release |
| M15 candles that touch both stop and target need M1 to resolve | Tight-stop M15 trades before Jul 2026 can come back AMBIGUOUS | Same: deeper M1 history |
| Evaluator financing supports only swap modes 1/5 | Multi-day index holds (US500/NAS100/GER40) are unscoreable, which blocks overnight-drift research | Reviewed financing support for modes 2/3 |
| 8 pending jobs per lab | 8 of 8 Claude slots now in use; the other phase-2 intents files are waiting in `research/results/` | Operator `run-one` to drain the queue |

## Status classification

| Category | Models |
|---|---|
| Developed (phase 2) | 9 versions above (8 registered; M5 rejected by ledger timeframe validation) |
| Historically promising (phase 2) | **none** |
| Live paper scanning | Index Trend-Day 0.2.0, Crypto Trend Breakout 0.3.0 (phase 1, unchanged) |
| Forward-tested / independently verified profitable | **none yet** |

## Recommended next actions

1. Keep the two live models running unchanged; review them after about 3 months of prospective data.
2. Owner: drain the queue with `run-one`, and consider the infrastructure items above. Deeper M1 history is the main enabler for credible M5/M15 research.
3. My next research directions, chosen for evidence rather than frequency:
   - multi-day H4 trend in gold/FX with the Friday exit, extending the crypto result;
   - an independent replication of the index trend-day effect at other decision anchors, as a new model; the live version stays untouched.

Even if these work, realistic frequency is likely 1–2 signals a day, not 3–10.

Evidence: `notes/RESEARCH_JOURNAL.md` (phase 2 section), `research/results/*_full.json` and intents, `research/bodies/` (model sources before helper inlining), `research/build_models.py`, `strategies/*/`.
