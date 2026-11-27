"""Bounded read-only reproduction of the outcome watcher's cold-start allocation."""
import argparse
import gc
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import tracemalloc

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'backend'))
parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['eager','stream']);parser.add_argument('--rows',type=int,default=5000)
args=parser.parse_args()
from quant_live.resources import enforce,usage
enforce(memory_mb=384,cpu_percent=15,cpu_seconds=25)
with tempfile.TemporaryDirectory() as tmp:
    os.environ['TRADING_HUB_DATA_DIR']=tmp
    from jsonl_index import JsonlIndex
    from observations import _observation_summary,_watch_projection
    from outcomes import watch_barriers_valid
    path=ROOT/'backend/data/setup_observations.jsonl'
    index=JsonlIndex(path,_observation_summary,(),schema='profile-only-no-sidecar',persist=False)
    positions=[];offset=0;raw_bytes=0
    with path.open('rb') as handle:
        for raw in handle:
            try:row=json.loads(raw)
            except (json.JSONDecodeError,UnicodeDecodeError):offset+=len(raw);continue
            if isinstance(row,dict) and row.get('record_type')=='setup_snapshot' and not (row.get('rule_evidence') or {}).get('strategy_valid') and (row.get('time_provenance') or {}).get('timezone_normalization_status')=='VERIFIED':
                positions.append(len(index.spans));index.spans.append((offset,len(raw)-1));raw_bytes+=len(raw)
            offset+=len(raw)
            if len(positions)>=args.rows:break
    del row,raw;gc.collect();tracemalloc.start(12);start=time.perf_counter()
    retained={};invalid=set()
    if args.mode=='eager':
        for position,row in zip(positions,index.load(positions)):
            if watch_barriers_valid(row):retained[position]=_watch_projection(row)
            else:invalid.add(position)
    else:
        for position,row in zip(positions,index.iter_load(positions)):
            if watch_barriers_valid(row):retained[position]=_watch_projection(row)
            else:invalid.add(position)
    elapsed=time.perf_counter()-start;current,peak=tracemalloc.get_traced_memory()
    top=[{'allocation':str(stat.traceback[0]),'mib':stat.size/1048576,'blocks':stat.count} for stat in tracemalloc.take_snapshot().statistics('lineno')[:8]]
    signature=hashlib.sha256(json.dumps({'retained':retained,'invalid':sorted(invalid)},sort_keys=True,separators=(',',':')).encode()).hexdigest()
    result={'mode':args.mode,'actual_snapshot_rows':len(positions),'raw_input_bytes':raw_bytes,'retained_projections':len(retained),'invalid_barriers':len(invalid),
            'output_sha256':signature,'traced_peak_mib':peak/1048576,'traced_retained_mib':current/1048576,'elapsed_seconds':elapsed,'top_retained_allocations':top,'resources':usage(),
            'scope':'isolated genuine-record sample, not an attached live-process heap profile; no production file or sidecar writes'}
    (Path(__file__).parent/f'memory_{args.mode}.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))
