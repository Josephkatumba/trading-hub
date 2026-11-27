"""Claude-authored experimental model: 24-Hour Channel Trend Breakout. No verified edge.

Mechanism (intraday time-series momentum with a wide, noise-tolerant stop): a fresh
M15 close above the prior 24-hour high (below the 24-hour low) while the H4 EMA trend
points the same way indicates that the higher-timeframe trend is resuming. Unlike
tight-stop pattern entries, the stop is 1.5 H1 ATRs so ordinary M15 noise does not
exit the trade; 2.5R objective; 24-hour limit or the next broker data gap.
No compression precondition (distinct from compression-escape models).

v0.2.0 (declared train-selected trial): restricted to XAUUSD, BTCUSD and ETHUSD, the
markets where v0.1.0 was positive on the training split; v0.1.0 lost across FX and
indices. Rules unchanged. Only validation/test can confirm it; selection bias disclosed.

Uses only closed candles from the supplied snapshot. Pure functions only.
"""

CHANNEL = 96               # M15 candles = 24 hours
STOP_H1_ATR = 1.5
TARGET_R = 2.5
HORIZON = 24 * 3600
MIN_HORIZON = 3 * 3600
MARKETS = {'XAUUSD', 'BTCUSD', 'ETHUSD'}

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
    if snapshot['symbol'] not in MARKETS:
        return []
    bars = snapshot['frames'].get('M15', ())
    h1 = snapshot['frames'].get('H1', ())
    h4 = snapshot['frames'].get('H4', ())
    if len(bars) < CHANNEL + 3 or len(h1) < 26 or len(h4) < 40:
        return []
    last, prev = bars[-1], bars[-2]
    upper = max(b['high'] for b in bars[-CHANNEL - 1:-1])
    lower = min(b['low'] for b in bars[-CHANNEL - 1:-1])
    upper_prev = max(b['high'] for b in bars[-CHANNEL - 2:-2])
    lower_prev = min(b['low'] for b in bars[-CHANNEL - 2:-2])
    if last['close'] > upper and prev['close'] <= upper_prev:
        side = 1
    elif last['close'] < lower and prev['close'] >= lower_prev:
        side = -1
    else:
        return []
    closes = [b['close'] for b in h4[-40:]]
    k = 2.0 / 21
    ema = closes[0]
    series = []
    for x in closes:
        ema = ema + k * (x - ema)
        series.append(ema)
    if side > 0 and not (closes[-1] > series[-1] > series[-4]):
        return []
    if side < 0 and not (closes[-1] < series[-1] < series[-4]):
        return []
    atr_h1 = atr_of(h1, 24)
    atr = atr_of(bars, 14)
    if atr_h1 <= 0 or atr <= 0:
        return []
    now = last['utc'] + 900
    horizon = min(HORIZON, seconds_to_cutoff(snapshot['symbol'], now))
    if horizon < MIN_HORIZON:
        return []
    quote = snapshot['quote']
    long = side > 0
    entry = quote['ask'] if long else quote['bid']
    risk = STOP_H1_ATR * atr_h1
    stop = entry - risk if long else entry + risk
    target = entry + TARGET_R * risk if long else entry - TARGET_R * risk
    return [{'direction': 'LONG' if long else 'SHORT', 'stop_loss': stop, 'take_profit': target, 'horizon_seconds': horizon,
             'atr': atr, 'rationale': 'Fresh M15 close beyond the prior 24-hour range in the H4 EMA-trend direction; 1.5 H1-ATR stop, 2.5R objective.'}]
