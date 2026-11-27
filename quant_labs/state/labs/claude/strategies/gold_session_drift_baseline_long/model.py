"""Claude-authored experimental model: Gold Session Drift (pre-registered 2026-10-23, commit 862075e, H5).

Intraday momentum for XAUUSD: at the close of the M15 candle 60 minutes after the New York 09:30
open, if gold has moved >= 0.5 daily ATR from the London 08:00 open price and closes in the outer 25%
of the range since the London open, follow the move. Stop 0.35 daily ATR; 2.2R; exit 20:45 UTC.
BASELINE = True gives the pre-registered baseline B5: same timing and risk, always LONG, no condition.
Pure functions only.
"""

BASELINE = True
MOVE_ATR = 0.5
EXTREME_FRAC = 0.75
STOP_ATR = 0.35
TARGET_R = 2.2

DAILY_BREAK = {'XAUUSD', 'XAGUSD', 'NAS100', 'US500', 'GER40'}
CUTOFF = 20 * 3600 + 45 * 60   # 20:45 UTC, ahead of the 21:00/22:00 UTC broker break / index rollover


def seconds_to_cutoff(symbol, now):
    """Seconds until the next broker data gap that would make an outcome unmeasurable."""
    if symbol in DAILY_BREAK:
        return (CUTOFF - now % 86400) % 86400
    since_sunday = (now // 86400 + 4) % 7 * 86400 + now % 86400
    return (5 * 86400 + CUTOFF - since_sunday) % (7 * 86400)


def atr_of(bars, n):
    trs = []
    for i in range(len(bars) - n, len(bars)):
        b, pc = bars[i], bars[i - 1]['close']
        trs.append(max(b['high'] - b['low'], abs(b['high'] - pc), abs(b['low'] - pc)))
    return sum(trs) / len(trs)


def days_from_civil(y, m, d):
    y = y - 1 if m <= 2 else y
    era = (y if y >= 0 else y - 399) // 400
    yoe = y - era * 400
    doy = (153 * (m + (-3 if m > 2 else 9)) + 2) // 5 + d - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def year_of(t):
    z = t // 86400 + 719468
    era = (z if z >= 0 else z - 146096) // 146097
    doe = z - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    return yoe + era * 400 + (1 if mp >= 10 else 0)


def weekday(days):
    return (days + 4) % 7  # 0 = Sunday


def nth_sunday(y, m, n):
    first = days_from_civil(y, m, 1)
    return first + (7 - weekday(first)) % 7 + 7 * (n - 1)


def last_sunday(y, m):
    nxt = days_from_civil(y + (m == 12), m % 12 + 1, 1) - 1
    return nxt - weekday(nxt)


def utc_offset(zone, t):
    y = year_of(t)
    if zone == 'US':
        start = nth_sunday(y, 3, 2) * 86400 + 7 * 3600
        end = nth_sunday(y, 11, 1) * 86400 + 6 * 3600
        return -4 * 3600 if start <= t < end else -5 * 3600
    start = last_sunday(y, 3) * 86400 + 3600
    end = last_sunday(y, 10) * 86400 + 3600
    return (2 * 3600 if start <= t < end else 3600) if zone == 'EU' else (3600 if start <= t < end else 0)


def broker_day(t):
    """Broker trading-day index (day rolls at 17:00 New York)."""
    return (t + utc_offset('US', t) + 7 * 3600) // 86400


def broker_days(bars, duration, before):
    """Aggregate completed candles into broker days strictly before the broker day containing `before`."""
    today = broker_day(before)
    days = []
    for b in bars:
        if b['utc'] + duration > before:
            break
        key = broker_day(b['utc'])
        if key >= today:
            break
        if days and days[-1]['key'] == key:
            d = days[-1]
            d['high'] = max(d['high'], b['high'])
            d['low'] = min(d['low'], b['low'])
            d['close'] = b['close']
            d['bars'] += 1
        else:
            days.append({'key': key, 'open': b['open'], 'high': b['high'], 'low': b['low'], 'close': b['close'], 'bars': 1})
    return days


def detect(snapshot):
    if snapshot['symbol'] != 'XAUUSD':
        return []
    bars = snapshot['frames'].get('M15', ())
    h4 = snapshot['frames'].get('H4', ())
    if len(bars) < 80 or len(h4) < 100:
        return []
    now = bars[-1]['utc'] + 900
    day = now // 86400
    if weekday(day) in (0, 6):
        return []
    ny_open = day * 86400 + 9 * 3600 + 1800 - utc_offset('US', now)
    if now != ny_open + 3600:
        return []
    lo_open = day * 86400 + 8 * 3600 - utc_offset('UK', now)
    session = [b for b in bars if lo_open <= b['utc'] < now]
    if not session or session[0]['utc'] != lo_open or len(session) != (now - lo_open) // 900:
        return []
    days = [d for d in broker_days(h4, 14400, lo_open) if d['bars'] >= 4]
    if len(days) < 15:
        return []
    trs = [max(d['high'] - d['low'], abs(d['high'] - p['close']), abs(d['low'] - p['close'])) for p, d in zip(days[-15:-1], days[-14:])]
    atr_d = sum(trs) / len(trs)
    atr = atr_of(bars, 14)
    if atr_d <= 0 or atr <= 0:
        return []
    move = session[-1]['close'] - session[0]['open']
    hi = max(b['high'] for b in session)
    lo = min(b['low'] for b in session)
    location = (session[-1]['close'] - lo) / (hi - lo) if hi > lo else 0.5
    if BASELINE:
        direction = 'LONG'
    elif move >= MOVE_ATR * atr_d and location >= EXTREME_FRAC:
        direction = 'LONG'
    elif -move >= MOVE_ATR * atr_d and location <= 1 - EXTREME_FRAC:
        direction = 'SHORT'
    else:
        return []
    horizon = seconds_to_cutoff('XAUUSD', now)
    if horizon < 3600 or horizon > 12 * 3600:
        return []
    quote = snapshot['quote']
    long = direction == 'LONG'
    entry = quote['ask'] if long else quote['bid']
    risk = STOP_ATR * atr_d
    stop = entry - risk if long else entry + risk
    target = entry + TARGET_R * risk if long else entry - TARGET_R * risk
    why = 'Baseline B5: always long at the same time and risk.' if BASELINE else \
        'Gold moved %.2f daily ATR from the London open into the first New York hour, closing in the outer quarter of its range; following the session drift to 20:45 UTC.' % (abs(move) / atr_d)
    return [{'direction': direction, 'stop_loss': stop, 'take_profit': target, 'horizon_seconds': horizon, 'atr': atr, 'rationale': why}]
