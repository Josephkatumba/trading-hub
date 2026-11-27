"""Quant Labs engine health: one explainable status (OK / DEGRADED / DOWN) with reasons.

Distinguishes market closure from staleness (FX, metals and indices close at weekends; crypto
does not), reports per-model last evaluation, delivery failures, 24h uptime from the existing
engine heartbeat, and closed candles that were never evaluated. Read-only.
"""
import time
from datetime import datetime, timedelta, timezone

CRYPTO = {'BTCUSD', 'ETHUSD'}
STALE_SECONDS = 300


def market_closed(symbol, now):
    """Weekend closure for non-crypto CFDs (Friday ~21:00 UTC to Sunday ~22:00 UTC); conservative."""
    if symbol in CRYPTO:
        return False
    d = datetime.fromtimestamp(now, timezone.utc)
    wd, h = d.weekday(), d.hour  # Monday=0
    return (wd == 4 and h >= 21) or wd == 5 or (wd == 6 and h < 22)


def health(store, runtime_status, now=None, beats=None):
    now = time.time() if now is None else now
    reasons, level = [], 'OK'

    def degrade(msg, to='DEGRADED'):
        nonlocal level
        reasons.append(msg)
        if to == 'DOWN' or level == 'OK':
            level = to
    if not runtime_status.get('enabled'):
        degrade('quant consumer disabled (TRADEDEN_QUANT_LIVE_ENABLED is not 1)', 'DOWN')
    elif not runtime_status.get('running'):
        degrade('quant consumer thread not running', 'DOWN')
    last = runtime_status.get('last_processed')
    if runtime_status.get('enabled') and (not last or now - last > STALE_SECONDS):
        degrade(f'no snapshot processed for {int(now - last) if last else "unknown"} s', 'DOWN')
    inputs = {}
    for symbol, item in (runtime_status.get('latest_inputs') or {}).items():
        age = now - item['asof'] if item.get('asof') else None
        state = 'MARKET_CLOSED' if market_closed(symbol, now) else 'FRESH' if age is not None and age <= STALE_SECONDS else 'STALE'
        inputs[symbol] = {'state': state, 'age_seconds': age}
    stale = sorted(s for s, v in inputs.items() if v['state'] == 'STALE')
    if stale:
        degrade('stale market input: ' + ', '.join(stale))
    from .diagnostics import diagnostics
    diag = diagnostics(store)['models']
    models = {k: {'last_successful_evaluation': v['last_successful_evaluation'], 'worker_failures': v['worker_failures'],
                  'closed_bars_not_evaluated': sum(v['closed_bars_not_evaluated'].values())} for k, v in diag.items()}
    failures = sum(sum(v['worker_failures'].values()) for v in diag.values())
    if failures:
        degrade(f'{failures} model worker failures recorded')
    with store.db() as c:
        bad = c.execute("SELECT state,count(*) n FROM outbox WHERE state IN ('FAILED','DELIVERY_UNKNOWN') AND updated>=? GROUP BY state", (now - 86400,)).fetchall()
    delivery_problems = {r['state']: r['n'] for r in bad}
    if delivery_problems:
        degrade('Telegram delivery problems in 24h: ' + ', '.join(f'{k} {v}' for k, v in delivery_problems.items()))
    uptime = None
    try:
        import reports
        end = datetime.fromtimestamp(now, timezone.utc)
        uptime = reports.uptime(end - timedelta(hours=24), end, reports.heartbeats() if beats is None else beats)
    except Exception:
        uptime = None
    return {'status': level, 'reasons': reasons, 'checked_at': now, 'inputs': inputs, 'models': models,
            'delivery_problems_24h': delivery_problems, 'uptime_24h': uptime,
            'replay_policy': 'Candles closed while the engine was down are never evaluated as live signals (fail-closed freshness gate); '
                             'outcomes of existing signals are resolved from fetched history. Missed candles are counted, not replayed.'}
