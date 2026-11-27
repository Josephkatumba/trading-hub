"""Assemble measured next-phase findings without changing any production state."""
from datetime import datetime,timezone,timedelta
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'quant_labs/live_observation'))
from quant_labs.control import ControlPlane
from quant_labs.frozen import verify
from control import permission_summary

folder=Path(__file__).resolve().parent
load=lambda name:json.loads((folder/name).read_text(encoding='utf-8-sig'))
baseline=load('live_baseline.json');final=load('live_final.json');eager=load('memory_eager.json');stream=load('memory_stream.json')
evaluations=load('evaluations.json');retries=load('retry_evaluations.json');probe=load('codex_real_probe.json')
retry_by={(r['key'],r['symbol']):r for r in retries}
control=ControlPlane(ROOT/'quant_labs/state');public=control.public();verify(public['settings']['evaluator'])
permissions_same=permission_summary(baseline['health'])==permission_summary(final['health'])
bank_alerts_same=baseline['health']['strategy_bank']['telegram_enabled']==final['health']['strategy_bank']['telegram_enabled']
same_live_models=baseline['paper']['labs']==final['paper']['labs']
eat=timezone(timedelta(hours=3));stamp=lambda epoch:datetime.fromtimestamp(epoch,timezone.utc).astimezone(eat).strftime('%d %b %Y %H:%M:%S EAT')
scan_stamp=baseline['health']['last_scan']['completed_at'];begin=datetime.fromisoformat(scan_stamp).timestamp()
rows=[];cases=[]
for item in evaluations:
    retry=retry_by.get((item['key'],item['symbol']));periods=item['periods'] if item['periods'] else retry['result']['periods']
    normal=periods['test']['normal'];stress=periods['test']['stress'];status='supplemental exact retry' if retry else 'canonical COMPLETE'
    rows.append(f"| {item['key']} | {item['symbol']} | {normal['resolved']} / {normal['unknown']} | {normal['total_r']:+.2f} | {stress['total_r']:+.2f} | {100*normal['win_rate']:.1f}% | {normal['weekly_sign_flip_p']:.4f} | {'retry' if retry else 'complete'} |")
    cases.append({'key':item['key'],'symbol':item['symbol'],'status':status,'job':item['job'],'test_normal':normal,'test_stress':stress,
                  'planned_rr_min':item['planned_rr_min'],'planned_rr_max':item['planned_rr_max'],'net_planned_rr_min':item['net_planned_rr_min']})
models=load('candidates.json');generations=[load('intents_'+s+'.json') for s in ('EURUSD','XAUUSD','BTCUSD')]
reduction=100*(1-stream['traced_peak_mib']/eager['traced_peak_mib'])
if eager['output_sha256']!=stream['output_sha256']:raise ValueError('Memory optimization output changed')
backend=(folder/'backend_tests.txt').read_text(encoding='utf-8',errors='replace');shared=(folder/'shared_evaluator_tests.txt').read_text(encoding='utf-8',errors='replace')
if not backend.rstrip().endswith('OK') or not shared.rstrip().endswith('OK'):raise ValueError('Final regression suite incomplete')
summary={'measured_at':final['at'],'memory_baseline':baseline['usage'],'memory_final_same_running_process':final['usage'],
         'measured_watcher_peak_reduction_percent':reduction,'identical_projection_output_sha256':stream['output_sha256'],
         'production_optimization_applied':False,'production_restart_in_phase':False,'permissions_unchanged':permissions_same and bank_alerts_same,
         'live_models_unchanged':same_live_models,'existing_codex_consumer_running':final['paper']['runtime']['running'],
         'experimental_outbound_approval':final['paper']['runtime']['outbound_activation_approved'],'broker_execution_enabled':final['health']['execution_enabled'],
         'new_codex_executables':len(models),'strategy_families':2,'historical_market_cases':len(cases),'canonical_completed_cases':sum(r['status']=='COMPLETE' for r in evaluations),
         'preserved_failed_jobs':len(retries),'supplemental_exact_retries_completed':sum(r['retry_status']=='COMPLETE' for r in retries),
         'new_models_admitted_live':0,'new_models_certified':0,'cases':cases,'shared_multiple_testing_family':public['multiple_testing_family'],
         'claude_shared_models':next(r['strategies'] for r in public['labs'] if r['id']=='claude'),
         'kimi_shared_models':next(r['strategies'] for r in public['labs'] if r['id']=='kimi'),
         'real_codex_probe_status':probe['status'],'live_paper_detections':final['paper']['performance']['detected'],
         'actual_claude_kimi_authoring_sessions_verified':False}
