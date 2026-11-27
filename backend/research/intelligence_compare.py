"""Reproducible offline context comparison on a hashed existing MT5 snapshot.

Run from repo root: python -m backend.research.intelligence_compare --output PATH
No execution simulation: historical quote timestamps are unavailable. Synthetic
zero-spread quotes isolate candle-quality effects and cannot establish feasibility.
"""
import argparse
from bisect import bisect_right
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'backend'))
from quant_labs.data import SharedData
from market_intel.engine import build
from market_intel.rules import TF
from research.intelligence_preview import evaluate, VERSION

DATASET = 'bf130602dca4f955f64160bc9b85f0bc4246195f9685afbde91d1856c2c62cd3'
COUNTS = {'M15': 400, 'H1': 600, 'H4': 199, 'D1': 199}


def compare():
    data = SharedData(ROOT / 'quant_labs/state/shared', DATASET)
    out = {'version': VERSION, 'dataset': DATASET, 'sampling': 'last 120 available D1 closes, one context per day',
           'quote_assumption': 'synthetic fresh bid=ask=last closed M15 close; not observed execution quotes',
           'performance': 'NOT_EVALUATED: no strategy, entries or fills; no win-rate/expectancy claim',
           'production_enabled': False, 'markets': {}}
    out['source_sha256'] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                            for p in (Path(__file__), ROOT/'backend/research/intelligence_preview.py',
                                      ROOT/'backend/market_intel/engine.py', ROOT/'backend/market_intel/rules.py')}
    for symbol in ('XAUUSD', 'BTCUSD'):
        full = {tf: data.read(symbol, tf) for tf in COUNTS}
        clocks = {tf: [b['utc']+TF[tf] for b in bars] for tf, bars in full.items()}
        records, reasons = [], Counter()
        for day in full['D1'][-120:]:
            now = day['utc'] + TF['D1']
            f = {}
            for tf, n in COUNTS.items():
                end = bisect_right(clocks[tf], now)
                f[tf] = full[tf][max(0, end-n):end]
            q = {'bid': f['M15'][-1]['close'], 'ask': f['M15'][-1]['close'], 'tick_at': now} if f['M15'] else None
            baseline = build(symbol, f, q, now)
            preview = evaluate(symbol, f, q, now)
            reasons.update(preview['blockers'])
            records.append({'at': now, 'baseline_stale': baseline['stale'],
                            'baseline_scenarios_met': [k for k in ('bullish', 'bearish') if baseline['scenarios'][k]['currently_met']],
                            'preview_scenarios_met': [k for k in ('bullish', 'bearish') if preview['analysis'] and preview['analysis']['scenarios'][k]['currently_met']],
                            'preview_status': preview['status'], 'blockers': preview['blockers']})
        out['markets'][symbol] = {'observations': len(records),
                                 'baseline_stale': sum(r['baseline_stale'] for r in records),
                                 'baseline_met_contexts': sum(bool(r['baseline_scenarios_met']) for r in records),
                                 'preview_met_contexts': sum(bool(r['preview_scenarios_met']) for r in records),
                                 'preview_blocked': sum(r['preview_status']=='BLOCKED' for r in records),
                                 'blocker_counts': dict(reasons), 'records': records}
    return out


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    # Exclusive creation preserves prior evidence; callers choose a new artifact.
    result = compare()
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(result, handle, indent=2, allow_nan=False)
    print(json.dumps({s: {k:v for k,v in r.items() if k != 'records'} for s,r in result['markets'].items()}, indent=2))
