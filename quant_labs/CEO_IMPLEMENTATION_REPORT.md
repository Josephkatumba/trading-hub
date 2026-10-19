# TradeDen — Three Independent Quant Labs

CEO implementation report · **20 October 2026, Nairobi**

**First implementation milestone complete as an isolated local prototype. No production deployment or live integration has occurred.** Codex, Claude Code and Kimi have distinct development workspaces and application-level capabilities. Claude and Kimi agents have not been launched; their workspaces remain empty and ready for actual independent sessions. No strategy is certified profitable or promoted.

## Executive assessment

The architecture supports independent ownership and a single frozen measurement contract. Lab submissions cannot set outcome labels, choose favorable costs, edit another lab’s registered versions/results, execute source code inside the evaluator, certify their own profitability, or activate production. A trusted operator runs bounded foreground jobs; results, rejected ideas and duplicate attempts remain auditable.

**Material boundary:** isolation is enforced by the control-plane interface and by refusing to execute submitted code. It is **not OS-level sandboxing of unrestricted same-Windows-account shells**. A shell with direct file access can bypass application scopes or remove read-only attributes. Before connecting mutually untrusted autonomous shells, provision separate Windows identities/ACLs or containers. No such identities, containers or external-model sessions were created by this milestone. This limitation is explicit rather than presenting directory separation as a security boundary.

## 1. Existing architecture and design choice

The existing platform already has production signal engines, Strategy Bank/Strategy Lab measurement, older research backtests and an independent audit/research framework. The existing frontend and backend were left unchanged. The corrected `research_autonomous` execution contract is reused in a separately frozen evaluator, with its New York timezone data packaged locally for isolated Windows workers.

The new package, `quant_labs/`, is intentionally separate from production imports, MT5 initialization, Telegram clients and existing app routes. This allows concrete review and tests before any integration. Prior Codex research is imported only as source/provenance, not silently certified under the new common engine. No prior Claude/Kimi research is invented or relabelled.

## 2. Three laboratories

| Lab | Workspace | Registered versions | Active jobs | Status |
|---|---|---:|---:|---|

| Codex Quant Lab | `state/labs/codex/` | 6 | 0 | Five imported research hypotheses plus one infrastructure contract fixture; no new edge claim. |

| Claude Quant Lab | `state/labs/claude/` | 0 | 0 | Empty, provisioned for an actual independent agent; no research run. |

| Kimi Quant Lab | `state/labs/kimi/` | 0 | 0 | Empty, provisioned for an actual independent agent; no research run. |


Each workspace contains `strategies/`, `notes/`, `AGENTS.md`, a lab-only capability, a registry export, experiment history and performance export. The canonical central ledger uses `(lab, strategy ID, version)` keys and hashes source code. Updates/deletions of registered versions or recorded performance are prohibited by SQLite triggers. New ideas and versions are unrestricted in count; bounded per-run inputs and queues control computational load.

Research freedom includes any methodology supported by actual data, rather than restricting labs to the original four strategy families. All variants and failed trials must remain documented. Reviewable source/specification size limits and per-job intent limits protect resources; they do not limit the number of strategy families. Exact repeated economic intent streams are deduplicated across labs and reference the first evaluation instead of pretending to supply independent evidence.

## 3. Common frozen evaluation and accounting

Evaluator version: `tradeden-shared-eval-1.0.0`

Evaluator identity: `bbc0c08a5728abca935bc95db1d5d85a773a93e8042309d192ff3dd56a736c8b`

The identity covers the engine, cost policy, accounting metrics, corrected execution implementation, timezone data and trusted worker/control interfaces. A mismatch or unlisted evaluator file fails verification. Each job pins this identity and the dataset. Future changes must get a separately reviewed contract/version; no lab can select or silently modify its own accounting.

