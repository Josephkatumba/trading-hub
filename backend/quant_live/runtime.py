"""Shared-data model pipeline, durable paper signals and append-only outcome revisions."""
from dataclasses import asdict
from datetime import datetime,timezone
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid
from .adapter import canonical,TF_SECONDS
from .execution import Plan,simulate,rounded
from .store import LAB_NAMES,PROJECT
from .model_host import LaboratoryProvider
from .telegram import message,ExperimentalNotifier

def numeric(v):return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)
def weekend_seconds(start,end):
    """Seconds of Saturday/Sunday (UTC) inside [start,end]."""
    if not end>start:return 0
    total=0;day=int(start//86400)
    while day*86400<end:
        if (day+4)%7 in (0,6):total+=max(0,min(end,(day+1)*86400)-max(start,day*86400))
        day+=1
    return total
def qualify(snapshot,model,d,now):
    q=snapshot.get('quote',{});meta=snapshot.get('metadata',{});tf=model['manifest']['timeframe'];bars=snapshot['frames'].get(tf,[])
    if not snapshot.get('time_verified'):return None,'UNVERIFIED_TIME'
    if not numeric(snapshot.get('asof')) or not -5<=now-snapshot['asof']<=60:return None,'STALE_SNAPSHOT'
    if not numeric(q.get('tick_at')) or not -5<=now-q['tick_at']<=30:return None,'STALE_OR_FUTURE_QUOTE'
    if not bars or not 0<=now-(bars[-1]['utc']+TF_SECONDS[tf])<=2*TF_SECONDS[tf]:return None,'STALE_OR_FUTURE_CANDLE'
    for required in model['manifest'].get('requirements',{}):
        if required=='M1':continue # Minute history refines outcomes; missing paths stay unknown.
        history=snapshot['frames'].get(required,[])
        if not history:return None,'STALE_OR_MISSING_MODEL_CONTEXT'
        last_close=history[-1]['utc']+TF_SECONDS[required]
        # Higher-timeframe context legitimately ages over the weekend market close (e.g. Friday's D1
        # on Monday). Only weekend hours actually spanned are excused; midweek staleness still fails.
        allowance=2*TF_SECONDS[required]+(weekend_seconds(last_close,now) if TF_SECONDS[required]>=14400 else 0)
        if not 0<=now-last_close<=allowance:return None,'STALE_OR_MISSING_MODEL_CONTEXT'
    if not all(numeric(q.get(k)) and q[k]>0 for k in ('bid','ask')) or q['ask']<q['bid']:return None,'INVALID_QUOTE'
    direction=d.get('direction')
    if direction not in ('LONG','SHORT'):return None,'INVALID_DIRECTION'
    if not meta.get('tradable_long' if direction=='LONG' else 'tradable_short'):return None,'INSTRUMENT_NOT_TRADABLE'
    if not all(numeric(d.get(k)) for k in ('stop_loss','take_profit','horizon_seconds','atr')):return None,'INVALID_LEVELS'
    if d['atr']<=0 or not 60<=d['horizon_seconds']<=604800:return None,'INVALID_RISK_OR_HORIZON'
    long=direction=='LONG';entry=q['ask'] if long else q['bid'];exit_quote=q['bid'] if long else q['ask']
    tick=meta.get('tick_size')
    if not numeric(tick) or tick<=0:return None,'TICK_SIZE_UNAVAILABLE'
    stop=rounded(d['stop_loss'],tick,not long);target=rounded(d['take_profit'],tick,not long)
    risk=entry-stop if long else stop-entry;reward=target-entry if long else entry-target
    if min(stop,target,entry)<=0 or risk<=0 or reward<=0:return None,'INVALID_GEOMETRY'
    if not (stop<exit_quote<target if long else target<exit_quote<stop):return None,'QUOTE_ALREADY_AT_BARRIER'
    if not .5*d['atr']<=risk<=5*d['atr']:return None,'UNREALISTIC_STOP_DISTANCE'
    if abs(entry-bars[-1]['close'])>.5*d['atr']:return None,'ENTRY_DRIFT'
    spread=q['ask']-q['bid'];cost=meta.get('commission_price')
    if not numeric(cost) or cost<0:return None,'COSTS_UNVERIFIED'
    reserve=cost+spread*.75
    net_rr=(reward-reserve)/(risk+reserve)
    if spread/risk>.1 or net_rr<2:return None,'SPREAD_OR_NET_RR'
    at=bars[-1]['utc']+TF_SECONDS[tf]
    sid='ql_'+hashlib.sha256(canonical([model['lab'],model['key'],model['version'],snapshot['symbol'],at])).hexdigest()[:32]
    return {'signal_id':sid,'lab':model['lab'],'lab_name':LAB_NAMES[model['lab']],'model_key':model['key'],'model_name':model['manifest']['name'],
            'model_version':model['version'],'classification':'EXPERIMENTAL','symbol':snapshot['symbol'],'broker_symbol':snapshot['broker_symbol'],
            'direction':direction,'timeframe':tf,'signal_bar_closed_at':at,'entry_at':now,'input_data_timestamp':snapshot['asof'],
            'input_sha256':snapshot['input_sha256'],'model_source_sha256':model['sha'],'entry':entry,'entry_type':'MARKET_PAPER_QUOTE',
            'stop_loss':stop,'take_profit':target,'risk':risk,'planned_rr':reward/risk,'net_planned_rr':net_rr,
            'deadline':now+d['horizon_seconds'],'spread':spread,'commission_price':cost,'metadata':meta,'atr':d['atr'],
            'rationale':str(d.get('rationale',''))[:1000],'session':session(now),'actual_realized_r':None,
            'r_basis':'simulated signal outcome, not actual executed-trade R'},None

def session(at):
    hour=datetime.fromtimestamp(at,timezone.utc).hour
    return 'UTC_00_07' if hour<7 else 'UTC_07_12' if hour<12 else 'UTC_12_16' if hour<16 else 'UTC_16_24'

def bounded_model(store,model,snapshot):
    folder=store.folder/'workers';folder.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=folder) as temporary:
        path=Path(temporary);(path/'input.json').write_text(json.dumps({'source':model['source'],'source_sha256':model['sha'],'snapshot':snapshot}),encoding='utf-8')
        flags=subprocess.CREATE_NO_WINDOW if sys.platform=='win32' else 0
        try:
            run=subprocess.run([sys.executable,'-I',str(Path(__file__).with_name('worker.py')),str(path/'input.json')],stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=5,creationflags=flags)
        except subprocess.TimeoutExpired:return {'status':'TIMED_OUT'}
        if not (path/'result.json').exists():return {'status':'FAILED','reason':'worker stopped before producing bounded output'}
        return json.loads((path/'result.json').read_text(encoding='utf-8'))

