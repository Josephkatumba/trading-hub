# Seven Codex models: experimental paper admission

All six Trend Reclaim targets and Range Sweep Reversion retain their original
0.1.0 source, manifests, instrument lists, barriers and horizons. They are
EXPERIMENTAL, not certified profitable. Instruments: EURUSD, XAUUSD, BTCUSD only.
No production code, dashboard code, existing model or permission was changed.

From the repository root:

```
python -m quant_labs.paper_integration.manage forward
```

This read-only command refreshes `forward_performance.json` from the actual paper
ledger and loopback engine. The normal engine independently continues collecting
signals and outcome revisions when this command/session exits. It does not send
Telegram, submit orders, register models or import historical signals.

## Evidence and accounting

- `preserved_sources.json`: raw file and normalized registered-source hashes.
- `shared_evaluator_validation.json`: 21 exact historical request revalidations,
  each identical across train/validation/test periods to its preserved result.
  Three original FAILED jobs remain FAILED; successful recoveries remain separate.
- `genuine_provider_probes.json`: 21 real-cache bounded executable probes;
  no synthetic opportunities, live signal inserts or external sends.
- `admission.json`: enrollment and safety comparisons; no engine restart.
- `forward_performance.json`: each model's independent forward cohort, executions,
  signals, latest outcomes, uncertainty, and overlap exclusions. Never pooled with
  historical results or across correlated target variants. Existing dashboard
  rolling-window summaries remain unchanged; this file provides separate cohort
  accounting without the dashboard's latest-1000-signal window.
- `backend_tests.txt` and `admission_tests.txt`: isolated regression evidence.
- `pre_admission.sqlite3`: ignored private consistent pre-admission backup.

SQLite enrollment and rejection tables live only inside the experimental paper
database. The `codex_forward_*` triggers apply only to the seven enrolled model
identities, and therefore take effect in the already running consumer without
loading another session's pending engine edits. Duplicate economic identities
continue to use the existing unique run/signal keys. Concurrent admission is
serialized by SQLite. A known latest outcome releases that model/instrument's
reservation at its recorded exit; a missing or ambiguous result reserves the
original deadline, matching the historical evaluator's opportunity convention.
Overlapping candidates are logged separately and are not admitted as signals or
counted as trades. Forward cohort reports also reconstruct exclusions after late
outcome revisions; unknowns are never assigned zero return or treated as wins.
Per-target trials are correlated and have no pooled independent-edge claim.

## Scheduling and data

All seven use closed M15 features with H1 context. Minimum implementation needs
are 80 completed M15 and 64 H1 candles; the declared provider request is 300 M15,
160 H1, and 120 M1. M1 refines outcome resolution rather than entry detection.
Missing intrabar history/ties can leave outcomes unknown and do not prevent a
correctly supplied M15/H1 entry evaluation. Gaps, invalid bars, stale quotes,
missing context and invalid geometry are not repaired or freshness-waived.

The existing market worker waits 30 seconds after a scan; actual cycle time also
includes collection work. The consumer rotates up to eight model slots per market
handoff within ten seconds, across all laboratories. Per model/version/instrument/
closed M15 candle there is at most one worker claim (including an initial partial
candle at enrollment). This is a 15-minute signal decision cadence, not a promise
of executions exactly every 30 seconds. Rotation/budget/input failures can skip a
bar and must be reported as missing coverage, not fabricated observations.

Barriers undergo the unchanged shared live tick rounding and admission checks;
no source parameters or original horizons were retuned. Six Trend Reclaim horizons
remain 6/8/12/18/24/36 hours; Range Sweep remains 12 hours.

## Safety

All seven registrations have scan_enabled=1, alert_enabled=0 and EXPERIMENTAL
status. No delivery approval was created or changed. Global experimental mode
was verified DRY_RUN with approval false and execution disabled. The scoped
overlap/instrument guards do not confer delivery or broker capabilities. Future
delivery requires separate approval and current safety checks. Historical
research results remain in their original directories; forward data begins only
at the recorded per-model enrollment time. No restart, push or deployment is
part of this integration.
