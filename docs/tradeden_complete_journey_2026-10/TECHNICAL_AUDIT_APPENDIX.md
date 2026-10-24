# TradeDen — Technical Audit Appendix

**Companion to "TRADEDEN — The Complete Journey" · October 2026** · Founder: Joseph Katumba · Evidence cut-off 2026-10-24 · Repository HEAD `920676d` (branch `codex/tradeden-session-handoff`)

This appendix collects the code-, data- and operations-level findings behind the main report. It uses the same labels:

- **[VERIFIED]:** observed in a file, store, git or `/api/health`;
- **[ASSESSMENT]:** reviewer judgement;
- **[PROPOSAL]:** a recommended change, not yet made.

**No production file, flag, credential or strategy parameter was changed during this review.** All stores were opened read-only. SQLite was opened with `mode=ro`.

## A1. Codebase profile [VERIFIED]

| Metric | Value |
|---|---|
| Tracked files | 1,038 (`git ls-files`) |
| Lines (py/js/mjs/css/html/ps1/mq5) | backend ≈ 35,500 · quant_labs ≈ 14,600 · src ≈ 7,400 · tests ≈ 2,500 · research_autonomous ≈ 1,900 · audit_independent ≈ 350 · deploy ≈ 150 · mt5 ≈ 70 |
| Test files tracked | 119 |
| Commits | 216 (2026-09-21 → 2026-10-24); 21 local commits not on `origin/main` |
| Branches | `main`, `codex/commercial-mvp-phase1`, `codex/tradeden-session-handoff` (HEAD), `phase1-foundation-fixes`, `tradeden-garden`; remote also `feature/trading-hub-v3-engine` |
| Untracked at review start | `quant_labs/state/runtime_relocation/v1_runtime_20261023T215101Z.zip` and its manifest |
| Runtime | Python (system 3.14 present; engine venv not inspected), FastAPI, MetaTrader5 Python API, Vite, Three.js, Lightweight Charts 5.2, Playwright tests |

## A2. Findings register

Severity levels:
- **P0:** act now; harm or integrity risk today.
- **P1:** correctness or major reliability problem.
- **P2:** important weakness.
- **P3:** hygiene.

