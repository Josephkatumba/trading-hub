"""Independent, fail-closed execution, timestamps, revisions and authorization."""
from __future__ import annotations
import bisect
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_FLOOR, ROUND_CEILING
import hashlib
import json
import math
from pathlib import Path
from zoneinfo import ZoneInfo

VERSION = 'independent-execution-1.0.1'
FINAL = {'TP','SL','TIME_EXIT'}
NY = ZoneInfo('America/New_York')

def fresh(age, limit=300, tolerance=5):
    try: return math.isfinite(float(age)) and -tolerance <= float(age) <= limit
    except (TypeError, ValueError): return False

def confirmation_valid(bar_closed_at, entry_at, quote_age, max_delay=300):
    try:
        bar_closed_at,entry_at=float(bar_closed_at),float(entry_at)
        return fresh(quote_age) and all(math.isfinite(x) for x in (bar_closed_at,entry_at)) and 0 <= entry_at-bar_closed_at <= max_delay
    except (TypeError,ValueError):return False

def alert_authorized(status, approval, enabled=True):
    """To be checked at delivery time; no static-spec or stored-alert bypass."""
    return enabled and status in {'QUALIFIED','APPROVED_EXPERIMENTAL','PRODUCTION'} and bool(str(approval or '').strip())

def rounded(price, tick, up=False):
    if not math.isfinite(price) or not math.isfinite(tick) or tick<=0: raise ValueError('invalid tick/price')
    return float((Decimal(str(price))/Decimal(str(tick))).to_integral_value(rounding=ROUND_CEILING if up else ROUND_FLOOR)*Decimal(str(tick)))

def validate_bars(bars, seconds, asof):
    """Keep gaps visible, reject duplicates/nonmonotonic/invalid/future/forming bars."""
    valid=[]; rejected={}; previous=-math.inf
    for b in bars:
        reason=None
        try:
            t=float(b['utc']); op,hi,lo,cl=(float(b[k]) for k in ('open','high','low','close'))
            spread=float(b['spread'])
            if not all(math.isfinite(v) for v in (t,op,hi,lo,cl,spread)): reason='nonfinite'
            elif t<=previous: reason='duplicate_or_unsorted'
            elif min(op,hi,lo,cl)<=0 or lo>min(op,cl) or hi<max(op,cl) or lo>hi or spread<0: reason='invalid_ohlc_or_spread'
            elif t>asof: reason='future'
            elif t+seconds>asof: reason='forming'
            previous=max(previous,t)
        except (KeyError,ValueError,TypeError): reason='missing_or_invalid_fields'
        if reason: rejected[reason]=rejected.get(reason,0)+1
        else: valid.append(dict(b))
    return valid,rejected

def contiguous(bars,start,end,seconds):
    times=[b['utc'] for b in bars]
    expected=list(range(int(start),int(end),seconds))
    return start==int(start) and end==int(end) and times==expected

@dataclass(frozen=True)
class Plan:
    signal_id: str
    symbol: str
    direction: str
    signal_bar_closed_at: float
    entry_at: float
    entry: float
    stop_loss: float
    take_profit: float
    deadline: float
    risk: float
    entry_spread: float

def valid_plan(p,asof):
    vals=[p.signal_bar_closed_at,p.entry_at,p.entry,p.stop_loss,p.take_profit,p.deadline,p.risk,p.entry_spread]
    return (all(math.isfinite(x) for x in vals) and p.direction in ('LONG','SHORT') and
            p.signal_bar_closed_at<=p.entry_at<=asof and p.entry_at<p.deadline and p.risk>0 and p.entry_spread>=0 and
            math.isclose(abs(p.entry-p.stop_loss),p.risk,rel_tol=1e-9,abs_tol=1e-12) and
            ((0<p.stop_loss<p.entry<p.take_profit) if p.direction=='LONG' else (0<p.take_profit<p.entry<p.stop_loss)))

def touch(p,b,scale=1):
    spread=b['spread']*scale
    return (b['low']<=p.stop_loss,b['high']>=p.take_profit) if p.direction=='LONG' else (b['high']+spread>=p.stop_loss,b['low']+spread<=p.take_profit)

def financing(p,exit_at,meta,scale=1):
    start=datetime.fromtimestamp(p.entry_at,timezone.utc).astimezone(NY)
    end=datetime.fromtimestamp(exit_at,timezone.utc).astimezone(NY)
    day=start.date(); nights=0
    while day<=end.date():
        boundary=datetime(day.year,day.month,day.day,17,tzinfo=NY)
        if start<boundary<=end:
            weekday=(boundary.weekday()+1)%7
            nights+=3 if weekday==meta.get('swap_rollover3days') else 1
        day+=timedelta(days=1)
    if not nights: return 0.0
    mode=meta.get('swap_mode'); swap=meta.get('swap_long' if p.direction=='LONG' else 'swap_short')
    if mode==0: return 0.0
    if swap is None: return None
    if mode==1:
        if not meta.get('point'):return None
        credit=swap*meta['point']
    elif mode==5: credit=p.entry*swap/100/360
    else: return None # currency conversion and historical specs unavailable
    cost=-credit*nights
    return max(cost,0)*scale + min(cost,0) if scale==1 else max(cost,0)*scale

