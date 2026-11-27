"""Render the CEO report solely from saved genuine observation evidence."""
from datetime import datetime,timezone,timedelta
import json
from pathlib import Path
import statistics

folder=Path(__file__).resolve().parent
load=lambda name:json.loads((folder/name).read_text(encoding='utf-8-sig'))
summary=load('summary.json');samples=load('samples.json');restart=load('restart.json');db=load('database_check.json');system=load('system_check.json')
eat=timezone(timedelta(hours=3));stamp=lambda at:datetime.fromtimestamp(at,timezone.utc).astimezone(eat).strftime('%d %B %Y %H:%M:%S EAT')
iso=lambda at:datetime.fromtimestamp(at,timezone.utc).strftime('%H:%M:%S UTC') if at is not None else 'Unavailable'
manifest=json.loads((folder.parents[0]/'state/labs/codex/strategies/compression_escape/manifest.json').read_text(encoding='utf-8'))
rows=[]
for symbol in manifest['instruments']:
    item=summary['final_inputs'].get(symbol)
    if not item:rows.append(f'| {symbol} | No collector input | — | — | — |');continue
    age=item['quote_age_at_collection_seconds'];frames=item['frames']
    label='Worker evaluated' if symbol in summary['actual_model_evaluated_markets'] else 'Stale input rejected'
    rows.append(f"| {symbol} | {label} | {age:.2f} | {item['bid']:g} / {item['ask']:g} | {item['spread_price']:.8g} / {item['tick_size']:.8g} |")
