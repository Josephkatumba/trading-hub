"""Strategy readiness: what the monitored strategies are waiting for on XAUUSD / BTCUSD, from live closed candles.

Statements are computed from data (levels, conditions met / not met). They describe conditions, never
trades. Approved signal strategies (Category A) are distinguished from research models (Category B).
"""
from . import rules as R
from .live import frames


def _broker_days_h4(h4, now):
    days, today = [], R.broker_day(now)
    for b in h4:
        if b['utc'] + 14400 > now:
            break
        k = R.broker_day(b['utc'])
        if k >= today:
            break
        if days and days[-1]['key'] == k:
            d = days[-1]
            d['high'], d['low'], d['close'], d['bars'] = max(d['high'], b['high']), min(d['low'], b['low']), b['close'], d['bars'] + 1
        else:
            days.append({'key': k, 'high': b['high'], 'low': b['low'], 'close': b['close'], 'bars': 1})
    return [d for d in days if d['bars'] >= 4]


def crypto_breakout(store, symbol, now):
    f = frames(store, symbol, now, {'H4': 160, 'D1': 60})
    h4, d1 = f['H4'], f['D1']
    if len(h4) < 121 or len(d1) < 55:
        return {'strategy': 'Crypto Trend Breakout v0.3.0', 'category': 'A', 'state': 'INSUFFICIENT_DATA'}
    hi, lo = max(b['high'] for b in h4[-120:]), min(b['low'] for b in h4[-120:])
    c = [d['close'] for d in d1]
    rising = sum(c[-50:]) / 50 > sum(c[-55:-5]) / 50
    last = h4[-1]['close']
    return {'strategy': 'Crypto Trend Breakout v0.3.0', 'category': 'A', 'state': 'WAITING',
            'statement': f"{'BUY' if rising else 'SELL'} side active (50-day baseline {'rising' if rising else 'falling'}): needs an H4 close "
                         + (f"above {hi:,.2f} ({(hi - last) / last * 100:+.1f}% from the last close)" if rising else f"below {lo:,.2f} ({(lo - last) / last * 100:+.1f}%)")
                         + '; not met.',
            'levels': {'breakout_high': hi, 'breakout_low': lo, 'last_h4_close': last}}


def gold_compression(store, now):
    f = frames(store, 'XAUUSD', now, {'H4': 120})
    days = _broker_days_h4(f['H4'], now)
    if len(days) < 16:
        return {'strategy': 'Gold Compression Acceptance v0.1.0', 'category': 'B (research, internal)', 'state': 'INSUFFICIENT_DATA'}
    prior = days[-1]
    trs = [max(d['high'] - d['low'], abs(d['high'] - p['close']), abs(d['low'] - p['close'])) for p, d in zip(days[-16:-2], days[-15:-1])]
    ratio = (prior['high'] - prior['low']) / (sum(trs) / len(trs))
    armed = ratio < 0.7
    return {'strategy': 'Gold Compression Acceptance v0.1.0', 'category': 'B (research, internal)', 'state': 'ARMED' if armed else 'INACTIVE',
            'statement': (f"Prior day compressed ({ratio:.2f} x daily ATR < 0.70): waiting for two M15 closes beyond {prior['high']:,.2f} or {prior['low']:,.2f} "
                          'between 08:00 London and 18:00 UTC.') if armed else
                         f"Inactive today: prior day range {ratio:.2f} x daily ATR is not compressed (needs < 0.70)."}


def summary(intel, items, approved_cover):
    st = intel['structure']
    struct = f"D1 {st['D1']['state']}, H4 {st['H4']['state']}, H1 {st['H1']['state']}"
    if not approved_cover:
        return f"{intel['symbol']}: {struct}. No approved signal strategy trades this market; research models are monitored internally."
    waiting = [i for i in items if i['category'] == 'A' and i.get('state') == 'WAITING']
    return f"{intel['symbol']}: {struct}. " + ('No approved strategy has triggered: entry conditions remain unmet.' if waiting else 'Approved strategy status unavailable.')


def readiness(store, symbol, intel, now):
    items, approved_cover = [], symbol in ('BTCUSD',)
    if symbol == 'BTCUSD':
        items.append(crypto_breakout(store, 'BTCUSD', now))
    if symbol == 'XAUUSD':
        items.append(gold_compression(store, now))
    return {'summary': summary(intel, items, approved_cover), 'items': items,
            'note': 'Conditions computed from live closed candles; not trade recommendations.'}
