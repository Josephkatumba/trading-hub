# TRADEDEN Product Audit

Date: 2026-11-24 · Branch audited: `tradeden-demo-forward` at `c01395b` · Author: CTO audit (Phase 1)

This audit covers the repository as it stands, measured against the commercial product brief
(six modules, SaaS tiers, professional terminal UI). It is based on the code, the tests and
the recorded data. It does not rely on earlier reports' claims.

## 1. Executive summary

TRADEDEN is not a prototype. It is a substantial, safety-conscious **research and signal
platform** with ~38k lines of backend Python, ~2.6k lines of frontend modules, around 500
backend tests and 168 frontend tests. Its strongest asset is **evidence discipline**:
append-only stores, a verified broker time basis, outcome integrity rules, pre-registered
research and an honest "no edge" verdict.

The gap to a commercial product is mostly **product shape**, not missing engines:

| Need | Reality |
|---|---|
| Six coherent modules | Capabilities exist but are spread across ~10 subsystems with their own vocabularies (Garden, Strategy Bank, Quant Labs, Edge Lab, Scalper, market_intel). |
| Honest strategy status | Registry status `PRODUCTION` means "original live strategy", not "proven". There was no customer-safe tier. **Fixed in Phase 1** (`product/evidence.py`). |
| SaaS accounts | OIDC sessions, PostgreSQL, CSRF and Free/Pro limits already exist (`commercial.py`). Only 2 tiers; billing inactive. |
| Execution | No server-side order path at all (by design). cTrader cBot has a strong demo-only gate. There was no shared policy for future adapters. **Fixed in Phase 1** (`product/execution_policy.py`). |
| Frontend | A distinctive "Garden" 3D constellation plus journal views. Navigation doesn't match the 8-section terminal the brief describes. |

**Commercial honesty constraint.** Every research program (Edge Discovery V1/V2, V3,
tds-1.0 scalper walk-forward, Strategy Bank forward results) concluded there is **no
demonstrated edge**. The product must therefore launch as an **intelligence, research and
discipline platform**. It must not be sold as a signals-that-make-money service until recorded
forward evidence says otherwise. This is a positioning decision as much as an engineering one.

## 2. Stack

