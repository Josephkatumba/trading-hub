# Commercial MVP Phase 1

This extends `fa651dc8e4a7d5bdd380207e9a54552634c2edaa`. The existing private
deployment and historical evidence remain intact. No services, billing, live
trading or public deployment have been activated.

## Trade planning

The low R:R values had several causes: strategies calculated levels from a closed
bar while execution uses the current ask/bid; spread and subsequent movement reduce
reward; genuinely shallow structural targets cannot support a trade. Such patterns
remain useful observations and must not be forced into qualified trades.

Trendline retains its H1 swing target and M15 invalidation, S/R its next zone edge
and rejection invalidation, and SMC its liquidity swing and order-block invalidation.
Trend/Momentum retains its measured impulse target, capped at a nearer intervening
closed H1 swing when available. Stops never move inward; targets never extend.
Broker tick-size rounding is conservative, including fractional tick sizes. Original
strategy levels are retained in `plan_evidence.pattern_plan`. Historic records are
not recalculated or rewritten.

`TRADING_HUB_MIN_NET_RR` defaults to 1.5 and cannot be lower; 2R is preferred.
Executable prices include spread. Additional commission/slippage is configurable
globally or by symbol in **price units**, deducted from reward and added to risk.
The zero default is explicitly an assumption, not a broker cost estimate. Configure
verified instrument costs before making net-return claims. Fresh, verified quotes,
ordered barriers and strategy confirmation are still required. Pattern strength and
pattern confirmation are separately reported; an unqualified plan remains visible.

## Charts

Markets is separate from Garden. The optional official TradingView advanced widget
uses explicit vendor symbol mappings; its quotes can differ from the broker. It does
not feed scanner decisions. The TRADEden chart uses Lightweight Charts 5.2 with
verified UTC MT5 candles, bounded requests, overlays and observation/confirmation
markers. Historical outcome markers use the recorded evaluation horizon, not an
invented intrabar hit time. Conflicted outcomes stay excluded. No scraping or paid
chart dependency is introduced; TradingView attribution remains present.

Integration references: [official widget documentation](https://www.tradingview.com/widget-docs/widgets/charts/advanced-chart/),
[Lightweight Charts](https://tradingview.github.io/lightweight-charts/docs),
and the [GER40 reference symbol](https://www.tradingview.com/symbols/CAPITALCOM-GER40/).

## Accounts and proposed tiers

Auth0-compatible OIDC authorization-code login uses PKCE, state, nonce, signed
ID-token validation and opaque database-backed sessions. Cookies are Secure,
HttpOnly and SameSite=Lax. Writes require CSRF tokens. User journals (trades,
accounts, reviews) are keyed by the authenticated user and use optimistic versions;
another device's changes cannot silently overwrite a record. Commercial builds do
not bundle the owner's imported trades or automatically import browser history.
The original local/private mode remains available behind the existing owner gate.

| Tier | Server-enforced market access | Journals | Export | Proposed price |
| --- | --- | --- | --- | --- |
| Free | XAUUSD, EURUSD, GBPUSD; 7-day market history | Persistent user-owned records | No bulk API export | $0 |
| Pro | All supported markets; 90-day market history | Persistent user-owned records | Paginated journal API export | $19/month |

Journal history is not discarded when a Pro grant expires. Shared executed-trade
history and private research/admin endpoints are withheld from commercial users.
Entitlement filters run on the server, including before performance aggregation.
The export API is prepared; a customer-facing download button is a later small UI task.

Checkout and webhook endpoints remain disabled. The minimum next billing work is
provider checkout/portal wiring and signed, idempotent webhook verification which
updates server entitlements from subscription state. Test cancellation, retries,
expiry and refunds in provider test mode before activating billing. Do not let a
browser request grant Pro. No unnecessary premium features are required.

## Production preparation

Use the existing Windows MT5 worker and one backend process. Keep JSONL market
history and its backups separate from PostgreSQL user storage. The previous measured
Windows recommendation remains 2 vCPU / 8 GB RAM / 80 GB SSD, subject to real server
load tests. PostgreSQL may be local or remotely hosted with verified TLS; no hosting
has been purchased. Same-origin HTTPS frontend/API is the simplest cookie deployment.

1. Create an Auth0 Regular Web Application with callback
   `https://YOUR_DOMAIN/api/auth/callback`; configure its application origin and
   secure recovery/MFA policy. OIDC discovery issuer must match the configured issuer.
2. Use `commercial.env.example` as a template. Generate unique secrets; keep them
   outside the repository and browser build. Protect DB backups and service credentials.
   Verify the broker timezone rather than guessing. Keep API bound to loopback.
3. Install `backend/requirements-production.txt`. Set the database URL in the
   protected shell/service environment. Run `python backend/commercial_store.py migrate`
   once before starting the application. This idempotent version-1 migration creates
   users, sessions, entitlements and owner-keyed journals. The equivalent PostgreSQL
   DDL is `backend/migrations/0001_commercial.sql`; use one migration method, not both.
4. Build with `VITE_AUTH_REQUIRED=1`, `VITE_ENGINE_SAME_ORIGIN=1`, `VITE_BASE_PATH=/`
   and `npm run build`. Only these public Vite values belong in the frontend environment.
   Configure `deploy/start-engine.ps1` with `TRADING_HUB_AUTH_MODE=oidc`.
5. `Caddyfile.commercial` is prepared but inactive. First validate in protected
   staging with real PostgreSQL, issuer credentials and HTTPS. Retain the existing
   owner-gated configuration until acceptance is complete. Access logging excludes
   authorization callback parameters. Health and ready endpoints remain available.
6. Back up both PostgreSQL and JSONL; test restore and retention. For a temporary
   manual Pro test, use `commercial_store.py grant-pro --user-id UUID --expires-at UNIX`
   with a future expiry in an administrator shell. This is not billing activation.

## Verification boundaries and launch gates

Local tests cover all four strategies, precision/cost gates, real RSA ID-token
validation, the OIDC PKCE/state/callback flow, CSRF, session revocation, ownership,
conflicting journal saves, entitlement expiry and PostgreSQL DDL compilation.
Database persistence tests use SQLite; a real PostgreSQL service is unavailable here.
The browser test renders the actual Lightweight Charts canvas with fixture candles,
checks selections/mobile layout and Garden navigation. The vendor embed script is
stubbed in the test; live TradingView availability is an external staging check.

Before public release: connect a real OIDC tenant and PostgreSQL database; complete
two-account/two-device HTTPS acceptance, real broker chart checks, database restore,
rate/load and security review. Login limiting is per process; production uses one
worker. Configure provider-level abuse protections and restrict administrator access.
Live trading remains disabled. Historical quarantine and original backup hashes must
continue to pass `backend/verify_evidence.py`; never publish those private artifacts.

Local verification results: full backend suite ran 484 tests, passing with 7 real-store
comparisons skipped in that isolated run; all 15 historical comparisons passed separately
on byte-identical canonical copies. The final 14 commercial tests passed, including
concurrent same-user callbacks. All 168 frontend tests and 2 browser tests passed.
Private and commercial production builds passed; the existing large 3D bundle warning
remains. Evidence checks verified 4 original files, 4 canonical files and 127 raw
quarantined lines unchanged. Audit found no missing observation references or exact
outcome copies; 1,356 conflicting extra variants in 1,346 keys remain preserved and
excluded from verified results.
