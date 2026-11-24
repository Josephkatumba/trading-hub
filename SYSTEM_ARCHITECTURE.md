# TRADEDEN System Architecture

Status: target architecture with current mapping · 2026-11-24 · See `PRODUCT_AUDIT.md` for findings.

## 1. Principles

1. **Evidence before claims.** Every number a customer sees comes from a recorded row. Strategy
   tiers rise only on recorded forward evidence that passes a significance test.
2. **Fail closed.** Unknown plan → FREE; unknown account type → no execution; unreadable stop
   file → stopped; new API route → private.
3. **Append-only research truth.** JSONL stores stay canonical. Product read models are derived and
   rebuildable.
4. **Evolve, don't rewrite.** New modules wrap existing engines through narrow interfaces.
5. **Execution is opt-in, demo-only, and gated in two places** (server policy and broker-side cBot).

## 2. Module map

```
                    ┌──────────────────────── Frontend (Vite, ES modules) ─────────────────────────┐
                    │ Overview · Market Radar · AI Analyst · Signal Centre · Strategy Lab ·          │
                    │ Portfolio · Analytics · Settings                                               │
                    └───────────────▲───────────────────────────────────────────────────────────────┘
                                    │ HTTPS (Caddy) · cookie session + CSRF
┌───────────────────────────────────┴──────────────────────────────────────────────────────────────┐
│ API process (FastAPI)                                                                              │
│  commercial.py  auth/session/entitlement guard ── product/plans.py (tiers, capabilities)           │
│  /api/market/*  radar, setups, outcomes, performance           (Market Radar, Signal Centre)       │
│  /api/strategy-bank, /api/signal-quality, /api/research/*      (Strategy Intelligence)             │
│  /api/platform/* plans · strategies/evidence · execution/status · modules   (product layer, new)   │
└───────▲──────────────────────▲───────────────────────────▲───────────────────────────────────────┘
        │ reads                 │ reads                     │ reads
┌───────┴──────────┐  ┌─────────┴──────────────┐  ┌─────────┴──────────────────────────────────────┐
│ Research store    │  │ User store (PostgreSQL)│  │ Execution (future adapters)                    │
│ JSONL + index     │  │ users, sessions,       │  │ product/execution_policy.py  ← every order     │
│ setups, lifecycle,│  │ entitlements, journal  │  │ MT5 adapter: market data only today            │
│ outcomes, bank,   │  │ (+ watchlists, prefs,  │  │ cTrader cBot: demo-only gate in C#             │
│ qualification     │  │  plans v2: Phase 8)    │  │ emergency stop + audit.jsonl                   │
└───────▲───────────┘  └────────────────────────┘  └────────────────────────────────────────────────┘
        │ writes
┌───────┴───────────────────────────────────────────────────────────────────────────────────────────┐
│ Workers (today: threads in the API process; target: separate worker process)                      │
│  market scanner (30 s) · signal outcome resolver · Strategy Bank · quant_live · market_intel ·    │
│  Telegram notifier · scheduled reports                                                             │
└───────▲───────────────────────────────────────────────────────────────────────────────────────────┘
        │ MetaTrader5 IPC (local terminal, broker time normalised)
     MT5 terminal (IC Markets demo)
```

## 3. The six product modules → code

| Module | Existing code (reuse) | Product layer / next |
|---|---|---|
| Market Radar | `main.py` scan loop, `strategies/*`, `observations.py`, `market_data.py` | Per-instrument market state API (direction, volatility, S/R from strategy evidence); user watchlists |
| AI Market Analyst | `analyst.py`, `market_intel/*` | `analyst/` facts builder → optional LLM narrator that receives facts only and has its output validated against them |
| Signal Centre | lifecycle/outcome stores, `signal_outcomes.py`, `strategy_bank` signals, `signal_quality/` | Unified `Signal` read model (below) over all sources |
| Strategy Intelligence | `strategy_bank/qualification.py`, `research/*`, `ctrader_scalper/engine`, `quant_labs` | `product/evidence.py` tiers (done); unified catalogue incl. research verdicts |
| Execution Engine | cBot, `quant_live/execution.py` helpers | `product/execution_policy.py` (done); adapter interface; position/execution log |
| Performance Analytics | `performance.py`, `strategy_lab.py`, `src/behavior.js` | Signal-level calendar P&L in R; account equity from recorded fills |

## 4. Key contracts

### 4.1 Strategy evidence tier (implemented)