| # | Sev | Area | Finding | Evidence | Recommended fix | Label |
|---|---|---|---|---|---|---|
| 1 | P0 | Product safety | Production Telegram alerts are enabled for `trendline_v5` (negative in every test, below all random-entry controls), Trend/Momentum (0 live targets), S/R and SMC. 37 signals and 34 outcome messages were sent between 19 and 23 Oct. | `/api/health` → `telegram_alerts.enabled: true`; `backend/data/telegram_notifications.jsonl` status counts; `V6_RESEARCH_REPORT.md` §1 | Shadow or disable alerts for Category C/D strategies; label the remainder "research, unproven" | VERIFIED / PROPOSAL |
| 2 | P0 | Product safety | Strategy Bank Telegram is enabled. 65 messages were sent; the forward record is 114 signals, −48.8R (hypothetical barrier R). | `/api/health` → `strategy_bank.telegram_enabled: true`; `strategy_bank/signals.jsonl` | Disable bank Telegram; keep scanning | VERIFIED / PROPOSAL |
| 3 | P0 | Secrets | The Telegram bot token was pasted into a chat. Revocation was advised on 2026-10-19; no evidence it was done. | `backend/TELEGRAM_T031_REPORT.md` "Outstanding" | Revoke with BotFather, update `backend/.env`, restart, run `telegram_setup.py check` | VERIFIED (as reported) |
| 4 | P0 | Data integrity | The live store (`backend/data`, 2.6 GB) is inside an over-quota OneDrive folder. Sync bytes corrupted `setup_observations.jsonl` on 2026-10-05 (81 lines) and the lifecycle log (1 line). The index still reports 79 unparseable lines. | `PROJECT_LOG.md` 2026-10-12; `deploy/READINESS.md`; `/api/health` storage | Stopped-writer backup → `recover_store.py` → set `TRADING_HUB_DATA_DIR` to a local non-synced path | VERIFIED / PROPOSAL |
| 5 | P1 | Research ops | Quant Labs runtime renames fail under OneDrive (2/770 vs 0/778 locally). 6 of 37 queue jobs FAILED. The relocation tool stopped safely and has not been applied. | `CEO_REPORT_INFRASTRUCTURE.md`; `control.sqlite3` job states | `python -m quant_labs.maintenance.relocate_runtime --apply` with OneDrive paused | VERIFIED / PROPOSAL |
| 6 | P1 | Outcomes | Resolver skips the entry minute: an M1 stop at the confirmation minute can be ignored in favour of a later TP. | `audit_independent/CEO_AUDIT_REPORT.md` §3; `probe_outcomes.py` | Include the entry minute when entry equals its open, or mark it unknown | VERIFIED |
| 7 | P1 | Outcomes | First-hit decided without proving contiguous intrabar coverage; day-long gaps accepted before a TP; `max_gap_hours` not enforced on hits. | same | Validate session-aware coverage before any terminal outcome | VERIFIED |
| 8 | P1 | Outcomes | Seven-day-old signal with 2 M15 bars returns NO_HIT; no end-coverage check. | same | Return INCOMPLETE and retry | VERIFIED |
| 9 | P1 | Outcomes / bank | Bank stores the entry from the detection quote but resolves from the earlier `confirmed_at` bar close (example: USDJPY bar close 10:00, detection 10:31:20). | same | Persist `signal_bar_closed_at` and `entry_at` separately | VERIFIED |
| 10 | P1 | Governance | `rules.alerting()` allows every EXPERIMENTAL spec regardless of ARCHIVED status. `BankAlerts.deliver()` trusts a stored flag. `qualification.transition()` is an ungated write. | audit §3 | A central authorisation check at send time | VERIFIED |
| 11 | P1 | Availability | Heartbeat coverage was 27.6 h of 111 h (about 25%), 19–23 Oct. The watchdog made 13 relaunches and suppressed 155 after its hourly limit. | `engine_heartbeat.jsonl`; `ops/watchdog.jsonl` | Diagnose relaunch failure, back off with alerting to the owner, pin `TRADING_HUB_MT5_TERMINAL_PATH` | VERIFIED |
| 12 | P2 | Freshness | The bank accepts quote age −3600 s and a confirming bar 1 h in the future. The resolver accepts a future minute inside the confirmation candle. | audit §3 (P2) | A shared bounded freshness validator | VERIFIED |
| 13 | P2 | Execution realism | Production `_touch` defaults a missing spread to zero for shorts. Barrier R omits gaps, commission and financing. Commission defaults to 0 in production qualification. | audit §3; `deploy/COMMERCIAL_MVP.md` | Configure verified per-symbol costs; resolve with bid/ask ticks | VERIFIED |
| 14 | P2 | Memory | Engine working set 4.31 GiB / private 4.89 GiB. Nested-JSON index sidecar of about 235 MB. A streaming watcher fix (−97.9% peak on a sample) is staged, not loaded. | `quant_labs/CEO_NEXT_PHASE_REPORT.md` | Deploy the staged fix at the next controlled restart; profile index maps | VERIFIED |
| 15 | P2 | Data depth | M1 is capped at 100,000 bars (about 3 months). The full-year files exist in the terminal. MaxBars raise not performed. | `CEO_REPORT_INFRASTRUCTURE.md`; dataset manifest `bf130602…` | Run `docs/M1_MAINTENANCE_RUNBOOK.md` in a weekend window | VERIFIED |
| 16 | P2 | Data semantics | The live cache holds about 200 bars per TF. D1 is stale every Monday (fixed in Quant Labs gate 2026-10-23). The crypto Friday gap makes multi-day holds INCOMPLETE. There is no verified session calendar, swap history or dividend data. | `notes/RESEARCH_JOURNAL.md`; `MILESTONE_1_SIGNAL_OPERATIONS.md` | A canonical validated bar contract; a calendar source | VERIFIED |
| 17 | P2 | Isolation | Lab isolation is application-level, not OS-level; a same-account shell can bypass scopes. | `quant_labs/CEO_IMPLEMENTATION_REPORT.md` | Separate Windows identities, ACLs or containers before any third-party use | VERIFIED |
| 18 | P2 | Statistics | No global multiple-testing family spans V6/T-033, the bank, the expansion and the three labs. Promotion gate thresholds (≥ 60 signals, ≥ +0.05R, PF ≥ 1.10) carry no uncertainty bound. | reports; `strategy_bank/qualification.py` | A global trial ledger; a lower-bound criterion on cost-stressed expectancy | VERIFIED / PROPOSAL |
| 19 | P2 | Process | No CI on push; the only workflow deploys GitHub Pages. Suites run piecemeal by different sessions. `test_observation_index` (full real-store replay) did not complete in 25 minutes. | `.github/`; `MILESTONE_1_SIGNAL_OPERATIONS.md` | CI for unit suites; separate nightly real-store job | VERIFIED |
| 20 | P2 | Repository | Described as public, with 21 unpushed commits. Tracked `.zip` runtime archives. The overnight audit found no secrets in tracked files. `.env`, `backend/data/`, `quant_labs/state/owner/` and the SQLite ledgers are gitignored (confirmed with `git check-ignore`). | `CEO_COMPREHENSIVE_REPORT_2026-10-23.md`; git | Slim archives (or move them to release assets) and rerun a secret scan before any push | VERIFIED |
| 21 | P3 | Dead path | MT5 bridge EA (`mt5/TradingHub_Bridge.mq5`) shows OFFLINE; the engine uses the Python API directly. | `/api/health` → `bridge` | Document as deprecated or remove | VERIFIED |
| 22 | P3 | Documentation drift | Handoffs disagree with live state: "Telegram is DRY_RUN" holds only for lab categories; "nothing committed" predates later commits; model counts vary (15/16/17). | various | A generated status page from `/api/health` and approval files | VERIFIED |

