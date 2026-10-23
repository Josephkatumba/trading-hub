"""Quant Labs section for the existing 23:00 EAT daily and Friday weekly Telegram reports.

Read-only over the live store. Reports zero when nothing happened; never fabricates activity.
Experimental research performance is labelled and kept separate from production performance.
"""
import json
from collections import Counter
from .report import metrics
from .diagnostics import diagnostics


def summary(store, start, end):
    """Counts for one report window [start, end) given as UTC epoch seconds."""
    models = [m for m in store.models() if m['status'] == 'EXPERIMENTAL' and m['scan_enabled']]
    with store.db() as c:
        runs = c.execute('SELECT state,body FROM runs WHERE at>=? AND at<?', (start, end)).fetchall()
        finals = c.execute("SELECT signal,body FROM outcomes WHERE at>=? AND at<?", (start, end)).fetchall()
        outbox = c.execute('SELECT signal,state FROM outbox WHERE updated>=? AND updated<?', (start, end)).fetchall()
    states = Counter(r['state'] for r in runs)
    bodies = [json.loads(r['body'] or '{}') for r in runs]
    signals = store.signals(1000)
    window_signals = [s for s in signals if start <= s['entry_at'] < end]
    resolved = {}
    for row in finals:
        o = json.loads(row['body'])
        if o.get('status') in ('TP', 'SL', 'TIME_EXIT') and o.get('simulated_net_r') is not None:
            resolved[row['signal']] = o
    by_model = Counter()
    for sid, o in resolved.items():
        s = store.signal(sid)
        if s:
            by_model[f"{s['lab']}:{s['model_name']} v{s['model_version']}"] += o['simulated_net_r']
    forward_all = metrics(signals, store.outcomes())
    diag = diagnostics(store)['models']
    return {'active_models': len(models), 'telegram_models': sum(1 for m in models if m['alert_enabled']),
            'evaluations': states.get('COMPLETE', 0), 'setups': sum(1 for b in bodies if b.get('decisions')),
            'confirmed': sum(1 for s in window_signals if s.get('confirmed')),
            'quality_rejected': sum(1 for s in window_signals if not s.get('confirmed')),
            'resolved': len(resolved), 'tp': sum(o['status'] == 'TP' for o in resolved.values()),
            'sl': sum(o['status'] == 'SL' for o in resolved.values()), 'time_exits': sum(o['status'] == 'TIME_EXIT' for o in resolved.values()),
            'net_r': sum(o['simulated_net_r'] for o in resolved.values()),
            'forward_expectancy_all_time': forward_all['average_r'], 'forward_resolved_all_time': forward_all['resolved'],
            'best': max(by_model.items(), key=lambda x: x[1]) if by_model else None,
            'worst': min(by_model.items(), key=lambda x: x[1]) if by_model else None,
            'scanner_errors': sum(v for k, v in states.items() if k not in ('COMPLETE', 'REJECTED', 'REVOKED', 'RUNNING')),
            'stale_input': states.get('REJECTED', 0),
            'missing_data': sum(1 for b in bodies if b.get('data_shortfall')),
            'unevaluated_closed_candles_all_time': sum(sum(d['closed_bars_not_evaluated'].values()) for d in diag.values()),
            'telegram': dict(Counter(r['state'] for r in outbox))}


def lines(s):
    if s is None:
        return ['  Quant Labs store unavailable: nothing reported.']
    best = f"{s['best'][0]} {s['best'][1]:+.2f}R" if s['best'] else 'n/a'
    worst = f"{s['worst'][0]} {s['worst'][1]:+.2f}R" if s['worst'] else 'n/a'
    exp = 'n/a' if s['forward_expectancy_all_time'] is None else f"{s['forward_expectancy_all_time']:+.2f}R"
    return [f"  Active strategies: {s['active_models']} (Telegram-enabled paper candidates: {s['telegram_models']})",
            f"  Evaluations completed: {s['evaluations']}   Setups detected: {s['setups']}",
            f"  Confirmed paper signals: {s['confirmed']}   Quality-gate rejections: {s['quality_rejected']}",
            f"  Resolved: {s['resolved']} (TP {s['tp']} / SL {s['sl']} / time {s['time_exits']})   Net: {s['net_r']:+.2f}R",
            f"  Forward expectancy (all time): {exp} over {s['forward_resolved_all_time']} resolved",
            f"  Best: {best}   Worst: {worst}",
            f"  Scanner errors: {s['scanner_errors']}   Stale input: {s['stale_input']}   Missing data: {s['missing_data']}",
            '  Telegram: ' + (', '.join(f'{k} {v}' for k, v in sorted(s['telegram'].items())) or 'no messages'),
            '  Experimental research only, separate from production. Not validated; paper outcomes after estimated costs.']


def default_source(start_dt, end_dt):
    """Sources.quant_labs default: reads the live store only when quant-live is enabled."""
    from . import service
    if not service.enabled():
        return None
    return summary(service.store(), start_dt.timestamp(), end_dt.timestamp())