def simulate(p:Plan,m15,m1,asof,commission=0,meta=None,scale=1,times=None,minute_times=None):
    """Only completed bars available as-of; exact entries include the entry minute.
    Gaps remain unknown (no guessed broker calendar). Ties need contiguous M1.
    Partial entry candles require M1 including entry minute; touches within that
    minute are unknown unless entry is at its open. No artificial first-hit claims.
    """
    if not valid_plan(p,asof) or not math.isfinite(asof) or commission<0 or not math.isfinite(commission) or not math.isfinite(scale) or scale<1:
        return {'status':'INVALID_PLAN','r':None}
    stop_at=min(p.deadline,asof)
    times=times if times is not None else [b['utc'] for b in m15]
    minute_times=minute_times if minute_times is not None else [b['utc'] for b in m1]
    first=p.entry_at-p.entry_at%900
    index=bisect.bisect_left(times,first)
    sign=1 if p.direction=='LONG' else -1
    # Extra adverse entry slippage plus changed entry spread under stress.
    actual_entry=p.entry+sign*0.25*p.entry_spread*scale
    if sign==1: actual_entry+=(scale-1)*p.entry_spread
    def done(status,at,price=None,method='M15',reason=None):
        result={'status':status,'r':None,'exit_at':at,'method':method,'reason':reason,'resolver_version':VERSION}
        if status not in FINAL: return result
        carry=financing(p,at,meta or {},scale)
        if carry is None: return {**result,'status':'FINANCING_UNSUPPORTED','reason':'historical currency conversion unavailable'}
        exit_slip=0.5*current_spread if status=='SL' else 0.25*current_spread
        fill=price-sign*exit_slip
        result.update(r=(sign*(fill-actual_entry)-commission*scale-carry)/p.risk,exit_price=fill,
                      entry_price=actual_entry,financing_price=carry,commission_price=commission*scale)
        return result
    expected=first; current_spread=p.entry_spread*scale
    if index>=len(m15) or m15[index]['utc']!=first:
        return done('INCOMPLETE',p.entry_at,reason='entry candle missing')
    for ix in range(index,len(m15)):
        b=m15[ix]
        t=b['utc']
        if t>=stop_at: break
        if t!=expected: return done('INCOMPLETE',expected,reason='missing M15 candle; session calendar unverified')
        if t+900>asof: return done('PENDING',t,reason='forming M15 candle excluded')
        expected=t+900; current_spread=b['spread']*scale
        lo=max(t,p.entry_at); hi=min(t+900,stop_at)
        full=lo==t and hi==t+900
        stop,target=touch(p,b,scale)
        if full:
            op=b['open']+(current_spread if sign==-1 else 0)
            if op<=p.stop_loss if sign==1 else op>=p.stop_loss:
                return done('SL',t,op,reason='stop gap at open')
            if op>=p.take_profit if sign==1 else op<=p.take_profit:
                return done('TP',t,p.take_profit,reason='target limit conservatively filled')
            if stop!=target:
                return done('SL' if stop else 'TP',t+900,p.stop_loss if stop else p.take_profit,reason='one barrier; timestamp upper bound')
        if (not full) or (stop and target):
            first_min=lo-lo%60
            minutes=m1[bisect.bisect_left(minute_times,first_min):bisect.bisect_left(minute_times,hi)]
            required_end=math.ceil(hi/60)*60
            if not contiguous(minutes,first_min,required_end,60) or any(x['utc']+60>asof for x in minutes):
                # A wholly safe coarse candle proves no barrier inside its subinterval,
                # but cannot provide an executable timed exit in a partial candle.
                if not stop and not target and hi==t+900: continue
                return done('AMBIGUOUS' if full else 'INCOMPLETE',lo,method='M1',reason='continuous minute coverage unavailable')
            for minute in minutes:
                current_spread=minute['spread']*scale
                sl,tp=touch(p,minute,scale)
                if minute['utc']<lo and (sl or tp):
                    return done('AMBIGUOUS',lo,method='M1',reason='barrier in entry minute, tick order unknown')
                if minute['utc']+60>hi:
                    return done('INCOMPLETE',hi,method='M1',reason='partial exit minute')
                if sl and tp: return done('AMBIGUOUS',minute['utc'],method='M1',reason='both barriers within one minute')
                if sl or tp:
                    op=minute['open']+(current_spread if sign==-1 else 0)
                    price=(min(p.stop_loss,op) if sign==1 else max(p.stop_loss,op)) if sl else p.take_profit
                    return done('SL' if sl else 'TP',minute['utc']+60,price,'M1')
            if full and stop and target:
                return done('AMBIGUOUS',lo,method='M1',reason='M1 and M15 barrier evidence disagree')
            if hi==p.deadline:
                last=minutes[-1]
                return done('TIME_EXIT',hi,last['close']+(current_spread if sign==-1 else 0),'M1')
        if full and t+900==p.deadline:
            return done('TIME_EXIT',p.deadline,b['close']+(current_spread if sign==-1 else 0))
    return done('PENDING' if asof<p.deadline and expected>=stop_at else 'INCOMPLETE',expected,reason='path does not cover deadline')

class RevisionStore:
    """Research-local append-only corrections; no historical file is overwritten."""
    def __init__(self,path): self.path=Path(path)
    def append(self,signal_id,result,provenance,prior_id=None):
        previous=[]
        if self.path.exists():
            previous=[json.loads(x) for x in self.path.read_text().splitlines() if x.strip()]
        old=next((x for x in reversed(previous) if x['signal_id']==signal_id),None)
        digest=hashlib.sha256(json.dumps({'result':result,'provenance':provenance},sort_keys=True).encode()).hexdigest()
        if old and old['content_hash']==digest: return None
        row={'signal_id':signal_id,'revision':old['revision']+1 if old else 1,'supersedes':old['revision_id'] if old else prior_id,
             'revision_id':signal_id+':'+digest[:20],'content_hash':digest,'result':result,'provenance':provenance,
             'recorded_at':datetime.now(timezone.utc).isoformat()}
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.path.open('a',encoding='utf-8') as f: f.write(json.dumps(row,sort_keys=True)+'\n')
        return row
