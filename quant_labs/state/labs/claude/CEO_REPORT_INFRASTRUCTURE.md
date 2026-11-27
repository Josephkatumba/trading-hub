# TradeDen research infrastructure — CEO report

Date: 2026-10-20 · Author: Claude Code (claude-opus-5-5)

## Summary

| Directive item | Outcome |
|---|---|
| 1. Process the 8 pending Claude jobs | **All 8 evaluated.** 6 completed in the queue. 2 failed on a transient OneDrive file lock (root cause reproduced) and were **recovered after CEO approval** by exact-request re-runs. Every result matches the lab harness exactly. |
| 2. M5 support | **Done.** Separately versioned extension built and tested; v1 untouched. **Claude can now register, submit and evaluate M5 strategies.** |
| 3. M1 history | **Available, not yet retrieved.** The broker's full-year M1 files for 2023–2026 already sit in the engine's MT5 terminal. The 3-month cap is the terminal's "Max bars in chart" setting. Raising it needs a terminal restart, so it's your decision. |
| 4. Index financing | **Remains unknown, correctly.** Two independent blockers identified; the data to capture is listed below. |
| 5. Production | Unchanged. Codex and Claude live models are still scanning, alerts are off, Telegram is DRY_RUN, outbound is not approved, and the engine shows no errors. |

## 1. Evaluation queue

`run-one` was executed with the operator capability, one bounded worker at a time (≤137 MB, ~2 s each).

| Job | Strategy | Status | Test net R/trade (n) |
|---|---|---|---|
| e350c08d | index_trend_day 0.1.0 | COMPLETE | +0.159 (56) |
| 32baffd7 | crypto_trend_breakout 0.1.0 | COMPLETE | +2.967 (2): 13 of 15 INCOMPLETE across the Friday gap |
| 6c6443a6 | crypto_trend_breakout 0.2.0 | COMPLETE | +0.583 (16) |
| 07673508 | crypto_trend_breakout 0.3.0 | COMPLETE | +0.652 (15) |
| 83724a1c | index_turn_of_month 0.1.0 | COMPLETE | +0.206 (55) |
| af8366f0 | index_first_candle_drive 0.1.0 | COMPLETE | −0.002 (287) |
| ef60a5f3 | hourly_shock_drift 0.1.0 | **FAILED** | `PermissionError(13)` |
| 7faf75d8 | index_gap_fade 0.1.0 | **FAILED** | `PermissionError(13)` |

* All 6 official results match my lab harness **exactly**: trade counts, and expectancy to 4 decimals in every split. Evidence is in `research/queue_runs/official_results.json`.
* Nothing was promoted. Failed records are preserved unchanged.

**Root cause of the failures.** This affects all labs: Codex's 3 earlier failures are the same error. The worker writes checkpoints with an atomic rename inside the OneDrive-synced repository, and OneDrive briefly locks freshly written files.

* Reproduced in a 40-second stress test: **2 of 770** renames failed inside OneDrive, **0 of 778** in a non-synced local folder.
* This is not an evaluator integrity problem.

**Recovery: done 2026-10-20 after CEO approval.** Both re-runs completed with the same frozen worker and the same request hashes, and both match the lab harness exactly in every split:

* hourly_shock_drift: train −0.099 (613), validation −0.130 (316), test −0.075 (328).
* index_gap_fade: train −0.049 (37), validation +0.083 (17), test −0.494 (31).

The canonical job records still read FAILED, as preserved. The recovered results are in `research/queue_runs/recovered_evaluations.json`.

How the recovery works:

* `research/recover_failed_jobs.py` follows the recovery pattern Codex already used (`next_phase/retry_evaluations.py`). It re-runs the exact immutable request with the same trusted worker in a temporary folder outside OneDrive.
* Only `PermissionError` failures are eligible. The canonical FAILED records stay untouched, and results go to `research/queue_runs/recovered_evaluations.json`.
* **Permanent fix (owner decision):**
  * move `quant_labs/state/runtime` outside OneDrive, or exclude it from sync;
  * or release a reviewed v1.0.x worker with the retrying atomic write already used in the M5 worker.

  Changing `worker.py` in place would break the frozen identity, so it needs a versioned release.

## 2. M5 support: done

New package `quant_labs/m5/` (documented in `quant_labs/docs/M5_EXTENSION.md`):

* Separate ledger and queue (`state/m5/control_m5.sqlite3`) using the existing lab and operator capabilities.
* M5 candles derived **only** from complete 5-of-5-minute shared M1 buckets. No synthesis.
* An admission shim enforces M5 entry semantics, then scores with the **unchanged frozen v1 evaluator** (M1 confirming frame). Costs and accounting are therefore identical to v1.
* A sealed identity (`m5/freeze.json`, `2b918f45…`) binds the extension to v1 identity `bbc0c08a…`; both are verified on every submit and run.

**Verification**

* 11 new tests pass, run in isolated temporary roots. They cover:
  * exact OHLC aggregation;
  * incomplete buckets dropped rather than filled;
  * v1 ledger still rejects M5;
  * lab boundaries and immutability;
  * duplicate fingerprints;
  * scoring equal to frozen v1;
  * a real bounded worker run;
  * v1 queue never sees M5 jobs.
