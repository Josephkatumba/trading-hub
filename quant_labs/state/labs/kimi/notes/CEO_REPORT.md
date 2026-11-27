# Kimi Quant Lab — CEO milestone report

**Date:** 23 October 2026 · Prepared by the actual Kimi Code session (host: katjo Windows laptop)
**Scope:** First development milestone of the Kimi Quant Lab under the TradeDen CEO directive of 20 Oct 2026.

## Executive summary

Three genuinely different executable strategy families were discovered,
implemented, backtested with realistic costs, versioned, registered in the Kimi
Quant Lab research ledger, submitted to the frozen shared evaluator queue,
verified against the live provider interface, and registered into TradeDen's
live paper scanner. **Honest headline: after two disciplined variants per
family, none demonstrates positive cost-stressed expectancy out-of-sample.**
All variants, including the negative results, are preserved and registered.
Live paper observation is running so forward evidence can accumulate.

## Milestone checklist

| # | Requirement | Status |
|---|---|---|
| 1 | ≥3 genuinely different executable models | DONE — 3 families × 2 versions = 6 registered versions |
| 2 | Historical backtesting + evaluation each | DONE — causal replay with frozen-evaluator parity (0 rejections = exact intent sets) |
| 3 | Registered strategy versions in Kimi Quant Lab | DONE — 6 versions in the shared research ledger |
| 4 | Provider-interface compatibility tests | DONE — restricted-language validation, executor agreement 9/9 snapshots per model, bounded worker COMPLETE |
| 5 | Genuine-market-data compatibility test | DONE — 6 probes COMPLETE on live MT5 cache, 0 live writes |
| 6 | Documented integration path to live paper scanner | DONE — models registered EXPERIMENTAL/scanning; `notes/INTEGRATION_PATH.md` |
| 7 | CEO report with actual results | THIS DOCUMENT |

## Strategy families (distinct mechanisms, not derived from Codex's work)

1. **London Sweep Reversal** — session-liquidity fade: sweep of the Asian range
   at the London open that closes back inside is faded to the opposite boundary.
2. **Volatility Exhaustion Fade** — volatility-behavior mean reversion: an M15
   climax (>1.6 ATR, elevated tick volume, extreme close, 20-bar break) faded to
   the recent mean, only in non-trending H1 regimes (ER filter).
3. **Opening Range Drive** — microstructure-confirmation breakout: a tight
   London opening range broken on ≥1.4–1.8x median tick volume with H1 agreement.

All produce structural SL, realistic TP, planned RR ≥ 2, and the exact
`detect(snapshot)` live contract.

## Pooled results (normal / stress, simulated net paper R per trade)

| Model/version | Intents | Train expR | Val expR | Test expR | Test win | Test PF | Verdict |
|---|---|---|---|---|---|---|---|
| london_sweep_reversal 0.1.0 | 142 | -0.10 / -0.19 | -0.10 / -0.19 | -0.61 / -0.72 | 15.2% | 0.34 | REJECTED |
| london_sweep_reversal 0.2.0 | 48 | -0.16 | -0.36 | -0.43 | 15.4% | 0.53 | REJECTED |
| opening_range_drive 0.1.0 | 384 | -0.04 / -0.08 | -0.07 / -0.13 | -0.04 / -0.11 | 34.1% | 0.94 | REJECTED |
| opening_range_drive 0.2.0 | 164 | -0.05 | -0.12 | -0.13 | 30.0% | 0.83 | REJECTED |
| vol_exhaustion_fade 0.1.0 | 168 | +0.20 / +0.11 | -0.09 / -0.17 | -0.16 / -0.25 | 19.5% | 0.82 | REJECTED |
| vol_exhaustion_fade 0.2.0 | 113 | +0.32 | -0.04 | -0.35 | 15.2% | 0.62 | REJECTED |

0.2.0 changes were a-priori motivated (DST-aware session clocks; selectivity
against noise) and chosen before inspecting any 0.2.0 outcome. Test was not
tuned. Per-symbol tables (`research/results/per_symbol_tables.json`) show no
symbol with consistent cross-period positivity; signs flip between partitions
(small samples, wide weekly uncertainty — the same pattern Codex's phase found).

Costs are the frozen shared policy: 0.25-spread adverse entry/TP/time fills,
0.5-spread stops, symbol commissions, swap modes 1/5; stress doubles adverse
costs and removes swap credits. Indices (NAS100/US500/GER40) cannot be
resolved by the shared evaluator (swap modes 2/3 → FINANCING_UNSUPPORTED), so
historical evaluation covered EURUSD, GBPUSD, GBPJPY, XAUUSD, BTCUSD, ETHUSD;
models remain index-capable for live observation.

## Canonical evaluation status

All six intent sets are QUEUED in the frozen shared evaluator
(jobs `449bbcf5…`, `1c980eb4…`, `7eb1bc4a…`, `46b9d7ec…`, `d2cec6e6…`,
`472ccf43…`). The trusted operator runs `run-one`; lab credentials cannot
self-run or self-certify. Local replications used the identical frozen engine
code and dataset pins, with zero rejected intents, so canonical results should
match the local figures above.

## Compatibility and live integration evidence

- `validate_source` PASS ×3; direct-vs-restricted executor agreement 9/9
  genuine historical snapshots per model; bounded worker COMPLETE ×3
  (~15 MiB peak vs 192 MiB limit, ~0.06 s CPU vs 4 s).
- Genuine-cache probes COMPLETE ×6 (BTCUSD/XAUUSD × 3 models), 0 live writes,
  0 outbound calls.
- Live registry: three 0.2.0 models EXPERIMENTAL, scan_enabled, alert disabled;
  engine dashboard shows `kimi` READY; rotation includes Kimi models with no
  restart. Zero live detections so far is expected (registration landed in the
  broker daily break; the consumer fails closed on stale quotes by design).

## Resources and boundaries

Sweeps ran bounded in the background (~35 s per full 6-symbol pass). No
production setting, Codex/Claude record, frozen evaluator file, credential, or
permission was modified. No push, no outbound Telegram, no broker action.
Local-only commits; remote push requires CEO approval.

## Next steps (within current authority)

1. Let paper observation accumulate forward evidence for the 0.2.0 models.
2. Investigate a fourth family (e.g., higher-timeframe failed-auction reversion)
   under the same discipline, since three mechanisms failed to transfer.
3. After the canonical queue run, record transitions in the research ledger and
   re-express the pooled multiple-testing picture with the updated family size.

**Bottom line:** the lab is operational end-to-end — models are real,
executable, integrated and observable — but there is no verified edge yet, and
this report does not claim one. Success metric remains independently validated
positive expectancy; that bar is not met by any Kimi candidate to date.
