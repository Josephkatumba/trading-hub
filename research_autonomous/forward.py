"""Bounded file-driven shadow collector. No live engine connection and no sender.

Input: one JSON snapshot {symbol, asof, quote:{bid,ask,tick_at}, frames:{H1:[...]}}.
An optional benchmark H1 series supports relative_lag. Input snapshot must be
captured prospectively by a separately approved read-only feed integration.
Offline historical files are never labelled actual forward evidence.
"""
from dataclasses import replace,asdict
import hashlib
import json
from pathlib import Path
import time
from .foundation import confirmation_valid,validate_bars,RevisionStore
from .hypotheses import Features,SPECS
from .experiment import make_plan

def detect(snapshot,meta):
    symbol=snapshot['symbol'];asof=float(snapshot['asof']);quote=snapshot['quote']
    age=asof-float(quote['tick_at'])
    bid,ask=float(quote['bid']),float(quote['ask'])
    if not (bid>0 and ask>=bid):return [],'invalid quote'
    bars,rejected=validate_bars(snapshot['frames']['H1'],3600,asof)
    if len(bars)<122:return [],'insufficient completed history'
    f=Features(bars);i=len(bars)-1;close_at=float(f.utc[i]+3600)
    if not confirmation_valid(close_at,asof,age):return [],'stale/future quote or delayed/future confirming bar'
    other=None
    if snapshot.get('benchmark_H1'):
        benchmark,_=validate_bars(snapshot['benchmark_H1'],3600,asof)
        if len(benchmark)>=122:other=Features(benchmark)
    plans=[]
    for spec in SPECS:
        if spec.key=='relative_lag' and symbol not in ('BTCUSD','ETHUSD'):continue
        decision=f.decide(spec.key,i,other)
        if decision is None:continue
        p,reason=make_plan(symbol,spec,f,i,decision,{'open':bid,'spread':ask-bid},meta)
        if p is None:continue
        p=replace(p,signal_id=f'{spec.key}:{spec.version}:{symbol}:{asof}',entry_at=asof,deadline=asof+spec.horizon_hours*3600)
        plans.append({'strategy':spec.key,'version':spec.version,'regime':decision['regime'],'plan':asdict(p),'mode':'SHADOW_ONLY','alert_authorized':False})
    return plans,None

def collect(path,meta,output):
    snapshot=json.loads(Path(path).read_text())
    # Protect against rebranding historical replay as forward evidence.
    if abs(time.time()-float(snapshot['asof']))>300:raise ValueError('prospective snapshot must be within five minutes of collector clock')
    plans,reason=detect(snapshot,meta)
    digest=hashlib.sha256(Path(path).read_bytes()).hexdigest()
    store=RevisionStore(output)
    for p in plans:store.append(p['plan']['signal_id'],p,{'snapshot_sha256':digest,'actual_forward_execution':False})
    return {'shadow_observations':len(plans),'rejection':reason,'production_authorized':False}

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('snapshot');parser.add_argument('metadata');parser.add_argument('--output',default=str(Path(__file__).with_name('shadow_events.jsonl')))
    args=parser.parse_args()
    destination=Path(args.output).resolve();root=Path(__file__).resolve().parent
    if root not in destination.parents:parser.error('output must stay inside isolated research workspace')
    print(json.dumps(collect(args.snapshot,json.loads(Path(args.metadata).read_text()),destination),indent=2))
