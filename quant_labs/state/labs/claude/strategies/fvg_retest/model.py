"""Claude-authored experimental model: Fair-Value-Gap Retest Continuation. No verified edge.

Mechanism (order-flow imbalance): a displacement candle that leaves a three-candle
price gap (candle 3 low above candle 1 high, or the bearish mirror) marks one-sided
aggressive flow. When price first returns into that unfilled gap and the retest candle
closes back out of it in the displacement direction, with the H1 trend agreeing,
resting interest at the imbalance is assumed to defend it and the move resumes.
Stop beyond the far side of the gap; fixed 2.5R objective; exits before broker gaps.

Uses only closed candles from the supplied snapshot. Pure functions only.
"""

SEARCH = 16            # look back this many M15 candles for an unfilled gap
MIN_DISPLACEMENT = 1.0 # displacement candle body in M15 ATRs
MIN_GAP = 0.25         # gap size in M15 ATRs
STOP_BUFFER = 0.25
TARGET_R = 2.5
HORIZON = 8 * 3600
MIN_HORIZON = 2 * 3600

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


def h1_trend(h1):
    closes = [b['close'] for b in h1[-80:]]
    k = 2.0 / 51
    ema = closes[0]
    series = []
    for x in closes:
        ema = ema + k * (x - ema)
        series.append(ema)
    if closes[-1] > series[-1] and series[-1] > series[-6]:
        return 1
    if closes[-1] < series[-1] and series[-1] < series[-6]:
        return -1
    return 0


def detect(snapshot):
    bars = snapshot['frames'].get('M15', ())
    h1 = snapshot['frames'].get('H1', ())
    if len(bars) < SEARCH + 20 or len(h1) < 80:
        return []
    trend = h1_trend(h1)
    if trend == 0:
        return []
    atr = atr_of(bars, 14)
    if atr <= 0:
        return []
    last = bars[-1]
    n = len(bars)
    for j in range(n - 2, n - SEARCH, -1):
        a, m, c = bars[j - 2], bars[j - 1], bars[j]
        after = bars[j + 1:n - 1]
        if trend > 0:
            top, bottom = c['low'], a['high']
            if top - bottom < MIN_GAP * atr or m['close'] - m['open'] < MIN_DISPLACEMENT * atr:
                continue
            if any(b['low'] <= top for b in after):
                break  # most recent valid gap already retested: not a first touch
            if last['low'] <= top and last['low'] > bottom - 0.5 * atr and last['close'] > top and last['close'] > last['open']:
                direction = 'LONG'
                stop = min(bottom, last['low']) - STOP_BUFFER * atr
            else:
                continue
        else:
            top, bottom = a['low'], c['high']
            if top - bottom < MIN_GAP * atr or m['open'] - m['close'] < MIN_DISPLACEMENT * atr:
                continue
            if any(b['high'] >= bottom for b in after):
                break
            if last['high'] >= bottom and last['high'] < top + 0.5 * atr and last['close'] < bottom and last['close'] < last['open']:
                direction = 'SHORT'
                stop = max(top, last['high']) + STOP_BUFFER * atr
            else:
                continue
        now = last['utc'] + 900
        horizon = min(HORIZON, seconds_to_cutoff(snapshot['symbol'], now))
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
                 'rationale': 'First retest of an unfilled M15 fair-value gap left by a %.1f-ATR displacement, rejected in the H1 trend direction; stop beyond the gap, 2.5R objective.' % (abs(m['close'] - m['open']) / atr)}]
    return []
