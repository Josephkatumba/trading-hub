# Integration contract for Codex, Claude Code and Kimi

This is an isolated local prototype. It is not connected to production, MT5, Telegram or order execution. Each AI should explicitly read this file and its own workspace's `AGENTS.md` before research. No external Claude or Kimi agent was launched during setup.

## Ownership and authority

| Lab | Workspace | Development capability |
|---|---|---|
| Codex Quant Lab | `quant_labs/state/labs/codex/` | Register/version Codex source, submit Codex intents, pause/resume Codex jobs, reject Codex ideas |
| Claude Quant Lab | `quant_labs/state/labs/claude/` | The same operations, scoped to `claude` |
| Kimi Quant Lab | `quant_labs/state/labs/kimi/` | The same operations, scoped to `kimi` |

Every workspace has its own `strategies/`, `notes/`, immutable registry export, experiment history, performance export and scoped `.lab-token`. The canonical SQLite ledger partitions every strategy and performance record by lab. Identical strategy IDs in different labs do not collide. A version cannot be updated or deleted: register a new version instead. Preserve failed variants and disclose all prior trials.

Lab capabilities do not grant worker execution, independent review, CEO approval, evaluator changes, shared-data writes or production integration. Reviewer capabilities are separately provisioned to the owner, not given to researchers. Reviewers cannot review their own lab. The prototype permits documented rejection/data requests, not a profitability certificate or production activation.

**Isolation boundary:** these capabilities protect the control-plane interface. They do not sandbox an unrestricted shell running under the same Windows account. Never treat API credentials or Windows read-only file attributes as an adversarial filesystem boundary. Before running mutually untrusted autonomous shells, provision separate Windows identities/ACLs or containers and test those boundaries. The evaluator never executes submitted Python/JS/source code, which closes that path inside the shared worker.

## Register a hypothesis

Place your own source and a specification under your workspace. All rule or parameter changes need a new semantic version. The specification must contain:

```json
{
  "id": "your_unique_hypothesis",
  "version": "1.0.0",
  "name": "A descriptive hypothesis name",
  "hypothesis": "An economic or statistical reason to investigate it",
  "entry_conditions": "Exact causal rules",
  "exit_conditions": "Exact barrier and time rules",
  "stop_loss_method": "Exact invalidation methodology",
  "take_profit_method": "Exact objective methodology",
  "risk_model": "Planned-risk units and exposure assumptions",
  "intended_conditions": "Market/regime/session hypothesis",
  "limitations": "Known data, execution and modelling limits",
  "timeframe": "H1",
  "declared_trials": 1
}
```

Supported initial analysis timeframes: M1, M15, H1, H4 and D1, where the shared snapshot has actual data. No strategy-count cap exists. Source uploads are bounded to 256 KiB and specs to 64 KiB; larger projects should submit a reviewable source manifest and retain their complete files in their own workspace. The evaluator records source hashes; independent review must verify the complete generator and parameter history.

Example for Claude, from the repository root in PowerShell:

```powershell
$env:TRADEDEN_LAB_TOKEN = Get-Content -Raw quant_labs/state/labs/claude/.lab-token
python -m quant_labs.cli register claude quant_labs/state/labs/claude/strategies/spec.json quant_labs/state/labs/claude/strategies/strategy.py
```

Kimi and Codex substitute only their own lab ID and workspace. A Codex token cannot register, submit, pause or resume Claude/Kimi work.

## Submit declarative trade intents

Develop hypotheses independently in your own workspace. Submit a JSON array of intents, not executable code or precomputed outcomes:

```json
[
  {
    "symbol": "EURUSD",
    "direction": "LONG",
    "signal_bar_closed_at": 1788868800,
    "entry_at": 1788868800,
    "stop_loss": 1.1,
    "take_profit": 1.106,
    "horizon_seconds": 14400
  }
]
```

The values above demonstrate the schema only; they are not a market signal or recommended prices. Do not optimize them against known outcomes. Entry is reconstructed by the evaluator from the shared bid-open and recorded spread, not accepted from the lab. Historical entries must equal the confirming candle close, on an exact minute boundary. A confirming bar must exist in the declared timeframe. Minute entries need actual M1 quote coverage; M15 boundaries can use M15 opens. The stop/target must remain on the correct sides after conservative tick rounding. Horizons are bounded to seven days; missing paths are incomplete, not invented no-hit outcomes.

```powershell
python -m quant_labs.cli submit claude your_unique_hypothesis 1.0.0 quant_labs/state/labs/claude/strategies/intents.json
```

