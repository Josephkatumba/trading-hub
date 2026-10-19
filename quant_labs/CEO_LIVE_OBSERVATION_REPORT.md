# CEO report — live MT5 paper observation

**20 October 2026 · Africa/Nairobi**

**Result:** the live paper consumer is enabled and running. Genuine MT5 data reached the actual Codex Compression Escape 0.1.0 executable. **Zero genuine detections, zero qualified paper signals and zero experimental Telegram previews** occurred during this bounded observation. No opportunity was injected or forced.

The engine remains running locally after the observation. Experimental outbound delivery and broker execution remain disabled. No public deployment was performed.

## Requested findings

| Question | Observed result |
|---|---|
| Consumer started? | **Yes.** Controlled graceful restart from PID 24752 to 40304; `TRADEDEN_QUANT_LIVE_ENABLED=1` persisted for subsequent local starts. |
| Genuine MT5 data reached Codex? | **Yes.** Existing shared collector supplied 16 instruments. The actual bounded model evaluated BTCUSD, ETHUSD, EURUSD, GBPUSD and GBPJPY. Source/version hashes match the registered executable. |
| Genuine signals? | **0 detections; 0 qualified paper signals.** The database contains no fabricated or synthetic signal records. |
| Planned RR and status? | Model status **EXPERIMENTAL**, scanning enabled, alert permission disabled. With no signal, entry/SL/TP and planned/net planned RR are **not applicable**. Qualification retains the minimum **1:2 net planned RR** gate. |
| Genuine Telegram previews? | **0**, because no genuine signal qualified. Formatting, identity, authorization and duplicate prevention were not exercised on a genuine live alert in this window; earlier synthetic verification remains separate. |
| Failures? | No MT5 disconnect, worker failure or production-permission drift in 12 samples. Five durable model-input rejections recorded stale/future-input gate failures. Gold and index quotes were stale and excluded; details below. Large whole-engine memory is an operational limitation. |
| Separate experimental Telegram channel ready? | **Not yet operationally cleared.** Live paper observation is working, but there is no genuine live signal/preview/outcome evidence in this window, account costs remain assumptions, and outbound activation/routing is not wired in this dry-run release. Continue paper observation; a separate implementation/configuration review and explicit CEO approval are required before any experimental delivery. |

## Observation and evidence

The restart began at 20 October 2026 00:44:22 EAT. The sampled stability window ran from **20 October 2026 00:46:39 EAT to 20 October 2026 00:52:09 EAT**, approximately 5.5 minutes, with twelve read-only samples at 30-second intervals. Startup and subsequent evaluations covered completed M15 inputs on both sides of the 00:45 EAT boundary.

The live database has **9 completed executable evaluations** and **5 rejected inputs**, 15,735 cached genuine candles, zero signals, zero previews and zero outcome revisions. Delivery approval is null, and model alert permission is zero. Claude and Kimi remain pending; no models were attributed to them.

The worker executes the actual registered source, with the source hash recorded in durable run evidence and matching the Codex model file. Normalized input hashes and timestamps are recorded separately. No MT5 terminal or broker connection was created for a laboratory: the existing native MT5 session/collector is reused. The final system check found **1 local engine listener** on 127.0.0.1:8000 and **1 MT5 terminal process**.

## Genuine data quality

The existing explicit source-time basis **America/New_York+07:00** was preserved. No timezone was guessed or shifted to manufacture freshness. M15/H1 candles passed finite-OHLC, ordering, historical-spread and completed-bar validation. Active markets supplied 299 completed M15 and 159 completed H1 candles after exclusion of their still-forming latest bars. The actual model needs at least 80/50 respectively. The final active-market M15 close was **21:45:00 UTC**, and the H1 close was **21:00:00 UTC**. Opening times, close times and OHLC are retained in the input evidence.

Quotes and symbol specifications came from the same live collector handoff. Spread below is ask minus bid in price units; tick size is the broker's `symbol_info.trade_tick_size`, with no precision-based fallback. Missing or zero broker tick size fails qualification. Quote age below is measured **at collection**, not at the later dashboard/report read; small negative ages fall within the existing five-second clock tolerance.

| Market | Actual model handling | Quote age at collection (s) | Captured bid / ask | Spread / tick size |
|---|---|---:|---:|---:|
| XAUUSD | Stale input rejected | 3167.95 | 4140.38 / 4140.78 | 0.4 / 0.01 |
| EURUSD | Worker evaluated | -0.05 | 1.12121 / 1.12164 | 0.00043 / 1e-05 |
| GBPUSD | Worker evaluated | -2.05 | 1.33037 / 1.33113 | 0.00076 / 1e-05 |
| GBPJPY | Worker evaluated | -2.04 | 210.805 / 211.01 | 0.205 / 0.001 |
| BTCUSD | Worker evaluated | -2.06 | 81910.5 / 81916.5 | 6 / 0.01 |
| ETHUSD | Worker evaluated | -2.24 | 2398.01 / 2400.97 | 2.96 / 0.01 |
| NAS100 | Stale input rejected | 3117.20 | 29552.4 / 29553.4 | 1 / 0.01 |
| US500 | Stale input rejected | 3117.62 | 7696.2 / 7696.7 | 0.5 / 0.01 |
| GER40 | Stale input rejected | 3164.53 | 25207.6 / 25211.6 | 4 / 0.01 |

