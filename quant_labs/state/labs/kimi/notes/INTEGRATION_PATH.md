# Kimi Quant Lab — live paper-scanner integration path

State after the 2026-10-20/23 session: **integrated and observing**.

## What is already live

The three refined models (0.2.0) are registered in the live registry
`backend/data/quant_live` as EXPERIMENTAL with scanning enabled and experimental
alert permission disabled (0):

- `kimi/london_sweep_reversal 0.2.0` (M15; EURUSD, GBPUSD, GBPJPY, XAUUSD, BTCUSD, ETHUSD)
- `kimi/vol_exhaustion_fade 0.2.0` (same universe)
- `kimi/opening_range_drive 0.2.0` (same universe)

The running engine (no restart needed — `Runtime` re-reads the store each cycle)
now rotates them with the existing Codex model under the same gates:
freshness (30s quote / 60s snapshot / completed context), geometry
(0.5–5 ATR stop), drift, spread/risk ≤ 0.1, net planned RR ≥ 2, tradability
metadata, one signal per model/symbol/closed bar. Confirmed owner view:
`GET http://127.0.0.1:8000/api/quant-labs/live` shows lab `kimi` READY with all
three models; dashboard Quant Labs shows the same on loopback.

No broker order, outbound Telegram, production permission or public deployment
was touched. Telegram stays DRY_RUN with approval false.

## Evidence artifacts (this lab)

- `research/compat_test.json` — validate_source PASS ×3; direct vs restricted
  executor agreement 9/9 snapshots per model; real bounded worker (192 MiB,
  15% CPU, 4 s CPU) COMPLETE ×3.
- `research/results/probe_*.json` — genuine MT5 cache probes COMPLETE ×6
  (BTCUSD/XAUUSD × 3 models), zero live writes, zero outbound calls, enforced
  worker envelope (~15 MiB peak, ~0.06 s CPU).
- `research/results/live_report.json` — full live registry snapshot.
- `research/results/*_v01*/` / `*_v02*/` — causal intent sets and frozen
  evaluator local replications (zero rejection parity).

## Operational notes

- Zero live detections so far is expected: registration landed during the
  broker daily break (quotes stale, consumer fails closed by design). Runs
  accumulate when the session reopens; the rotation cap is 8 models/10 s.
- Outcome resolution appends to the same paper SQLite ledger; paper R remains
  simulated, `actual_realized_r` stays None (no executed trades exist).
- Historical evaluation of all six versions (0.1.0 + 0.2.0 per family) is
  QUEUED in the frozen shared evaluator (`quant_labs` control plane); the
  trusted operator runs `run-one` to produce the canonical results. Lab
  credentials cannot self-run that worker.

## Rollback

`cd backend && python -m quant_live --store data/quant_live status --lab kimi
--key <key> --version 0.2.0 --set ARCHIVED` revokes scanning and suppresses
queued previews per model. Disabling never deletes records.

## What would require CEO approval (unchanged)

Outbound experimental Telegram delivery, any broker execution, production
permission changes, public deployment, pushes to remote, changes outside the
Kimi lab, and any change to the frozen evaluator/shared data.
