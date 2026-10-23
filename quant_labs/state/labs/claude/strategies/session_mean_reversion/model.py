"""Claude-authored experimental model: Session-Mean Stretch Reversion. No verified edge.

Mechanism (inventory/mean reversion in non-trending regimes): when the H1 market is
range-bound (low efficiency ratio), a move that stretches price beyond 2.5 standard
deviations from the current broker day's average price and is rejected at a new
session extreme reflects temporary liquidity demand that market makers lean against.
Target is the session mean itself; trade only when that mean is at least 2.2R away
from a stop placed beyond the session extreme.

Uses only closed candles from the supplied snapshot. Pure functions only.
"""

import math

STRETCH = 2.5          # (close - session mean) / session standard deviation
MAX_EFFICIENCY = 0.30  # H1 efficiency ratio over 24 bars (range-bound regime)
WICK = 0.5             # rejection wick share of the signal candle range
STOP_BUFFER = 0.25
MIN_RR = 2.2
HORIZON = 6 * 3600
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
    if len(bars) < 40 or len(h1) < 30:
        return []
    last = bars[-1]
    now = last['utc'] + 900
    hour = now % 86400 // 3600
    if symbol not in CRYPTO and not 6 <= hour < 19:
        return []
    closes = [b['close'] for b in h1[-25:]]
    path = sum(abs(closes[i] - closes[i - 1]) for i in range(1, len(closes)))
    if path <= 0 or abs(closes[-1] - closes[0]) / path > MAX_EFFICIENCY:
        return []
    today = broker_day(now)
    session = [b for b in bars if broker_day(b['utc']) == today]
    if len(session) < 16:
        return []
    typical = [(b['high'] + b['low'] + b['close']) / 3 for b in session]
    mean = sum(typical) / len(typical)
    sd = math.sqrt(sum((x - mean) ** 2 for x in typical) / len(typical))
    atr = atr_of(bars, 14)
    if sd <= 0 or atr <= 0:
        return []
    rng = last['high'] - last['low']
    if rng <= 0:
        return []
    hi = max(b['high'] for b in session)
    lo = min(b['low'] for b in session)
    z = (last['close'] - mean) / sd
    direction = None
    if z >= STRETCH and last['high'] >= hi and (last['high'] - max(last['open'], last['close'])) >= WICK * rng and last['close'] < last['open']:
        direction, stop = 'SHORT', hi + STOP_BUFFER * atr
    elif z <= -STRETCH and last['low'] <= lo and (min(last['open'], last['close']) - last['low']) >= WICK * rng and last['close'] > last['open']:
        direction, stop = 'LONG', lo - STOP_BUFFER * atr
    if direction is None:
        return []
    horizon = min(HORIZON, seconds_to_cutoff(symbol, now))
    if horizon < MIN_HORIZON:
        return []
    quote = snapshot['quote']
    long = direction == 'LONG'
    entry = quote['ask'] if long else quote['bid']
    risk = entry - stop if long else stop - entry
    reward = mean - entry if long else entry - mean
    if risk <= 0 or reward < MIN_RR * risk:
        return []
    return [{'direction': direction, 'stop_loss': stop, 'take_profit': mean, 'horizon_seconds': horizon, 'atr': atr,
             'rationale': 'Range-bound H1 regime; close %.1f session SD from the broker-day mean with a rejection wick at the session extreme; target the session mean (%.1fR).' % (abs(z), reward / risk)}]