Stale gold/index inputs were not turned into detections. The evidence does not assert a broker holiday or maintenance calendar as their cause. In-progress candles were removed rather than treated as completed. The adapter preserves missing data and conflicting closed-bar evidence.

For any future detection, qualification checks current snapshot/quote/context, direction-specific tradability, finite positive prices and levels, broker tick size, entry/SL/TP ordering, entry drift, stop distance, spread relative to risk and net planned RR ≥2. Costs include the disclosed research commission proxy and execution reserve. These gates passed isolated regression tests; **live entry geometry and net RR were not exercised on a genuine detection because none occurred**. Broker account fees are not independently verified by this observation.

## Signal lifecycle and Telegram

No live signal existed to enter CONFIRMED/ACTIVE, TP_HIT, SL_HIT, CLOSED or UNRESOLVED states. Consequently, no genuine lifecycle resolution or realized paper R is claimed. Actual executed R remains unavailable; the engine did not place orders.

The durable lifecycle/outcome resolver remains active for future genuine signals. Missing paths and ambiguous barrier ordering retain unknown outcomes and cannot count as wins. Revisions preserve corrected evidence. A 1,000-record dashboard window does not remove older pending signals from resolution.

The experimental notifier remained **DRY_RUN** in every sample. The live outbox is empty; no new-lab message was sent. Existing production Telegram notifications and scheduled reports retained their existing permissions and healthy running status. Their normal authorized delivery was neither tested by sending a message nor disabled. A genuine preview will be created only after a real qualified detection.

## Stability and limitations

All four existing strategies retained their exact LIVE identities/versions. During the samples, each continued reporting 16 successful evaluations and zero strategy errors. MT5 stayed CONNECTED, with fresh scanner health and no consumer exception. Steady scan time ranged **0.98–2.93 seconds**, median **1.01 seconds**, versus a pre-restart sample of 1.74 seconds. The first cold scan after restart took 24.88 seconds; it is not pooled into the steady-state comparison. This short observation does not establish long-term reliability.

The actual model workers enforced Windows limits of **192 MiB committed memory, 15% machine CPU, four CPU seconds and one process**, plus the parent elapsed timeout. Observed worker peak committed memory was at most **14.02 MiB**. The engine's interval CPU use was **0.08–0.90% of the 20-logical-CPU machine** during the samples.

**Whole-engine memory is materially larger:** sampled working set **4.27–4.31 GiB**, with a process-lifetime peak of 5.73 GiB and final private memory around 4.89 GiB. The laptop reported approximately 5.31 GiB free out of 23.73 GiB physical RAM at final check. The worker limit does not cap the entire existing engine. No pre-restart process-memory baseline was captured, so the increase cannot be attributed to the new consumer or cleared as harmless from this evidence. Retain this as an operational concern before expanding the service.

The existing observation index reported 79 unparseable legacy lines before restart; the final count was 79. The separate EA bridge was OFFLINE before and after; the native MT5 connection used here remained connected. Neither pre-existing condition was disguised as a new consumer success or silently repaired.

The real local dashboard was checked against the running engine in a fresh browser session: live paper consumer visible, experimental delivery disabled, Markets and Garden still available, no page errors. A genuine-data screenshot is saved separately from all synthetic test screenshots.

## Configuration and validation

The running process's effective environment was preserved in memory, including credential values that were never printed or saved into evidence. Only `TRADEDEN_QUANT_LIVE_ENABLED` changed. All unrelated `.env` lines matched their baseline digest. Production alerts, reports, authoritative outcomes, Strategy Bank and its Telegram flag retained their settings; broker execution remained false. The old dedicated engine console received a graceful stop; no overlapping port-8000 engine was launched.

Isolated tests use a temporary data directory and explicitly default the paper feature off for legacy fixtures, while live-consumer tests opt in within their test scope. This prevents the now-enabled local `.env` flag from changing test assumptions. No synthetic opportunities were inserted into the live database.

**Regression result:** Ran 622 tests in 79.234s; PASS.

Evidence in this folder: `before.json`, `restart.json`, `samples.json`, `summary.json`, `database_check.json`, `system_check.json`, `dashboard_check.json`, `dashboard-live.png` and `backend_tests.txt`. The engine startup log is local and the live SQLite store remains under `backend/data/quant_live`.