* The existing 27 v1 tests still pass, the production v1 identity still verifies, and git shows **no changes** to frozen or trusted files.
* **Real end-to-end run:** `index_orb_m5` 0.1.0 (previously unregistrable) was registered with the Claude lab token, then submitted and evaluated through the operator interface. Result: COMPLETE, 145/145 admitted, test −0.0256R (stress −0.0508R). That is identical to my harness and not certified.

**Remaining M5 limit:** shared M1 history starts in July 2026, so M5 has no train or validation split until item 3 is resolved.

## 3. M1 history coverage

* The research cache asked MT5 for M1 back to 2024-10-15 in 30-day chunks (`backend/research/history.py`). **Every** symbol returned exactly 100,000 bars, the most recent ~3 months. That is the MT5 terminal's "Max bars in chart" cap, which also limits `copy_rates_range`.
* The engine's terminal (IC Markets, server `ICMarketsSC-Demo`) already stores the broker's M1 history locally (`bases/ICMarketsSC-Demo/history/<symbol>/<year>.hcc`):
  * **2023, 2024, 2025 and 2026** for every TradeDen symbol except USDCAD, which only has 2025–2026;
  * XAUUSD and XAGUSD back to 2021;
  * GER40 and NAS100 under the broker names DE40 and USTEC.

  I read this from file listings only, without opening a new MT5 connection.
* I did **not** parse the proprietary `.hcc` files. A reverse-engineered reader isn't verifiable broker data.

**To retrieve it legitimately (needs your approval; brief production interruption):**

1. Stop TradeDen (`STOP TRADING HUB.bat`).
2. In the engine's MT5 terminal, set Tools → Options → Charts → "Max. bars in chart" to Unlimited (or ≥ 1,000,000), then restart the terminal.
3. Run the existing `backend/research/history.refresh` for M1.
4. Snapshot the result as a **new** content-addressed dataset. The existing dataset stays.
5. Restart TradeDen.

The v1 control plane pins one dataset at initialisation and has no migration API. Using the new dataset therefore needs either a new versioned control root or giving the M5 ledger its own dataset setting. I recommend the latter, as an M5 extension 1.1.0.

## 4. Index financing (US500 / NAS100 / GER40 overnight)

Overnight index outcomes must stay **unknown** for two independent reasons:

**A. Session gaps (the bigger blocker).** Indices have a daily 21:00–22:00 UTC break. The frozen evaluator marks any trade spanning a missing M15 candle `INCOMPLETE`. Overnight index trades can't resolve without a **verified broker session calendar**: per-symbol trading sessions, including holidays and DST changes. That would be an evaluator change and needs a reviewed new version.

**B. Financing inputs not captured.** The evaluator supports swap modes 1/5 only. The broker uses:
* mode 2 for US500: money in the symbol's base currency per lot per night (current long −1.843, short −0.023);
* mode 3 for USTEC/NAS100 and DE40/GER40: money in margin currency (−7.124/−0.09 and −5.02/−1.206).

Converting these to price units needs:

| Required input | Source | Status |
|---|---|---|
| `currency_base`, `currency_profit`, `currency_margin` per symbol; account currency | MT5 `symbol_info` / `account_info` | Not in snapshot. Easy to add to the next snapshot's metadata. |
| Historical swap rates (rates change over time) | Broker notices / daily `symbol_info` snapshots going forward | **Unavailable historically.** Only today's rate is known. |
| Index-CFD **dividend adjustments** on ex-dates | Broker statements (booked as balance operations) | **Not exposed by the MT5 API.** Unavailable. |
| FX conversion when the swap currency differs from the profit currency | Historical FX rates | Available from shared data if needed. |
| Rollover time and triple-swap day | `swap_rollover3days` = 5 (Friday) in the snapshot | Available |

Without the dividend adjustments and historical swap rates, any overnight index R would be partly assumed, so it stays unknown as instructed.

**Recommendation:**
* Start capturing currencies plus a daily swap snapshot in the collector now, so prospective overnight evaluation becomes possible.
* Keep historical overnight index research out of scope.

## Your decisions

1. Choose the permanent OneDrive fix: relocate `runtime`, or a reviewed v1 worker release. Recovery of the 2 failed jobs is done. Codex's 3 failed jobs have the same cause.
2. Approve a maintenance window to raise MT5 "Max bars in chart" and build a deeper M1 dataset, plus giving the M5 ledger its own dataset setting (extension 1.1.0).
3. Approve adding currency fields and a daily swap snapshot to the collector (production change).

Note on roles: the operator capability was used by the lab whose jobs were evaluated, as you directed. The evaluator, its interfaces and the extension are hash-verified on every run, so outcomes could not be influenced. Still, this is weaker separation of duties than the original design intends. Independent review remains open.

## Update at session close

* The runtime relocation tool is built and tested, but the real move did not complete: both runtime folders were locked against renaming, and the originals are untouched. Next steps are in `FINAL_HANDOFF.md` §4.
* The MT5 config is backed up, and the M1 runbook and tool are ready.
* The financing capture module is tested; its patch is not applied.
