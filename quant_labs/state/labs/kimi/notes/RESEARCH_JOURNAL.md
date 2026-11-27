# Kimi Quant Lab — research journal

All experiments by the actual Kimi Code session of 2026-10-20 (host: katjo Windows
laptop), under the TradeDen CEO directive of 20 Oct 2026. Local research only;
official scoring comes from the frozen shared evaluator queue (operator-run).

## Dataset

Shared content-addressed snapshot `bf130602dca4f955f64160bc9b85f0bc4246195f9685afbde91d1856c2c62cd3`
(bid OHLC, price-unit spread, tick volume; M1/M15/H1/H4/D1). Policy splits:
train 2024-10-15..2025-10-01, validation 2025-10-01..2026-04-01, test 2026-04-01..2026-10-01.

Key constraint discovered: shared evaluator financing supports swap modes 1/5 only.
NAS100 (mode 3), US500 (mode 2), GER40 (mode 3) resolve to FINANCING_UNSUPPORTED
(unknown), so historical evaluation focuses on EURUSD, GBPUSD, GBPJPY, XAUUSD, BTCUSD, ETHUSD.

## Experiment log

| # | Date | Model/version | Change | Hypothesis class | Result (normal, pooled) | Verdict |
|---|---|---|---|---|---|---|
| 1 | 2026-10-20 | london_sweep_reversal 0.1.0 | initial | session liquidity sweep fade | train -0.10R/tr, val -0.10R/tr, test -0.61R/tr (142 intents) | REJECTED |
| 2 | 2026-10-20 | opening_range_drive 0.1.0 | initial | session OR breakout + volume | train -0.04R/tr, val -0.07R/tr, test -0.04R/tr (384 intents) | REJECTED |
| 3 | 2026-10-20 | vol_exhaustion_fade 0.1.0 | initial | volatility climax mean reversion | train +0.20R/tr but val -0.09R/tr, test -0.16R/tr (168 intents) | REJECTED (train-only optimism) |
| 4 | 2026-10-20 | london_sweep_reversal 0.2.0 | DST-aware London window; sweep 0.10 ATR; rejection wick; range cap 3.5 ATR | same family, execution alignment fix | train -0.16R/tr, val -0.36R/tr, test -0.43R/tr (48 intents) | REJECTED |
| 5 | 2026-10-20 | opening_range_drive 0.2.0 | DST-aware window; volume 1.8x; cap 2.5 ATR; body 0.4 ATR | same family, selectivity | train -0.05R/tr, val -0.12R/tr, test -0.13R/tr (164 intents) | REJECTED |
| 6 | 2026-10-20 | vol_exhaustion_fade 0.2.0 | ER cap 0.28; volume 1.6x; horizon 18h | same family, selectivity | train +0.32R/tr, val -0.04R/tr, test -0.35R/tr (113 intents) | REJECTED (train-only optimism) |

Verdict after two disciplined rounds per family: no family shows positive
cost-stressed expectancy out-of-sample. Per-symbol tables
(results/per_symbol_tables.json) show no symbol with consistent cross-period
positivity. This mirrors the Codex phase finding: weekly uncertainty is wide and
no candidate approaches a significant positive edge. No parameters were tuned on
test outcomes; 0.2.0 changes were a-priori motivated (session clock alignment,
selectivity). Registration and queue submission proceed for the canonical record;
live paper observation proceeds for forward evidence.

Refinement discipline: 0.2.0 parameters were chosen a priori (session clock
alignment; selectivity against noise) before inspecting 0.2.0 outcomes on any
period. Validation is used to accept/reject; test is reported once, not tuned.

## Canonical queue outcomes (operator run, 2026-10-23)

Five of six queued jobs COMPLETE; canonical test expectancy matches the local
replications above (lsr 0.1.0 -0.61, lsr 0.2.0 -0.43, vef 0.1.0 -0.16,
vef 0.2.0 -0.35, ord 0.1.0 -0.04 R/tr). `opening_range_drive 0.2.0`
(job `472ccf43…`) is FAILED as an operational failure, not a statistical
rejection; it stays FAILED in `experiments.jsonl` and needs an operator retry.

## Phase 2: failure analysis and screening round

`research/failure_analysis.py` (output `results/failure_analysis.json`,
`results/regime_by_period.json`) broke the six rejected versions down by
exit status, MFE/MAE, hour, weekday and H1 efficiency-ratio regime. Signs flip
between partitions in every bucket; no stable sub-regime survived.

Six new candidates (`strategies/candidates/*`, all 0.1.0, one declared trial
each) were then screened with `harness.py run --screen`: intents generated only
for train + validation, so the test period stays sealed (0 test intents).
The first screening pass capped generation at the validation boundary and
produced train-only figures; it was re-run on 2026-10-23 by a Claude Code
session at the owner's request to complete the screen. Train figures reproduced
exactly; no candidate source, manifest or parameter was changed.

| # | Candidate 0.1.0 | Class | Train expR normal / stress (n) | Val expR normal / stress (n) | Val PF | Verdict |
|---|---|---|---|---|---|---|
| 7 | asian_range_drive | inversion of lsr (continuation) | -0.31 / -0.39 (110) | -0.02 / -0.12 (51) | 0.97 | REJECTED |
| 8 | daily_extreme_reversion | prior-day failed auction | -0.23 / -0.30 (676) | -0.35 / -0.42 (367) | 0.62 | REJECTED |
| 9 | failed_or_reversion | inversion of ord (fade) | -0.08 / -0.16 (990) | -0.08 / -0.17 (520) | 0.89 | REJECTED |
| 10 | h1_momentum | H1 trend persistence | -0.06 / -0.11 (707) | -0.04 / -0.08 (388) | 0.94 | REJECTED |
| 11 | vol_expansion_continuation | inversion of vef (continuation) | -0.22 / -0.37 (838) | -0.21 / -0.39 (413) | 0.75 | REJECTED |
| 12 | xau_afternoon_drift | session time-of-day drift | -0.14 / -0.22 (1477) | -0.06 / -0.15 (762) | 0.91 | REJECTED |

n = resolved trades, pooled over EURUSD, GBPUSD, GBPJPY, XAUUSD, BTCUSD, ETHUSD.
`xau_afternoon_drift` has no symbol filter, so it was screened on all six
markets despite its name. `h1_momentum` had 21 `confirming_bar_unavailable`
evaluator rejections. Weekly sign-flip p-values are all ≥ 0.54.

Verdict: all six fail the train gate and validation under normal costs, and
are worse under stress. Inverting the three rejected families did not produce
an edge in the opposite direction, so their losses come from costs and noise,
not from a tradable signal with the wrong sign. None goes on to test or
registration. Results: `results/scr_<candidate>/summary.json`.

## Method notes

- Causal replay: model `detect(snapshot)` sees only completed bars (close <= signal
  time); entry reconstructed by the frozen evaluator at the next bar open with
  recorded spread, as in live.
- Locks/boundary purges replicate engine.evaluate exactly; local runs show zero
  rejections, i.e. the submitted intent sets are exactly the evaluated sets.
- Costs: frozen policy (0.25 spread adverse entry/TP/time, 0.5 spread on stop,
  symbol commission, swap modes 1/5; stress doubles).
- Compatibility: all sources pass validate_source; direct vs restricted-worker
  decisions agree 100% on 9 genuine snapshots each; real bounded worker COMPLETE.