`EXPERIMENTAL | VALIDATED | PRODUCTION | ARCHIVED`, derived by `product/evidence.py` from the
qualification registry and recorded Strategy Bank outcomes:

- VALIDATED = ≥60 resolved forward signals, expectancy ≥0.05R, PF ≥1.10, **and** a
  Bonferroni-corrected (α=0.05 family-wise, one-sided) lower bound of expectancy > 0.
- PRODUCTION = VALIDATED + an approval reference on a QUALIFIED transition.
- The registry label `PRODUCTION` alone never makes a strategy VALIDATED.

### 4.2 Unified Signal (Phase 4 design)

```
signal_id, source (engine|bank|cbot), strategy_key, strategy_version, evidence_tier,
instrument, direction, entry, stop_loss, take_profit, rr_planned (net of modelled costs),
confidence {value, kind: "rule_points"|"quality_score", calibrated: false},
status (WATCHING…ACTIVE|INVALIDATED|EXPIRED|RESOLVED), status_history[],
invalidation {conditions[], reason?}, outcome {result: TARGET|STOP|TIME_EXIT|EXPIRED|
INVALIDATED|UNVERIFIED, r_multiple?, resolved_at?, integrity},
detected_at, confirmed_at, timestamps all UTC ISO-8601
```

Rules: built by adapters per source, read-only; losing, expired and invalidated signals are
always included; `r_multiple` only when barriers are proven to be the planned SL/TP.

### 4.3 Execution policy (implemented)

`evaluate(order, account, config, stop_state) -> Decision(allowed, reasons[])`. Denies unless
**all** of the following hold: enabled flag `TRADEDEN_EXECUTION_ENABLED=1`; mode `demo`; account
reports `is_demo=True` and `is_live=False`; SL on the protective side; TP (if any) on the profit side;
risk ≤ limit; daily loss + risk ≤ limit; open positions < limit; consecutive losses < limit;
strategy tier VALIDATED/PRODUCTION or a declared demo forward experiment; no emergency stop.
Limits are clamped to hard ceilings (1% risk, 3% daily, 3 positions, 3 losses).
Emergency stop: `python -m product.execution_policy stop "<reason>"`, release with a reason,
both audited to `<data>/execution/audit.jsonl`.

### 4.4 Plans and entitlements

`product/plans.py` defines FREE/TRADER/PROFESSIONAL/AUTOMATED (provisional $0/19/49/99,
billing inactive). Stored `free`→FREE, `pro`→TRADER. PROFESSIONAL/AUTOMATED are not grantable
until migration `0002` adds them, and no plan offers live execution.

## 5. API surface (current)

- Health: `/api/health`, `/api/ready`
- Market: `/api/market/radar|opportunities|strategies|setup-episodes|setups/{id}[/history|lifecycle|analysis|similar]|outcomes|performance|strategy-lab|evaluation|chart|candles`
- Research: `/api/strategy-bank[/signals]`, `/api/signal-quality`, `/api/research/overview`, `/api/scalper/*`, quant_live routes
- Accounts: `/api/auth/login|callback|me|logout`, `/api/journal/*`, `/api/billing/*` (503)
- Platform (new): `/api/platform/plans` (public), `/strategies/evidence`, `/execution/status`, `/modules` (operator)
- OpenAPI: `/docs` (FastAPI), private by default in commercial mode.

## 6. Deployment and scaling path

| Stage | Shape |
|---|---|
| Today (operator) | One Windows host, MT5 terminal, one Uvicorn worker with threads, loopback or Caddy |
| Private beta | Same host behind Caddy/TLS, OIDC, PostgreSQL, invite allowlist (`deploy/PRIVATE_BETA.md`) |
| Paid launch | Split **scanner worker** (MT5 host) from **stateless API** (N workers) via a read model in PostgreSQL; data dir outside OneDrive; backups verified |
| Scale | Market data from a vendor feed in addition to the MT5 terminal; per-user alert fan-out queue |

## 7. Configuration (no silent changes)

All flags default to the safe value; see `backend/.env.example` and `deploy/*.env.example`.
New in Phase 1 (all optional): `TRADEDEN_EXECUTION_ENABLED` (off), `TRADEDEN_EXECUTION_MODE`
(`demo` only), `TRADEDEN_MAX_RISK_PER_TRADE_PCT`, `TRADEDEN_MAX_DAILY_LOSS_PCT`,
`TRADEDEN_MAX_OPEN_POSITIONS`, `TRADEDEN_MAX_CONSECUTIVE_LOSSES`.
