"""Reproducible rules: clock/sessions, trend, levels, level events, regime. Pure functions on closed candles.

Candles are dicts with 'utc' (opening UTC epoch), 'open', 'high', 'low', 'close'. Callers pass only
candles whose close time (utc + timeframe) is <= the evaluation time.
"""
from statistics import median

TF = {'M1': 60, 'M15': 900, 'H1': 3600, 'H4': 14400, 'D1': 86400}

RULES = {
    'T1': 'Trend: UP if close > EMA50, EMA20 > EMA50 and EMA50 higher than 5 candles ago; DOWN mirror; otherwise NEUTRAL (needs >= 60 candles).',
    'L1': 'Previous broker day high/low: H1 candles grouped by broker day (17:00 New York roll), last complete day.',
    'L2': 'Previous week high/low: complete broker days of the previous Monday-Friday week.',
    'L3': 'Swing levels: H4 pivot highs/lows with 2 lower highs (higher lows) on each side, last 8 of each.',
    'L4': 'Outer range: highest high / lowest low of the last 20 complete D1 candles.',
    'E1': 'Level event on today\'s M15 candles formed AFTER the level existed (session levels: after the session ended; swings: after the '
          'pivot was confirmed): ACCEPTED = 2+ consecutive closes beyond; FAILED = a close beyond then back inside; SWEEP = wick beyond with no '
          'close beyond; FORMING = session still in progress; else UNTESTED. Resistance/support is by position relative to price.',
    'S1': 'Sessions (DST-aware): Asia 00:00-06:00 UTC; London 08:00-16:30 London; New York 09:30-16:00 New York; overlap = New York open to London close. '
          'London range (liquidity levels) = London open to the New York open.',
    'S2': 'New York vs London liquidity: whether New York-session candles traded beyond the pre-New-York London high or low, and where they closed.',
    'R1': 'Trend regime: H1 efficiency ratio over 24 candles >= 0.35 TRENDING, <= 0.20 RANGING, otherwise MIXED.',
    'R2': 'Volatility regime: ATR(H1,24) percentile vs the prior 20 days, < 1/3 LOW, > 2/3 HIGH, otherwise NORMAL.',
    'R3': 'Range expansion: current broker-day range >= 1.2 x ATR of the previous 14 broker days.',
    'R4': 'Volatility shock: last closed H1 range >= 3 x median range of the same UTC hour over the previous 20 days (cause not verified).',
    'C1': 'Bullish confirmation: an H1 close above the nearest resistance while the H4 trend is not DOWN.',
    'C2': 'Bearish confirmation: an H1 close below the nearest support while the H4 trend is not UP.',
    'C3': 'Avoid directional trades when: trend regime RANGING with price inside the previous-day range; D1 and H4 trends conflict; '
          'a volatility shock is present; or data is stale.',
}


# ----- clock --------------------------------------------------------------------------------------------
def _days_from_civil(y, m, d):
    y -= m <= 2
    era = (y if y >= 0 else y - 399) // 400
    yoe = y - era * 400
    doy = (153 * (m + (-3 if m > 2 else 9)) + 2) // 5 + d - 1
    return era * 146097 + yoe * 365 + yoe // 4 - yoe // 100 + doy - 719468


def _year(t):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(t, timezone.utc).year


def _wd(days):
    return (days + 4) % 7  # 0 = Sunday


def _nth_sunday(y, m, n):
    first = _days_from_civil(y, m, 1)
    return first + (7 - _wd(first)) % 7 + 7 * (n - 1)


def _last_sunday(y, m):
    last = _days_from_civil(y + (m == 12), m % 12 + 1, 1) - 1
    return last - _wd(last)


def offset(zone, t):
    """UTC offset in seconds for 'US' (New York) or 'UK' (London)."""
    y = _year(t)
    if zone == 'US':
        on = _nth_sunday(y, 3, 2) * 86400 + 7 * 3600 <= t < _nth_sunday(y, 11, 1) * 86400 + 6 * 3600
        return (-4 if on else -5) * 3600
    on = _last_sunday(y, 3) * 86400 + 3600 <= t < _last_sunday(y, 10) * 86400 + 3600
    return 3600 if on else 0


def broker_day(t):
    return (t + offset('US', t) + 7 * 3600) // 86400


