# Private beta acceptance and deployment

Prepared from commit `8d7fba671766a4c38998f1e0e69c5e5ac7331405` on
`codex/commercial-mvp-phase1`. This repository is prepared, not deployed. No hosting,
tenant, PostgreSQL service, domain or VPS credentials have been supplied. No billing,
public release or trading execution is activated.

## Changes and protection

Private beta requires an explicit OIDC subject allowlist. Login callbacks and existing
sessions both enforce invitations, so removing a subject blocks the session's next
request. Identity subjects remain server-side; users cannot grant themselves Pro.
Free/Pro ownership, history/symbol scopes and CSRF remain enforced by the server.

`/api/market/opportunities` returns only live-strategy, qualified plans from a fresh
scan. It rechecks quote age, ordered levels, execution costs and minimum net R:R.
Historical confirmations stay research evidence, not current trading instructions.
Developing observations remain visible. The dashboard's old observation-only
"opportunity map" wording has been corrected. All four strategies remain registered.

Readiness now checks the commercial schema as well as scanner freshness; database
failure returns a redacted 503. No account details or connection strings are returned.
The Windows supervisor restarts only its own engine process tree after sustained
failure, with a 10-minute warmup and 30-second restart backoff. It never kills other
Python processes or MT5. MT5 initialization can target an explicit installed terminal
and reconnect when that terminal disappears. No trading methods are invoked.

## Exact external requirements

1. **Windows VPS:** a licensed Windows x64 machine, initially 2 vCPU / 8 GB RAM /
   80 GB SSD, private administrator access and a dedicated runtime user. Install
   Python 3.14, the pinned production dependencies, MT5, PostgreSQL/client tools
   (or a secured external PostgreSQL service), and Caddy. Keep backend port 8000
   loopback-only; restrict RDP to VPN/admin addresses. No purchase has been made.