resources=[r['body']['resources'] for r in db['runs'] if r['state']=='COMPLETE']
peak_worker=max(r['peak_committed_mb'] for r in resources)
scans=[r['health']['last_scan']['elapsed_ms']/1000 for r in samples]
working=[r['usage']['working_set_mb']/1024 for r in samples]
cpu=[r['usage']['interval_machine_cpu_percent'] for r in samples if 'interval_machine_cpu_percent' in r['usage']]
tests=(folder/'backend_tests.txt').read_text(encoding='utf-8',errors='replace')
test_line=next((line for line in reversed(tests.splitlines()) if line.startswith('Ran ')),'Final suite still running')
tests_ok=tests.rstrip().endswith('OK')
before=load('before.json')['health'];last=samples[-1]['health']
report=f'''# CEO report — live MT5 paper observation

**20 October 2026 · Africa/Nairobi**

**Result:** the live paper consumer is enabled and running. Genuine MT5 data reached the actual Codex Compression Escape 0.1.0 executable. **Zero genuine detections, zero qualified paper signals and zero experimental Telegram previews** occurred during this bounded observation. No opportunity was injected or forced.

The engine remains running locally after the observation. Experimental outbound delivery and broker execution remain disabled. No public deployment was performed.

## Requested findings

| Question | Observed result |
|---|---|
| Consumer started? | **Yes.** Controlled graceful restart from PID {restart['old_pid']} to {restart['pid']}; `TRADEDEN_QUANT_LIVE_ENABLED=1` persisted for subsequent local starts. |
| Genuine MT5 data reached Codex? | **Yes.** Existing shared collector supplied 16 instruments. The actual bounded model evaluated BTCUSD, ETHUSD, EURUSD, GBPUSD and GBPJPY. Source/version hashes match the registered executable. |
| Genuine signals? | **0 detections; 0 qualified paper signals.** The database contains no fabricated or synthetic signal records. |
| Planned RR and status? | Model status **EXPERIMENTAL**, scanning enabled, alert permission disabled. With no signal, entry/SL/TP and planned/net planned RR are **not applicable**. Qualification retains the minimum **1:2 net planned RR** gate. |
| Genuine Telegram previews? | **0**, because no genuine signal qualified. Formatting, identity, authorization and duplicate prevention were not exercised on a genuine live alert in this window; earlier synthetic verification remains separate. |
| Failures? | No MT5 disconnect, worker failure or production-permission drift in {summary['samples']} samples. Five durable model-input rejections recorded stale/future-input gate failures. Gold and index quotes were stale and excluded; details below. Large whole-engine memory is an operational limitation. |
| Separate experimental Telegram channel ready? | **Not yet operationally cleared.** Live paper observation is working, but there is no genuine live signal/preview/outcome evidence in this window, account costs remain assumptions, and outbound activation/routing is not wired in this dry-run release. Continue paper observation; a separate implementation/configuration review and explicit CEO approval are required before any experimental delivery. |

## Observation and evidence

The restart began at {stamp(datetime.fromisoformat(load('before.json')['captured_at']).timestamp())}. The sampled stability window ran from **{stamp(summary['observation_start'])} to {stamp(summary['observation_end'])}**, approximately {(summary['observation_end']-summary['observation_start'])/60:.1f} minutes, with twelve read-only samples at 30-second intervals. Startup and subsequent evaluations covered completed M15 inputs on both sides of the 00:45 EAT boundary.

The live database has **{db['run_states'].get('COMPLETE',0)} completed executable evaluations** and **{db['run_states'].get('REJECTED',0)} rejected inputs**, {db['cached_candle_count']:,} cached genuine candles, zero signals, zero previews and zero outcome revisions. Delivery approval is null, and model alert permission is zero. Claude and Kimi remain pending; no models were attributed to them.

The worker executes the actual registered source, with the source hash recorded in durable run evidence and matching the Codex model file. Normalized input hashes and timestamps are recorded separately. No MT5 terminal or broker connection was created for a laboratory: the existing native MT5 session/collector is reused. The final system check found **{system['engine_listener_count']} local engine listener** on {system['bind_address']}:8000 and **{system['mt5_terminal_process_count']} MT5 terminal process**.

## Genuine data quality

The existing explicit source-time basis **{last['source_time_basis']}** was preserved. No timezone was guessed or shifted to manufacture freshness. M15/H1 candles passed finite-OHLC, ordering, historical-spread and completed-bar validation. Active markets supplied 299 completed M15 and 159 completed H1 candles after exclusion of their still-forming latest bars. The actual model needs at least 80/50 respectively. The final active-market M15 close was **{iso(summary['final_inputs']['BTCUSD']['frames']['M15']['last_close_at'])}**, and the H1 close was **{iso(summary['final_inputs']['BTCUSD']['frames']['H1']['last_close_at'])}**. Opening times, close times and OHLC are retained in the input evidence.

Quotes and symbol specifications came from the same live collector handoff. Spread below is ask minus bid in price units; tick size is the broker's `symbol_info.trade_tick_size`, with no precision-based fallback. Missing or zero broker tick size fails qualification. Quote age below is measured **at collection**, not at the later dashboard/report read; small negative ages fall within the existing five-second clock tolerance.

| Market | Actual model handling | Quote age at collection (s) | Captured bid / ask | Spread / tick size |
|---|---|---:|---:|---:|
{chr(10).join(rows)}

Stale gold/index inputs were not turned into detections. The evidence does not assert a broker holiday or maintenance calendar as their cause. In-progress candles were removed rather than treated as completed. The adapter preserves missing data and conflicting closed-bar evidence.

For any future detection, qualification checks current snapshot/quote/context, direction-specific tradability, finite positive prices and levels, broker tick size, entry/SL/TP ordering, entry drift, stop distance, spread relative to risk and net planned RR ≥2. Costs include the disclosed research commission proxy and execution reserve. These gates passed isolated regression tests; **live entry geometry and net RR were not exercised on a genuine detection because none occurred**. Broker account fees are not independently verified by this observation.

## Signal lifecycle and Telegram

No live signal existed to enter CONFIRMED/ACTIVE, TP_HIT, SL_HIT, CLOSED or UNRESOLVED states. Consequently, no genuine lifecycle resolution or realized paper R is claimed. Actual executed R remains unavailable; the engine did not place orders.

The durable lifecycle/outcome resolver remains active for future genuine signals. Missing paths and ambiguous barrier ordering retain unknown outcomes and cannot count as wins. Revisions preserve corrected evidence. A 1,000-record dashboard window does not remove older pending signals from resolution.

The experimental notifier remained **DRY_RUN** in every sample. The live outbox is empty; no new-lab message was sent. Existing production Telegram notifications and scheduled reports retained their existing permissions and healthy running status. Their normal authorized delivery was neither tested by sending a message nor disabled. A genuine preview will be created only after a real qualified detection.

## Stability and limitations

All four existing strategies retained their exact LIVE identities/versions. During the samples, each continued reporting 16 successful evaluations and zero strategy errors. MT5 stayed CONNECTED, with fresh scanner health and no consumer exception. Steady scan time ranged **{min(scans):.2f}–{max(scans):.2f} seconds**, median **{statistics.median(scans):.2f} seconds**, versus a pre-restart sample of {before['last_scan']['elapsed_ms']/1000:.2f} seconds. The first cold scan after restart took {restart['health']['last_scan']['elapsed_ms']/1000:.2f} seconds; it is not pooled into the steady-state comparison. This short observation does not establish long-term reliability.

The actual model workers enforced Windows limits of **192 MiB committed memory, 15% machine CPU, four CPU seconds and one process**, plus the parent elapsed timeout. Observed worker peak committed memory was at most **{peak_worker:.2f} MiB**. The engine's interval CPU use was **{min(cpu):.2f}–{max(cpu):.2f}% of the 20-logical-CPU machine** during the samples.

**Whole-engine memory is materially larger:** sampled working set **{min(working):.2f}–{max(working):.2f} GiB**, with a process-lifetime peak of {max(r['usage']['peak_working_set_mb'] for r in samples)/1024:.2f} GiB and final private memory around {samples[-1]['usage']['private_mb']/1024:.2f} GiB. The laptop reported approximately {system['free_physical_kib']/1048576:.2f} GiB free out of {system['total_physical_kib']/1048576:.2f} GiB physical RAM at final check. The worker limit does not cap the entire existing engine. No pre-restart process-memory baseline was captured, so the increase cannot be attributed to the new consumer or cleared as harmless from this evidence. Retain this as an operational concern before expanding the service.

The existing observation index reported {before['storage']['setup_observations.jsonl']['index']['unparseable_lines']} unparseable legacy lines before restart; the final count was {last['storage']['setup_observations.jsonl']['index']['unparseable_lines']}. The separate EA bridge was OFFLINE before and after; the native MT5 connection used here remained connected. Neither pre-existing condition was disguised as a new consumer success or silently repaired.

The real local dashboard was checked against the running engine in a fresh browser session: live paper consumer visible, experimental delivery disabled, Markets and Garden still available, no page errors. A genuine-data screenshot is saved separately from all synthetic test screenshots.

## Configuration and validation

The running process's effective environment was preserved in memory, including credential values that were never printed or saved into evidence. Only `TRADEDEN_QUANT_LIVE_ENABLED` changed. All unrelated `.env` lines matched their baseline digest. Production alerts, reports, authoritative outcomes, Strategy Bank and its Telegram flag retained their settings; broker execution remained false. The old dedicated engine console received a graceful stop; no overlapping port-8000 engine was launched.

Isolated tests use a temporary data directory and explicitly default the paper feature off for legacy fixtures, while live-consumer tests opt in within their test scope. This prevents the now-enabled local `.env` flag from changing test assumptions. No synthetic opportunities were inserted into the live database.

**Regression result:** {test_line}; {'PASS' if tests_ok else 'see backend_tests.txt for final completion'}.

Evidence in this folder: `before.json`, `restart.json`, `samples.json`, `summary.json`, `database_check.json`, `system_check.json`, `dashboard_check.json`, `dashboard-live.png` and `backend_tests.txt`. The engine startup log is local and the live SQLite store remains under `backend/data/quant_live`.
'''
(folder.parent/'CEO_LIVE_OBSERVATION_REPORT.md').write_text(report,encoding='utf-8')
print(json.dumps({'report':str(folder.parent/'CEO_LIVE_OBSERVATION_REPORT.md'),'genuine_signals':db['signal_count'],'previews':db['preview_count'],'tests_complete':tests_ok},indent=2))