| Required measure | Implemented contract |
|---|---|
| Planned and realized R:R | Planned executable reward/risk and 2R/3R/4R/5R/7R+ bands; realized mean net winning-R / mean losing-R. These are different quantities. |
| Win rate and expectancy | Positive net outcomes among resolved trades; mean net R with all unknown outcomes separately counted. No unknown-to-zero conversion. |
| Costs and stress | Bid/ask entry/exit sides, conservative tick rounding, worse stop-gap fills, explicit assumed commission/slippage and current swap proxies; doubled spreads/adverse costs and no financing credits in stress. |
| Profit factor, drawdown, streaks | Net gains/losses, realized-exit additive R drawdown, longest negative-outcome streak. Floating and unknown risk is explicitly excluded, not concealed. |
| Frequency and completeness | Attempts, resolved/unknown/status counts, opportunities per month, complete fraction, missing-data rejection counts and per-market data-quality records. |
| OOS evidence | Fixed chronological train/validation/test intervals with split-crossing trades purged. The underlying cache was exposed to earlier research; this is not pristine future evidence. |
| Forward results | An explicit NOT_STARTED/null status. No historical replay is relabelled prospective, and prospective capture/commitment integration remains disabled. |
| Statistical uncertainty | Entry-week block bootstrap intervals and exploratory weekly sign-flip p-values, plus a pooled Holm correction over declared variants and unique experiment attempts across laboratories. |
| Correlated/overlapping opportunities | Same-strategy/symbol overlaps are rejected; weekly blocks retain same-week dependence. Multi-asset aggregate metrics are standalone equal-risk outcomes, not a validated portfolio or broker equity curve. |

No 60–70% win-rate promise or minimum profitable-looking result is used. The common engine accepts correctly ordered plans and reports their actual R geometry; it does not tighten stops, extend targets or choose favorable sequencing to reach aspirational targets. Planned 7R or 9R alone says nothing about hit probability or expectancy.

### Execution and statistical limits

The evaluator reconstructs entry prices from recorded bid-open plus spread. Submitted source is retained for independent review but never executed in the worker. Therefore arbitrary lab strategies remain possible, while common fill/accounting rules remain fixed. **Historical intents alone cannot prove causality or detect selective omission**: source review, complete trial disclosure and prospective intent commitment are still mandatory.

The frozen commission schedule and slippage assumptions are research proxies, not certified historical account charges. Broker bar spread is not a full ask OHLC/tick reconstruction. Financing uses current snapshot modes supported by the reference contract; missing currency conversion fails closed at rollover. Session calendars are not inferred from gaps. Ambiguous ties, partial-entry uncertainty, missing execution paths and incomplete histories stay visible.

The weekly sign-flip test assumes symmetric weekly outcomes and does not fix censoring, cross-week dependence or undisclosed prior experiments. Holm family counts pool all three labs, including imported declared variants; these counts are only as complete as disclosure. No p-value automatically authorizes a profitability certificate, shadow feed or production change.

## 4. Shared market data

Dataset identity: `bf130602dca4f955f64160bc9b85f0bc4246195f9685afbde91d1856c2c62cd3`

The content-addressed snapshot contains **80 compressed files**, **2,777,725 validated completed bars**, and about **51.0 MiB** of compressed history across 16 supported instruments and M1/M15/H1/H4/D1 timeframes. All nine requested priority instruments are included. Original broker caches were read only and not overwritten. Shared blobs/manifests are immutable by API, hash-verified and marked read-only as an additional accidental-write guard.

Raw timestamps, normalized UTC, source metadata, bid OHLC, recorded spreads and tick-volume fields are preserved. Validated reads exclude malformed/duplicate/future/forming bars and retain gap counts. Broker session/holiday calendars and historical ask extremes remain unverified. Missing paths cannot establish a first TP/SL hit. MT5 tick volume is never represented as centralized traded volume. All laboratories read the same snapshot identity; there is no per-lab favorable dataset substitution.

## 5. Lifecycle, independent review and permissions

IDEA → RESEARCH → BACKTEST → HISTORICAL_VALIDATION → SHADOW_FORWARD_TEST → INDEPENDENT_REVIEW → CEO_APPROVAL → PRODUCTION.

