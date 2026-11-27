"""Offline Phase 2 validation: frozen context protocol and recorded-plan cost replay.

No live service imports, MT5 calls, permissions or production writes. Run from root:
python -m backend.research.phase2_validation --output docs/phase2-validation.json
"""
import argparse
from bisect import bisect_right
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT)); sys.path.insert(0,str(ROOT/'backend'))
from quant_labs.data import SharedData
from research.intelligence_compare import DATASET, COUNTS
from research.intelligence_preview import evaluate, VERSION
from research.broker_calendar import BrokerCalendar
from market_intel.engine import build
from market_intel.rules import TF
from quant_live.execution import Plan, simulate


def epoch(s):
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc).timestamp()


def partition(t):
    return 'train' if t<epoch('2025-10-01') else 'validation' if t<epoch('2026-04-01') else 'test'


def window(full, clocks, now):
    out={}
    for tf,n in COUNTS.items():
        end=bisect_right(clocks[tf],now)
        out[tf]=full[tf][max(0,end-n):end]
    return out


def mean_ci(pairs):
    """Weekly cluster bootstrap, preserving dependence within each UTC week."""
    groups=defaultdict(list)
    for t,v in pairs:
        groups[int((t-4*86400)//604800)].append(v) # Monday-aligned UTC weeks
    weeks=list(groups.values())
    if not pairs:
        return {'n':0,'mean':None,'weekly_95_ci':None,'weeks':0}
    ci=None
    if len(weeks)>=8:
        rng=random.Random(20261027)
        draws=[]
        for _ in range(1000):
            selected=[rng.choice(weeks) for _ in weeks]
            draws.append(sum(sum(w) for w in selected)/sum(len(w) for w in selected))
        draws.sort(); ci=[draws[24],draws[974]]
    return {'n':len(pairs),'mean':sum(v for _,v in pairs)/len(pairs),'weekly_95_ci':ci,'weeks':len(weeks),
            'uncertainty_status':'WEEKLY_BLOCK_BOOTSTRAP' if ci else 'INSUFFICIENT_WEEK_CLUSTERS'}


def trade_stats(rows,field):
    known=sorted((r for r in rows if r[field].get('r') is not None),key=lambda r:r['at'])
    values=[r[field]['r'] for r in known]
    wins=[r for r in values if r>0];losses=[r for r in values if r<=0]
    equity=peak=dd=streak=longest=0
    for r in values:
        equity+=r;peak=max(peak,equity);dd=max(dd,peak-equity)
        streak=streak+1 if r<=0 else 0;longest=max(longest,streak)
    return {**mean_ci([(r['at'],r[field]['r']) for r in known]), 'attempts':len(rows),
            'unknown':len(rows)-len(known),'statuses':dict(Counter(r[field]['status'] for r in rows)),
            'win_rate':len(wins)/len(values) if values else None,
            'average_winner':sum(wins)/len(wins) if wins else None,
            'average_loser':sum(losses)/len(losses) if losses else None,
            'profit_factor':sum(wins)/-sum(losses) if sum(losses)<0 else None,
            'realized_drawdown_r':dd,'longest_losing_streak':longest,
            'unknown_minus_1_5r_sensitivity':(sum(values)-1.5*(len(rows)-len(known)))/len(rows) if rows else None}


def run():
    started=time.perf_counter()
    c=BrokerCalendar.published()
    data=SharedData(ROOT/'quant_labs/state/shared',DATASET)
    protocol={'version':VERSION,'dataset':DATASET,
              'sampling':'every H1 close with broker hour divisible by 4; 2024-10-15 <= t < 2026-10-12',
              'splits':['2024-10-15','2025-10-01','2026-04-01','2026-10-12'],
              'selection':'none; no fitted thresholds; chronological test is reused historical data, not pristine holdout',
              'quote_assumption':'context replay: synthetic fresh bid=ask=latest M15 close; no historical tick freshness claim',
              'calendar_authority':c.profile['authority'],
              'news_labels':'UNAVAILABLE: shock is a price observation, not verified news',
              'production_enabled':False}
    results={'protocol':protocol,'markets':{},'cohort':{}}
    all_data={}
    for symbol in ('XAUUSD','BTCUSD'):
        full={tf:data.read(symbol,tf) for tf in COUNTS}
        clocks={tf:[b['utc']+TF[tf] for b in rows] for tf,rows in full.items()}
        all_data[symbol]=(full,clocks)
        buckets=defaultdict(Counter); reasons=Counter();records=[]
        times=[b['utc']+3600 for b in full['H1'] if epoch('2024-10-15')<=b['utc']+3600<epoch('2026-10-12') and (c.clock(b['utc']+3600)//3600)%4==0]
        for index,now in enumerate(times):
            f=window(full,clocks,now)
            price=f['M15'][-1]['close'] if f['M15'] else None
            q={'bid':price,'ask':price,'tick_at':now} if price else None
            baseline=build(symbol,f,q,now)
            upgraded=evaluate(symbol,f,q,now,calendar=c)
            strict=evaluate(symbol,f,q,now) # original isolated prototype, unchanged policy
            h4=upgraded['data_quality']['H4']
            row={'at':now,'split':partition(now),'session':baseline['sessions']['current'],
                 'regime':baseline['regime']['trend']['state'],
                 'volatility':baseline['regime']['volatility']['state'],
                 'shock':baseline['regime']['shock']['state'],
                 'weekend':baseline['sessions']['weekend'],
                 'market_state':upgraded['market_state'],
                 'baseline_stale':baseline['stale'],
                 'baseline_scenarios':sum(baseline['scenarios'][k]['currently_met'] for k in ('bullish','bearish')),
                 'strict_blocked':strict['status']=='BLOCKED',
                 'upgraded_blocked':upgraded['status']=='BLOCKED',
                 'upgraded_scenarios':sum(upgraded['analysis']['scenarios'][k]['currently_met'] for k in ('bullish','bearish')) if upgraded['analysis'] else 0,
                 'h4_missing_expected':h4.get('calendar_coverage',{}).get('unexpected_missing'),
                 'blockers':upgraded['blockers']}
            records.append(row); reasons.update(row['blockers'])
            for label in ('all','split:'+row['split'],'session:'+row['session'],'regime:'+row['regime'],
                          'volatility:'+row['volatility'],'weekend:'+str(row['weekend']),'market:'+row['market_state']):
                buckets[label].update({'contexts':1,'baseline_stale':int(row['baseline_stale']),
                                      'strict_blocked':int(row['strict_blocked']),
                                      'upgraded_blocked':int(row['upgraded_blocked']),
                                      'baseline_scenarios':row['baseline_scenarios'],
                                      'upgraded_scenarios':row['upgraded_scenarios']})
            if index%1000==0:
                print(f'{symbol}: {index}/{len(times)} contexts',flush=True)
        test=[r for r in records if r['split']=='test']
        results['markets'][symbol]={'buckets':dict(buckets),'blocker_counts':dict(reasons),
            'test_change_in_block_rate':mean_ci([(r['at'],int(r['upgraded_blocked'])-int(r['strict_blocked'])) for r in test]),
            'records':records}
    # A retained observed-plan cohort, not a newly generated or independent strategy.
    source=ROOT/'audit_independent/signal_evidence.json'
    evidence=json.loads(source.read_text())
    cohort=[]; minute_cache={}
    for s in evidence:
        symbol=s['symbol']
        if symbol not in all_data:
            continue
        full,clocks=all_data[symbol];now=s['start'];f=window(full,clocks,now)
        risk=abs(s['entry']-s['stop_loss'])
        spread=s.get('spread')
        if spread is None:
            ratio=s.get('features',{}).get('spread_risk')
            spread=ratio*risk if ratio is not None else None
        if spread is None:
            cohort.append({'symbol':symbol,'at':now,'retained':False,'normal':{'status':'NO_SPREAD','r':None},'stress':{'status':'NO_SPREAD','r':None}})
            continue
        long=s['direction']=='LONG'
        q={'bid':s['entry']-spread if long else s['entry'],
           'ask':s['entry'] if long else s['entry']+spread,'tick_at':now}
        preview=evaluate(symbol,f,q,now,calendar=c)
        deadline=now+7*86400
        if s.get('time_exit_at'):
            deadline=datetime.fromisoformat(s['time_exit_at']).timestamp()
        plan=Plan(s.get('signal_id') or s['setup_id'],symbol,s['direction'],datetime.fromisoformat(s['confirmed_at']).timestamp(),
                  now,s['entry'],s['stop_loss'],s['take_profit'],deadline,risk,spread)
        if symbol not in minute_cache:
            minute_cache[symbol]=data.read(symbol,'M1')
        m15=full['M15'];m1=minute_cache[symbol]
        asof=datetime.fromisoformat(data.manifest['broker_provenance']['end']).timestamp()
        normal=simulate(plan,m15,m1,asof,.07 if symbol=='XAUUSD' else 0,data.metadata(symbol))
        stress=simulate(plan,m15,m1,asof,.07 if symbol=='XAUUSD' else 0,data.metadata(symbol),2)
        cohort.append({'id':plan.signal_id,'symbol':symbol,'strategy':s.get('strategy_id',s.get('key')),
                       'at':now,'retained':preview['status']=='CONTEXT_ONLY','blockers':preview['blockers'],
                       'normal':normal,'stress':stress})
    for symbol in ('XAUUSD','BTCUSD'):
        rows=[r for r in cohort if r['symbol']==symbol]
        kept=[r for r in rows if r['retained']]
        results['cohort'][symbol]={'original':{k:trade_stats(rows,k) for k in ('normal','stress')},
                                  'filtered':{k:trade_stats(kept,k) for k in ('normal','stress')},
                                  'resolved_only_paired_delta_vs_original':{
                                      k:mean_ci([(r['at'],(r[k]['r'] if r['retained'] else 0)-r[k]['r']) for r in rows if r[k].get('r') is not None]) for k in ('normal','stress')},
                                  'no_trade_control_r':0}
    results['cohort_records']=cohort
    results['cohort_limits']='50 retained historical plans, mixed strategy versions and research sources; synthetic entry quote reconstruction; fixed 7-day horizon unless recorded; no tick receipt verification; conditional retrospective filter, not new scanner or independent portfolio; unknowns excluded from resolved statistics'
    inputs=[Path(__file__),ROOT/'backend/research/broker_calendar.py',ROOT/'backend/research/broker_sessions.json',
            ROOT/'backend/research/intelligence_preview.py',ROOT/'backend/market_intel/engine.py',
            ROOT/'backend/market_intel/rules.py',ROOT/'backend/quant_live/execution.py',source]
    results['source_sha256']={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    results['elapsed_seconds']=time.perf_counter()-started
    return results


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    result=run()
    with args.output.open('x',encoding='utf-8') as handle:
        json.dump(result,handle,indent=1,allow_nan=False)
    print(json.dumps({'elapsed_seconds':result['elapsed_seconds'],'markets':{s:r['buckets'] for s,r in result['markets'].items()},'cohort':result['cohort']},indent=1))
