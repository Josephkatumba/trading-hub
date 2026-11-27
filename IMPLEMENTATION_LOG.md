# TRADEDEN Implementation Log

Newest first. Each entry: what changed, why, verification, and what was deliberately not changed.
Engine and research history before 2026-11-24 is in `PROJECT_LOG.md`.

## 2026-11-24 — Phase 1: audit, architecture and product layer

**Documents:** `PRODUCT_AUDIT.md`, `SYSTEM_ARCHITECTURE.md`, `PRODUCT_ROADMAP.md`,
`KNOWN_ISSUES.md`, this log.

**Code (new package `backend/product/`):**

- `plans.py`: four-tier catalogue (FREE $0 / TRADER $19 / PROFESSIONAL $49 / AUTOMATED $99,
  provisional, `BILLING_ACTIVE=False`). Legacy stored plans map `free`→FREE and `pro`→TRADER;
  unknown values fail closed to FREE. PROFESSIONAL/AUTOMATED are not grantable yet. No plan
  offers live execution.
- `evidence.py`: product evidence tiers EXPERIMENTAL / VALIDATED / PRODUCTION / ARCHIVED from
  the qualification registry and recorded Strategy Bank forward outcomes. VALIDATED requires the
  existing forward thresholds **plus** a Bonferroni-corrected one-sided lower confidence bound of
  expectancy above zero. Read-only.
- `execution_policy.py`: fail-closed order gate (disabled by default, demo-only, SL required,
  risk/daily-loss/position/loss-streak limits with hard ceilings, strategy tier check), emergency
  stop file with audited engage/release, status report, CLI. It does not call any broker.
- `api.py`: `GET /api/platform/plans`, `/strategies/evidence`, `/execution/status`, `/modules`.

**Wiring:** `main.py` includes the router. `commercial.py` makes `/api/platform/plans`
reachable without sign-in in OIDC mode, since it is public catalogue data. All other
`/api/platform/*` routes stay private (403) in commercial mode. `backend/.env.example`
documents the new execution variables (all commented out, defaults safe).

**Why the significance gate:** on the real data, `london_breakout` (115 resolved, +0.057R,
PF 1.11) and `macd_momentum` (98, +0.071R, PF 1.11) pass the coded alert thresholds. With 16
strategies tested and R standard deviation of about 1.2, their corrected lower bounds are −0.25R
and −0.33R. Without the gate the product would have called them VALIDATED, contradicting every
research verdict. With it, the live catalogue reports: 0 VALIDATED, 0 PRODUCTION, 23
EXPERIMENTAL, 38 ARCHIVED — "No strategy has demonstrated a validated edge."

**Tests:** `backend/tests/test_product_platform.py` (17 tests): plan mapping parity with
`commercial.py`, threshold parity with `qualification.py`, formula parity with
`qualification.forward_evidence`, labels never validating, threshold-noise regression from
real numbers, every execution denial path, limit clamping, emergency stop and audit, private-mode
routes, and commercial-mode exposure.

**Not changed (deliberately):** strategy registry statuses and promotion gate; any research
file or report; the uncommitted forward reports on this branch; alerting behaviour; the database
schema; frontend; cBot. No live trading enabled, no billing, nothing published.
