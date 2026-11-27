"""Causal executable replay, isolated from the frozen intent evaluator and live store."""
import argparse
from contextlib import closing
from bisect import bisect_right
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
import time
from types import MappingProxyType

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'backend'))
from quant_live.resources import enforce,usage
from quant_live.adapter import immutable,canonical
from quant_live.model_host import validate_source,BUILTINS,safe_import
from quant_live.runtime import qualify
from quant_live.costs import commission_price
from quant_labs.data import SharedData
from quant_labs.frozen import verify

def prepare(source):
    namespace={'__builtins__':{**BUILTINS,'__import__':safe_import}}
    exec(compile(validate_source(source),'<restricted-research-model>','exec'),namespace)
    return namespace['detect']

def causal_snapshot(symbol,at,m15,h1,position,hour_position,metadata,dataset):
    # The next bar supplies only its open and recorded spread as a historical
    # executable-quote proxy. Its high/low/close are NEVER supplied to the model.
    quote=m15[position];frames={'M15':m15[max(0,position-300):position],'H1':h1[max(0,hour_position-160):hour_position]}
    bid=quote['open'];spread=quote['spread']
    data={'source':'HISTORICAL_CAUSAL_REPLAY','symbol':symbol,'broker_symbol':metadata['broker_symbol'],'asof':at,
          'time_verified':True,'quote':{'bid':bid,'ask':bid+spread,'tick_at':at},'metadata':metadata,'frames':frames,'data_quality':{}}
    descriptor={'dataset':dataset,'symbol':symbol,'at':at,'m15_window':[max(0,position-300),position],'h1_window':[max(0,hour_position-160),hour_position],'quote':data['quote']}
    data['input_sha256']=hashlib.sha256(canonical(descriptor)).hexdigest()
    return data

def main():
    p=argparse.ArgumentParser();p.add_argument('--symbol',required=True);p.add_argument('--start',default='2024-10-15T00:00:00+00:00');p.add_argument('--end',default='2026-10-01T00:00:00+00:00')
    a=p.parse_args();enforce(memory_mb=384,cpu_percent=15,cpu_seconds=30)
    import sqlite3
    with closing(sqlite3.connect('file:'+str(ROOT/'quant_labs/state/control.sqlite3').replace('\\','/')+'?mode=ro',uri=True)) as db:
        settings={k:json.loads(v) for k,v in db.execute('SELECT key,value FROM settings')}
    verify(settings['evaluator']);data=SharedData(ROOT/'quant_labs/state/shared',settings['dataset'])
    m15=tuple(immutable(b) for b in data.read(a.symbol,'M15'));h1=tuple(immutable(b) for b in data.read(a.symbol,'H1'))
    ht=[b['utc']+3600 for b in h1];meta={**data.metadata(a.symbol),'commission_price':commission_price(a.symbol),'tradable_long':True,'tradable_short':True}
    candidates=json.loads((Path(__file__).parent/'candidates.json').read_text(encoding='utf-8'));models=[]
    for row in candidates:
        manifest=json.loads(Path(row['manifest']).read_text(encoding='utf-8'));source=Path(row['source']).read_text(encoding='utf-8')
        if hashlib.sha256(source.encode()).hexdigest()!=row['source_sha256']:raise ValueError('Predeclared model source changed')
        models.append({'lab':'codex','key':row['key'],'version':row['version'],'manifest':manifest,'source':source,'sha':row['source_sha256'],'detect':prepare(source)})
    start=datetime.fromisoformat(a.start).timestamp();end=datetime.fromisoformat(a.end).timestamp()
    results={m['key']:{'intents':[],'detections':0,'rejections':Counter(),'qualified_planned_rr':[],'qualified_net_planned_rr':[]} for m in models}
    count=0;began=time.monotonic()
    for position in range(80,len(m15)):
        at=m15[position]['utc']
        if not start<=at<end or m15[position-1]['utc']+900!=at:continue
        hi=bisect_right(ht,at)
        if hi<64:continue
        snapshot=causal_snapshot(a.symbol,at,m15,h1,position,hi,meta,settings['dataset'])
        read_only=MappingProxyType({**snapshot,'frames':MappingProxyType(snapshot['frames']),'quote':MappingProxyType(snapshot['quote']),'metadata':MappingProxyType(meta)})
        count+=1
        for model in models:
            decisions=model['detect'](read_only);result=results[model['key']]
            for decision in decisions:
                result['detections']+=1;signal,reason=qualify(snapshot,model,decision,at)
                if not signal:result['rejections'][reason]+=1;continue
                result['intents'].append({'symbol':a.symbol,'direction':signal['direction'],'signal_bar_closed_at':at,'entry_at':at,
                                          'stop_loss':signal['stop_loss'],'take_profit':signal['take_profit'],'horizon_seconds':decision['horizon_seconds']})
                result['qualified_planned_rr'].append(signal['planned_rr']);result['qualified_net_planned_rr'].append(signal['net_planned_rr'])
    report={'symbol':a.symbol,'dataset':settings['dataset'],'evaluator':settings['evaluator'],'bars_evaluated':count,'start':a.start,'end':a.end,
            'elapsed_seconds':time.monotonic()-began,'models':results,'resources':usage(),
            'limitations':'Already exposed historical data; historical bid-open/recorded-spread entry proxy, current swap metadata and assumed fees; no live-store writes or performance certification.',
            'live_writes':0,'causal_features':'Only completed M15/H1 slices; next bar high/low/close never supplied; exact entry time; no trade outcome supplied to source.'}
    (Path(__file__).parent/f'intents_{a.symbol}.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('symbol','bars_evaluated','elapsed_seconds','resources')},indent=2))
    print(json.dumps({k:{'detections':v['detections'],'qualified_intents':len(v['intents']),'rejections':dict(v['rejections'])} for k,v in results.items()},indent=2))

if __name__=='__main__':main()