## A3. Verified strengths worth preserving [VERIFIED]

- **Closed-bar contract and causality tests:** the bank test injects a one-bar leak and fails it.
- **Verified MT5 time basis** (`America/New_York+07:00`). DST gaps are rejected, never guessed.
- **Immutable confirmation plans,** append-only outcome revisions and quarantine of damaged bytes. Nothing is guessed.
- **Executable-price qualification:** quote ≤ 300 s, executable R:R ≥ 1.5 with spread, and tick-size rounding.
- **Frozen evaluator** `bbc0c08a5728abca…` with identity verification; SQLite triggers forbid updates or deletes of registered versions and results.
- **Bounded workers** under Windows Job Objects (memory, CPU, process caps); a single lease holder.
- **Telegram reliability:** dedup keys, baseline-on-activation, expiry, retries, redaction, pacing.
- **Honest data handling:** unsupported VWAP, unavailable macro and crypto-derivatives data, "rule pts" not probabilities.

## A4. Data-store inventory (sizes and counts only) [VERIFIED]

| Store | Size / rows | Note |
|---|---|---|
| `setup_observations.jsonl` | 1,715,642,818 B; 345,293 indexed rows; 79 unparseable | append-only |
| `market_outcomes.jsonl` | 691,935,764 B | per-horizon labels |
| `setup_lifecycle.jsonl` | 9,815,252 B | |
| `setup_confirmations.jsonl` | 433,042 B | |
| `signal_outcomes.jsonl` | distinct setups: 432 (incl. v3 backfill and shadow) | authoritative resolver |
| `telegram_notifications.jsonl` | 396 baseline, 71 pending→sent transitions | signals and outcomes |
| `strategy_bank/signals.jsonl` | 114 distinct signals | 19–23 Oct |
| `quant_live/signals.sqlite3` | models 17, runs 1,312, candles 56,079, signals 0, outcomes 0, outbox 0 | paper consumer |
| `quant_labs/state/control.sqlite3` | jobs 37 (30 complete, 6 failed, 1 duplicate), strategies 45, results 30 | research ledger |
| `engine_heartbeat.jsonl` | 1,651 beats, 2026-10-19 06:44 → 2026-10-23 21:55 UTC | |
| `ops/watchdog.jsonl` | 199 events (2026-10-23) | |

## A5. Feature flags at review (names and values only) [VERIFIED]

`TRADEDEN_TELEGRAM_ALERTS_ENABLED=1`, `TRADEDEN_STRATEGY_BANK_ENABLED=1`, `TRADEDEN_STRATEGY_BANK_TELEGRAM_ENABLED=1`, `TRADEDEN_TELEGRAM_REPORTS_ENABLED=1`, `TRADEDEN_SIGNAL_OUTCOMES_ENABLED=1`, `TRADEDEN_QUANT_LIVE_ENABLED=1`, `TRADEDEN_QUANT_LIVE_TELEGRAM_ENABLED=1`, `TRADEDEN_INTEL_BRIEFINGS_ENABLED=1`. Execution: `execution_enabled: false`.

## A6. Approvals on file [VERIFIED]

| File | Status | Scope |
|---|---|---|
| `approvals/2026-10-23_quant_labs_live_signal_integration.json` | Approved (CEO), production false | Five 20-Oct strategies as EXPERIMENTAL paper signals |
| `approvals/2026-10-23b_paper_candidates_only.json` | Approved (CEO), production false | Outbound only for `index_trend_day` 0.2.0 and `crypto_trend_breakout` 0.3.0 |
| `approvals/PENDING_intel_briefings_request.json` | PENDING_CEO_REVIEW | Category C briefings 08:00 and 15:00 EAT |
| `approvals/PENDING_research_observations_request.json` | PENDING_CEO_REVIEW | Category B, recommended narrow scope (R4, Turn-of-Month, Range Sweep) |
| `approvals/PENDING_research_only_delivery_request.json` | PENDING_CEO_REVIEW | 3 rejected models; recommendation: **decline** |

## A7. Reproduction commands (read-only)

```
python audit_independent/probe_outcomes.py          # 7 adversarial resolver probes
python -m unittest quant_labs.tests                 # frozen evaluator v1 (27)
python -m unittest quant_labs.m5.tests              # M5 extension (11)
python -m quant_labs.validate                       # evaluator identity verification
curl http://127.0.0.1:8000/api/health               # live state (engine must be running)
```

The inventory and charts in this report were produced by read-only scripts kept outside the repository. Their outputs are `strategy_inventory.json`, `strategy_inventory.csv` and `charts/`.
