"""Lab-scoped source registration and read-only genuine-cache probe.

The frozen evaluator still consumes declarative intents and never executes source.
This bridge does not admit a model to the running consumer or enable delivery.
"""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import os
import sqlite3
import sys
import tempfile
import time
from types import SimpleNamespace
import urllib.request

from .control import ControlPlane
from .bootstrap import DEFAULT_STATE
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from quant_live.adapter import canonical,TF_SECONDS
from quant_live.model_host import validate_source
from quant_live.runtime import bounded_model,qualify

def register_source(control,token,lab,manifest,source):
    control.own(token,lab)
    if manifest.get('lab')!=lab or manifest.get('authorship',{}).get('lab')!=lab or not manifest.get('authorship',{}).get('session_reference'):
        raise ValueError('Own lab and actual authoring-session provenance required')
    validate_source(source)
    spec={'id':manifest['key'],'version':manifest['version'],'name':manifest['name'],'timeframe':manifest['timeframe'],
          'hypothesis':manifest.get('hypothesis') or manifest['name'],
          'entry_conditions':'Executable pure detect(snapshot), causally replayed with completed supplied candles only.',
          'exit_conditions':'Fixed declared SL/TP and horizon from executable output; common frozen execution policy.',
          'stop_loss_method':manifest.get('risk_model','See registered executable structural invalidation rule.'),
          'take_profit_method':manifest.get('planned_rr','See registered executable take-profit rule.'),
          'risk_model':manifest.get('risk_model','One planned risk unit; simulated outcomes only.'),
          'intended_conditions':manifest.get('hypothesis') or manifest['name'],
          'limitations':manifest.get('known_limitations','No verified edge; prospective and independent review required.'),
          'declared_trials':manifest.get('declared_trials_in_phase',1),'authorship':manifest['authorship'],
          'live_manifest_sha256':hashlib.sha256(canonical(manifest)).hexdigest()}
    try:existing=control.get_strategy(lab,spec['id'],spec['version'])
    except KeyError:return control.register(token,lab,spec,source)
    if existing['sha']!=hashlib.sha256(source.encode()).hexdigest() or json.loads(existing['body'])!=spec:
        raise ValueError('Registered strategy version immutable')
    return {'lab':lab,'id':spec['id'],'version':spec['version'],'source_sha256':existing['sha'],'already_registered':True}

def cached_snapshot(report,db_path,symbol,requirements):
    item=report['runtime']['latest_inputs'].get(symbol)
    if not item:raise ValueError('No genuine collector snapshot for requested market')
    if item['source']!='MT5_SHARED_COLLECTOR':raise ValueError('Genuine collector provenance required')
    frames={}
    uri='file:'+Path(db_path).resolve().as_posix()+'?mode=ro'
    with closing(sqlite3.connect(uri,uri=True)) as db:
        for tf,count in requirements.items():
            if tf not in TF_SECONDS or not isinstance(count,int) or not 1<=count<=12000:raise ValueError('Invalid bounded requirements')
            rows=db.execute('SELECT b.body FROM candles b WHERE symbol=? AND tf=? AND utc+?<=? AND NOT EXISTS (SELECT 1 FROM candle_revisions r WHERE r.symbol=b.symbol AND r.tf=b.tf AND r.utc=b.utc) ORDER BY utc DESC LIMIT ?',
                            (symbol,tf,TF_SECONDS[tf],item['asof'],count)).fetchall()
            frames[tf]=[json.loads(r[0]) for r in reversed(rows)]
    snapshot={'source':'MT5_SHARED_CACHE_PROBE','symbol':symbol,'broker_symbol':item['broker_symbol'],'asof':item['asof'],
              'time_verified':item['time_verified'],'source_basis':item['source_basis'],'quote':item['quote'],
              'metadata':item['metadata'],'frames':frames,'data_quality':item['data_quality']}
    snapshot['input_sha256']=hashlib.sha256(canonical(snapshot)).hexdigest()
    return snapshot

def probe(control,token,lab,manifest,report,db_path,symbol,now=None):
    control.own(token,lab);record=control.get_strategy(lab,manifest['key'],manifest['version'])
    if manifest['lab']!=lab or json.loads(record['body']).get('live_manifest_sha256')!=hashlib.sha256(canonical(manifest)).hexdigest():
        raise PermissionError('Own registered source/manifest binding required')
    data=cached_snapshot(report,db_path,symbol,manifest['requirements']);now=time.time() if now is None else now
    age=now-data['quote']['tick_at'] if data['quote'].get('tick_at') is not None else None
    if not data['time_verified'] or not -5<=now-data['asof']<=60 or age is None or not -5<=age<=30:
        return {'status':'INPUT_REJECTED','reason':'STALE_OR_UNVERIFIED_INPUT','live_writes':0}
    for tf in manifest['requirements']:
        if tf=='M1':continue
        rows=data['frames'].get(tf,[])
        if not rows or not 0<=now-(rows[-1]['utc']+TF_SECONDS[tf])<=2*TF_SECONDS[tf]:
            return {'status':'INPUT_REJECTED','reason':'STALE_OR_MISSING_COMPLETED_CONTEXT','live_writes':0}
    model={'lab':lab,'key':manifest['key'],'version':manifest['version'],'manifest':manifest,'source':record['source'],'sha':record['sha']}
    with tempfile.TemporaryDirectory() as folder:result=bounded_model(SimpleNamespace(folder=Path(folder)),model,data)
    decisions=[]
    for decision in result.get('decisions',[]):
        signal,reason=qualify(data,model,decision,now)
        decisions.append({'qualifies':signal is not None,'reason':reason,'paper_signal_preview':signal})
    return {'status':result['status'],'lab':lab,'source_sha256':record['sha'],'source':data['source'],'input_sha256':data['input_sha256'],
            'asof':data['asof'],'symbol':symbol,'resources':result.get('resources'),'decisions':decisions,
            'scope':'read-only real-data capability probe, not live model admission or a committed signal','live_writes':0,'outbound_calls':0}

def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=['register','probe']);p.add_argument('--root',default=str(DEFAULT_STATE))
    p.add_argument('--lab',required=True,choices=['codex','claude','kimi']);p.add_argument('--manifest',required=True);p.add_argument('--source')
    p.add_argument('--symbol',default='BTCUSD');p.add_argument('--engine',default='http://127.0.0.1:8000')
    p.add_argument('--live-db',default=str(Path(__file__).resolve().parents[1]/'backend/data/quant_live/signals.sqlite3'))
    a=p.parse_args();control=ControlPlane(a.root);token=os.environ.get('TRADEDEN_LAB_TOKEN','');manifest=json.loads(Path(a.manifest).read_text(encoding='utf-8'))
    if a.command=='register':result=register_source(control,token,a.lab,manifest,Path(a.source).read_text(encoding='utf-8'))
    else:
        if a.engine not in ('http://127.0.0.1:8000','http://localhost:8000'):raise ValueError('Local engine only')
        with urllib.request.urlopen(a.engine+'/api/quant-labs/live',timeout=10) as r:report=json.load(r)
        result=probe(control,token,a.lab,manifest,report,a.live_db,a.symbol)
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
