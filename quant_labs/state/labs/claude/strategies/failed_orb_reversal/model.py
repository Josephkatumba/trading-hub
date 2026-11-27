"""Claude-authored experimental model: Failed London Opening-Range Breakout (pre-registered 2026-10-23, commit 674ab1e).

Inverse of Kimi's Opening Range Drive question: are FAILED London opening-range breakouts
informative? Opening range = four M15 candles from 08:00 London (DST-aware). Breakout = a
close beyond the range by >= 0.1 ATR within the next 12 candles; failure = a close back inside
the range within the following 4 candles. Trade opposite the breakout at the failure close;
stop beyond the breakout extreme + 0.15 ATR; 2.2R; time limit 16:00 London or next data gap.
First breakout/failure per day only. Independent Claude implementation. Pure functions only.
"""

SYMBOLS = {'EURUSD', 'GBPUSD', 'GBPJPY', 'XAUUSD', 'BTCUSD', 'ETHUSD'}
BREAK_ATR = 0.1
BREAK_WINDOW = 12
FAIL_WINDOW = 4
STOP_BUFFER = 0.15
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
    if snapshot['symbol'] not in SYMBOLS:
        return []
    bars = snapshot['frames'].get('M15', ())
    if len(bars) < 60:
        return []
    last = bars[-1]
    now = last['utc'] + 900
    offset = utc_offset('UK', now)
    day = (now + offset) // 86400
    if weekday(day) in (0, 6):
        return []
    start = day * 86400 + 8 * 3600 - offset
    rng_bars = [b for b in bars if start <= b['utc'] < start + 3600]
    if len(rng_bars) != 4 or [b['utc'] for b in rng_bars] != [start + 900 * k for k in range(4)]:
        return []
    atr = atr_of(bars, 14)
    if atr <= 0:
        return []
    hi = max(b['high'] for b in rng_bars)
    lo = min(b['low'] for b in rng_bars)
    after = [b for b in bars if b['utc'] >= start + 3600]
    brk = None
    for i, b in enumerate(after):
        if b['utc'] >= start + 3600 + BREAK_WINDOW * 900:
            break
        if b['close'] > hi + BREAK_ATR * atr or b['close'] < lo - BREAK_ATR * atr:
            brk = i
            break
    if brk is None:
        return []
    up = after[brk]['close'] > hi
    fail = None
    for j in range(brk + 1, min(brk + 1 + FAIL_WINDOW, len(after))):
        if lo <= after[j]['close'] <= hi:
            fail = j
            break
    if fail is None or after[fail] is not last:
        return []  # the signal is the first failure close, and it must be the latest closed candle
    segment = after[brk:fail + 1]
    if up:
        direction, stop = 'SHORT', max(b['high'] for b in segment) + STOP_BUFFER * atr
    else:
        direction, stop = 'LONG', min(b['low'] for b in segment) - STOP_BUFFER * atr
    horizon = min(day * 86400 + 16 * 3600 - offset - now, seconds_to_cutoff(snapshot['symbol'], now))
    if horizon < 3600:
        return []
    quote = snapshot['quote']
    long = direction == 'LONG'
    entry = quote['ask'] if long else quote['bid']
    risk = entry - stop if long else stop - entry
    if risk <= 0:
        return []
    target = entry + TARGET_R * risk if long else entry - TARGET_R * risk
    return [{'direction': direction, 'stop_loss': stop, 'take_profit': target, 'horizon_seconds': horizon, 'atr': atr,
             'rationale': 'London opening-range breakout %s failed: price closed back inside the range within %d candles; trading the failure, stop beyond the breakout extreme, 2.2R.' % ('up' if up else 'down', fail - brk)}]
