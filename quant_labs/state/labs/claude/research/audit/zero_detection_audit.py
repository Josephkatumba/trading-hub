"""Phase 1 zero-detection audit of the live Quant Labs consumer (read-only over the live store).

1. Breakdown of live evaluations by strategy, instrument, UTC session, timeframe, outcome,
   rejection reason, data shortfall, staleness and qualification.
2. Expected signals: each model's historical qualified-signal rate by UTC hour-of-day (from
   frozen-evaluator replays of the same source) applied to the hours actually evaluated live;
   Poisson probability of observing zero.
3. Independent replay: rebuild each evaluated snapshot from the live candle cache and run the
   model source directly (outside the live pipeline) to confirm the live decisions.
"""
import json
import math
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
sys.path.insert(0, str(ROOT / 'backend'))
from quant_live.model_host import execute

TF = {'M1': 60, 'M15': 900, 'H1': 3600, 'H4': 14400, 'D1': 86400}
LIVE = ROOT / 'backend/data/quant_live/signals.sqlite3'
RESULTS = HERE.parent / 'results'
HIST_INTENTS = {'compression_escape': 'compression_escape_0.1.0_full_intents.json', 'index_trend_day': 'index_trend_day_0.2.0_full_intents.json',
                'crypto_trend_breakout': 'crypto_trend_breakout_0.3.0_full_intents.json', 'hourly_shock_drift': 'hourly_shock_drift_0.1.0_full_intents.json',
                'index_gap_fade': 'index_gap_fade_0.1.0_full_intents.json', 'index_turn_of_month': 'index_turn_of_month_0.1.0_full_intents.json'}
HIST_WEEKDAYS = 512  # weekdays in the 2024-10-15..2026-10-01 replay window


def session(t):
    h = datetime.fromtimestamp(t, timezone.utc).hour
    return 'Asia 00-07' if h < 7 else 'London 07-12' if h < 12 else 'Overlap 12-16' if h < 16 else 'NY 16-24'


def main():
    db = sqlite3.connect(f'file:{LIVE.as_posix()}?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    models = {r['key']: {**dict(r), 'manifest': json.loads(r['body'])} for r in db.execute('SELECT * FROM models')}
    runs = [(r['state'], r['at'], json.loads(r['body'] or '{}')) for r in db.execute('SELECT state,at,body FROM runs')]
    runs = [r for r in runs if r[2].get('key')]  # identity-logged runs (since 2026-10-23 restart)
    breakdown = defaultdict(Counter)
    hours = defaultdict(lambda: defaultdict(set))  # model -> symbol -> evaluated UTC hours
    for state, at, b in runs:
        k = b['key']
        breakdown['by_strategy'][(k, state)] += 1
        breakdown['by_instrument'][(b['symbol'], state)] += 1
        breakdown['by_session'][(session(b['bar_closed_at']), state)] += 1
        breakdown['by_timeframe'][(models[k]['manifest']['timeframe'], state)] += 1
        breakdown['decisions'][(k, 'setup' if b.get('decisions') else 'no_setup' if state == 'COMPLETE' else state)] += 1
        if b.get('quality_rejection'):
            breakdown['quality_rejections'][(k, b['quality_rejection'])] += 1
        if b.get('data_shortfall'):
            breakdown['data_shortfall'][(k, json.dumps(b['data_shortfall']))] += 1
        if state == 'REJECTED':
            breakdown['stale_or_unverified'][(k, b.get('reason'))] += 1
        if state == 'COMPLETE':
            hours[k][b['symbol']].add(int(b['bar_closed_at'] // 3600))
    window = (min(r[1] for r in runs), max(r[1] for r in runs)) if runs else (None, None)

    # 2. Expected signals from historical hour-of-day rates (same source, frozen evaluator replays).
    expected = {}
    for key, fname in HIST_INTENTS.items():
        path = RESULTS / fname
        if not path.exists() or key not in hours:
            continue
        by_sym_hour = Counter((i['symbol'], int(i['entry_at'] % 86400 // 3600)) for i in json.loads(path.read_text()))
        lam = 0.0
        for sym, hset in hours[key].items():
            for h in hset:
                lam += by_sym_hour[(sym, h % 24)] / HIST_WEEKDAYS
        expected[key] = {'expected_signals': lam, 'p_zero_if_rates_hold': math.exp(-lam), 'evaluated_symbol_hours': sum(len(v) for v in hours[key].values())}

    # 3. Independent replay of evaluated snapshots from the live candle cache.
    replay = Counter()
    for state, at, b in runs:
        if state != 'COMPLETE':
            continue
        m = models[b['key']]
        frames = {}
        for tf, n in m['manifest']['requirements'].items():
            rows = db.execute('SELECT body FROM candles WHERE symbol=? AND tf=? AND utc+?<=? ORDER BY utc DESC LIMIT ?',
                              (b['symbol'], tf, TF[tf], b['bar_closed_at'], n)).fetchall()
            frames[tf] = [json.loads(r['body']) for r in reversed(rows)]
        snap = {'symbol': b['symbol'], 'frames': frames, 'quote': {'bid': frames[m['manifest']['timeframe']][-1]['close'], 'ask': frames[m['manifest']['timeframe']][-1]['close'], 'tick_at': b['bar_closed_at']},
                'metadata': {}, 'asof': b['bar_closed_at']}
        try:
            out = execute(m['source'], snap)
        except Exception as exc:
            replay[(b['key'], 'error ' + type(exc).__name__)] += 1
            continue
        live = bool(b.get('decisions'))
        replay[(b['key'], 'agree' if bool(out) == live else 'DISAGREE')] += 1
    report = {'window_utc': [datetime.fromtimestamp(x, timezone.utc).isoformat() if x else None for x in window],
              'runs_with_identity': len(runs),
              'breakdown': {k: {' | '.join(map(str, kk)): v for kk, v in c.most_common()} for k, c in breakdown.items()},
              'expected_from_history': expected,
              'independent_replay': {' | '.join(k): v for k, v in replay.most_common()}}
    (HERE / 'zero_detection_audit.json').write_text(json.dumps(report, indent=1))
    print(json.dumps({k: report[k] for k in ('window_utc', 'runs_with_identity', 'expected_from_history', 'independent_replay')}, indent=1))
    for k in ('by_session', 'by_timeframe', 'quality_rejections', 'stale_or_unverified', 'data_shortfall'):
        print(k, dict(list(report['breakdown'].get(k, {}).items())[:12]))


if __name__ == '__main__':
    main()
