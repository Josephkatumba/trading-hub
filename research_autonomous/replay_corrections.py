"""Append corrected interpretations of the frozen audit signals to a RESEARCH store.

Does not import production modules or write backend/data. These are simulated plan
outcomes, not broker fills; a production migration still needs CEO approval.
"""
from collections import Counter
from dataclasses import asdict
from datetime import datetime,timezone
import gzip
import hashlib
import json
from pathlib import Path
from .foundation import Plan,RevisionStore,simulate,validate_bars,VERSION
from .experiment import CACHE,ROOT,BASE,fee,iso

def main():
    source=ROOT/'audit_independent/signal_evidence.json'
    signals=json.loads(source.read_text());metadata=json.loads((CACHE/'manifest.json').read_text())
    cache_asof=datetime.fromisoformat(metadata['end']).timestamp()
    asof=max(s['start'] for s in signals)
    folder=BASE/'corrections';folder.mkdir(exist_ok=True)
    store=RevisionStore(folder/'revisions.jsonl');changes=[];status=Counter()
    source_hash=hashlib.sha256(source.read_bytes()).hexdigest()
    for symbol in sorted({s['symbol'] for s in signals}):
        frames={};manifest={}
        for tf,seconds in [('M15',900),('M1',60)]:
            raw=(CACHE/f'{symbol}_{tf}.json.gz').read_bytes()
            frames[tf]=validate_bars(json.loads(gzip.decompress(raw)),seconds,cache_asof)[0]
            manifest[tf]=hashlib.sha256(raw).hexdigest()
        times=[b['utc'] for b in frames['M15']];minutes=[b['utc'] for b in frames['M1']]
        for s in (s for s in signals if s['symbol']==symbol):
            risk=abs(s['entry']-s['stop_loss']);spread=s.get('spread')
            if spread is None:
                ratio=s.get('features',{}).get('spread_risk')
                spread=risk*ratio if ratio is not None else None
            deadline=s['start']+7*86400
            if s.get('time_exit_at'):deadline=datetime.fromisoformat(s['time_exit_at']).timestamp()
            if spread is None:
                result={'status':'UNAVAILABLE','r':None,'reason':'entry spread unavailable; never substituted zero'}
                p=None
            else:
                p=Plan(s.get('signal_id') or s['setup_id'],symbol,s['direction'],
                       datetime.fromisoformat(s['confirmed_at']).timestamp(),s['start'],s['entry'],s['stop_loss'],s['take_profit'],deadline,risk,spread)
                result=simulate(p,frames['M15'],frames['M1'],asof,fee(symbol),metadata['symbols'][symbol]['meta'],1,times,minutes)
            prior=s.get('outcome_status') if s['source']=='bank' else s.get('status')
            provenance={'resolver':VERSION,'source_signal_evidence_sha256':source_hash,'cache_hashes':manifest,
                        'resolver_sha256':hashlib.sha256((BASE/'foundation.py').read_bytes()).hexdigest(),
                        'cache_asof':iso(cache_asof),'evaluation_asof':iso(asof),'old_record_id':s.get('outcome_id') or s.get('signal_id'),
                        'old_status':prior,'old_r':s.get('r_multiple'),'new_plan':asdict(p) if p else None,
                        'entry_basis':'recorded historical plan; actual broker fill unverified','costs':'assumed commission/slippage plus current swap proxy'}
            revision=store.append(s.get('signal_id') or s['setup_id'],result,provenance,prior_id=s.get('outcome_id') or s.get('signal_id'))
            status[result['status']]+=1
            if revision:changes.append(revision['revision_id'])
    summary={'signals':len(signals),'new_revisions':len(changes),'statuses':dict(status),'backend_modified':False,
             'source_sha256':source_hash,'caution':'Changes reflect coverage, entry semantics, horizon and cost policy; they do not prove all prior results wrong.'}
    (folder/'latest_summary.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps(summary,indent=2))

if __name__=='__main__':main()
