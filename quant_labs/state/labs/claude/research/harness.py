"""Claude Quant Lab causal replay harness.

Replays a registered-style pure ``detect(snapshot)`` model over the frozen shared
snapshot, exposing only candles whose close time <= the decision time, then scores
the resulting declarative intents with the *frozen* shared evaluator code
(imported read-only; nothing in quant_labs/evaluation is modified).

Quote proxy (disclosed): bid = open of the M15 candle that starts at the decision
time, ask = bid + that candle's recorded spread. That candle's high/low/close are
never exposed to the model.

The live qualification gate of backend/quant_live/runtime.qualify is emulated so
the replayed intents approximate what the live paper provider would admit.
"""
import argparse
import hashlib
import json
import sys
import time
from bisect import bisect_right
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'backend'))
from quant_labs.data import SharedData  # noqa: E402
from quant_labs.evaluation.v1.engine import evaluate, POLICY  # noqa: E402
from quant_live.model_host import validate_source, BUILTINS, safe_import  # noqa: E402

DATASET = 'bf130602dca4f955f64160bc9b85f0bc4246195f9685afbde91d1856c2c62cd3'
TF = {'M1': 60, 'M5': 300, 'M15': 900, 'H1': 3600, 'H4': 14400, 'D1': 86400}
LAB = Path(__file__).resolve().parents[1]


def load_model(source_path):
    source = Path(source_path).read_text(encoding='utf-8')
    tree = validate_source(source)  # identical static gate to the live host
    namespace = {'__builtins__': {**BUILTINS, '__import__': safe_import}}
    exec(compile(tree, '<lab-pure-model>', 'exec'), namespace)
    return namespace['detect'], hashlib.sha256(source.encode()).hexdigest()


def live_gate(decision, entry_bid, spread, last_close, commission, tick):
    """Mirror of quant_live.runtime.qualify geometry/cost checks (no freshness)."""
    long = decision['direction'] == 'LONG'
    entry = entry_bid + spread if long else entry_bid
    atr = decision['atr']
    stop, target = decision['stop_loss'], decision['take_profit']
    risk = entry - stop if long else stop - entry
    reward = target - entry if long else entry - target
    if atr <= 0 or risk <= 0 or reward <= 0:
        return 'INVALID_GEOMETRY'
    if not .5 * atr <= risk <= 5 * atr:
        return 'UNREALISTIC_STOP_DISTANCE'
    if abs(entry - last_close) > .5 * atr:
        return 'ENTRY_DRIFT'
    reserve = commission + spread * .75
    if spread / risk > .1 or (reward - reserve) / (risk + reserve) < 2:
        return 'SPREAD_OR_NET_RR'
    if not 60 <= decision['horizon_seconds'] <= 604800:
        return 'INVALID_HORIZON'
    return None


def replay(detect, manifest, data, symbols, start=None, end=None):
    tf = manifest['timeframe']
    req = manifest['requirements']
    start = start or datetime_epoch(POLICY['train_start'])
    end = end or datetime_epoch(POLICY['test_end'])
    intents, gate_rejects, raw = [], {}, 0
    for symbol in symbols:
        meta = data.metadata(symbol)
        commission = POLICY['commission_price'].get(symbol, 0)
        frames = {k: (m5_from_m1(data.read(symbol, 'M1')) if k == 'M5' else data.read(symbol, k)) for k in req}
        closes = {k: [b['utc'] + TF[k] for b in frames[k]] for k in req}
        m15 = data.read(symbol, 'M15')
        m15_at = {b['utc']: b for b in m15}
        m1_at = {b['utc']: b for b in data.read(symbol, 'M1')} if tf in ('M1', 'M5') else {}
        primary = frames[tf]
        for bar in primary:
            t = bar['utc'] + TF[tf]
            if t < start or t >= end:
                continue
            quote_bar = m15_at.get(t) if t % 900 == 0 else m1_at.get(t)
            if quote_bar is None:  # market closed / gap: live would have no fresh quote
                continue
            snap_frames = {}
            for k, n in req.items():
                j = bisect_right(closes[k], t)
                snap_frames[k] = frames[k][max(0, j - n):j]
            snapshot = {'symbol': symbol, 'broker_symbol': meta.get('broker_symbol', symbol), 'source': 'CLAUDE_LAB_REPLAY',
                        'asof': t, 'time_verified': True,
                        'quote': {'bid': quote_bar['open'], 'ask': quote_bar['open'] + quote_bar['spread'], 'tick_at': t},
                        'metadata': meta, 'frames': snap_frames, 'data_quality': {}}
            for d in detect(snapshot) or []:
                raw += 1
                why = live_gate(d, quote_bar['open'], quote_bar['spread'], snap_frames[tf][-1]['close'], commission, meta['tick_size'])
                if why:
                    gate_rejects[why] = gate_rejects.get(why, 0) + 1
                    continue
                intents.append({'symbol': symbol, 'direction': d['direction'], 'signal_bar_closed_at': t, 'entry_at': t,
                                'stop_loss': d['stop_loss'], 'take_profit': d['take_profit'],
                                'horizon_seconds': int(d['horizon_seconds'])})
    return intents, {'raw_decisions': raw, 'live_gate_rejections': gate_rejects}


