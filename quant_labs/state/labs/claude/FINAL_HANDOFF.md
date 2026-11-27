# Claude Quant Lab — final handoff

Session: Claude Code (claude-opus-5-5), desktop session `14e835e0-e7e8-43cf-b286-855a18365bd7`, 2026-10-20.
Nothing is committed to git. Nothing was pushed or deployed. Telegram stays DRY_RUN and no broker execution exists.

## 1. Models and their status

| Status | Models |
|---|---|
| **Live paper scanning** (EXPERIMENTAL, scan on, alerts off; CEO-approved) | `index_trend_day` 0.2.0, `crypto_trend_breakout` 0.3.0. **Unchanged; forward tests valid.** |
| Historically promising, not forward-tested | the same two models (pooled +0.147R / 225 trades and +0.295R / 69 trades; neither significant after multiple-testing correction) |
| Rejected (all preserved and registered) | 13 other versions: phase 1 (shock drift, turn-of-month, gap fade, crypto 0.1.0) and phase 2 (9 M15/M5 mechanisms) |
| Independently verified profitable | **none** |

* **v1 research ledger:** 16 Claude strategy versions.
* **M5 ledger:** 1 version (`index_orb_m5`).
* Sources are under `strategies/`, with prior versions in `v0.x.0/` subfolders.
* The trial log is in `notes/RESEARCH_JOURNAL.md`.

## 2. Official evaluation results (frozen evaluator `bbc0c08a…`)

* **All 8 queued Claude v1 jobs are evaluated.**
  * 6 completed in the queue.
  * 2 failed on a OneDrive file lock. They were recovered with CEO approval by exact-request re-runs, and re-verified as **identical** (`research/queue_runs/recovered_reproducibility.json`).
  * Every official result equals the lab harness: `research/queue_runs/official_results.json`.
* **M5 job:** `index_orb_m5` 0.1.0, COMPLETE, −0.0256R over 145 trades. It matches the harness.
* Codex's 3 historical FAILED jobs have the same OneDrive cause. They are untouched; that recovery is the owner's or Codex's.

## 3. Infrastructure delivered

| Item | Status | Where |
|---|---|---|
| M5 support (separately versioned, v1 untouched) | **Done, tested, used end to end** | `quant_labs/m5/`, `docs/M5_EXTENSION.md` (11 tests) |
| OneDrive lock: root cause | Reproduced: 2 of 770 renames fail in OneDrive, 0 of 778 locally | `CEO_REPORT_INFRASTRUCTURE.md` |
| Runtime relocation tool (configurable via `--target` / `TRADEDEN_QUANT_RUNTIME_DIR`) | **Built and tested (3 tests). Not completed on real state** (see §4) | `quant_labs/maintenance/relocate_runtime.py` |
| Evidence archive of all runtime files plus SHA-256 manifests | **Done** (dated snapshot) | `quant_labs/state/runtime_relocation/` |
| MT5 config backup (engine terminal) | **Done, hash-verified**; local only because it holds encrypted account data | `%LOCALAPPDATA%\TradeDen\mt5_config_backup\20261019T235925Z\` |
| M1 history maintenance procedure plus tool | **Prepared**; window not run | `docs/M1_MAINTENANCE_RUNBOOK.md`, `maintenance/m1_history_refresh.py` (2 tests) |
| Read-only financing metadata extension | **Built and tested (6 tests)**; integration patch **not applied** | `backend/financing_snapshot.py`, `patches/financing_snapshot_main.patch` |

## 4. Pending operational steps (owner)

1. **Finish the runtime relocation.**
   * The tool stopped safely: both `runtime` folders were refused for rename, with the originals untouched. Fresh and aged test folders rename normally, so something is holding these two folders open, most likely OneDrive processing their recently written files.
   * When convenient, pause OneDrive sync (or reboot) and run:
     ```
     python -m quant_labs.maintenance.relocate_runtime --apply
     ```
   * It resumes safely, verifies every hash through the junction, and records the location in `state/runtime_location.json`.
   * Until then, v1 jobs may intermittently FAIL on the lock. Use the recovery pattern (`research/recover_failed_jobs.py`); the M5 worker already retries.
2. **M1 maintenance window** (needs separate approval; stops the engine): follow `docs/M1_MAINTENANCE_RUNBOOK.md`. Raise `MaxBars` from 100000 to Unlimited, restart MT5, run `m1_history_refresh --apply`, then restart TradeDen. The new dataset is not adopted automatically.
3. **Financing capture:**
   * Review and apply `patches/financing_snapshot_main.patch`; it is off by default.
   * Set `TRADEDEN_FINANCING_SNAPSHOT_ENABLED=1` and restart the engine.
   * Records start from that day only. Overnight index evaluation also needs a verified session calendar and index dividend adjustments; both are unavailable.
4. **Commit:** review and commit the lab, M5, maintenance and financing files listed by `git status`. They are untracked or modified and were not committed by this session. The pre-existing `quant_labs/state/labs/kimi/registry.jsonl` modification is not Claude's.
5. **Forward review:** reassess the two live models after about 3 months of prospective paper outcomes. Do not tune them in place.

## 5. Tests at handoff (all passing)

```
python -m unittest quant_labs.tests                       # 27 v1 tests
python -m unittest quant_labs.m5.tests                    # 11
python -m unittest quant_labs.maintenance.tests           # 3
python -m unittest quant_labs.maintenance.test_m1_refresh # 2
cd backend; python -m unittest tests.test_financing_snapshot  # 6
```

The production v1 evaluator identity and the M5 extension identity both verify. Git shows no changes to frozen or trusted evaluator files or to `backend/main.py`.

## 6. Governance notes

* The operator capability was used by Claude, at CEO direction, to run Claude's own jobs. Hash-verified code prevents influence on outcomes, but independent review remains outstanding.
* No profitability claim is made for any model.
