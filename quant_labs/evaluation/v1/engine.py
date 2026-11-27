"""Common intent-to-fill evaluator. Never executes laboratory source code."""
from bisect import bisect_left
from collections import Counter
from dataclasses import asdict
from datetime import datetime
import json
import math
from pathlib import Path
from .foundation import Plan,simulate,validate_bars,rounded
from .metrics import summarize

POLICY=json.loads(Path(__file__).with_name('policy.json').read_text())
TF={'M1':60,'M15':900,'H1':3600,'H4':14400,'D1':86400}
def epoch(x):return datetime.fromisoformat(x).timestamp()

def evaluate(data,request,checkpoint=None,save=None,should_pause=lambda:False):
    signals=request['signals'];spec=request['strategy'];start=epoch(POLICY['train_start']);end=epoch(POLICY['test_end'])
    checkpoint=checkpoint or {'index':0,'trades':[],'rejections':{},'locks':{}}
    trades=checkpoint['trades'];rejected=Counter(checkpoint['rejections']);locks=checkpoint['locks']
    current_symbol=None;frames={};times={};quality={}
    ordered=sorted(signals,key=lambda s:(s['symbol'],s['entry_at']))
    for index in range(checkpoint['index'],len(ordered)):
        if should_pause():
            checkpoint.update(index=index,trades=trades,rejections=dict(rejected),locks=locks)
            if save:save(checkpoint)
            return {'status':'PAUSED','processed':index,'checkpoint':checkpoint}
        s=ordered[index];symbol=s['symbol'];at=s['entry_at'];horizon=s['horizon_seconds'];long=s['direction']=='LONG'
        if symbol!=current_symbol:
            frames={};times={}
            for tf in set(('M15','M1',spec['timeframe'])):
                bars,errors=validate_bars(data.read(symbol,tf),TF[tf],min(end,epoch(data.manifest['broker_provenance']['end'])))
                frames[tf]=bars;times[tf]=[b['utc'] for b in bars]
                quality[symbol+':'+tf]={'kept':len(bars),'excluded':errors}
            current_symbol=symbol
        if not start<=at<end or at!=s['signal_bar_closed_at'] or at%60:
            rejected['invalid_time_or_entry_semantics']+=1;continue
        if horizon>POLICY['max_horizon_seconds'] or horizon<60:rejected['invalid_horizon']+=1;continue
        if at<locks.get(symbol,0):rejected['overlapping_symbol_opportunity']+=1;continue
        split=epoch(POLICY['validation_start']) if at<epoch(POLICY['validation_start']) else epoch(POLICY['test_start']) if at<epoch(POLICY['test_start']) else end
        if at+horizon>=split:rejected['chronological_boundary_purge']+=1;continue
        tf=spec['timeframe'];prior=bisect_left(times[tf],at-TF[tf])
        if prior>=len(times[tf]) or times[tf][prior]!=at-TF[tf]:rejected['confirming_bar_unavailable']+=1;continue
        entry_tf='M15' if at%900==0 else 'M1';entry_index=bisect_left(times[entry_tf],at)
        if entry_index>=len(times[entry_tf]) or times[entry_tf][entry_index]!=at:rejected['entry_quote_unavailable']+=1;continue
        quote=frames[entry_tf][entry_index];entry=quote['open']+(quote['spread'] if long else 0)
        meta=data.metadata(symbol);stop=rounded(s['stop_loss'],meta['tick_size'],not long);target=rounded(s['take_profit'],meta['tick_size'],not long)
        risk=(entry-stop) if long else (stop-entry);reward=(target-entry) if long else (entry-target)
        if risk<=0 or reward<=0 or quote['spread']/risk>POLICY['max_spread_to_risk']:
            rejected['invalid_levels_or_spread_cost']+=1;continue
        p=Plan(str(index),symbol,s['direction'],at,at,entry,stop,target,at+horizon,risk,quote['spread'])
        normal=simulate(p,frames['M15'],frames['M1'],end,POLICY['commission_price'][symbol],meta,1,times['M15'],times['M1'])
        stress=simulate(p,frames['M15'],frames['M1'],end,POLICY['commission_price'][symbol],meta,2,times['M15'],times['M1'])
        # Lock on the normal scenario only; stress uses exactly the same intents.
        locks[symbol]=normal['exit_at'] if normal.get('r') is not None else p.deadline
        trades.append({'intent_index':index,'plan':asdict(p),'normal':normal,'stress':stress})
        if (index+1)%20==0 and save:save({'index':index+1,'trades':trades,'rejections':dict(rejected),'locks':locks})
    periods={}
    for name,lo,hi in [('train',start,epoch(POLICY['validation_start'])),('validation',epoch(POLICY['validation_start']),epoch(POLICY['test_start'])),('test',epoch(POLICY['test_start']),end)]:
        selected=[t for t in trades if lo<=t['plan']['entry_at'] and t['plan']['deadline']<hi]
        periods[name]={scenario:summarize(selected,lo,hi,scenario) for scenario in ('normal','stress')}
    return {'status':'COMPLETE','periods':periods,'trades':trades,'intent_count':len(signals),'rejections':dict(rejected),'data_quality':quality,
            'forward_test':{'status':'NOT_STARTED','verified_performance':None},'profitability_certified':False,
            'causal_strategy_code_review':'REQUIRED; supplied historical intents alone cannot establish absence of look-ahead',
            'purpose':request.get('purpose','RESEARCH'),'evaluator_version':POLICY['version']}
