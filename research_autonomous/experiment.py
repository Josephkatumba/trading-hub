"""One bounded foreground competition. Never connects to MT5, APIs or Telegram.

Run: python -m research_autonomous.experiment --max-seconds 240
All outputs go into a unique immutable run directory. No optimizers/background jobs.
"""
from __future__ import annotations
import argparse
import bisect
from collections import Counter,defaultdict
from dataclasses import asdict
from datetime import datetime,timezone
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import sys
import time
import numpy as np
from .foundation import Plan,simulate,validate_bars,rounded,VERSION,FINAL
from .hypotheses import Features,SPECS

ROOT=Path(__file__).resolve().parents[1]
CACHE=ROOT/'backend/data/research/bars'
BASE=Path(__file__).resolve().parent
SYMBOLS=['XAUUSD','XAGUSD','BTCUSD','ETHUSD','EURUSD','GBPUSD','USDJPY','USDCHF','USDCAD','AUDUSD','NZDUSD','EURJPY','GBPJPY','NAS100','US500','GER40']
START='2024-10-15'; END='2026-10-01'
FOLDS=[('2025-10-01','2026-01-01'),('2026-01-01','2026-04-01'),('2026-04-01','2026-07-01'),('2026-07-01','2026-10-01')]
MAX_TRIALS=83 # 5 registered hypotheses x 16 instruments + 3 selection policies
FX={'EURUSD','GBPUSD','USDJPY','USDCHF','USDCAD','AUDUSD','NZDUSD','EURJPY','GBPJPY'}
def ts(date):return datetime.fromisoformat(date).replace(tzinfo=timezone.utc).timestamp()
def iso(x):return datetime.fromtimestamp(x,timezone.utc).isoformat()
def dump(path,obj):path.write_text(json.dumps(obj,indent=2,allow_nan=False,default=str),encoding='utf-8')
def fee(symbol):return (.007 if 'JPY' in symbol else .00007) if symbol in FX else .07 if symbol=='XAUUSD' else .0014 if symbol=='XAGUSD' else 0
def phase(at):return 'train' if at<ts('2025-10-01') else 'validation' if at<ts('2026-04-01') else 'test'
def fold_end(at):
    for lo,hi in FOLDS:
        if ts(lo)<=at<ts(hi):return ts(hi)
    return ts('2025-10-01')
def complete(r):return r.get('status') in FINAL and r.get('r') is not None