The ledger stores research-stage events and rejected variants. Backtest and historical-validation labels mean measurement completed, not edge certified. Researchers cannot skip to independent review, CEO approval or production. A separate reviewer capability must belong to a different lab and can record rejection, data requirements or pending-forward review notes. It cannot create a profitability certificate. Prospective capture and promotion are deliberately inactive at this milestone.

| Principal | Granted scope | Not granted |
|---|---|---|
| Lab researcher | Register/version own source/specs; submit own intents; pause/resume own jobs; preserve/reject own hypotheses; read shared public evidence | Other labs’ writes, evaluator/data changes, worker launch, self-review, CEO approval, alerts, orders |
| Trusted operator | Explicit single-worker execution and queue pause/resume | Automatic strategy promotion, production/Telegram integration |
| Independent reviewer | Document another lab’s completed evaluation, with evidence | Review own lab or bypass forward/CEO gates |
| CEO capability | Reserved separately for a future approved governance integration | No production activation path is implemented in this prototype |

Owner/reviewer credentials are kept outside development workspaces; no credential is exposed by the dashboard or included in this report. Agent capability tokens are provisioned, but external Claude Code and Kimi tool sessions still need to be attached by the owner. API-scoped tokens do not constrain a direct same-account filesystem shell.

## 6. Local research dashboard prototype

The self-contained `dashboard.html` opens without a server. The optional preview binds only `127.0.0.1` on its own port and offers a GET-only snapshot endpoint. No existing TradeDen route, feature or public hosting configuration changed. Browser checks verified desktop rendering, a 390px mobile layout without horizontal page overflow, lab filtering, the qualified empty state, accurate prior-research counts and no script errors. Screenshots are retained.

The prototype shows all three laboratories, registered versions, active and rejected work, historical provenance, a research leaderboard, a qualified leaderboard, forward status, queue history, evaluator/data identities and recorded resource use. The five prior Codex hypotheses are clearly labelled as prior research awaiting common evaluation; infrastructure checks are excluded from the research leaderboard. Claude/Kimi counts remain zero. Both qualified and prospective-result views remain honestly empty.

The UI is read only. Queue operations work through the authenticated local control plane; no fake run/pause buttons or uncontrolled background loops were added. This is a reviewable local prototype, not a production dashboard integration. Large-scale deployment would need paginated data views, retention/disk policies and additional authentication/OS deployment work.

## 7. Resource controls and queue durability

| Control | Enforced behavior |
|---|---|
| Parallelism | One running job across the shared queue; one process inside the Windows Job Object; sequential foreground execution. |
| CPU | Windows hard cap of 20% machine CPU, below-normal priority, 20 user-mode CPU seconds per worker segment. |
| Memory | Windows committed-process-memory cap: 384 MiB default, operator policy range 64–512 MiB. This is not a claim about total machine memory or every future tool an external AI launches. |
| Wall time | 30 seconds default, 45 seconds maximum per segment, controller kill on timeout and a secondary worker watchdog. |
| Queue/input budgets | Eight pending/paused jobs per lab, 2,000 intents per experiment, bounded source/spec uploads, at most 20 resume segments per job. No fixed strategy-count cap. |
| Pause/resume | Persistent queued pause, active-worker checkpoint request, atomic checkpoints, explicit resume against the same immutable request/data/evaluator. |
| Persistence | SQLite canonical state, immutable results, append-only events and per-lab exports; killed/timed-out/failed states remain visible. |

There is no daemon, scheduler, cron job, public server or live-engine connection. External laboratory research code is not launched by the queue; its own process/tool limits must be enforced separately before granting broad autonomous execution. The local dashboard is a small preview, not yet a hardened multi-user service.

Windows limit semantics follow [Microsoft’s CPU-rate-control documentation](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_cpu_rate_control_information) and [committed-memory job limits](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_extended_limit_information). Their effectiveness was checked on this laptop, not assumed from configuration alone.

## 8. Verification evidence

