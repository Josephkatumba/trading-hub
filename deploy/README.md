# TRADEden V2 private production deployment

Commercial Phase 1 preparation: [COMMERCIAL_MVP.md](COMMERCIAL_MVP.md).
Private beta deployment and exact external requirements: [PRIVATE_BETA.md](PRIVATE_BETA.md).
The private deployment below remains available; the commercial configuration is inactive.

## Architecture and cost assumptions

Use one general-purpose Windows x64 VPS initially: MT5 terminal, Python FastAPI
engine with exactly one worker, durable indexed JSONL database, Caddy HTTPS proxy
and Vite static build. The autonomous engine scans every 30 seconds after each
completed scan; browsers read the cached scan. No laptop dependency remains once
the terminal and engine run on that server. No order submission is implemented.

Planning size: 2 vCPU, **8 GB RAM practical launch minimum**, 80 GB SSD initially,
daily encrypted off-server backup. The old observation file already exceeds 1 GB;
measure daily growth and provision capacity for retention and backups. Budget
must be obtained for an 8 GB licensed Windows VM, plus domain and backup;
the former USD 20–50 placeholder is not a verified current quote. Benchmark this broker's complete
16-symbol scan and index rebuild on the selected host before accepting its size.
See [measured readiness and commercial plan](READINESS.md) for actual local measurements,
historical repair provenance and remaining launch gates.

MT5 Python talks directly to the terminal, so a Linux web-only container does not
replace this dependency ([MetaQuotes integration](https://www.mql5.com/en/docs/python_metatrader5)).
A future Linux API with a separate Windows ingestion agent is possible, but requires
an authenticated ingestion protocol and replay/backfill support. Neither is assumed
to exist. Generic MT5 virtual hosting is not a general-purpose Python/web server.

## Prepare without publishing

1. Obtain CEO authorization for provider, cost, domain and public launch first.
2. Install Windows-compatible Python 3.14 x64, Node, MT5 and Caddy >=2.8 on the
   approved server. Clone the committed repository to `C:/TRADEden/app`.
3. Create `.venv` with `python -m venv .venv`; install
   `.venv/Scripts/python -m pip install -r backend/requirements-production.txt`.
   Run `.venv/Scripts/python backend/tests/run_suite.py` and `npm test`.
   `--with-live-store` additionally compares copies of the large historical store
   against the legacy implementation; this can take many minutes and several GB.
   Run `npm ci`; set `$env:VITE_BASE_PATH='/'` and
   `$env:VITE_ENGINE_SAME_ORIGIN='1'`; run `npm run build`.
4. Set the variables from `deploy/.env.example` in the runtime account's private
   environment. The example is documentation, not an automatically loaded file.
   Generate the password hash interactively with `caddy hash-password`.
   Restrict environment/config/log/data access to that account and administrators.
5. Stop the old engine for migration. Copy all five JSONL files from `backend/data`
   to `C:/TRADEden/data`; compare SHA256 hashes before and after the copy. Retain
   the untouched original. Omit `.index` sidecars; they rebuild automatically.
   Do not put runtime storage under OneDrive. Run
   `.venv/Scripts/python backend/store_audit.py --data-dir C:/TRADEden/data`.
   Existing damaged records cannot be reconstructed from missing bytes. Audit
   outputs contain only counts. Never rewrite history to make the audit pass.
6. Log into MT5 under a dedicated Windows account, preferably with a read-only
   investor password. Disable terminal AutoTrading and Python trading. Verify the
   broker time basis rather than copying the previous broker setting blindly.
7. Run `powershell -NoProfile -File deploy/start-engine.ps1`. Test local radar,
   `/api/health`, `/api/ready`, strategies, history and performance. Compare counts
   with the old store. Do not launch a second engine against the same store.
8. Validate Caddy using `caddy validate --config deploy/Caddyfile --adapter caddyfile`.
   This does not launch the listener. Caddy is not installed in the recovery
   workspace, so server-side configuration validation is an acceptance gate.

## Approved launch and restart policy

After authorization, point domain DNS to the host, open only ports 80/443, and
start Caddy with `caddy run --config deploy/Caddyfile --adapter caddyfile`.
Caddy provisions and renews certificates automatically when DNS/ports are correct
([HTTPS requirements](https://caddyserver.com/docs/automatic-https)). All dashboard
and API routes require the configured user's hashed password
([authentication](https://caddyserver.com/docs/caddyfile/directives/basic_auth)).
The engine binds loopback only; block 8000 externally. Restrict RDP to VPN/admin IPs.
The production build uses the same-origin API on HTTPS, including browsers that
previously saved a laptop engine URL.

Use Windows Task Scheduler under the **same dedicated user as MT5**: trigger at
logon, restart on failure every minute, unlimited execution time, no overlapping
instances, and start MT5 before the engine. Keep that session alive when RDP is
disconnected; do not log out. MT5 session behavior varies by broker/server: a full
reboot and unattended reconnect test is mandatory. Do not assume a session-0
Windows service can reach a terminal in another user's desktop. Caddy may run as
a service with the environment above and persistent certificate storage.

Schedule `deploy/check-health.ps1` every minute. Nonzero means stale/offline,
storage failure or missing scans. Wire its result to the approved monitor; alert
on sustained failure, disk below 20%, memory pressure and backup failure. Closed
markets may make scan health ready while tick quotes are stale; qualifications
still fail closed. Monitor quote freshness during the instrument's open hours.
Store engine stderr/stdout in rotating logs with ACLs; do not publish diagnostics.

## Backup, restore and rollback

Stop the engine for a consistent copy of all five files. Encrypt daily backups
outside the server; retain 7 daily and 4 weekly versions. Restart immediately.
Test a restore into a separate directory monthly, run the streaming audit, rebuild
indexes and check historical counts. Snapshot the store before upgrades.
Rollback code by checking out the previous release **after stopping the engine**;
keep the same immutable source records. Use a restored snapshot for incompatible
schema changes, never overwrite the only live copy.

## Scope and subscription path

The initial deployment is a private single-owner dashboard with gateway user
authentication. Journal/account imports remain browser localStorage and do not
sync between devices. The persistent server database is the existing indexed
append-only JSONL store, not SQL: preserving its historical identity is deliberate.
One process is required; no horizontal writers are supported.

Before subscription access: replace gateway credentials with OIDC sessions,
add server-side users, memberships, plan/entitlement checks and per-user journal
storage in PostgreSQL, then enforce ownership on every private record and write
route. Market observations can remain shared public-market research, with separate
executed-trade records scoped to users. Use stable existing strategy/setup IDs
as migration keys. No payments, subscription claims, multi-user isolation or
profitability guarantees are implemented in this release.

Public launch remains blocked until authorization, provisioned server/domain,
secret configuration, Caddy authentication/TLS checks, broker data rights,
restart tests and backup restore checks are complete.
