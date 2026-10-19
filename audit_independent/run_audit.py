"""Offline independent audit. Reads source stores/cached bars; writes only beside this file."""
import bisect
import collections
import datetime as dt
import gzip
import hashlib
import json
import math
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(__file__).resolve().parent
DATA = ROOT / 'backend/data'
UTC = dt.timezone.utc
def epoch(s):
    return dt.datetime.fromisoformat(s).timestamp()
def rows(path):
    with path.open('rb') as f:
        for line in f:
            try: yield json.loads(line)
            except (ValueError, UnicodeDecodeError): continue
def latest(path, key):
    return list({r[key]: r for r in rows(path) if key in r}.values())
def load(symbol, tf):
    p = DATA / 'research/bars' / f'{symbol}_{tf}.json.gz'
    if not p.exists(): return []
    with gzip.open(p, 'rt') as f: return sorted(json.load(f), key=lambda b:b['utc'])
def ema(values, n):
    result=[]; x=values[0]
    for v in values:
        x += 2/(n+1)*(v-x); result.append(x)
    return result
def touch(s, b):
    spread=b.get('spread', 0)
    if s['direction']=='LONG': return b['low']<=s['stop_loss'], b['high']>=s['take_profit']
    return b['high']+spread>=s['stop_loss'], b['low']+spread<=s['take_profit']

def replay(s, bars, times, cutoff, multiplier=1):
    """No inferred intraminute order; missing active minutes prevent first-hit claims.
    Session gaps also fail closed because no independent session calendar is supplied.
    Commission/slippage are explicit sensitivity assumptions, not broker facts.
    """
    start=s['start']; end=min(start+7*86400, cutoff)
    i=bisect.bisect_right(times, start-60)
    previous=None
    risk=abs(s['entry']-s['stop_loss'])
    if not risk: return {'status':'INVALID'}
    # A minute overlapping confirmation cannot establish a post-entry barrier touch.
    while i<len(bars) and bars[i]['utc']<end:
        b=bars[i]; t=b['utc']; stop,target=touch(s,b)
        if t<start:
            if stop or target: return {'status':'ENTRY_MINUTE_UNKNOWN'}
            previous=t; i+=1; continue
        if previous is None and t-start>60: return {'status':'MISSING_START'}
        if previous is not None and t-previous>90: return {'status':'GAP_UNKNOWN'}
        if t+60>end and (stop or target): return {'status':'END_MINUTE_UNKNOWN'}
        if stop and target: return {'status':'AMBIGUOUS'}
        if stop or target:
            long=s['direction']=='LONG'; sign=1 if long else -1
            open_exit=b['open']+(0 if long else b.get('spread',0))
            level=s['stop_loss'] if stop else s['take_profit']
            fill=min(level,open_exit) if long and stop else max(level,open_exit) if stop else level
            fee=(0.007 if 'JPY' in s['symbol'] else 0.00007) if s['symbol'] in FX else 0.07 if s['symbol']=='XAUUSD' else 0.0014 if s['symbol']=='XAGUSD' else 0
            # Extra execution reserve on both outcomes; spread already embedded in recorded entry/barriers.
            cost=multiplier*(fee+0.5*b.get('spread',0))
            return {'status':'SL' if stop else 'TP','r':(sign*(fill-s['entry'])-cost)/risk,'hit':t}
        previous=t; i+=1
    return {'status':'OPEN' if cutoff<start+7*86400 else 'NO_HIT'} if previous is not None and end-previous<=120 else {'status':'TRUNCATED'}

