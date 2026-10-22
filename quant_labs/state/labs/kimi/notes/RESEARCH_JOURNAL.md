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