def weekday(t):
    return _wd(t // 86400)


# ----- primitives ---------------------------------------------------------------------------------------
def ema(values, n):
    k, e, out = 2 / (n + 1), values[0], []
    for v in values:
        e += k * (v - e)
        out.append(e)
    return out


def atr(bars, n):
    trs = [max(b['high'] - b['low'], abs(b['high'] - a['close']), abs(b['low'] - a['close'])) for a, b in zip(bars[-n - 1:-1], bars[-n:])]
    return sum(trs) / len(trs) if trs else None


# ----- T1 trend -----------------------------------------------------------------------------------------
def trend(bars):
    if len(bars) < 60:
        return {'state': 'UNAVAILABLE', 'reason': f'{len(bars)} closed candles (< 60)'}
    closes = [b['close'] for b in bars]
    e20, e50 = ema(closes, 20), ema(closes, 50)
    up = closes[-1] > e50[-1] and e20[-1] > e50[-1] and e50[-1] > e50[-6]
    down = closes[-1] < e50[-1] and e20[-1] < e50[-1] and e50[-1] < e50[-6]
    return {'state': 'UP' if up else 'DOWN' if down else 'NEUTRAL', 'close': closes[-1], 'ema20': e20[-1], 'ema50': e50[-1],
            'ema50_5_ago': e50[-6], 'as_of_close': bars[-1]['utc']}


# ----- L1/L2/L3 levels ----------------------------------------------------------------------------------
def broker_days(h1, now):
    days = []
    today = broker_day(now)
    for b in h1:
        k = broker_day(b['utc'])
        if days and days[-1]['key'] == k:
            d = days[-1]
            d['high'], d['low'], d['close'], d['bars'] = max(d['high'], b['high']), min(d['low'], b['low']), b['close'], d['bars'] + 1
        else:
            days.append({'key': k, 'open': b['open'], 'high': b['high'], 'low': b['low'], 'close': b['close'], 'bars': 1, 'start': b['utc']})
    complete = [d for d in days if d['key'] < today and d['bars'] >= 12]
    current = days[-1] if days and days[-1]['key'] == today else None
    return complete, current


def previous_week(complete):
    if not complete:
        return None
    # Monday-based week of each broker day; the broker day key counts days since epoch (Thursday).
    week = lambda k: (k - 4) // 7
    this = week(complete[-1]['key'] + 1) if _wd(complete[-1]['key']) == 5 else week(complete[-1]['key'])
    prior = [d for d in complete if week(d['key']) == this - 1] or [d for d in complete if week(d['key']) == this]
    return {'high': max(d['high'] for d in prior), 'low': min(d['low'] for d in prior), 'days': len(prior)} if prior else None


def swings(h4, k=2, keep=8):
    highs, lows = [], []
    for i in range(k, len(h4) - k):
        b = h4[i]
        if all(b['high'] > h4[j]['high'] for j in range(i - k, i + k + 1) if j != i):
            highs.append({'price': b['high'], 'at': b['utc']})
        if all(b['low'] < h4[j]['low'] for j in range(i - k, i + k + 1) if j != i):
            lows.append({'price': b['low'], 'at': b['utc']})
    return highs[-keep:], lows[-keep:]


# ----- E1 level events ----------------------------------------------------------------------------------
def level_event(bars, level, side):
    """side='above' for a resistance-type level (high), 'below' for a support-type level (low)."""
    if not bars or level is None:
        return {'event': 'UNAVAILABLE'}
    beyond = (lambda x: x > level) if side == 'above' else (lambda x: x < level)
    closes_beyond = [beyond(b['close']) for b in bars]
    wick = any(beyond(b['high'] if side == 'above' else b['low']) for b in bars)
    run = best = 0
    for c in closes_beyond:
        run = run + 1 if c else 0
        best = max(best, run)
    first = next((i for i, c in enumerate(closes_beyond) if c), None)
    failed = first is not None and any(not c for c in closes_beyond[first + 1:])
    if best >= 2 and closes_beyond[-1]:
        event = 'ACCEPTED'
    elif failed and not closes_beyond[-1]:
        event = 'FAILED'
    elif wick and first is None:
        event = 'SWEEP'
    elif first is not None:
        event = 'BEYOND' if closes_beyond[-1] else 'FAILED'
    else:
        event = 'UNTESTED'
    return {'event': event, 'latest_close_side': ('above' if bars[-1]['close'] > level else 'below')}


# ----- S1/S2 sessions -----------------------------------------------------------------------------------
def sessions(m15, now):
    day0 = now - now % 86400
    lo_open = day0 + 8 * 3600 - offset('UK', now)
    ny_open = day0 + 9 * 3600 + 1800 - offset('US', now)
    ny_close = day0 + 16 * 3600 - offset('US', now)
    pick = lambda a, b: [x for x in m15 if a <= x['utc'] and x['utc'] + 900 <= min(b, now)]
    lo_close = day0 + 16 * 3600 + 1800 - offset('UK', now)
    asia, london, ny = pick(day0, day0 + 6 * 3600), pick(lo_open, ny_open), pick(ny_open, ny_close)
    rng = lambda bs, end: {'high': max(b['high'] for b in bs), 'low': min(b['low'] for b in bs), 'candles': len(bs),
                           'complete': now >= end, 'ends_at': end} if bs else None
    london_on, ny_on = lo_open <= now < lo_close, ny_open <= now < ny_close
    if weekday(now) in (0, 6):
        current = 'Weekend'
    elif london_on and ny_on:
        current = 'London/New York overlap'
    elif london_on:
        current = 'London'
    elif ny_on:
        current = 'New York'
    elif now < day0 + 6 * 3600:
        current = 'Asia'
    elif now < lo_open:
        current = 'Pre-London'
    else:
        current = 'After New York close'
    out = {'current': current, 'asia': rng(asia, day0 + 6 * 3600), 'london': rng(london, ny_open), 'new_york': rng(ny, ny_close),
           'weekend': weekday(now) in (0, 6)}
    if out['london'] and ny:
        out['ny_vs_london'] = {'took_london_high': any(b['high'] > out['london']['high'] for b in ny),
                               'took_london_low': any(b['low'] < out['london']['low'] for b in ny),
                               'last_close_vs_london': ('above' if ny[-1]['close'] > out['london']['high'] else
                                                        'below' if ny[-1]['close'] < out['london']['low'] else 'inside')}
    return out


# ----- R1-R4 regime -------------------------------------------------------------------------------------
def regime(h1, days_complete, current_day):
    out = {}
    if len(h1) >= 25:
        c = [b['close'] for b in h1[-25:]]
        path = sum(abs(c[i] - c[i - 1]) for i in range(1, 25))
        er = abs(c[-1] - c[0]) / path if path else 0
        out['trend'] = {'state': 'TRENDING' if er >= 0.35 else 'RANGING' if er <= 0.20 else 'MIXED', 'efficiency_ratio': er}
    else:
        out['trend'] = {'state': 'UNAVAILABLE'}
    if len(h1) >= 24 * 21:
        now_atr = atr(h1, 24)
        hist = [atr(h1[:k], 24) for k in range(len(h1) - 24 * 20, len(h1), 24)]
        pct = sum(h < now_atr for h in hist) / len(hist)
        out['volatility'] = {'state': 'LOW' if pct < 1 / 3 else 'HIGH' if pct > 2 / 3 else 'NORMAL', 'atr_h1_24': now_atr, 'percentile_20d': pct}
    else:
        out['volatility'] = {'state': 'UNAVAILABLE', 'reason': f'{len(h1)} H1 candles (< {24 * 21})'}
    if current_day and len(days_complete) >= 15:
        trs = [max(d['high'] - d['low'], abs(d['high'] - p['close']), abs(d['low'] - p['close'])) for p, d in zip(days_complete[-15:-1], days_complete[-14:])]
        datr = sum(trs) / len(trs)
        r = current_day['high'] - current_day['low']
        out['expansion'] = {'state': 'EXPANDING' if r >= 1.2 * datr else 'NORMAL', 'day_range': r, 'daily_atr_14': datr, 'ratio': r / datr if datr else None}
    else:
        out['expansion'] = {'state': 'UNAVAILABLE'}
    if len(h1) >= 24 * 21:
        last = h1[-1]
        same = [b['high'] - b['low'] for b in h1[:-1] if b['utc'] % 86400 == last['utc'] % 86400][-20:]
        base = median(same) if len(same) >= 10 else None
        rng = last['high'] - last['low']
        out['shock'] = {'state': 'SHOCK' if base and rng >= 3 * base else 'NONE', 'ratio': rng / base if base else None,
                        'note': 'cause not verified (no authoritative news feed connected)'}
    else:
        out['shock'] = {'state': 'UNAVAILABLE'}
    return out