FX={'EURUSD','GBPUSD','USDJPY','USDCHF','USDCAD','AUDUSD','NZDUSD','EURJPY','GBPJPY'}
def metrics(rs):
    values=[s['replay']['r'] for s in rs if 'r' in s['replay']]
    eq=peak=dd=0
    for s in sorted((s for s in rs if 'r' in s['replay']),key=lambda s:s['replay']['hit']):
        eq+=s['replay']['r']; peak=max(peak,eq); dd=max(dd,peak-eq)
    ci=None
    if values:
        # Resample entry UTC dates, keeping same-day dependence within a block.
        blocks=collections.defaultdict(list)
        for s in rs:
            if 'r' in s['replay']: blocks[int(s['start']//86400)].append(s['replay']['r'])
        rng=random.Random(19026); groups=list(blocks.values()); means=[]
        for _ in range(2000):
            sample=[v for _ in groups for v in rng.choice(groups)]
            means.append(sum(sample)/len(sample))
        means.sort(); ci=[means[50],means[1950]]
    gains=sum(max(0,v) for v in values); losses=-sum(min(0,v) for v in values)
    return {'signals':len(rs),'resolved':len(values),'statuses':dict(collections.Counter(s['replay']['status'] for s in rs)),
            'total_r':sum(values),'expectancy_r':sum(values)/len(values) if values else None,
            'profit_factor':gains/losses if losses else None,'win_rate':sum(v>0 for v in values)/len(values) if values else None,
            'max_drawdown_realized_r':dd,'day_block_bootstrap_95':ci}

def main():
    captured={}
    for name in ('setup_confirmations.jsonl','signal_outcomes.jsonl','strategy_bank/signals.jsonl'):
        content=(DATA/name).read_bytes()
        dest=OUT/'inputs'/name
        dest.parent.mkdir(parents=True,exist_ok=True); dest.write_bytes(content)
        captured[name]={'size':len(content),'sha256':hashlib.sha256(content).hexdigest()}
    confirmations=latest(OUT/'inputs/setup_confirmations.jsonl','setup_id')
    outcomes=latest(OUT/'inputs/signal_outcomes.jsonl','setup_id')
    bank=latest(OUT/'inputs/strategy_bank/signals.jsonl','signal_id')
    signals=[]
    for o in outcomes:
        if o.get('shadow') or not all(o.get(k) is not None for k in ('entry','stop_loss','take_profit')): continue
        signals.append({**o,'key':o.get('strategy_id','legacy'),'start':epoch(o['confirmed_at']),'source':'production'})
    for s in bank:
        signals.append({**s,'key':s['strategy_key'],'start':epoch(s.get('detected_at') or s['confirmed_at']),'source':'bank'})
    cutoff=max(s['start'] for s in signals)
    cutoff=math.ceil(cutoff/900)*900
    wanted={s.get('observation_id') for s in signals if s.get('observation_id')}
    snapshots={}
    for r in rows(DATA/'setup_observations.jsonl'):
        if r.get('observation_id') in wanted: snapshots[r['observation_id']]=r
    coverage={}; features=collections.Counter()
    for symbol in sorted({s['symbol'] for s in signals}):
        m1=load(symbol,'M1'); times=[b['utc'] for b in m1]
        h1=load(symbol,'H1'); ht=[b['utc']+3600 for b in h1]
        m15=load(symbol,'M15'); mt=[b['utc']+900 for b in m15]
        e50=ema([b['close'] for b in h1],50) if h1 else []; e200=ema([b['close'] for b in h1],200) if h1 else []
        coverage[symbol]={'m1_count':len(m1),'first':times[0] if times else None,'last':times[-1] if times else None}
        for s in (s for s in signals if s['symbol']==symbol):
            j=bisect.bisect_right(ht,s['start'])-1; k=bisect.bisect_right(mt,s['start'])-1
            risk=abs(s['entry']-s['stop_loss']); long=s['direction']=='LONG'
            aligned=j>=200 and ((e50[j]>e200[j]) if long else (e50[j]<e200[j]))
            tr=[max(b['high']-b['low'],abs(b['high']-m15[n-1]['close']),abs(b['low']-m15[n-1]['close'])) for n,b in enumerate(m15[max(1,k-13):k+1],max(1,k-13))]
            atr=sum(tr)/len(tr) if len(tr)==14 else None
            snapshot=snapshots.get(s.get('observation_id'),{})
            snap={**snapshot,**snapshot.get('features',{})}
            spread=s.get('spread',snap.get('spread'))
            s['features']={'htf_aligned':aligned,'stop_atr':risk/atr if atr else None,'target_atr':abs(s['take_profit']-s['entry'])/atr if atr else None,
                           'spread_risk':spread/risk if spread is not None and risk else None,'snapshot_score':snap.get('score'),
                           'snapshot_htf':snap.get('higher_timeframe_bias'),'snapshot_rsi':snap.get('rsi'),'snapshot_nearest_level_atr':snap.get('nearest_level_atr')}
            f=s['features']
            s['gates']={'htf':aligned,'location':atr is not None and 0.5<=risk/atr<=3 and abs(s['take_profit']-s['entry'])/atr<=4,
                        'cost':f['spread_risk'] is not None and f['spread_risk']<=0.1}
            s['replay']=replay(s,m1,times,cutoff)
            s['stress_replay']=replay(s,m1,times,cutoff,2)
    signals.sort(key=lambda s:s['start'])
    # Predeclared research policy, no outcome-based parameter search.
    retained=[]; last={}
    for s in signals:
        key=(s['symbol'],s['direction'])
        s['experimental']=all(s['gates'].values()) and s['start']-last.get(key,-math.inf)>=14400
        if s['experimental']: retained.append(s); last[key]=s['start']
    split=epoch('2026-10-08T00:00:00+00:00')
    periods={'all':lambda s:True,'train_purged':lambda s:s['start']<split-7*86400,'test':lambda s:s['start']>=split}
    comparisons={p:{'original':metrics([s for s in signals if pred(s)]),'experimental':metrics([s for s in retained if pred(s)])} for p,pred in periods.items()}
    ablations={g:metrics([s for s in signals if s['gates'][g]]) for g in ('htf','location','cost')}
    by_strategy={k:{'original':metrics([s for s in signals if s['key']==k]),'experimental':metrics([s for s in retained if s['key']==k])} for k in sorted({s['key'] for s in signals})}
    recorded={k:dict(collections.Counter(o.get('status') for o in outcomes if o.get('strategy_id')==k and not o.get('shadow'))) for k in sorted({o.get('strategy_id','legacy') for o in outcomes})}
    correlated=[]
    for n,s in enumerate(signals):
        matches=[p for p in signals[:n] if p['symbol']==s['symbol'] and p['direction']==s['direction'] and s['start']-p['start']<=14400]
        if matches: correlated.append({'signal':s.get('setup_id',s.get('signal_id')),'prior':matches[-1].get('setup_id',matches[-1].get('signal_id')),'symbol':s['symbol'],'seconds':s['start']-matches[-1]['start']})
    manifest=captured
    result={'cutoff_utc':dt.datetime.fromtimestamp(cutoff,UTC).isoformat(),'confirmations':len(confirmations),'outcome_records':len(outcomes),'bank_signals':len(bank),'snapshots_found':len(snapshots),'comparisons':comparisons,'ablations':ablations,'by_strategy':by_strategy,'recorded_statuses':recorded,'coverage':coverage,'correlated':correlated,'manifest':manifest}
    (OUT/'results.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    (OUT/'signal_evidence.json').write_text(json.dumps(signals,indent=2),encoding='utf-8')
    print(json.dumps({'comparisons':comparisons,'ablations':ablations,'correlated':len(correlated)},indent=2))

if __name__=='__main__': main()
