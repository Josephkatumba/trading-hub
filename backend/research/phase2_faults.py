"""Known-fault benchmark on real historical prefixes; not market-direction labels."""
import copy
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'backend'))
from research.phase2_validation import window, epoch, DATASET, COUNTS
from research.broker_calendar import BrokerCalendar
from research.intelligence_preview import evaluate
from market_intel.engine import build
from market_intel.rules import TF
from quant_labs.data import SharedData


def run():
    data=SharedData(ROOT/'quant_labs/state/shared',DATASET)
    c=BrokerCalendar.published();records=[]
    for symbol in ('XAUUSD','BTCUSD'):
        full={tf:data.read(symbol,tf) for tf in COUNTS}
        clocks={tf:[b['utc']+TF[tf] for b in rows] for tf,rows in full.items()}
        seen=set()
        for bar in full['H1']:
            now=bar['utc']+3600
            if not epoch('2025-01-01')<=now<epoch('2026-10-12') or c.state(symbol,now)!='SCHEDULED_OPEN':
                continue
            month=int(now//(30*86400))
            if month in seen:
                continue
            seen.add(month)
            original=window(full,clocks,now)
            for defect in ('missing_h4','stale_h4','misaligned_h4','h4_gap','future_quote','stale_quote','missing_quote'):
                f=copy.deepcopy(original)
                q={'bid':f['M15'][-1]['close'],'ask':f['M15'][-1]['close']+.01,'tick_at':now}
                if defect=='missing_h4': f['H4']=[]
                elif defect=='stale_h4': f['H4']=f['H4'][:-4]
                elif defect=='misaligned_h4': f['H4'][-1]['utc']+=60
                elif defect=='h4_gap': del f['H4'][-5]
                elif defect=='future_quote': q['tick_at']=now+600
                elif defect=='stale_quote': q['tick_at']=now-3600
                else: q=None
                base=build(symbol,f,q,now)
                upgraded=evaluate(symbol,f,q,now,calendar=c)
                if defect=='missing_h4': detected=upgraded['data_quality']['H4']['closed_bars']==0
                elif defect=='stale_h4': detected='H4: stale or absent history' in upgraded['blockers']
                elif defect=='misaligned_h4': detected='misaligned broker timeframe' in upgraded['data_quality']['H4']['errors']
                elif defect=='h4_gap': detected=upgraded['data_quality']['H4']['calendar_coverage']['unexpected_missing']>0
                else: detected=upgraded['quote_state']=='UNAVAILABLE_OR_STALE'
                records.append({'symbol':symbol,'at':now,'defect':defect,'upgraded_detected':detected,
                                'baseline_stale':base['stale'],'baseline_h4_state':base['structure']['H4']['state'],
                                'upgraded_status':upgraded['status']})
    summary={}
    for defect in sorted({r['defect'] for r in records}):
        rows=[r for r in records if r['defect']==defect]
        summary[defect]={'n':len(rows),'detected':sum(r['upgraded_detected'] for r in rows),
                         'baseline_stale_flags':sum(r['baseline_stale'] for r in rows)}
    return {'dataset':DATASET,'sample_unit':'one prefix per 30-day epoch bucket per market',
            'scope':'known data faults only; baseline stale flag is not a generic fault detector; no predictive-accuracy claim',
            'summary':summary,'records':records}


if __name__=='__main__':
    path=Path(sys.argv[1]);result=run()
    with path.open('x',encoding='utf-8') as handle: json.dump(result,handle,indent=1)
    print(json.dumps(result['summary'],indent=1))
