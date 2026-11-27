"""M5 admission shim in front of the unchanged frozen v1 evaluator.

The shim only enforces M5 entry semantics (entry at an exact 5-minute boundary that is
the close of a complete derived M5 candle). Fills, costs, financing, gap handling,
splits, purges, locks and metrics are all performed by quant_labs.evaluation.v1 with an
M1 confirming frame; the shim never computes an outcome itself.
"""
from collections import Counter
from ..evaluation.v1.engine import evaluate as evaluate_v1, POLICY

VERSION = 'tradeden-m5-extension-1.0.0'


def admit(data, signals):
    kept, rejected, times = [], Counter(), {}
    for s in signals:
        symbol, at = s['symbol'], s['entry_at']
        if symbol not in times:
            times[symbol] = {b['utc'] for b in data.read(symbol, 'M5')}
        if at % 300 or at != s['signal_bar_closed_at']:
            rejected['invalid_m5_boundary'] += 1
        elif at - 300 not in times[symbol]:
            rejected['m5_confirming_bar_unavailable'] += 1
        else:
            kept.append(s)
    return kept, rejected


def evaluate(data, request, checkpoint=None, save=None, should_pause=lambda: False):
    """`data` is an M5SharedData view; `request['strategy']['timeframe']` must be 'M5'."""
    if request['strategy'].get('timeframe') != 'M5':
        raise ValueError('M5 extension evaluates M5 strategies only')
    kept, rejected = admit(data, request['signals'])
    inner = {**request, 'signals': kept, 'strategy': {**request['strategy'], 'timeframe': 'M1'}}
    result = evaluate_v1(data.shared, inner, checkpoint, save, should_pause)
    if result['status'] != 'COMPLETE':
        return result
    merged = Counter(result['rejections'])
    merged.update(rejected)
    result.update(rejections=dict(merged), intent_count=len(request['signals']), m5_admitted=len(kept),
                  evaluator_version=POLICY['version'] + '+' + VERSION,
                  m5_extension={'version': VERSION, 'confirming_frame': 'derived M5 from complete shared M1 (5/5 minutes)',
                                'scoring': 'frozen v1 evaluator, M1 confirming frame, unchanged costs and accounting',
                                'coverage_note': 'shared M1 history starts July 2026; earlier M5 intents are rejected as unavailable'})
    return result
