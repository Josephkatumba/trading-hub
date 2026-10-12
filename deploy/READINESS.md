# Final integrity and launch readiness — 12 October 2026

## Historical recovery

Starting release: `3bca4b216c08f4d0fce873f6e5e22ccd53b8a8d2`.
Original production records were never rewritten. Fixed-length source prefixes were
copied, hashed and reread to verify backup equality while allowing later appends.
Private artifacts are outside the repository and OneDrive:
`C:/Users/katjo/.codex/visualizations/2026/10/12/01a12f5b-f478-7c01-89ad-ee1821329ec9/tradeden-integrity-20261012`.
`original/manifest.json` records sizes and SHA-256 hashes; `canonical/` contains the
clean projection, recovery journal, output hashes and raw quarantine files.

| File | Damaged lines | Clean records |
|---|---:|---:|
| setup_observations.jsonl | 81 | 237,621 |
| setup_lifecycle.jsonl | 1 | 14,784 |
| setup_confirmations.jsonl | 0 | 392 |
| market_outcomes.jsonl | 45 | 233,870 |

None of the 127 damaged lines contains a complete recoverable object or record
identifier. No price, timestamp or identity was guessed. Every damaged line is
retained byte for byte in quarantine with its original line, offset, size and hash.
The offline recovery tool can salvage complete embedded objects in future damage;
it rejects invalid UTF-8 rather than silently changing bytes.

The 2,165 additional outcome rows split into 809 repeat copies and 1,356 additional
variants with differing evidence across 1,346 conflicted keys. Copies differ only in generation metadata:
outcome_id, resolved_at, data_quality.observed_at and source_age_seconds. Source
timestamps, time provenance, prices, excursions and quality evidence remain part
of identity. The clean projection omits only the 809 copies, with journal entries
pointing to originals. Different horizons and label definitions remain separate.
Evidence variants are preserved and marked DUPLICATE_OUTCOME_CONFLICT at read
time; performance, research classification and training exclude them from verified
outcomes. No arbitrary latest/first price becomes an asserted historical truth.
Append retries now skip an existing semantic copy under a single-process lock.
Raw archives retain every original event. Executed trade records are not merged.
The clean audit found zero damaged lines, zero remaining repeat copies and zero
missing observation references for confirmations or outcomes. No executed-trade
file exists in this captured store; its absence is not manufactured trade history.

Recovery is prepared, not activated in the running legacy process. New live appends
continue in the original store. For rollout, stop the single writer, run
`python backend/recover_store.py --source <live-data> --output <new-private-directory>`,
audit its recovered directory, verify manifest hashes and reference consistency,
then point TRADING_HUB_DATA_DIR at that latest recovered directory and restart.
Never activate the older frozen projection and lose intervening appends. Keep the
original and backup immutable; indexes may be rebuilt. Do not run overlapping
writers. The cross-file snapshot is application-consistent only with the writer
stopped; the investigation snapshot was a verified prefix backup.

## Measured deployment requirements

Measured on the existing Windows laptop (14 physical / 20 logical cores,
approximately 24 GiB RAM), using the actual MT5 terminal and 16 instruments.
CPU percentages below are percentages of **one core**, not the entire laptop.
Measurements are not a substitute for a target VPS soak test.

| Workload | Actual measurement |
|---|---|
| Existing backend, 120 seconds | 3,457 MiB peak private memory; 10.61% one-core CPU |
| MT5, same observation period | 378 MiB peak private memory; 6.29% one-core CPU |
| Previous cold index reader | 2,633 MiB peak private memory |
| Streaming cold index reader | 639 MiB peak private memory; about 76% less |
| Complete worker, isolated historical clone | 4,034 MiB peak; 2,562 MiB after six scans |
| First complete scan including historical processing | 34.92 s wall, 27.31 s CPU |
| Subsequent complete scans | 0.79–1.07 s wall, 0.73–1.03 s CPU |

Cold index reads now stream individual lines instead of allocating the entire
file and split-line copies. Numeric libraries are limited to one thread at
production startup. The full-worker benchmark writes only an explicit clone;
read-only scans disable persistence. No benchmark submits orders.
Scripts: `deploy/measure-runtime.ps1` and `backend/benchmark_runtime.py`.
Six scans do not establish long-term memory stability or peak concurrent export
load. Cold startup remains materially heavier than a warm scan.

Choose **2 vCPU, 8 GB RAM, 80 GB SSD, licensed general-purpose Windows x64** as
the minimum practical launch configuration. Four GB cannot accommodate the measured
worker peak plus Windows and MT5. Six GB leaves inadequate operational headroom.
Measure daily file growth, enforce free-space alarms and retain encrypted off-host
backups. Acceptance requires an overnight soak, concurrent dashboard reads,
reboot/unattended MT5 reconnect, data freshness and backup/restore checks. Windows
licensing, region and broker latency affect price; obtain a current provider quote
before purchase. No hosting was purchased or published.

