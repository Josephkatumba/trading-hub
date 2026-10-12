# TRADEden V2 recovery — 12 October 2026

Final integrity investigation and measured hosting requirements are recorded in
[deployment readiness](../deploy/READINESS.md). It supersedes the unresolved
historical-data and sizing observations below; these sections retain the original
recovery chronology.

## Inherited work

Recovery began on `tradeden-garden` at `ee9b336`, one commit ahead of its remote;
`main` pointed at the same commit. No reset, stash, history rewrite or strategy
replacement was performed. The existing commits already contained Trendline v5.1,
Support & Resistance v2, Trend/Momentum v2, SMC v1, the responsive Garden,
per-strategy lifecycle, historical observations, confirmation events and outcomes.

The working tree had 30 modified files and three untracked files: qualification,
efficiency tests and V2 tests. This inherited work introduced quote-based 1.5R
qualification, withdrawal expiry classification, verified reconciled performance,
rule-point labels, incremental outcome reads, read caches, symbol caching and
shared immutable strategy data. It was inspected and preserved. Git does not
independently establish which assistant authored each uncommitted change.
During recovery the shared checkout advanced to `71e0cff`, which committed the
V2 working-tree files (including the inspected engine fixes). This deployment
commit builds on that commit and preserves it.

## Recovery additions

- Durable absolute storage override shared by observations, outcomes and health.
- Manual outcome derivation also rejects a missing beginning of the market path.
- MT5 reconnects a present-but-disconnected terminal; health freshness follows the
  same stale threshold as radar.
- HTTPS dashboards use the authenticated same-origin API despite old laptop URLs.
- Root-path production build, Caddy authentication/TLS configuration, pinned tested
  backend versions, Windows startup checks and a health-monitor script.
- Streaming read-only store audit, isolated test runner and migration/backup/restore
  runbook. Authentication is single-owner at the proxy; SQL users, OIDC and
  per-user journal storage are future subscription prerequisites.

## Store audit

This read-only audit observed the following; the engine may append more data later.

| Source | Valid objects | Damaged lines | Duplicate keys |
|---|---:|---:|---:|
| Confirmations | 392 | 0 | 0 setup IDs |
| Outcomes | 233,767 | 45 | 2,165 outcome keys |
| Lifecycle | 14,761 | 1 | not checked |
| Observations | 237,154 | 81 | not checked |

There was no trade-outcome file. Missing bytes cannot be recovered from these
files; retain backups for recovery attempts. Readers skip damaged lines and
verified reports deduplicate outcome identity. No historical source file was
rewritten by this recovery. Derived indexes may rebuild during tests.
All referenced confirmation and outcome observation IDs were found (zero missing).

## Verification

The frontend's 164 tests and production root-path build passed. Backend regression
checks cover all four strategies, qualification, golden scanner fixtures,
duplicate episodes, lifecycle, outcomes, performance, damaged storage and scanner
efficiency. All **458 isolated backend tests passed** in the final run. Both
deployment PowerShell scripts passed syntax checks; `git diff --check` passed.
The production build retains existing module/chunk-size warnings.

Real-store write equivalence passed against both the legacy and indexed writers;
all eight synthetic index-equivalence checks passed. A broad legacy/live-store run
reported a comparison failure before completion. Its harness copied the actively
appending source twice, allowing different inputs. The harness now makes one copy
and clones it for the second implementation. The corrected write comparison passed;
the entire expensive real-store read-comparison suite was not rerun. The obsolete
run was stopped; this is not presented as a full live-store regression pass.

## Operational limits

The persistent database remains indexed append-only JSONL, with one writer;
journal imports remain local to each browser. No payment processing, multi-user
tenant isolation or real-money execution was added. The scanner's index summaries
still grow with the historical log; plan capacity and a future archival policy.

No provider was purchased and no application was publicly launched. Caddy is
unavailable in this workspace; authentication/TLS configuration needs validation
on the selected Windows server. Broker licensing, session reconnect after reboot,
backup restore and real-time feed operation on that server remain launch gates.