Each request is limited to 2,000 intents and each lab to eight pending/paused jobs. These are per-experiment resource limits, not a limit on research ideas. Exact duplicate intent experiments share a fingerprint across laboratories, preserve the duplicate record and reference the original job; they are not executed or counted as independent evidence again. Never split or rename variants to evade trial accounting.

## Frozen data and evaluator

The shared dataset is content-addressed under `state/shared/`. Originals remain in the existing backend cache and are not modified. The snapshot preserves raw timestamps, UTC, bid OHLC, spreads, source metadata and tick-volume fields. A validated read excludes invalid, duplicate, future and forming bars; gaps remain visible. Session/holiday calendars and precise historical ask extremes are unavailable and explicitly unverified. MT5 tick volume is not centralized traded volume.

The evaluator identity covers its execution engine, metrics, policy, timezone data and trusted worker/control interfaces. Every job pins the evaluator and dataset hashes. A changed file fails verification. Researchers cannot choose a more favorable resolver, upload outcome labels, override costs or edit an existing result. New evaluator versions require a separately reviewed release, retaining prior contracts and evaluations.

Training, validation and historical-test dates are fixed in `evaluation/v1/policy.json`. Trades crossing a split boundary are purged. The historical cache was already exposed to earlier research; chronological separation is not a genuinely untouched future sample. Historical intents alone cannot prove absence of look-ahead or selective omission. Independent source review and prospective intent commitment are mandatory before qualification.

## Queue, pause and resume

Lab commands:

```powershell
python -m quant_labs.cli pause claude JOB_ID
python -m quant_labs.cli resume claude JOB_ID
python -m quant_labs.cli status
```

An active worker checkpoints between intents; large data reads finish before the next checkpoint. Timed-out runs can resume the last atomic checkpoint. A resumed evaluation keeps the same immutable request and frozen inputs. Replayed checkpoint work does not append a duplicate final result. Per-job segments are capped at 20. Failed integrity checks require operator investigation, not silent retries under changed code.

Only the trusted local operator can start a worker, using a separate environment variable and capability. The owner must not give operator or reviewer secrets to research agents:

```powershell
$env:TRADEDEN_OPERATOR_TOKEN = (Get-Content -Raw quant_labs/state/owner/credentials.json | ConvertFrom-Json).'operator:owner'
python -m quant_labs.cli --token-env TRADEDEN_OPERATOR_TOKEN run-one
python -m quant_labs.cli --token-env TRADEDEN_OPERATOR_TOKEN queue-pause
python -m quant_labs.cli --token-env TRADEDEN_OPERATOR_TOKEN queue-resume
```

`run-one` is a single foreground operation, not a daemon. Windows Job Objects impose a 20% machine CPU hard cap, one process, 384 MiB committed memory by default, 20 user-mode CPU seconds and 30 wall seconds by default (45 wall seconds maximum). A secondary worker watchdog bounds it if the controller exits. Queue pause also asks the active worker to checkpoint; resuming the queue does not automatically resume each paused job. No API route or dashboard button starts research workers.

## Review and lifecycle

IDEA → RESEARCH → BACKTEST → HISTORICAL_VALIDATION → SHADOW_FORWARD_TEST → INDEPENDENT_REVIEW → CEO_APPROVAL → PRODUCTION.

Backtest/historical-validation stages record completed measurement, not a profitability certificate. Source/code review, complete data, net expectancy, cost stress, drawdown, independent opportunity counts and all search trials matter. The pooled Holm family includes registrations/declared variants and unique experiment attempts across all three labs; it cannot recover undisclosed prior trials or fix missing-data bias.

Prospective capture and production integrations are deliberately inactive. `SHADOW_FORWARD_TEST` cannot be asserted using historical replay. There is no method to self-certify profitability or activate production. A reviewer from another lab may record a rejection or a need for forward data, but cannot skip forward evidence or CEO approval.

Use the research leaderboard as a comparison of uncensored simulated subsets, not trade advice. The qualified leaderboard remains empty until an approved future governance implementation can verify all gates. Planned 2R/3R/4R/5R/7R+ objectives and 60–70% win-rate aspirations never override realistic fills, uncertainty or positive cost-stressed expectancy.

## Local dashboard

```text
python -m quant_labs.preview --export
python -m quant_labs.preview --port 8766
```

`dashboard.html` is a self-contained read-only snapshot. The optional preview binds only `127.0.0.1`; its API supports GET only and exposes no credentials or mutation routes. Stop the foreground preview with Ctrl+C. It is independent of the operational TradeDen dashboard and makes no public deployment.
