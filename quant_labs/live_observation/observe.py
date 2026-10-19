"""Read-only bounded live observation. Never creates a model opportunity or signal."""
import argparse
import ctypes as c
from ctypes import wintypes as w
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import sqlite3
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parent))
from control import get,permission_summary,OUT

class Memory(c.Structure):
    _fields_=[('cb',w.DWORD),('faults',w.DWORD)]+[(name,c.c_size_t) for name in ('peak_ws','ws','peak_paged','paged','peak_nonpaged','nonpaged','pagefile','peak_pagefile','private')]

def process_usage(pid):
    kernel=c.WinDLL('kernel32',use_last_error=True);psapi=c.WinDLL('psapi')
    kernel.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];kernel.OpenProcess.restype=w.HANDLE
    kernel.GetProcessTimes.argtypes=[w.HANDLE,c.c_void_p,c.c_void_p,c.c_void_p,c.c_void_p]
    kernel.CloseHandle.argtypes=[w.HANDLE]
    psapi.GetProcessMemoryInfo.argtypes=[w.HANDLE,c.c_void_p,w.DWORD]
    handle=kernel.OpenProcess(0x410,False,pid)
    if not handle:raise c.WinError(c.get_last_error())
    try:
        mem=Memory();mem.cb=c.sizeof(mem)
        if not psapi.GetProcessMemoryInfo(handle,c.byref(mem),c.sizeof(mem)):raise c.WinError(c.get_last_error())
        times=[c.c_ulonglong() for _ in range(4)]
        if not kernel.GetProcessTimes(handle,*[c.byref(t) for t in times]):raise c.WinError(c.get_last_error())
        return {'working_set_mb':mem.ws/1048576,'peak_working_set_mb':mem.peak_ws/1048576,'private_mb':mem.private/1048576,
                'cpu_seconds':(times[2].value+times[3].value)/10000000,'logical_cpus':os.cpu_count()}
    finally:kernel.CloseHandle(handle)

def input_check(item,at):
    q=item['quote'];m=item['metadata'];issues=[]
    age=at-q['tick_at'] if q.get('tick_at') is not None else None
    if not item['time_verified']:issues.append('UNVERIFIED_TIME')
    if age is None or not -5<=age<=30:issues.append('STALE_OR_FUTURE_QUOTE')
    if q['bid']<=0 or q['ask']<q['bid']:issues.append('INVALID_QUOTE')
    if m['tick_size']<=0:issues.append('TICK_SIZE_UNAVAILABLE')
    for tf,seconds,minimum in [('M15',900,80),('H1',3600,50)]:
        frame=item['frames'].get(tf,{})
        closed=frame.get('last_close_at')
        if frame.get('closed_count',0)<minimum:issues.append('INCOMPLETE_'+tf)
        if closed is None or not 0<=item['asof']-closed<=2*seconds:issues.append('STALE_OR_FUTURE_'+tf)
    return {'source':item['source'],'source_basis':item['source_basis'],'asof':item['asof'],'tick_at':q.get('tick_at'),
            'quote_age_at_collection_seconds':item['asof']-q['tick_at'] if q.get('tick_at') is not None else None,
            'bid':q['bid'],'ask':q['ask'],'spread_price':q['ask']-q['bid'],'spread_points':(q['ask']-q['bid'])/m['point'],
            'tick_size':m['tick_size'],'tick_size_source':m.get('tick_size_source'),'frames':{tf:item['frames'].get(tf) for tf in ('M15','H1')},
            'issues_at_sample':issues,'model_runs':item['last_model_runs'],'last_model_run_at':item['last_model_run_at'],
            'processed_count':item['processed_count'],'generated_signal_count':item['generated_signal_count'],'input_sha256':item['input_sha256']}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--samples',type=int,default=12);parser.add_argument('--interval',type=float,default=30)
    args=parser.parse_args();restart=json.loads((OUT/'restart.json').read_text(encoding='utf-8'));baseline=restart['health']
    baseline_permission=permission_summary(baseline);samples=[];failures=[];previous=None
    for index in range(args.samples):
        started=time.time()
        try:
            health=get('/api/health');paper=get('/api/quant-labs/live');usage=process_usage(restart['pid'])
            if previous:
                usage['interval_machine_cpu_percent']=100*(usage['cpu_seconds']-previous['usage']['cpu_seconds'])/(started-previous['at'])/usage['logical_cpus']
            checks={symbol:input_check(item,started) for symbol,item in paper['runtime'].get('latest_inputs',{}).items()}
            same=permission_summary(health)==baseline_permission
            if not same:failures.append({'at':started,'failure':'PRODUCTION_PERMISSION_DRIFT'})
            if health['status']!='CONNECTED':failures.append({'at':started,'failure':'MT5_NOT_CONNECTED'})
            if paper['runtime'].get('last_error'):failures.append({'at':started,'failure':paper['runtime']['last_error']})
            row={'at':started,'health':health,'paper':paper,'input_checks':checks,'usage':usage,'production_permissions_unchanged':same}
            samples.append(row);previous=row
            (OUT/'samples.json').write_text(json.dumps(samples,indent=2),encoding='utf-8')
            print(json.dumps({'sample':index+1,'eat':datetime.fromtimestamp(started,timezone.utc).astimezone(__import__('datetime').timezone(__import__('datetime').timedelta(hours=3))).isoformat(),
                              'mt5':health['status'],'scanner_ms':health['last_scan'].get('elapsed_ms'),'inputs':len(checks),
                              'worker_markets':[s for s,v in checks.items() if v['model_runs']],
                              'signals':len(paper['signals']),'outbox':len(paper['outbox']),'consumer_running':paper['runtime']['running'],
                              'working_set_mb':round(usage['working_set_mb'],1),'permissions_unchanged':same}),flush=True)
        except Exception as exc:
            failures.append({'at':started,'failure':type(exc).__name__});print(json.dumps(failures[-1]),flush=True)
        if index+1<args.samples:time.sleep(max(0,args.interval-(time.time()-started)))
    if not samples:raise RuntimeError('No valid observation samples')
    last=samples[-1];paper=last['paper']
    summary={'observation_start':samples[0]['at'],'observation_end':last['at'],'samples':len(samples),
             'consumer_started':paper['runtime']['enabled'] and paper['runtime']['running'],'genuine_input_markets':list(last['input_checks']),
             'actual_model_evaluated_markets':sorted({s for row in samples for s,v in row['input_checks'].items() if v['model_runs']}),
             'genuine_detections':len(paper['signals']),'qualified_paper_signals':sum(bool(s.get('confirmed')) for s in paper['signals']),
             'signals':paper['signals'],'previews':paper['outbox'],'experimental_telegram_mode':paper['runtime']['telegram_mode'],
             'experimental_activation_approved':paper['runtime']['outbound_activation_approved'],
             'permissions_unchanged_all_samples':all(row['production_permissions_unchanged'] for row in samples),
             'failures':failures,'final_inputs':last['input_checks'],'resource_samples':[{'at':r['at'],**r['usage']} for r in samples]}
    (OUT/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps({k:summary[k] for k in ('samples','consumer_started','actual_model_evaluated_markets','genuine_detections','qualified_paper_signals','experimental_telegram_mode','permissions_unchanged_all_samples','failures')},indent=2),flush=True)

if __name__=='__main__':main()
