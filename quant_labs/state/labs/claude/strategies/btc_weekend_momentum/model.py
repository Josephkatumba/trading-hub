"""Claude-authored experimental model: Bitcoin Weekend Momentum (pre-registered 2026-10-23, commit 862075e, H6).

At the close of the first H4 candle opening at or after Saturday 00:00 UTC (after the broker's Friday
gap): if BTCUSD moved >= 1.0 weekly ATR from the week's first H4 open on/after Monday 00:00 UTC to the
last close before Friday 21:00 UTC, follow that direction. Weekly ATR = mean range of the previous
8 such Monday-Friday windows. Stop 0.5 weekly ATR; 2.0R; exit Sunday 20:00 UTC.
The decision's 'atr' field is the mean daily range of the last 14 UTC days (the holding-period
volatility unit used by the live stop-distance gate). BASELINE = True gives B6: always LONG each weekend.
Pure functions only.
"""

BASELINE = False
MOVE_WATR = 1.0
STOP_WATR = 0.5
TARGET_R = 2.0
WEEKS = 8

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


def week_window(monday0, h4):
    """Range and move of the Monday 00:00 UTC -> Friday 21:00 UTC window, from H4 candles closed by then."""
    end = monday0 + 4 * 86400 + 21 * 3600
    seg = [b for b in h4 if monday0 <= b['utc'] and b['utc'] + 14400 <= end]
    if len(seg) < 20:
        return None
    return {'open': seg[0]['open'], 'close': seg[-1]['close'], 'high': max(b['high'] for b in seg), 'low': min(b['low'] for b in seg)}


def detect(snapshot):
    if snapshot['symbol'] != 'BTCUSD':
        return []
    h4 = snapshot['frames'].get('H4', ())
    if len(h4) < 300:
        return []
    last, prev = h4[-1], h4[-2]
    now = last['utc'] + 14400
    day = last['utc'] // 86400
    saturday0 = day * 86400 if weekday(day) == 6 else None
    if saturday0 is None or not (last['utc'] >= saturday0 and prev['utc'] < saturday0):
        return []
    monday0 = saturday0 - 5 * 86400
    this = week_window(monday0, h4)
    prior = [week_window(monday0 - 7 * 86400 * k, h4) for k in range(1, WEEKS + 1)]
    if this is None or any(w is None for w in prior):
        return []
    watr = sum(w['high'] - w['low'] for w in prior) / WEEKS
    move = this['close'] - this['open']
    if BASELINE:
        direction = 'LONG'
    elif abs(move) >= MOVE_WATR * watr:
        direction = 'LONG' if move > 0 else 'SHORT'
    else:
        return []
    exit_at = saturday0 + 86400 + 20 * 3600
    horizon = exit_at - now
    if horizon < 6 * 3600:
        return []
    daily = []
    for k in range(1, 15):
        seg = [b for b in h4 if (day - k) * 86400 <= b['utc'] < (day - k + 1) * 86400]
        if seg:
            daily.append(max(b['high'] for b in seg) - min(b['low'] for b in seg))
    if len(daily) < 10:
        return []
    atr = sum(daily) / len(daily)
    quote = snapshot['quote']
    long = direction == 'LONG'
    entry = quote['ask'] if long else quote['bid']
    risk = STOP_WATR * watr
    stop = entry - risk if long else entry + risk
    target = entry + TARGET_R * risk if long else entry - TARGET_R * risk
    why = 'Baseline B6: always long each weekend at the same time and risk.' if BASELINE else \
        'Bitcoin moved %.2f weekly ATR during the trading week; following that direction through the weekend to Sunday 20:00 UTC.' % (abs(move) / watr)
    return [{'direction': direction, 'stop_loss': stop, 'take_profit': target, 'horizon_seconds': horizon, 'atr': atr, 'rationale': why}]