2. **OIDC tenant:** create an Auth0 Regular Web Application. Provide issuer, client
   ID and server client secret through protected runtime configuration. Set callback
   exactly to `https://BETA_DOMAIN/api/auth/callback`. Enable only intended identity
   connections; disable open signup for the beta. Obtain invited users' exact `sub`
   values from the provider administrator interface; populate the subject allowlist.
   Configure recovery, abuse protection and administrator MFA. Provider integration
   uses [authorization-code login with PKCE](https://auth0.com/docs/get-started/authentication-and-authorization-flow/authorization-code-flow-with-pkce).
3. **PostgreSQL:** provision database and restricted application credentials. Use
   `postgresql+psycopg://...` in protected configuration; external connections require
   `sslmode=verify-full` and a trusted root certificate. URL-encode special password
   characters. Run `python backend/commercial_store.py migrate` once as the schema
   owner, then use a separate application role with SELECT/INSERT/UPDATE/DELETE on
   users, sessions and journal, plus SELECT on entitlements and schema_migrations.
   Manual Pro grants use administrator credentials, not the application's role.
   Never use a PostgreSQL superuser for the application. Migrate under one owner only.
4. **Domain/HTTPS:** provide a beta domain and DNS pointing to the VPS. Validate
   `deploy/Caddyfile.commercial` on the server before activation. Set Caddy's domain
   and static-build root through its protected service environment, retain its
   certificate storage, and allow certificate issuance on 80/443. The app's protected
   data is invite-only even though its sign-in shell can be reached. Activation awaits
   the designated host/configuration; nothing was published from this workspace.
5. **Broker:** install/log in to the intended MT5 terminal under that same runtime
   user, preferably with an investor/read-only login. Disable terminal AutoTrading
   and Python trading. Set the exact terminal executable path. Independently verify
   server time basis, symbol contract/tick sizes, and data redistribution rights.
   Review round-trip commission/slippage per instrument in price units. Spread uses
   the actual bid/ask automatically; no arbitrary estimates are fabricated. Set
   `TRADING_HUB_EXECUTION_COSTS_REVIEWED=1` only after documenting those assumptions.
6. **Backups/monitoring:** supply an encrypted off-server backup location, retention
   policy and alert destination. Archive original recovery evidence separately; do
   not place it in the web root. Reserve disk space for growing JSONL records.

## Installation sequence (on the designated VPS only)

- Copy `private-beta.runtime.example.json` into a protected directory outside the
  checkout/OneDrive; replace all placeholders. Restrict ACLs to the runtime user and
  administrators. Generate a unique random session signing secret of at least 32
  characters. Never commit the completed file or expose it in frontend Vite settings.
- Load server settings with `deploy/load-runtime.ps1 -ConfigPath PATH`. The loader
  parses JSON as data, never evaluates code or prints secret values. Run the explicit
  database migration, then `python backend/beta_preflight.py --online`. It must report
  every check true: config, secure connection, discovery metadata and schema. It
  does not prove real login; the two-account acceptance below does.
- Build with only public build flags `VITE_AUTH_REQUIRED=1`,
  `VITE_ENGINE_SAME_ORIGIN=1`, `VITE_BASE_PATH=/`. The owner's imported trades are
  excluded. Set Caddy's `TRADEDEN_DOMAIN` and `TRADEDEN_WEB_ROOT` separately.
- Run `register-beta-task.ps1 -ConfigPath PATH -RuntimeUser USER` to preview; pass
  `-Install` to register on the VPS. The task runs at that user's interactive logon,
  allows no overlapping runs, and restarts after supervisor failure. It is not
  registered on the CEO's laptop by this work.
  Invoke local reviewed scripts with `powershell -NoProfile -ExecutionPolicy RemoteSigned
  -File SCRIPT ...`; this sets only that process policy, not the machine's policy.
  Review/unblock downloaded release scripts on the designated server or sign them
  under your administrator's policy. Enterprise policy can override this setting.
- MT5 requires the correct user's Windows session. Disconnect RDP instead of logging
  out. After reboot, that session must be re-established via an administrator-approved
  protected sign-in mechanism. Task registration alone does not create that session.
  Test a full reboot and network interruption. Do not assume session-0 service access
  or unattended restart until those tests pass.
- Activate HTTPS only on the authorized private-beta host after preflight and local
  checks pass. Connect from two invited accounts on separate devices; verify journals
  remain isolated, Free cannot obtain Pro markets/export, expired Pro falls back to
  Free, an uninvited identity gets 403, and removing an invite blocks its old session.

## Backup and failure acceptance

Use `backup-postgres.ps1 -ConfigPath PATH -BackupDirectory PATH` with PGHOST, PGPORT,
PGUSER, PGDATABASE and an ACL-protected PGPASSFILE. No password is passed on the
command line. It produces a custom archive, checks its table listing, and records a
SHA-256 checksum. A listing is not a restore test. Restore into a **new separate
database** using `pg_restore --exit-on-error --no-owner --no-acl --dbname=BETA_RESTORE
ARCHIVE`, migrate/verify schema, and test known user-owned records and counts there.
Do not restore over production. See [PostgreSQL archive documentation](https://www.postgresql.org/docs/current/app-pgdump.html).
For stronger recovery objectives, add managed/PITR backups; daily dumps alone lose
changes since the last backup. Back up cluster roles separately where applicable.

For JSONL, stop the designated scanner before copying the five market-history files
to a fresh backup directory; restart and audit a separate restored copy. Keep raw
quarantine and original manifests unchanged. Never replace the live store with the
canonical projection without a stopped-writer migration and explicit count checks.

Schedule redacted health checks every minute and database backup daily. Alert on
sustained readiness failures, backup failures, disk below 20% and memory pressure.
Protect and retain rotated supervisor logs; define cleanup retention on the VPS.
The supervisor recovers from process/stale-scan failure, not incorrect secrets or
an absent interactive Windows session. Those require an administrator.

## Local verification versus deployment acceptance

Local automatic tests cover invite revocation, missing configuration, database
readiness failure, current-qualified opportunities, existing isolation/entitlements,
all four strategy fixtures, market-data reuse/reconnection and browser chart rendering.
The broker probe uses a disposable store and cannot modify live historical evidence.
The local broker check connected to 15 available instruments, ran all four live
strategies, returned 100 verified-UTC XAUUSD/M15 candles and reconnected successfully.
Missing or low-R:R plans remained unqualified; no targets were fabricated. These
results validate this terminal, not the as-yet-unprovisioned VPS or its cost schedule.
PostgreSQL migrations are compiled and tested using SQLite; real PostgreSQL
migration/backup/restore and actual OIDC HTTPS login still require external services.
The browser tests render real Lightweight Charts with fixtures; TradingView's official
script is stubbed, so vendor network/rendering is a final beta-host check.

The VPS architecture moves the terminal, scanner, database and web server away from
the laptop. Laptop independence is ready in configuration, but must be demonstrated
by a VPS reboot followed by successful scans while the laptop is powered off.

Verification for this change: backend 490 tests run, OK with 7 real-store comparisons
skipped; targeted beta 4/4 and commercial 15/15 passed. Frontend 168/168, browser
2/2 and commercial production build passed. PowerShell scripts parsed and scheduled
task preview passed without installation. Evidence checks verified 4 backup files,
4 projection files and 127 quarantine lines unchanged. The expensive real-store
read-comparison suite was not repeated because no historical read/write implementation
changed; its prior 15/15 result remains the baseline. Real PostgreSQL and VPS
backup/reboot acceptance remain unexecuted, not claimed as passing.