| Layer | Technology | Notes |
|---|---|---|
| Backend | Python 3.14, FastAPI 0.141, Uvicorn (single worker), threads for workers | `backend/main.py` (1,400 lines) is the app and scan loop |
| Market data | MetaTrader5 Python package, local terminal, IC Markets demo | Broker time basis verified (`America/New_York+07:00`) |
| Storage (research) | Append-only JSONL + derived byte-offset index (`jsonl_index.py`) | `backend/data/`: **9.3 GB**, git-ignored, inside OneDrive |
| Storage (users) | SQLAlchemy 2 + PostgreSQL (psycopg 3); SQLite in tests | One migration (`migrations/0001_commercial.sql`) |
| Auth | Authlib OIDC code flow + PKCE, opaque server sessions, CSRF header | Auth0-compatible; private-beta subject allowlist |
| Frontend | Vite (unpinned `latest`), vanilla ES modules, Three.js, lightweight-charts | 3 entry pages: `index.html`, `scalper.html`, `research.html` |
| Notifications | Telegram bot (`telegram_notifier.py`), off by default | Strategy Bank has its own separate Telegram gate |
| Execution | cTrader cBot `TradeDenScalper.cs` (C#), demo-only, activation-gated | MT5 EA `mt5/TradingHub_Bridge.mq5` is a data bridge |
| Deploy | Windows host, Caddy reverse proxy, PowerShell supervision, Postgres backup scripts | `deploy/` |
| Tests | `unittest` (backend), `node --test` (frontend), Playwright (2 browser specs) | |

## 3. Module-by-module findings

Legend: ✅ functional · 🟡 partial · 🔴 broken · ⬜ missing

### A. Market Radar: ✅ functional, 🟡 for product

- ✅ Autonomous 30 s scanner (`autonomous_market_worker`) over a 16-symbol universe. The
  **official ten already include every instrument in the brief**: XAUUSD, BTCUSD, ETHUSD,
  NAS100, US500, GER40, GBPJPY (+ EURUSD, GBPUSD, USDJPY). Broker aliases are resolved
  (GER40→DE40, NAS100→USTEC).
- ✅ Four registered live strategies (`strategies/registry.py`): trendline v5.1, S/R v2,
  trend/momentum v2, SMC v1. Each is isolated, so a failing strategy cannot affect the others.
- ✅ Lifecycle WATCHING/DETECTED → DEVELOPING → CONFIRMING → CONFIRMED → ACTIVE →
  INVALIDATED/EXPIRED/RESOLVED, persisted append-only, with freshness, spread and R:R gates
  before confirmation.
- ✅ `/api/market/radar` reads cached scans; `/api/ready` and `/api/health` probes.
- 🟡 No per-user watchlists (the commercial store has no watchlist table).
- 🟡 "Market direction / volatility / trend / S&R" exist inside strategy evidence and
  `market_intel/` (Gold/Bitcoin only), not as a uniform per-instrument market state.

### B. AI Market Analyst: 🟡 partial (rule-based)

- ✅ `analyst.py` (`deterministic-setup-analyst-v1`) explains setups from engine data only.
- ✅ `market_intel/` produces Gold/Bitcoin briefings with readiness rules (preview only unless flagged).
- ⬜ No LLM layer. **Reusable as the grounding layer**: any future LLM must only narrate the
  facts these modules produce. It must not compute prices or invent levels.

### C. Signal Centre: 🟡 partial

- ✅ Every setup, lifecycle transition, confirmation and market outcome is recorded,
  including invalidated and expired setups (README: "never counted as trades").
- ✅ `signal_outcomes.py` authoritative resolver; `signal_presentation.py`; Strategy Bank signals with `outcome_status`.
- ✅ Signal Quality Engine (`signal_quality/`) scores signals with a frozen model.
- 🟡 Three signal stores with different schemas (engine setups, Strategy Bank signals, cBot
  journal). There is no single "signal" record with the brief's fields
  (entry/SL/TP/RR/strategy/confidence/status/invalidation/outcome).
- 🟡 "Confidence" today is rule points / quality score, **not a calibrated probability**. The UI
  must say so.

### D. Strategy Intelligence: 🟡 partial, research-grade

- ✅ Strategy Bank: 20 experimental rule strategies with an append-only qualification registry
  (DISCOVERED → … → QUALIFIED/PRODUCTION/ARCHIVED) and a coded promotion gate on recorded
  forward evidence.
- ✅ Edge Discovery V1/V2, V3 (pre-registered, development/holdout, ledgers), cTrader
  scalper walk-forward with a cost-aware simulator, Quant Labs (multi-lab research harness).
- ✅ Transaction costs are modelled in the scalper simulator and V2/V3 research.
- 🔴 **Labelling risk (fixed in Phase 1):** registry `PRODUCTION` and
  `APPROVED_EXPERIMENTAL` read as endorsements. On the real data, two bank strategies
  (`london_breakout` +0.057R/PF 1.11 over 115; `macd_momentum` +0.071R/PF 1.11 over 98)
  clear the coded alert thresholds (60 / 0.05R / 1.10). Those thresholds have no significance
  test or multiple-testing control. Once corrected for 16 strategies tested, both have
  negative lower confidence bounds.
- 🟡 Research lives in four places (`backend/research/`, `quant_labs/`, `research_autonomous/`,
  `ctrader_scalper/engine`), and there is no single strategy catalogue across them.

### E. Execution Engine: 🟡 partial by design

- ✅ No server-side code path sends orders (a test asserts `order_send` and similar calls are
  absent from the scanner path).
- ✅ cTrader cBot: refuses `Account.IsLive` at start **and before every order**. It requires an
  activation code and the exact demo account number, and enforces daily loss, max positions, a
  consecutive-loss halt and an equity kill switch. `ExecutionUnlocked=false`.
- ✅ Forward experiment `fwd-xau-001` is prepared (0.25% risk, 1 position, 1% daily loss); the user activates it.
- ⬜ No account management, position monitoring or execution log on the server.
- ⬜ There was no shared policy for future adapters. **Added in Phase 1:** a fail-closed gate,
  an emergency stop and an audit log.

### F. Performance Analytics: 🟡 partial

- ✅ `performance.py` (setup performance by reporting day), `strategy_lab.py`, `evaluation.py`.
- ✅ Frontend journal analytics: P&L, win rate, PF, avg R, drawdown, equity curve
  (`src/behavior.js`, `src/data.js`) from imported trades.
- 🟡 These are two unconnected worlds: signal outcomes (research) and imported broker trades
  (journal). There is no daily/weekly/monthly signal P&L calendar and no account equity from
  recorded fills.

### Commercial infrastructure: 🟡 good foundation

- ✅ OIDC (PKCE, nonce, issuer checks), opaque hashed sessions (8 h), CSRF, login rate limit,
  private-beta allowlist, fail-closed market scoping (`scope_payload`), journal with optimistic versions.
- ✅ Free/Pro limits enforced server-side; billing routes return 503 (no grant path).
- 🟡 Only `free`/`pro` in the schema (CHECK constraint). The four-tier catalogue now lives in
  `product/plans.py` with a legacy mapping (`pro`→TRADER). A migration is needed before
  PROFESSIONAL/AUTOMATED can be granted.
- ⬜ No profiles, notification preferences or per-user watchlists.

### Frontend: 🟡

- ✅ Distinctive Garden constellation (3D with 2D fallback, reduced motion), Markets with
  TradingView embed and real candles, Strategy Lab, Analyst, journal, Scalper and Research dashboards.
- 🟡 Navigation ("Garden / Watch / Journal") doesn't map to the brief's 8 sections.
  `main.js` and `styles.css` are dense hand-written templates; 3 separate HTML entry points.
- 🟡 The Garden metaphor (🌱🌸🍂) suits a consumer audience. The "serious quantitative terminal"
  direction needs a decision: keep the Garden as the Overview hero and use terminal-style
  data views elsewhere (recommended), or retire it.

## 4. What can be reused (do not rebuild)

Scanner and strategy registry · lifecycle and outcome stores · JSONL index · broker time
normalisation · trade planning (net R:R gates) · Signal Quality engine · Strategy Bank and
qualification registry · research harnesses and ledgers · cBot safety gate and simulator ·
OIDC/session/CSRF/entitlement scoping · Telegram notifier · deploy scripts · Garden renderer.

## 5. What must be redesigned

1. **One signal contract** across engine, bank and cBot (Phase 4).
2. **One strategy catalogue** with product evidence tiers (started: `/api/platform/strategies/evidence`).
3. **Entitlements v2**: 4 tiers, capability-based guards instead of path allowlists in middleware (Phase 8).
4. **Frontend information architecture** to the 8 sections (Phase 2).
5. **Storage for multi-user scale**: research JSONL stays the source of truth. User-facing
   signal and performance reads need a queryable store (PostgreSQL tables fed from JSONL) before many users.

## 6. Technical debt

- `main.py` is a 1,400-line god module (app, MT5 session, scan loop, 40 routes).
- Single Uvicorn worker plus in-process threads; scanning and API share one process. Fine for
  one operator, not for SaaS load. Phase 3 should split the scanner worker from the read API.
- Research is spread across `backend/research`, `quant_labs`, `research_autonomous`,
  `audit_independent` and `ctrader_scalper/engine`, each with its own conventions.
- 54 untracked `*.log` files and ~15 report markdowns at the repository root (ignored by git
  but cluttering).
- Committed binaries: `ctrader_scalper/buildTradeDenScalper.dll` and 3 runtime `.zip`
  snapshots under `quant_labs/state/runtime_relocation/`.
- `"vite": "latest"` is unpinned, so builds are not reproducible.
- `ROADMAP.md` says "Not planned: TradeDen placing trades". That conflicts with the
  new vision; superseded for product planning by `PRODUCT_ROADMAP.md`.

## 7. Security risks (ranked)

| # | Risk | Severity | Status |
|---|---|---|---|
| 1 | 9.3 GB canonical data store inside OneDrive (already corrupted once, 2026-10-05) | High (integrity) | Open. Move via `TRADING_HUB_DATA_DIR` |
| 2 | Private mode has **no auth**; safe only on loopback. Any non-loopback bind exposes POST lifecycle/outcome routes | High if misdeployed | Documented in `backend/README.md`; needs a startup guard |
| 3 | Commercial route control is a path allowlist inside middleware. New routes default to private (good), but it is fragile | Medium | Phase 8: capability guards |
| 4 | Strategy labels could mislead paying customers (regulatory and consumer-protection exposure) | High (commercial) | **Mitigated**: evidence tiers |
| 5 | No server-side execution policy: a future adapter could bypass the safety the cBot has | High (future) | **Mitigated**: `execution_policy` |
| 6 | Telegram tokens live in `.env`/runtime JSON on disk | Medium | Acceptable for one host; secrets manager before multi-host |
| 7 | Committed DLL/zip artefacts (supply-chain review burden) | Low | Open |
| 8 | No secrets found in tracked files (pattern scan, 2026-11-24) | — | OK |

## 8. Verdict

Proceed with **evolution, not rewrite**. The engines are sound and honest. The work is to
(1) unify vocabulary and records into the six modules, (2) put a professional terminal on top,
(3) harden multi-user infrastructure, and (4) keep the evidence discipline visible to customers
as a feature: "we show every losing signal".
