# M5 research extension (`tradeden-m5-extension-1.0.0`)

A separately versioned path for M5 strategies. The frozen v1 evaluator
(`quant_labs/evaluation/v1/`) and its trusted interfaces (`control.py`, `data.py`,
`queue.py`, `worker.py`, `resources.py`) are unchanged and still verify.

## How it works

* **Data.** M5 candles are derived from the frozen shared M1 snapshot. A candle exists only when all five M1 minutes of its bucket exist. Incomplete buckets stay gaps, and no price is ever synthesised (`quant_labs/m5/data.py`).
* **Admission.** An intent must enter at an exact 5-minute boundary that is the close of a complete derived M5 candle. Otherwise it is rejected as `invalid_m5_boundary` or `m5_confirming_bar_unavailable` (`quant_labs/m5/engine.py`).
* **Scoring.** Admitted intents go to the **unchanged frozen v1 evaluator** with its M1 confirming frame. Fills, costs, stress, financing, gaps, splits, purges, locks and metrics are therefore identical to v1 by construction; a test asserts equality.
* **Ledger.** A separate SQLite ledger lives at `state/m5/control_m5.sqlite3`, with the same immutability triggers. v1 workers never see M5 jobs.
  * Capabilities are the existing lab and operator tokens, checked against the main control plane.
  * Exports go to `m5_registry.jsonl`, `m5_experiments.jsonl` and `m5_performance.jsonl` in each lab workspace.
* **Identity.** `quant_labs/m5/freeze.json` seals the extension's files and the v1 evaluator identity it wraps. Every submission and worker run verifies both.
* **Worker.** It has the same Windows Job Object limits as v1. Its atomic checkpoint write retries on the transient `PermissionError` that OneDrive causes (see below).

## Commands (repository root, PowerShell)

```powershell
$env:TRADEDEN_LAB_TOKEN = [System.IO.File]::ReadAllText('quant_labs/state/labs/<lab>/.lab-token').Trim()
python -m quant_labs.m5.cli register-live --lab <lab> --manifest <own-m5-manifest.json> --source <own-model.py>
python -m quant_labs.m5.cli submit <lab> <key> <version> <intents.json>
python -m quant_labs.m5.cli status
# owner/operator only:
python -m quant_labs.m5.cli --token-env TRADEDEN_OPERATOR_TOKEN run-one
python -m unittest quant_labs.m5.tests
```

The live provider already supports M5. The collector fetches broker `TIMEFRAME_M5` whenever a registered model requires it.

## Limits

* Shared M1 history (and therefore M5) starts in **July 2026**: about 3 months, all inside the v1 "test" split. Train and validation are empty for M5 until deeper M1 history is snapshotted into a new dataset.
* Derived M5 spread is the maximum of its five M1 spreads. That is conservative, and it can differ from the broker's native M5 spread field used live.
* Lifecycle transitions (`transition`) remain v1-only. M5 results are research records, not certification.