**27 isolated tests passed**. They check cross-lab write denial, distinct registries, version/result immutability, malformed intent/path rejection, common accounting across all three lab identities, duplicate detection, shared-data tamper detection, frozen evaluator identity, unknown-outcome accounting, queue quotas, pause/resume persistence, checkpoint equivalence, global pause, no self-review/production bypass, real worker caps, an actual memory-overrun attempt, an actual hard timeout, and read-only localhost routes. The localhost/browser checks required a permitted test rerun outside sandbox restrictions; they passed.

**6 browser checks passed**; desktop and mobile screenshots were visually inspected.

A Codex-only infrastructure fixture submitted **54 intents** across the nine priority markets and planned 2R, 3R, 4R, 5R, 7R and 9R cases. It completed with **53 resolved and 0 unknown** outcomes under the same evaluator. This fixture is expressly not research or evidence of an edge. Measured resource usage:

- Wall time: **6.65s**.
- Process CPU time recorded: **6.61s**.
- Peak committed process memory: **114.95 MiB**, within the **384 MiB** cap.
- Queried OS CPU cap: **20%**; queried maximum processes: **1**.

The tests exercise synthetic identities for isolation/accounting only; they do not represent actual Claude or Kimi strategy research. Actual stored research workspaces for those labs remain empty. Qualified strategies: **0**. Verified prospective forward results: **none**.

Pre-trade checks rejected 1 of the 54 submitted intents: {'invalid_levels_or_spread_cost': 1}. These are separate from the 53 evaluated outcomes, so every intent is accounted for. No rejected fixture was silently converted into a trade or omitted from the request history.

## 9. Integration handoffs and reproducibility

Read `docs/INTEGRATION.md` for schemas, entry-time assumptions, common data/cost rules, scoped commands, queue controls and lifecycle limits. `docs/CLAUDE_HANDOFF.md` and `docs/KIMI_HANDOFF.md` are ready for actual sessions. Each lab also has explicit workspace instructions. No message was sent to another chat or agent.

From the repository root:

```text
python -m quant_labs.bootstrap
python -m quant_labs.validate
python -m quant_labs.preview --export
python -m quant_labs.preview --port 8766
```

Bootstrap is idempotent and does not rewrite existing registered versions, lab tokens or research notes. The optional server is a foreground process; stop it with Ctrl+C. Worker execution requires the operator capability and an explicit `run-one` command documented separately. Do not expose owner credentials to research agents.

Evidence: `verification/tests.json`, `verification/dashboard-tests.json`, `verification/smoke.json`, desktop/mobile screenshots, the pinned evaluator manifest and shared-data manifest. Existing audit/research directories and all production source/configuration remain intact.

## 10. What is ready, and what must come next

**Ready now:** three independent logical lab workspaces and permissions; versioned registries; shared hash-pinned validated data; frozen common accounting; declarative submission interfaces; pooled trial accounting; controlled foreground queue with tested resource limits/pause/resume; read-only local dashboard; Claude/Kimi integration instructions.

**Not activated:** actual Claude/Kimi model sessions, unrestricted autonomous source execution, prospective live feed/commitment collection, independent profitability certification, CEO promotion workflow, production dashboard integration, experimental Telegram alerts or real orders.

Recommended sequence:

1. Review this prototype and choose an OS containment model before attaching mutually untrusted agent shells. Keep application scopes even after adding OS isolation.
2. Attach actual Claude Code and Kimi sessions to their own workspaces and capabilities; let each choose genuinely independent hypotheses, with source/variant disclosures. Codex should use the same contract.
3. Add precommitted prospective shadow capture and immutable quote evidence. Do not turn historical intent lists into a qualification substitute.
4. Independently review causal source, execution feasibility, data gaps, search history, out-of-sample stability and cost-stressed uncertainty; reject weak candidates without forcing a winner.
5. Prepare a concrete production integration/migration diff, regression tests, resource/retention plan and rollback for CEO review. **Obtain explicit approval before changing live permissions, alerts, trading or public dashboard behavior.**

No laboratory or strategy winner is declared. The milestone establishes a common measurement and governance boundary while keeping its remaining limitations visible.