def weekly_series(trades,start,end,field='normal'):
    n=max(1,math.ceil((end-start)/(7*86400))); values=np.zeros(n);counts=np.zeros(n)
    for t in trades:
        r=t[field]
        if complete(r):
            # Entry-week blocking preserves simultaneous cross-market opportunities;
            # max holding <=24h makes week boundaries a limited residual dependency.
            k=min(n-1,max(0,int((t['plan']['entry_at']-start)//(7*86400))))
            values[k]+=r['r'];counts[k]+=1
    return values,counts

def summarize(trades,start,end,field='normal',inference=False):
    known=[t for t in trades if complete(t[field])]
    rs=np.array([t[field]['r'] for t in known],dtype=float)
    equity=peak=dd=0
    for t in sorted(known,key=lambda t:t[field]['exit_at']):
        equity+=t[field]['r'];peak=max(peak,equity);dd=max(dd,peak-equity)
    gains=float(rs[rs>0].sum());loss=-float(rs[rs<0].sum())
    weeks,counts=weekly_series(trades,start,end,field)
    vol=float(weeks.std(ddof=1)) if len(weeks)>1 else 0
    out={'attempted':len(trades),'resolved':len(known),'unknown':len(trades)-len(known),'statuses':dict(Counter(t[field]['status'] for t in trades)),
         'total_r':float(rs.sum()),'expectancy_r':float(rs.mean()) if len(rs) else None,'profit_factor':gains/loss if loss else None,
         'win_rate':float((rs>0).mean()) if len(rs) else None,'max_realized_drawdown_r':dd,
         'weekly_pnl_mean_over_sd':float(weeks.mean()/vol) if vol else None,'opportunities_per_month':len(trades)/max((end-start)/86400/30.4375,1),
         'unknown_fraction':1-len(known)/len(trades) if trades else None,
         'unknown_minus_1_5r_scenario':float(rs.sum()-1.5*(len(trades)-len(known))),'weekly_pnl_r':weeks.tolist()}
    if inference and len(rs) and np.count_nonzero(counts)>=2:
        rng=np.random.default_rng(19102026)
        ix=rng.integers(0,len(weeks),size=(2500,len(weeks)))
        sums=weeks[ix].sum(axis=1);denom=counts[ix].sum(axis=1)
        estimates=sums[denom>0]/denom[denom>0]
        out['weekly_bootstrap_expectancy_ci95']=np.quantile(estimates,[.025,.975]).tolist()
        signs=rng.choice([-1,1],size=(5000,len(weeks)))
        null=signs@weeks
        out['weekly_sign_flip_p_one_sided']=(1+int(np.count_nonzero(null>=weeks.sum())))/5001
    else:
        out['weekly_bootstrap_expectancy_ci95']=None;out['weekly_sign_flip_p_one_sided']=1.0
    return out

def stats_for(trades,start,end):
    # Purge unresolved-at-boundary observations so future exits cannot leak backward.
    selected=[t for t in trades if start<=t['plan']['entry_at'] and t['plan']['deadline']<end]
    return {'normal':summarize(selected,start,end,inference=True),'stress':summarize(selected,start,end,'stress')}

def make_plan(symbol,spec,f,i,d,entry_bar,meta):
    entry_at=f.utc[i]+3600
    spread=entry_bar['spread'];long=d['direction']=='LONG';entry=entry_bar['open']+(spread if long else 0)
    stop=d['stop'] if d['stop'] is not None else entry+(-1 if long else 1)*d['stop_distance']
    tick=meta['tick_size'];stop=rounded(stop,tick,not long)
    risk=abs(entry-stop)
    target=d['target'] if d['target'] is not None else entry+(1 if long else -1)*d['target_r']*risk
    target=rounded(float(target),tick,not long)
    reward=(target-entry) if long else (entry-target)
    minimum=1.2 if spec.key=='shock_fade' else 1
    if risk<=0 or reward/risk<minimum or spread/risk>.1:return None,'execution_geometry_or_cost'
    if not (.25*d['atr']<=risk<=5*d['atr']):return None,'risk_outside_bounds'
    # Tick-valid stop must remain on the loss side after adverse rounding.
    if (long and stop>=entry) or (not long and stop<=entry):return None,'invalid_stop'
    sid=f'{spec.key}:{spec.version}:{symbol}:{int(entry_at)}'
    return Plan(sid,symbol,d['direction'],entry_at,entry_at,entry,stop,target,entry_at+3600*spec.horizon_hours,risk,spread),None

def select_training(past,by_regime):
    groups=defaultdict(list)
    for t in past:groups[(t['symbol'],t['regime'] if by_regime else 'ANY',t['strategy'])].append(t)
    choices={};scores={}
    for (symbol,regime,key),group in groups.items():
        known=[t for t in group if complete(t['normal'])]
        stress=[t['stress']['r'] for t in group if complete(t['stress'])]
        if len(known)<30 or len(known)/len(group)<.95 or len(stress)<30 or np.mean(stress)<=0:continue
        # Frozen training-only score: one-sided 90% normal approximation using weekly clusters.
        v,n=weekly_series(group,min(t['plan']['entry_at'] for t in group),max(t['plan']['deadline'] for t in group)+1)
        mean=sum(t['normal']['r'] for t in known)/len(known)
        residual=v-mean*n
        se=math.sqrt(len(v)/(len(v)-1)*float((residual**2).sum()))/len(known) if len(v)>1 else math.inf
        lower=mean-1.645*se
        if lower<=0:continue
        marker=(symbol,regime)
        if lower>scores.get(marker,-math.inf):scores[marker]=lower;choices[marker]=key
    return choices,{f'{k[0]}:{k[1]}':{'strategy':v,'score':scores[k]} for k,v in choices.items()}

def exposure_filter(trades):
    """Deterministic risk budget: <=3 simultaneous units, one symbol and one broad factor group."""
    accepted=[];active=[];reject=Counter()
    def factor(s):return 'FX' if s in FX else 'CRYPTO' if s in ('BTCUSD','ETHUSD') else 'METALS' if s in ('XAUUSD','XAGUSD') else 'EQUITY_INDICES'
    for t in sorted(trades,key=lambda t:(t['plan']['entry_at'],t['strategy'],t['symbol'])):
        at=t['plan']['entry_at'];active=[a for a in active if a['busy_until']>at]
        if len(active)>=3 or any(a['symbol']==t['symbol'] or factor(a['symbol'])==factor(t['symbol']) for a in active):
            reject['portfolio_exposure']+=1;continue
        accepted.append(t);active.append(t)
    return accepted,dict(reject)

def run(max_seconds=240,max_attempts=2000):
    started=time.monotonic()
    # Lower CPU scheduling priority on Windows; never create a worker process.
    if os.name=='nt':
        import ctypes
        ctypes.windll.kernel32.GetCurrentProcess.restype=ctypes.c_void_p
        ctypes.windll.kernel32.SetPriorityClass.argtypes=[ctypes.c_void_p,ctypes.c_ulong]
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(),0x00004000)
    config={'framework':'autonomous-research-1.0.0','resolver_version':VERSION,'start':START,'end':END,'symbols':SYMBOLS,
            'specs':[asdict(s) for s in SPECS],'folds':FOLDS,'purge_hours':48,'max_seconds':max_seconds,
            'max_attempts_per_experiment':max_attempts,'hypothesis_family_size':MAX_TRIALS,'optimizer':None,'workers':1,
            'execution':'bid bars; executable ask/bid entries; half-open paths; gaps unknown; .25 spread entry/limit/time slippage, .5 spread stops',
            'commission':'FX .00007 (.007 JPY), gold .07, silver .0014 price units round-trip; others zero, assumed',
            'financing':'current snapshot proxy modes 1/5 only; unknown conversions fail closed; stress doubles costs and drops credits',
            'stress':'2x entry/exit spreads, slippage, commissions and positive financing; same frozen stop/target/risk',
            'selection':'three policies: static diverse; train-only per-market; train-only per-market/regime; 30 known/95% coverage/positive stressed training/90% cluster score',
            'authorization':'offline only; no production promotion or notifications'}
    config_hash=hashlib.sha256(json.dumps(config,sort_keys=True).encode()).hexdigest()
    folder=BASE/'runs'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'_'+config_hash[:10])
    folder.mkdir(parents=True,exist_ok=False)
    dump(folder/'preregistered.json',config)
    frozen_code={p.name:p.read_bytes() for p in BASE.glob('*.py')}
    (folder/'source').mkdir()
    for name,content in frozen_code.items():(folder/'source'/name).write_bytes(content)
    events=open(folder/'experiments.jsonl','a',encoding='utf-8')
    def event(kind,**kwargs):events.write(json.dumps({'event':kind,'at':datetime.now(timezone.utc).isoformat(),**kwargs})+'\n');events.flush()
    source_manifest={};data_report={};histories={};features={};all_trades=[];experiment_results=[]
    source_meta=json.loads((CACHE/'manifest.json').read_text())
    asof=min(ts(END),datetime.fromisoformat(source_meta['end']).timestamp())
    def budget():
        if time.monotonic()-started>max_seconds:raise TimeoutError('foreground wall-clock budget exceeded; partial evidence retained')
    try:
        for symbol in SYMBOLS:
            budget();frames={};quality={}
            for tf,seconds in [('H1',3600),('M15',900),('M1',60)]:
                path=CACHE/f'{symbol}_{tf}.json.gz';raw=path.read_bytes()
                source_manifest[path.name]={'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}
                bars=json.loads(gzip.decompress(raw))
                bars,rejected=validate_bars(bars,seconds,asof)
                frames[tf]=bars
                gaps=sum(b['utc']-a['utc']!=seconds for a,b in zip(bars,bars[1:]))
                quality[tf]={'kept':len(bars),'rejected':rejected,'gaps':gaps,'first':iso(bars[0]['utc']) if bars else None,'last':iso(bars[-1]['utc']) if bars else None}
            # Retain only one full M15/M1 instrument at a time to bound memory.
            histories[symbol]={'H1':frames['H1']};features[symbol]=Features(frames['H1'])
            data_report[symbol]=quality
        print('Validated 16 instruments; running 80 registered hypothesis/market cases.',flush=True)
        for symbol in SYMBOLS:
            budget();f=features[symbol]
            frames={}
            for tf,seconds in [('M15',900),('M1',60)]:
                raw=(CACHE/f'{symbol}_{tf}.json.gz').read_bytes()
                if hashlib.sha256(raw).hexdigest()!=source_manifest[f'{symbol}_{tf}.json.gz']['sha256']:raise RuntimeError('cache changed during run')
                frames[tf]=validate_bars(json.loads(gzip.decompress(raw)),seconds,asof)[0]
            m15,m1=frames['M15'],frames['M1'];times=[b['utc'] for b in m15];mtimes=[b['utc'] for b in m1]
            meta=source_meta['symbols'][symbol]['meta']
            for spec in SPECS:
                budget();experiment_id=f'{spec.key}@{spec.version}:{symbol}';event('IDEA',experiment_id=experiment_id,spec=asdict(spec))
                if spec.key=='relative_lag' and symbol not in ('BTCUSD','ETHUSD'):
                    result={'experiment_id':experiment_id,'strategy':spec.key,'symbol':symbol,'status':'UNSUPPORTED','reason':'cross-market hypothesis restricted to BTC/ETH'}
                    experiment_results.append(result);event('UNSUPPORTED',**result);continue
                event('RESEARCH',experiment_id=experiment_id);event('IMPLEMENTATION',experiment_id=experiment_id)
                trials=[];rejections=Counter();busy=-math.inf;attempts=0
                other=features.get('ETHUSD' if symbol=='BTCUSD' else 'BTCUSD') if spec.key=='relative_lag' else None
                for i in range(121,len(f.utc)):
                    if i%512==0:budget()
                    entry_at=float(f.utc[i]+3600)
                    if not ts(START)<=entry_at<asof:continue
                    d=f.decide(spec.key,i,other)
                    if d is None:continue
                    if entry_at<busy:rejections['overlapping_strategy_symbol']+=1;continue
                    deadline=entry_at+spec.horizon_hours*3600
                    if deadline>=fold_end(entry_at)-48*3600:rejections['fold_boundary_embargo']+=1;continue
                    j=bisect.bisect_left(times,entry_at)
                    if j>=len(times) or times[j]!=entry_at:rejections['missing_entry_quote_proxy']+=1;continue
                    plan,reason=make_plan(symbol,spec,f,i,d,m15[j],meta)
                    if plan is None:rejections[reason]+=1;continue
                    if attempts>=max_attempts:rejections['resource_attempt_cap']+=1;continue
                    attempts+=1
                    normal=simulate(plan,m15,m1,asof,fee(symbol),meta,1,times,mtimes)
                    stressed=simulate(plan,m15,m1,asof,fee(symbol),meta,2,times,mtimes)
                    busy=max(normal['exit_at'] if complete(normal) else deadline,stressed['exit_at'] if complete(stressed) else deadline)
                    t={'experiment_id':experiment_id,'strategy':spec.key,'version':spec.version,'symbol':symbol,'regime':d['regime'],
                       'phase':phase(entry_at),'plan':asdict(plan),'normal':normal,'stress':stressed,'busy_until':busy}
                    trials.append(t);all_trades.append(t)
                stats={p:stats_for(trials,ts(lo),ts(hi)) for p,lo,hi in [('train',START,'2025-10-01'),('validation','2025-10-01','2026-04-01'),('test','2026-04-01',END)]}
                test=stats['test']['normal'];status='NEEDS_DATA' if test['resolved']<60 or (test['unknown_fraction'] or 0)>.05 else 'REJECTED' if (test['expectancy_r'] or 0)<=0 else 'REVIEW_ONLY'
                result={'experiment_id':experiment_id,'strategy':spec.key,'version':spec.version,'symbol':symbol,'status':status,'statistics':stats,'rejections':dict(rejections)}
                experiment_results.append(result);event('BACKTEST',experiment_id=experiment_id,statistics=stats['train'])
                event('OUT_OF_SAMPLE_VALIDATION',experiment_id=experiment_id,statistics={'validation':stats['validation'],'test':stats['test']})
                event(status,experiment_id=experiment_id,reason='provisional pending family-wise test and coverage gates')
            print(f'{symbol}: completed fixed-rule experiments',flush=True)
        # Holm correction includes all declared hypothesis/market cases and policy trials.
        active=[r for r in experiment_results if 'statistics' in r]
        policies={name:[] for name in ('static_diverse','train_market','train_regime')};selection_log=[];exposure_rejections={}
        for lo,hi in FOLDS:
            budget();cut=ts(lo)-48*3600
            past=[t for t in all_trades if t['plan']['deadline']<cut]
            market,market_evidence=select_training(past,False);regime,regime_evidence=select_training(past,True)
            future=[t for t in all_trades if ts(lo)<=t['plan']['entry_at'] and t['plan']['deadline']<ts(hi)-48*3600]
            selection_log.append({'fold':[lo,hi],'training_deadline_before':iso(cut),'market':market_evidence,'regime':regime_evidence})
            choices={'static_diverse':future,'train_market':[t for t in future if market.get((t['symbol'],'ANY'))==t['strategy']],
                     'train_regime':[t for t in future if regime.get((t['symbol'],t['regime']))==t['strategy']]}
            for name,proposals in choices.items():
                chosen,rejected=exposure_filter(proposals);policies[name].extend(chosen);exposure_rejections[name+':'+lo]=rejected
        policy_results={name:{'validation':stats_for(trades,ts('2025-10-01'),ts('2026-04-01')),'test':stats_for(trades,ts('2026-04-01'),ts(END))} for name,trades in policies.items()}
        pvals=[(r['experiment_id'],r['statistics']['test']['normal']['weekly_sign_flip_p_one_sided']) for r in active]
        pvals += [(name,r['test']['normal']['weekly_sign_flip_p_one_sided']) for name,r in policy_results.items()]
        adjusted={};running=0
        for i,(key,p) in enumerate(sorted(pvals,key=lambda x:x[1])):
            running=max(running,min(1,(MAX_TRIALS-i)*p));adjusted[key]=running
        for r in active:
            r['holm_p']=adjusted[r['experiment_id']]
            n=r['statistics']['test']['normal'];stress=r['statistics']['test']['stress'];val=r['statistics']['validation']['normal']
            ci=n['weekly_bootstrap_expectancy_ci95']
            passed=(n['resolved']>=60 and (n['unknown_fraction'] or 0)<=.05 and ci and ci[0]>0 and
                    (n['expectancy_r'] or 0)>0 and (stress['expectancy_r'] or 0)>0 and (val['expectancy_r'] or 0)>0 and r['holm_p']<.05)
            r['qualification']='SHADOW_REVIEW_CANDIDATE' if passed else 'NOT_QUALIFIED'
            event('QUALIFICATION_REVIEW',experiment_id=r['experiment_id'],qualification=r['qualification'],holm_p=r['holm_p'],production_authorized=False)
        for name,r in policy_results.items():r['holm_p']=adjusted[name]
        # Cross-strategy weekly dependence diagnostic on the final test period.
        w=[weekly_series([t for t in all_trades if t['strategy']==s.key and ts('2026-04-01')<=t['plan']['entry_at']<ts(END)],ts('2026-04-01'),ts(END))[0] for s in SPECS]
        with np.errstate(invalid='ignore',divide='ignore'):corr=np.corrcoef(w)
        corr=[[float(v) if math.isfinite(v) else None for v in row] for row in corr]
        dump(folder/'results.json',{'experiments':experiment_results,'policies':policy_results,'selection_log':selection_log,
                                   'portfolio_rejections':exposure_rejections,'family_weekly_correlations':{'keys':[s.key for s in SPECS],'matrix':corr},'family_size':MAX_TRIALS})
        with (folder/'trades.jsonl').open('w',encoding='utf-8') as file:
            for trade in all_trades:file.write(json.dumps(trade)+'\n')
        with (folder/'policy_trades.jsonl').open('w',encoding='utf-8') as file:
            for name,trades in policies.items():
                for trade in trades:file.write(json.dumps({'policy':name,**trade})+'\n')
        dump(folder/'data_quality.json',data_report)
        dump(folder/'data_manifest.json',{'cache_end':source_meta['end'],'basis':source_meta['basis'],'files':source_manifest,'original_manifest':source_meta})
        code={name:hashlib.sha256(content).hexdigest() for name,content in frozen_code.items()}
        if any((BASE/name).read_bytes()!=content for name,content in frozen_code.items()):raise RuntimeError('research source changed during run')
        dump(folder/'run_summary.json',{'status':'COMPLETE','seconds':time.monotonic()-started,'python':sys.version,'numpy':np.__version__,
                                      'platform':platform.platform(),'config_hash':config_hash,'code_hashes':code,'strategies':len(SPECS),
                                      'registered_cases':len(experiment_results),'executed_cases':len(active),'trades':len(all_trades),
                                      'shadow_review_candidates':[r['experiment_id'] for r in active if r['qualification']=='SHADOW_REVIEW_CANDIDATE'],
                                      'production_authorized':False})
        event('COMPLETE',seconds=time.monotonic()-started)
        print('Run saved: '+str(folder),flush=True)
        return folder
    except Exception as exc:
        event('FAILED',error=repr(exc));dump(folder/'run_summary.json',{'status':'FAILED','error':repr(exc),'seconds':time.monotonic()-started})
        raise
    finally:events.close()

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--max-seconds',type=int,default=240);parser.add_argument('--max-attempts',type=int,default=2000)
    args=parser.parse_args()
    if not 1<=args.max_seconds<=600 or not 1<=args.max_attempts<=5000:parser.error('bounds: 1..600 seconds, 1..5000 attempts')
    run(args.max_seconds,args.max_attempts)
