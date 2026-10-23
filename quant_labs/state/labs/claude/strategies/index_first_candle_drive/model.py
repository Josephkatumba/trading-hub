"""Claude-authored experimental model: Index Opening-Candle Drive. No verified edge.

Mechanism (opening-range momentum; adapted from Zarattini & Aziz 2023, who report a
first-5-minute-candle opening-range breakout on QQQ held to the close): the first
cash-session candle aggregates the overnight order imbalance released at the open.
Trade in the direction of the first M15 cash candle (dojis excluded), stop at that
candle's opposite extreme, a distant 6R objective, otherwise flat 15 minutes before
the cash close. Most payoff is expected from occasional full trend days.

15-minute (not 5-minute) candle because only M15 history spans train/validation/test.
Uses only closed candles from the supplied snapshot. Pure functions only.
"""

TARGET_R = 6.0
MIN_BODY = 0.25            # |close - open| / range of the opening candle
STOP_BUFFER = 0.0
EXIT_BEFORE_CLOSE = 900
SESSIONS = {'NAS100': ('US', 570, 960), 'US500': ('US', 570, 960), 'GER40': ('EU', 540, 1050)}

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
    if symbol not in SESSIONS:
        return []
    zone, open_min, close_min = SESSIONS[symbol]
    bars = snapshot['frames'].get('M15', ())
    if len(bars) < 20:
        return []
    first = bars[-1]
    now = first['utc'] + 900
    offset = utc_offset(zone, now)
    day = (now + offset) // 86400
    if weekday(day) in (0, 6):
        return []
    session_open = day * 86400 + open_min * 60 - offset
    session_close = day * 86400 + close_min * 60 - offset
    if first['utc'] != session_open:
        return []
    rng = first['high'] - first['low']
    atr = atr_of(bars, 14)
    if rng <= 0 or atr <= 0:
        return []
    body = first['close'] - first['open']
    if abs(body) < MIN_BODY * rng:
        return []
    quote = snapshot['quote']
    if body > 0:
        direction, entry, stop = 'LONG', quote['ask'], first['low'] - STOP_BUFFER * atr
    else:
        direction, entry, stop = 'SHORT', quote['bid'], first['high'] + STOP_BUFFER * atr
    long = direction == 'LONG'
    risk = entry - stop if long else stop - entry
    if risk <= 0:
        return []
    horizon = min(session_close - EXIT_BEFORE_CLOSE - now, seconds_to_cutoff(symbol, now))
    if horizon < 3600:
        return []
    target = entry + TARGET_R * risk if long else entry - TARGET_R * risk
    return [{'direction': direction, 'stop_loss': stop, 'take_profit': target, 'horizon_seconds': horizon, 'atr': atr,
             'rationale': 'Opening cash-session M15 candle closed %s; stop at its opposite extreme, 6R objective, flat before the cash close.' % ('up' if long else 'down')}]
