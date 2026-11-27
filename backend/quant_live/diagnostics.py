"""Operational diagnostics: why a model did or did not produce paper signals.

Separates, per model: evaluations with no setup, setups, insufficient data, stale/unverified
input, quality-gate rejections (by reason), worker/engine failures, confirmed signals,
Telegram delivery states, the last successful evaluation, and closed candles that were never
evaluated (engine offline or not scheduled). Read-only over the live store.
"""
from collections import Counter, defaultdict
import json

TF_SECONDS = {'M1': 60, 'M5': 300, 'M15': 900, 'H1': 3600, 'H4': 14400, 'D1': 86400}


def diagnostics(store):
    with store.db() as c:
        runs = c.execute('SELECT state,at,body FROM runs').fetchall()
        outbox = c.execute('SELECT o.signal,o.state,s.lab,s.model,s.version FROM outbox o LEFT JOIN signals s '
                           'ON s.id = CASE WHEN o.signal LIKE "%#outcome" THEN substr(o.signal,1,length(o.signal)-8) ELSE o.signal END').fetchall()
        confirmed = c.execute('SELECT lab,model,version,count(*) n FROM signals WHERE json_extract(body,"$.confirmed")=1 GROUP BY lab,model,version').fetchall()
    models = {(m['lab'], m['key'], m['version']): m for m in store.models()}
    out = {}
    for key, m in models.items():
        out['%s:%s@%s' % key] = {'status': m['status'], 'scan_enabled': bool(m['scan_enabled']), 'alert_enabled': bool(m['alert_enabled']),
                                 'timeframe': m['manifest']['timeframe'], 'instruments': m['manifest']['instruments'],
                                 'evaluations': 0, 'no_setup': 0, 'setups': 0, 'insufficient_data': 0, 'stale_input_rejected': 0,
                                 'quality_rejected': Counter(), 'worker_failures': Counter(), 'revoked': 0, 'confirmed_signals': 0,
                                 'delivery': Counter(), 'outcome_updates': Counter(), 'last_successful_evaluation': None,
                                 'evaluated_bars': defaultdict(set)}
    legacy = 0
    for r in runs:
        body = json.loads(r['body'] or '{}')
        name = '%s:%s@%s' % (body.get('lab'), body.get('key'), body.get('version'))
        d = out.get(name)
        if d is None:
            legacy += 1  # runs recorded before identity logging (2026-10-23)
            continue
        if body.get('data_shortfall'):
            d['insufficient_data'] += 1
        if r['state'] == 'COMPLETE':
            d['evaluations'] += 1
            d['last_successful_evaluation'] = max(d['last_successful_evaluation'] or 0, r['at'])
            d['evaluated_bars'][body['symbol']].add(body['bar_closed_at'])
            if body.get('decisions'):
                d['setups'] += 1
                if body.get('quality_rejection'):
                    d['quality_rejected'][body['quality_rejection']] += 1
            else:
                d['no_setup'] += 1
        elif r['state'] == 'REJECTED':
            d['stale_input_rejected'] += 1
        elif r['state'] == 'REVOKED':
            d['revoked'] += 1
        elif r['state'] != 'RUNNING':
            d['worker_failures'][r['state']] += 1
    for row in confirmed:
        d = out.get('%s:%s@%s' % (row['lab'], row['model'], row['version']))
        if d:
            d['confirmed_signals'] = row['n']
    for row in outbox:
        d = out.get('%s:%s@%s' % (row['lab'], row['model'], row['version']))
        if d:
            (d['outcome_updates'] if row['signal'].endswith('#outcome') else d['delivery'])[row['state']] += 1
    for name, d in out.items():
        seconds = TF_SECONDS[d['timeframe']]
        missed = {}
        for symbol, bars in d['evaluated_bars'].items():
            first, last = min(bars), max(bars)
            closes = store_closes(store, symbol, d['timeframe'], first, last, seconds)
            missed[symbol] = len(closes - bars)
        d['closed_bars_not_evaluated'] = missed
        d['closed_bars_not_evaluated_note'] = ('closed broker candles between the first and last evaluation of this model on the symbol '
                                               'that were never evaluated (engine offline or not scheduled); market closures have no candles')
        del d['evaluated_bars']
        for k in ('quality_rejected', 'worker_failures', 'delivery', 'outcome_updates'):
            d[k] = dict(d[k])
    return {'models': out, 'legacy_runs_without_identity': legacy,
            'categories': ['no_setup', 'setups', 'insufficient_data', 'stale_input_rejected', 'quality_rejected', 'worker_failures',
                           'revoked', 'confirmed_signals', 'delivery', 'closed_bars_not_evaluated']}


def store_closes(store, symbol, tf, first, last, seconds):
    with store.db() as c:
        rows = c.execute('SELECT utc FROM candles WHERE symbol=? AND tf=? AND utc+?>=? AND utc+?<=?', (symbol, tf, seconds, first, seconds, last)).fetchall()
    return {r['utc'] + seconds for r in rows}