class Runtime:
    def __init__(self,store,runner=bounded_model):self.store,self.runner=store,runner;self.providers={lab:LaboratoryProvider(lab,store) for lab in LAB_NAMES};self.cursor=0;self.resolve_cursor={}
    def process(self,snapshot,now=None):
        live_clock=now is None;now=time.time() if live_clock else now;owner=uuid.uuid4().hex;budget=time.monotonic()+10
        if not self.store.lease(owner,now,seconds=30):return {'status':'BUSY','signals':[]}
        generated=[];runs=[]
        try:
            self.store.add_candles(snapshot)
            models=[m for p in self.providers.values() for m in p.models()]
            # Per-cycle cap controls laptop work without imposing a strategy-count limit.
            selected=[models[(self.cursor+i)%len(models)] for i in range(min(8,len(models)))]
            self.cursor=(self.cursor+8)%max(1,len(models))
            for model in selected:
                if time.monotonic()>=budget:break
                if snapshot['symbol'] not in model['manifest']['instruments']:continue
                bars=snapshot['frames'].get(model['manifest']['timeframe'],[])
                if not bars:continue
                close=bars[-1]['utc']+TF_SECONDS[model['manifest']['timeframe']]
                marker=hashlib.sha256(canonical([model['lab'],model['key'],model['version'],snapshot['symbol'],close])).hexdigest()
                if not self.store.claim(marker,now):continue
                ident={'lab':model['lab'],'key':model['key'],'version':model['version'],'symbol':snapshot['symbol'],'bar_closed_at':close,
                       'data_shortfall':{tf:[len(snapshot['frames'].get(tf,[])),n] for tf,n in model['manifest'].get('requirements',{}).items() if len(snapshot['frames'].get(tf,[]))<n}}
                # Fail closed before spending a model worker on stale/unverified input.
                tick=snapshot.get('quote',{}).get('tick_at')
                if not numeric(tick) or not -5<=now-tick<=30 or not 0<=now-close<=2*TF_SECONDS[model['manifest']['timeframe']]:
                    self.store.finish_run(marker,'REJECTED',{**ident,'reason':'STALE_OR_FUTURE_INPUT'});continue
                result=self.runner(self.store,model,snapshot);runs.append({'model':model['key'],**result})
                if live_clock:now=time.time()
                current=self.store.model(model['lab'],model['key'],model['version'])
                if not current or current['status']!='EXPERIMENTAL' or not current['scan_enabled']:
                    self.store.finish_run(marker,'REVOKED',{**ident,'reason':'MODEL_DISABLED_DURING_RUN'});continue
                if result['status']!='COMPLETE':self.store.finish_run(marker,result['status'],{**ident,**result});continue
                decisions=result['decisions'];quality=None
                # One economic signal per model/symbol/closed bar.
                for decision in decisions[:1]:
                    signal,reason=qualify(snapshot,model,decision,now)
                    if signal and self.store.record(signal,True):
                        self.store.queue_message(signal['signal_id'],message(signal),now);generated.append(signal)
                    elif reason:
                        detected={'signal_id':'ql_'+hashlib.sha256(canonical([model['lab'],model['key'],model['version'],snapshot['symbol'],close])).hexdigest()[:32],
                                  'lab':model['lab'],'lab_name':LAB_NAMES[model['lab']],'model_key':model['key'],'model_name':model['manifest']['name'],
                                  'model_version':model['version'],'symbol':snapshot['symbol'],'timeframe':model['manifest']['timeframe'],
                                  'signal_bar_closed_at':close,'entry_at':now,'input_sha256':snapshot['input_sha256'],
                                  'classification':'EXPERIMENTAL','actual_realized_r':None,'planned_rr':None,'session':session(now)}
                        self.store.record(detected,False,reason);quality=reason
                        with self.store.db() as c:self.store.event(c,None,'QUALITY_REJECTED',{'lab':model['lab'],'key':model['key'],'version':model['version'],'symbol':snapshot['symbol'],'reason':reason,'input_sha256':snapshot['input_sha256']},now)
                self.store.finish_run(marker,'COMPLETE',{**ident,'quality_rejection':quality,'decisions':len(decisions),'resources':result.get('resources',{}),'input_sha256':snapshot['input_sha256'],'source_sha256':model['sha'],'input_data_timestamp':snapshot['asof']})
            self.resolve(snapshot['symbol'],now)
            notifier=ExperimentalNotifier(self.store);notifier.process(now)
            return {'status':'COMPLETE','signals':generated,'runs':runs,'telegram_mode':'EXPERIMENTAL_APPROVED' if notifier.live else 'DRY_RUN','outbound_calls':notifier.calls}
        finally:self.store.release(owner)
    def resolve(self,symbol,now):
        written=0;budget=time.monotonic()+5
        candidates=self.store.pending(symbol,self.resolve_cursor.get(symbol))
        for s in candidates:
            if time.monotonic()>budget:break
            self.resolve_cursor[symbol]=(s['entry_at'],s['signal_id'])
            if s['symbol']!=symbol or not s.get('confirmed'):continue
            p=Plan(s['signal_id'],symbol,s['direction'],s['signal_bar_closed_at'],s['entry_at'],s['entry'],s['stop_loss'],s['take_profit'],s['deadline'],s['risk'],s['spread'])
            m15=self.store.candles(symbol,'M15',s['entry_at']-900,min(now,s['deadline']))
            m1=self.store.candles(symbol,'M1',s['entry_at']-60,min(now,s['deadline']))
            result=simulate(p,m15,m1,now,s['commission_price'],s['metadata'])
            result={**result,'simulated_net_r':result.get('r'),'actual_realized_r':None,'execution_evidence':'PAPER_SIGNAL_ONLY'}
            written+=self.store.outcome(s['signal_id'],result,now)
        return written

def register_codex(store):
    folder=PROJECT/'quant_labs/state/labs/codex/strategies/compression_escape'
    manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'));source=(folder/'model.py').read_text(encoding='utf-8')
    store.register(manifest,source,manifest['authorship'])
