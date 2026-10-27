"""Compare retained historical bar gaps with the versioned published calendar."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'backend'))
from research.phase2_validation import SharedData, DATASET, TF
from research.broker_calendar import BrokerCalendar


if __name__=='__main__':
    d=SharedData(ROOT/'quant_labs/state/shared',DATASET);c=BrokerCalendar.published();out={}
    for symbol in ('XAUUSD','BTCUSD'):
        out[symbol]={}
        for tf in ('M15','H1','H4','D1'):
            bars=d.read(symbol,tf);counts=Counter();examples=[]
            for a,b in zip(bars,bars[1:]):
                if b['utc']-a['utc']==TF[tf]: continue
                missing=c.expected(symbol,a['utc']+TF[tf],b['utc'],tf)
                kind='UNEXPECTED_OR_UNKNOWN' if missing else 'COMPATIBLE_WITH_PUBLISHED_CLOSURE'
                counts[kind]+=1
                if len(examples)<8:
                    examples.append({'from':a['utc'],'to':b['utc'],'classification':kind,'missing_expected':len(missing)})
            out[symbol][tf]={'bars':len(bars),'gaps':dict(counts),'examples':examples}
    result={'dataset':DATASET,'authority':c.profile['authority'],'historical_schedule_verified':False,'markets':out,
            'source_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in
                (Path(__file__),ROOT/'backend/research/broker_calendar.py',ROOT/'backend/research/broker_sessions.json')}}
    with Path(sys.argv[1]).open('x') as handle: json.dump(result,handle,indent=1)
    print(json.dumps({s:{tf:v['gaps'] for tf,v in vals.items()} for s,vals in out.items()},indent=1))