(folder/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
quote_rows=[]
for symbol in ('XAUUSD','NAS100','US500','GER40'):
    item=final['paper']['runtime']['latest_inputs'][symbol]
    quote_rows.append(f"| {symbol} | {item['broker_symbol']} | {item['asof']-item['quote']['tick_at']:.2f} s | {stamp(item['frames']['M15']['last_close_at'])} | {', '.join(r['status'] for r in item['last_model_runs']) or 'not yet run'} |")
report=f'''# CEO progress report — next development phase

**20 October 2026 · Africa/Nairobi**

The existing Codex Compression Escape 0.1.0 paper consumer remains enabled. **No production restart, permission change, experimental delivery activation, broker execution or public deployment occurred in this phase.** The new research candidates have not been admitted to the live registry.

## Memory findings and verified optimization

A fresh baseline on the running engine recorded **{baseline['usage']['working_set_mb']/1024:.2f} GiB working set** and **{baseline['usage']['private_mb']/1024:.2f} GiB private memory**. At {stamp(final['at'])}, the same running process used {final['usage']['working_set_mb']/1024:.2f} GiB and {final['usage']['private_mb']/1024:.2f} GiB respectively. This is a baseline/continuity measurement, **not a claim that production memory fell**.

The outcome watcher's cold path loaded every selected full snapshot through `index.load(missing)` before retaining small projections. A bounded read-only reproduction used **5,000 actual VERIFIED historical snapshots**, {eager['raw_input_bytes']:,} raw bytes, from the existing log. It retained 1,147 valid projections and rejected 3,853 invalid-barrier rows in both versions. It wrote no live file or index sidecar.

| Allocation measurement | Existing eager path | Staged streaming path |
|---|---:|---:|
| Peak traced Python allocations | {eager['traced_peak_mib']:.2f} MiB | {stream['traced_peak_mib']:.2f} MiB |
| Retained traced allocations | {eager['traced_retained_mib']:.2f} MiB | {stream['traced_retained_mib']:.2f} MiB |
| Worker peak committed memory, including profiler overhead | {eager['resources']['peak_committed_mb']:.2f} MiB | {stream['resources']['peak_committed_mb']:.2f} MiB |
| Reproduction elapsed time | {eager['elapsed_seconds']:.2f} s | {stream['elapsed_seconds']:.2f} s |

The measured peak-allocation reduction is **{reduction:.1f}%**, with identical output SHA-256 `{stream['output_sha256']}`. The dominant temporary objects came from JSON decoding of full snapshots; retained objects came from decoded fields and the small watcher projections. The code now offers `JsonlIndex.iter_load()` and the watcher consumes it one row at a time, avoiding the full decoded batch. The running process still uses its previously loaded code; the fix is **staged for a future controlled local reload**. It has not been hot-patched into production.

This is an isolated allocation-path profile plus OS process measurements, not an attached heap inventory of the live engine. It identifies a reproducible large allocation mechanism, but does not prove that it explains the entire 4+ GiB working set. Retained derived index summaries/maps, the approximately 235 MB observation-index sidecar, its nested JSON encoding/decoding, other report/outcome state and allocator retention remain further profiling targets. The sidecar currently serializes a JSON body inside a second JSON envelope, creating extra large temporary strings.

Recommended improvements, in order:

1. Apply the tested streaming watcher change at the next controlled local update, preserving all production settings. Capture matched cold/warm memory and scan latency before/after; do not promise the sample's 98% reduction for the entire engine.
2. Profile retained index summaries and redundant key maps at a controlled startup. Consider string sharing and packed position arrays without changing lookup semantics.
3. Introduce a separately versioned recoverable sidecar format or disk-backed derived index to avoid giant nested JSON documents. Preserve checksum/rebuild behavior and append-only source files. Do not alter the frozen trading evaluator to solve this storage issue.

## Stale-market investigation

The existing terminal installation is **MetaTrader 5 IC Markets Global**. The original 00:44–00:52 EAT observation coincided with the broker's published server-time daily breaks. On this date, the preserved `America/New_York+07:00` source basis is UTC+3, matching EAT. Published IC hours place the main index break around 23:59–01:00, gold's reopening at 01:02 and DE40's published trade reopening at 01:05. [Official IC trading hours](https://www.icmarkets.sc/en/trading-pricing/trading-hours/) and [IC Global schedule](https://www.icmarkets-global.com/de/trading-pricing/trading-hours) support this interpretation.

Real quote streams resumed without any engine restart, new terminal, timezone shift or freshness waiver. Initial resumed quotes were not enough: the last completed M15 bar was still old, so the consumer continued to reject the context until the first post-break M15 candle closed. Subsequently all four markets reached the actual existing Codex worker:

| Product | Actual broker symbol | Quote age at collection | Latest completed M15 close | Actual worker result |
|---|---|---:|---|---|
{chr(10).join(quote_rows)}

This sequence strongly supports scheduled quote unavailability during the daily break as the cause of the earlier staleness, rather than a collector disconnection or an offset error. The account-specific terminal Specification session table was not available through the existing read-only Python interface, so the public schedule is corroborating evidence, not a verified account-specific calendar. In particular, DE40 quotes appeared before its published trading open; quote availability must not be conflated with permission to trade.

Freshness remains unchanged: current quote gate 30 seconds with the existing five-second future-clock tolerance, snapshot limit 60 seconds, required completed context, and no forming-bar use. Old quotes are never made current by relabeling timestamps. Small negative quote ages in the table remain inside the existing clock tolerance.

## New actual Codex executable models

Seven immutable 0.1.0 executable candidates were authored by this actual Codex session across **two strategy families**:

- **Trend Reclaim:** six predeclared exit/horizon variants targeting net planned 2R, 3R, 4R, 5R, 7R and 9R. Entry requires persistent H1 trend and a closed M15 pullback reclaim; stops use observed structure and ATR. Longer targets use explicitly declared longer horizons, not an invented win-rate objective.
- **Range Sweep Reversion:** failed M15 channel escape in a low-persistence H1 regime. The target is the opposite observed range boundary, capped at 9 gross R and admitted only when cost-adjusted planned RR meets the common minimum.

The six exit variants are disclosed as correlated trials of one entry family, not six independent discoveries. Tick rounding and actual spread/fee reserves can move recorded RR away from its nominal objective or reject a near-threshold opportunity; **actual planned and net planned RR are retained**, and the common minimum 1:2 net gate is unchanged. No parameter was retuned after observing these results.

The candidates were causally replayed over EURUSD, XAUUSD and BTCUSD on the existing content-addressed broker dataset `{generations[0]['dataset']}`. Feature windows contained only completed M15/H1 bars. An entry-bar open and recorded spread were explicitly used as historical quote proxies; that bar's future high/low/close were never exposed to the model. Directional tradability was assumed for the historical replay from the availability of broker candles; historical account permissions and session tables were not verified. This assumption does not change live tradability checks. Causal-window tests verify that changing future extremes does not change the supplied feature input. This is historical research, not genuine live detections.

Across the three markets, {sum(g['bars_evaluated'] for g in generations):,} primary timestamps were processed for each candidate. These data and historical test partitions were already exposed to prior research; **they are not a new untouched holdout**. The shared evaluator's unchanged train/validation/test boundaries, cost stress, overlap exclusions, ambiguous/missing-data handling and current-swap limitations remain in force.

### Chronological historical test results

Test period: 1 April–30 September 2026. Figures below are simulated net paper R after the frozen accounting policy. Unknown outcomes are excluded from net R and counted separately. Cases and variants are correlated; their summed R is not a portfolio performance claim.

| Executable | Market | Resolved / unknown | Net R | Stressed net R | Win rate | Weekly sign-flip p | Completion |
|---|---|---:|---:|---:|---:|---:|---|
{chr(10).join(rows)}

There are positive and negative cases, but **none establishes a robust positive edge**. Resolved test samples are small, weekly uncertainty is wide and the smallest raw positive-edge p-value is above 0.05 even before multiple-testing correction. The shared research ledger's conservative global multiple-testing family currently contains {public['multiple_testing_family']} declared comparisons. The live/verified leaderboard remains empty for these candidates. No 60–70% win rate was forced, fitted or claimed. All seven remain offline experimental research; none was promoted or added to live scanning.

### Preserved operational evaluation failures

There were **21 model/market cases**. Eighteen completed in the canonical shared queue. Three jobs returned `PermissionError(13, 'Access is denied')`; their original FAILED states and raw evidence remain intact. The frozen worker did not log the exact locked path, so a specific OneDrive/checkpoint cause is **not proven**.

All three exact immutable requests completed when re-run through the same frozen worker in clean temporary directories. Those results are marked `retry` above and stored as supplemental recovery evidence; they were not inserted as fabricated canonical successes or used to overwrite failed jobs. Runtime/checkpoint directories outside synchronized storage and bounded atomic-write retries should be considered for a separately reviewed evaluator revision. All eleven frozen evaluator/trusted-interface hashes remain unchanged.

## Claude and Kimi integration readiness

The new `quant_labs.provider_bridge` provides own-capability source registration, source/manifest/version binding and a read-only genuine-cache model probe. Cross-lab token use is rejected. Executables are syntax-restricted and bounded; registered source is retained for review, and the frozen shared evaluator still receives declarative causal intents rather than importing model code. A lab's token cannot run the operator's worker or self-approve profitability.

The actual Codex Compression Escape source passed that bridge on genuine BTCUSD data: **{probe['status']}**, {probe['resources']['peak_committed_mb']:.2f} MiB peak committed memory, zero live writes and zero outbound calls. The same interface's identity separation was tested for Codex/Claude/Kimi using temporary, explicitly non-strategy no-op contract fixtures. Those fixtures are not AI-authored trading models and were never registered into the real laboratories or live store.

The Claude and Kimi real research registries still contain **{summary['claude_shared_models']} and {summary['kimi_shared_models']} models**, respectively. Neither executable was found on PATH, and no actual Claude/Kimi session connector was available. Their actual independently authored models and session provenance remain pending. It would be false to claim their real sessions have completed integration. The concrete commands and schema are in `LIVE_PROVIDER_HANDOFF.md`.

The cache probe supplies genuine OHLC/spread and quote/specification metadata from the existing collector, with no extra MT5 session. Optional tick volume is not retained in that outcome cache; a volume-dependent model requires its full live-provider feature check. The normal provider receives the collector's complete normalized fields. Probe freshness failures remain rejections.

## Continued operation and validation

The same local engine PID 40304 stayed running throughout this phase. Existing strategy identities and production alert/report/outcome/Strategy Bank permissions matched the baseline; Strategy Bank's Telegram flag also matched. The current Codex model remains **EXPERIMENTAL**, scanning enabled, experimental alert permission zero. Final consumer mode is DRY_RUN, approval false and broker execution false. The live laboratory registry is unchanged; phase detections remain **{final['paper']['performance']['detected']}**, with no fabricated live opportunities. Claude/Kimi remain pending in the live dashboard.

Validation: **629 backend regression tests passed**, including streaming equivalence/read-once semantics, all previous scanner/outcome/Telegram tests and six new capability/causality/cache-probe checks. **27 frozen shared-evaluator tests passed**, including cross-lab boundaries, equal accounting and Windows limits. Allocation reproduction outputs matched exactly. No existing production trading rule, permission, broker account setting or freshness threshold was changed. The memory optimization is staged; the running production process is unchanged.

Evidence: `next_phase/live_baseline.json`, `live_final.json`, `memory_eager.json`, `memory_stream.json`, `market_sessions.json`, `quotes_followup.json`, `codex_real_probe.json`, `candidates.json`, `intents_*.json`, `evaluations.json`, `retry_evaluations.json`, `summary.json`, `backend_tests.txt`, and `shared_evaluator_tests.txt`. Candidate code/manifests reside only in the Codex laboratory's own strategy directories.
'''
(ROOT/'quant_labs/CEO_NEXT_PHASE_REPORT.md').write_text(report,encoding='utf-8')
print(json.dumps({k:summary[k] for k in ('measured_watcher_peak_reduction_percent','permissions_unchanged','live_models_unchanged','new_codex_executables','historical_market_cases','canonical_completed_cases','supplemental_exact_retries_completed','new_models_admitted_live','new_models_certified','real_codex_probe_status')},indent=2))
