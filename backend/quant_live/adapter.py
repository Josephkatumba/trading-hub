"""Validated read-only data from the existing collector, never a new MT5 session."""
from datetime import datetime,timezone
import hashlib
import json
import math
from types import MappingProxyType
from .execution import validate_bars

TF_SECONDS={'M1':60,'M5':300,'M15':900,'H1':3600,'H4':14400,'D1':86400}
def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def immutable(value):
    if isinstance(value,dict):return MappingProxyType({k:immutable(v) for k,v in value.items()})
    if isinstance(value,list):return tuple(immutable(v) for v in value)
    return value
def normalize_frame(rows,tf,point,basis,normalize,asof):
    normalized=[];errors={}
    for b in rows:
        stamp=normalize(b['time'],basis)
        if stamp.get('normalization_status')!='VERIFIED':return [],{'time_basis_unverified':len(rows)}
        try:
            raw={k:float(b[k]) for k in ('open','high','low','close')}
            raw['utc']=datetime.fromisoformat(stamp['normalized_utc']).timestamp()
            # A missing historical spread stays missing; never substitute zero.
            if 'spread_points' not in b:raise ValueError('spread missing')
            raw['spread']=float(b['spread_points'])*point
            if 'tick_volume' in b:raw['tick_volume']=int(b['tick_volume'])
            normalized.append(raw)
        except (ValueError,TypeError,KeyError):errors['invalid_or_missing_spread']=errors.get('invalid_or_missing_spread',0)+1
    bars,rejected=validate_bars(normalized,TF_SECONDS[tf],asof)
    for key,value in rejected.items():errors[key]=errors.get(key,0)+value
    if any(k not in ('forming','future') for k in errors):return [],errors
    return bars,errors

def from_collector(symbol,broker,frames,quote,metadata,basis,normalize):
    asof=quote['received_at'];normalized={};quality={}
    point=metadata.get('point')
    if not point or not math.isfinite(point):raise ValueError('instrument point unavailable')
    for tf,rows in frames.items():
        if tf not in TF_SECONDS:continue
        normalized[tf],quality[tf]=normalize_frame(rows,tf,point,basis,normalize,asof)
    tick=normalize(quote['raw_tick_at'],basis)
    tick_at=datetime.fromisoformat(tick['normalized_utc']).timestamp() if tick.get('normalization_status')=='VERIFIED' else None
    data={'symbol':symbol,'broker_symbol':broker,'asof':asof,'source':'MT5_SHARED_COLLECTOR','source_basis':basis,
          'time_verified':tick_at is not None,'quote':{'bid':quote['bid'],'ask':quote['ask'],'tick_at':tick_at},
          'metadata':metadata,'frames':normalized,'data_quality':quality}
    data['input_sha256']=hashlib.sha256(canonical(data)).hexdigest()
    return data