def m5_from_m1(m1):
    """Complete M5 candles from contiguous M1 (5 of 5 minutes present); incomplete buckets dropped."""
    out, bucket = [], []
    for b in m1:
        start = b['utc'] - b['utc'] % 300
        if bucket and bucket[0]['utc'] - bucket[0]['utc'] % 300 != start:
            bucket = []
        bucket.append(b)
        if len(bucket) == 5 and bucket[0]['utc'] == start:
            out.append({'utc': start, 'open': bucket[0]['open'], 'high': max(x['high'] for x in bucket),
                        'low': min(x['low'] for x in bucket), 'close': bucket[-1]['close'],
                        'spread': max(x['spread'] for x in bucket), 'tick_volume': sum(x.get('tick_volume', 0) for x in bucket)})
            bucket = []
    return out


def trading_days(lo, hi):
    """Weekdays (Mon-Fri, UTC) in [lo, hi)."""
    d0, d1 = int(lo // 86400), int(hi // 86400)
    return sum(1 for d in range(d0, d1) if (d + 4) % 7 not in (0, 6))


def datetime_epoch(s):
    from datetime import datetime
    return datetime.fromisoformat(s).timestamp()


def breakdown(result):
    """Per-symbol and per-split normal/stress summaries from evaluator trades."""
    from quant_labs.evaluation.v1.metrics import summarize
    splits = [('train', POLICY['train_start'], POLICY['validation_start']),
              ('validation', POLICY['validation_start'], POLICY['test_start']),
              ('test', POLICY['test_start'], POLICY['test_end'])]
    out = {}
    symbols = sorted({t['plan']['symbol'] for t in result['trades']})
    for sym in symbols:
        out[sym] = {}
        for name, lo, hi in splits:
            lo, hi = datetime_epoch(lo), datetime_epoch(hi)
            sel = [t for t in result['trades'] if t['plan']['symbol'] == sym and lo <= t['plan']['entry_at'] and t['plan']['deadline'] < hi]
            s = summarize(sel, lo, hi, 'normal')
            st = summarize(sel, lo, hi, 'stress')
            out[sym][name] = {'n': s['resolved'], 'unknown': s['unknown'], 'win': s['win_rate'], 'exp': s['net_expectancy_r'],
                              'stress_exp': st['net_expectancy_r'], 'pf': s['profit_factor'], 'dd': s['max_realized_drawdown_r']}
    return out


def frequency(intents, result, lo, hi):
    """Signals per weekday: gate-qualified intents (live-like) and evaluator-accepted trades (one open per symbol)."""
    days = max(1, trading_days(lo, hi))
    return {'weekdays': days, 'qualified_intents_per_weekday': round(len(intents) / days, 3),
            'evaluated_trades_per_weekday': round(len(result['trades']) / days, 3)}


def compact(period):
    keys = ['attempted', 'resolved', 'unknown', 'statuses', 'win_rate', 'net_expectancy_r', 'total_r', 'profit_factor',
            'max_realized_drawdown_r', 'longest_losing_streak', 'planned_rr_mean', 'realized_win_loss_ratio',
            'opportunities_per_month', 'weekly_bootstrap_expectancy_ci95', 'weekly_sign_flip_p']
    return {k: period.get(k) for k in keys}


def run(model_dir, symbols=None, splits=('train', 'validation'), tag=None):
    model_dir = Path(model_dir)
    manifest = json.loads((model_dir / 'manifest.json').read_text(encoding='utf-8'))
    detect, sha = load_model(model_dir / 'model.py')
    data = SharedData(ROOT / 'quant_labs/state/shared', DATASET)
    symbols = symbols or manifest['instruments']
    # Only replay the splits being examined, so the test window stays unseen until requested.
    bounds = {'train': (POLICY['train_start'], POLICY['validation_start']),
              'validation': (POLICY['validation_start'], POLICY['test_start']),
              'test': (POLICY['test_start'], POLICY['test_end'])}
    lo = min(datetime_epoch(bounds[s][0]) for s in splits)
    hi = max(datetime_epoch(bounds[s][1]) for s in splits)
    t0 = time.time()
    if manifest['timeframe'] == 'M5':  # M5 only exists where M1 history exists
        lo = max(lo, min(data.read(s, 'M1')[0]['utc'] for s in symbols) + 86400)
    intents, gate = replay(detect, manifest, data, symbols, lo, hi)
    t1 = time.time()
    eval_tf = 'M1' if manifest['timeframe'] == 'M5' else manifest['timeframe']  # frozen evaluator has no M5 confirming frame
    result = evaluate(data, {'signals': intents, 'strategy': {'timeframe': eval_tf}})
    report = {'model': manifest['key'], 'version': manifest['version'], 'source_sha256': sha, 'dataset': DATASET,
              'evaluator_version': POLICY['version'], 'symbols': symbols, 'splits_examined': list(splits),
              'intents': len(intents), 'replay': gate, 'evaluator_rejections': result['rejections'],
              'periods': {k: {sc: compact(v[sc]) for sc in ('normal', 'stress')} for k, v in result['periods'].items() if k in splits},
              'by_symbol': breakdown(result),
              'frequency': frequency(intents, result, lo, hi), 'seconds': {'replay': round(t1 - t0, 1), 'evaluate': round(time.time() - t1, 1)}}
    out_dir = LAB / 'research' / 'results'
    out_dir.mkdir(parents=True, exist_ok=True)
    name = f"{manifest['key']}_{manifest['version']}_{tag or '-'.join(splits)}"
    (out_dir / f'{name}.json').write_text(json.dumps(report, indent=1, default=str), encoding='utf-8')
    (out_dir / f'{name}_intents.json').write_text(json.dumps(intents), encoding='utf-8')
    return report


def main():
    p = argparse.ArgumentParser()
    p.add_argument('model_dir')
    p.add_argument('--symbols', nargs='*')
    p.add_argument('--splits', nargs='*', default=['train', 'validation'])
    p.add_argument('--tag')
    a = p.parse_args()
    r = run(a.model_dir, a.symbols, tuple(a.splits), a.tag)
    print(json.dumps({k: r[k] for k in ('model', 'version', 'intents', 'replay', 'evaluator_rejections', 'seconds', 'frequency')}))
    for split, v in r['periods'].items():
        n, s = v['normal'], v['stress']
        print(f"{split:10s} n={n['resolved']}/{n['attempted']} win={fmt(n['win_rate'])} exp={fmt(n['net_expectancy_r'])}R "
              f"stress={fmt(s['net_expectancy_r'])}R PF={fmt(n['profit_factor'])} DD={fmt(n['max_realized_drawdown_r'])} "
              f"rr={fmt(n['planned_rr_mean'])} p={fmt(n['weekly_sign_flip_p'])} statuses={n['statuses']}")
    for sym, v in r['by_symbol'].items():
        print('  ', sym, ' | '.join(f"{k}: n={x['n']} w={fmt(x['win'])} e={fmt(x['exp'])}" for k, x in v.items() if k in r['periods']))


def fmt(x):
    return 'NA' if x is None else f'{x:.3f}'


if __name__ == '__main__':
    main()
