"""Claude-authored experimental model: Prior-Day Level Acceptance Retest. No verified edge.

Mechanism (auction acceptance): the prior broker day's high/low is the most widely
watched reference level. When an M15 candle closes beyond it, and the first pullback
to the level holds (the retest candle closes back on the breakout side), the market
has accepted prices outside yesterday's value range and tends to extend. This is
the opposite of a sweep/failure setup: entry only after the level has held.
Stop beyond the retest low/high; fixed 2.5R objective; exits before broker gaps.

Prior day built from H1 candles (D1 context is rejected as stale by the live gate on
Mondays). Uses only closed candles from the supplied snapshot. Pure functions only.
"""

ZONE = 0.15            # retest must come within this many M15 ATRs of the level
MAX_PIERCE = 0.6       # retest may not trade more than this far back through the level
STOP_BUFFER = 0.3
TARGET_R = 2.5
MAX_BARS_SINCE_BREAK = 24
HORIZON = 8 * 3600
MIN_HORIZON = 2 * 3600
CRYPTO = {'BTCUSD', 'ETHUSD'}

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
    symbol = snapshot['symbol']
    bars = snapshot['frames'].get('M15', ())
    h1 = snapshot['frames'].get('H1', ())
    if len(bars) < 60 or len(h1) < 48:
        return []
    last = bars[-1]
    now = last['utc'] + 900
    hour = now % 86400 // 3600
    if symbol not in CRYPTO and not 6 <= hour < 19:
        return []
    days = broker_days(h1, 3600, now)
    if not days or days[-1]['bars'] < 12:
        return []
    pdh, pdl = days[-1]['high'], days[-1]['low']
    atr = atr_of(bars, 14)
    if atr <= 0:
        return []
    today = broker_day(now)
    session = [b for b in bars if broker_day(b['utc']) == today]
    if len(session) < 3:
        return []
    direction = None
    for side in (1, -1):
        level = pdh if side > 0 else pdl
        brk = None
        for i, b in enumerate(session[:-1]):
            if side * (b['close'] - level) > 0:
                brk = i
                break
        if brk is None or len(session) - 1 - brk > MAX_BARS_SINCE_BREAK or len(session) - 1 - brk < 2:
            continue
        between = session[brk + 1:-1]
        if side > 0:
            if any(b['low'] <= level + ZONE * atr for b in between):
                continue
            if last['low'] <= level + ZONE * atr and last['low'] >= level - MAX_PIERCE * atr and last['close'] > level and last['close'] > last['open']:
                direction, stop = 'LONG', min(last['low'], level) - STOP_BUFFER * atr
        else:
            if any(b['high'] >= level - ZONE * atr for b in between):
                continue
            if last['high'] >= level - ZONE * atr and last['high'] <= level + MAX_PIERCE * atr and last['close'] < level and last['close'] < last['open']:
                direction, stop = 'SHORT', max(last['high'], level) + STOP_BUFFER * atr
        if direction:
            break
    if direction is None:
        return []
    horizon = min(HORIZON, seconds_to_cutoff(symbol, now))
    if horizon < MIN_HORIZON:
        return []
    quote = snapshot['quote']
    long = direction == 'LONG'
    entry = quote['ask'] if long else quote['bid']
    risk = entry - stop if long else stop - entry
    if risk <= 0:
        return []
    target = entry + TARGET_R * risk if long else entry - TARGET_R * risk
    return [{'direction': direction, 'stop_loss': stop, 'take_profit': target, 'horizon_seconds': horizon, 'atr': atr,
             'rationale': 'Close beyond the prior broker-day %s, first retest held; stop beyond the retest, 2.5R objective.' % ('high' if long else 'low')}]