| Architecture | Cost and operational consequence |
|---|---|
| Windows VM: Caddy + frontend + API + MT5 | Recommended private launch: one host, same origin, simplest recovery. Same 8 GB floor. |
| Static frontend + Windows API/worker | CDN improves delivery and removes static traffic from VM, but does not reduce historical worker RAM or Windows licensing. Exact API CORS, secure sessions and CSRF protection required. |
| Static frontend + Linux API/Postgres + Windows feed worker | Future scaling option; adds authenticated ingestion, idempotent outbox, replay, freshness checks and another service. Not implemented or needed for private launch. |

Cloudflare Pages static requests are free and unlimited; function execution has
separate limits ([official pricing](https://developers.cloudflare.com/pages/functions/pricing/)).
For commercial user storage, Supabase Free has a 500 MB database, inactivity pauses
and no automatic backups; Pro starts at $25/month with daily backups. Keep market
archives out of a small user database ([official pricing](https://supabase.com/pricing)).
These are optional service comparisons, not purchases or endorsements.

## Authentication audit and minimal commercial plan

Current Caddy basic authentication is a single-owner gateway only. The loopback
FastAPI application has no user sessions or per-user authorization of its own;
all remote routes, including exports and documentation, depend on the gateway.
CORS is not authentication. Journal/accounts/reviews are browser localStorage and
do not persist across devices. Shared JSONL history is not a multi-tenant account
database. Current release is **not ready to sell multi-user subscriptions**.

1. Add managed OIDC login, validating issuer, audience, signature and expiry.
   Use server sessions with Secure, HttpOnly, SameSite cookies, session rotation,
   logout/revocation and CSRF/origin checks on mutations. Keep gateway protection
   until this passes review. Rate-limit authentication and costly exports.
2. Add PostgreSQL users, entitlements, journal_accounts, trades and reviews.
   Every private record belongs to a stable user UUID; enforce ownership on every
   read/write and database policy. Scope imports uniquely by user and external
   trade identity; use versioned updates for cross-device conflicts. Import browser
   records only after login and preserve the local copy until server acknowledgement.
   Share market research centrally; protect global diagnostics, dataset exports and
   mutation routes with an administrator role. One scanner serves all accounts.
3. Add server-enforced plan/expiry checks, defaulting to Free on missing or expired
   entitlement. Store Pro grants manually for initial testing. Price is $19/month;
   do not process payments or trust a client-supplied plan. Later billing webhooks
   can update the same entitlement table with idempotent event handling.
4. Test anonymous access, cross-user reads/writes, expired Pro access, logout,
   CSRF, duplicate imports, reconnect/sync conflicts and database restore before
   opening enrollment. Measure total VM, database and backup cost against subscriber
   revenue before committing to hosting.

Proposed smallest tier distinction, using existing features:

| Capability | Free | Pro — $19/month |
|---|---|---|
| Strategies | All four existing strategies | Same four |
| Instruments | Three selected instruments | All 16 |
| Research history | Seven days | 90 days |
| Journal and cross-device sync | Included | Included |
| Existing confirmation alerts | Included for selected instruments | Included for all instruments |
| Existing research exports | Basic dashboard | Export access |

Instrument/history/export gates must apply to API responses, not only UI. Retention
windows are product proposals, not permission to delete the original archive.
Do not add AI coaching, copy trading, social features or order execution for this
launch. Apply [OWASP authorization](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html),
[session](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)
and [CSRF](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html)
controls; PostgreSQL ownership policies can use
[row-level security](https://supabase.com/docs/guides/database/postgres/row-level-security).

## Remaining launch gates

Verification: 464 isolated backend tests and 164 frontend tests passed; the
production frontend build, Python compilation, PowerShell syntax checks and
`git diff --check` passed. Existing frontend bundle-size warnings remain.
All seven real-store comparison cases and eight synthetic cases passed after
correcting the test fixture's obsolete trendline-only live-view assumption.
The initial complete 15-case run passed 14 and exposed that fixture failure;
the corrected real/synthetic episode cases then passed in a two-case rerun.
The other six real cases were unchanged and passed in the complete run.
History/lifecycle ID checks use the suite's existing 40-ID sample plus final
edge IDs; episode comparisons cover all buckets and limits. No test was skipped
to hide the failure. Comparisons use byte-identical, frozen temporary copies,
never mutate live history, and are not a profitability or trading-execution test.

Public launch still requires CEO authorization, provider/domain provisioning,
secret setup, validated Caddy TLS/authentication, broker redistribution rights,
target-host soak/reconnect tests and verified off-host restore. No credentials,
private historical records or quarantine bytes are committed. Trading remains
observational; real-money execution is disabled.
