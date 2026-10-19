"""Independent accounting/invariant checks on a completed run; no simulator reuse."""
from collections import Counter
from datetime import datetime,timezone
import gzip
import hashlib
import json
import math
from pathlib import Path
from .experiment import BASE,CACHE,ts,FOLDS

def verify(folder):
    folder=Path(folder);records=[json.loads(s) for s in (folder/'trades.jsonl').read_text().splitlines()]
    manifests=json.loads((folder/'data_manifest.json').read_text())['files']
    assert all(hashlib.sha256((CACHE/name).read_bytes()).hexdigest()==m['sha256'] for name,m in manifests.items())
    summary=json.loads((folder/'run_summary.json').read_text());results=json.loads((folder/'results.json').read_text())
    assert summary['status']=='COMPLETE';assert len(records)==summary['trades']
    checked=0;symbols={};last=Counter();units=Counter()
    for t in records:
        p=t['plan'];key=(t['strategy'],t['symbol'])
        assert p['entry_at']==p['signal_bar_closed_at'] and p['entry_at']%3600==0
        assert p['entry_at']>=last[key];last[key]=t['busy_until']
        assert math.isclose(abs(p['entry']-p['stop_loss']),p['risk'],rel_tol=1e-9)
        # Verify executable entry directly from the cached bid-open, independent of simulation.
        if t['symbol'] not in symbols:
            bars=json.loads(gzip.decompress((CACHE/f"{t['symbol']}_M15.json.gz").read_bytes()))
            symbols[t['symbol']]={b['utc']:b for b in bars}
        b=symbols[t['symbol']][p['entry_at']]
        expected=b['open']+(b['spread'] if p['direction']=='LONG' else 0)
        assert math.isclose(expected,p['entry'],rel_tol=1e-12)
        for scenario in ('normal','stress'):
            r=t[scenario]
            if r.get('r') is None:continue
            sign=1 if p['direction']=='LONG' else -1
            independently=(sign*(r['exit_price']-r['entry_price'])-r['commission_price']-r['financing_price'])/p['risk']
            assert math.isclose(independently,r['r'],abs_tol=1e-12)
            assert p['entry_at']<=r['exit_at']<=p['deadline']
            checked+=1
    tests={}
    for r in results['experiments']:
        if 'statistics' not in r:continue
        group=[t for t in records if t['experiment_id']==r['experiment_id'] and ts('2026-04-01')<=t['plan']['entry_at'] and t['plan']['deadline']<ts('2026-10-01')]
        known=[t['normal']['r'] for t in group if t['normal'].get('r') is not None]
        assert len(known)==r['statistics']['test']['normal']['resolved']
        assert math.isclose(sum(known),r['statistics']['test']['normal']['total_r'],abs_tol=1e-9)
    output={'status':'PASS','trade_plans_checked':len(records),'fill_accounting_checks':checked,
            'checks':['48 cached data file hashes','entry prices independently reconstructed','entry/SL risk denominators',
                      'same-strategy/symbol nonoverlap','completed-exit timestamps','net-R fill accounting','per-experiment final-test totals'],
            'limits':'Does not establish feed accuracy, historical financing, tick-level sequencing, or profitability.'}
    (folder/'independent_verification.json').write_text(json.dumps(output,indent=2))
    print(json.dumps(output,indent=2))
    return output
if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('run',nargs='?');args=parser.parse_args()
    verify(Path(args.run) if args.run else sorted((BASE/'runs').iterdir())[-1])
