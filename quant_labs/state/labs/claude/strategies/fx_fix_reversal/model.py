"""Claude-authored experimental model: London Fix Pressure Reversal. No verified edge.

Mechanism (FX benchmark microstructure; Melvin & Prins 2015, Evans 2018): dealers
pre-hedge customer fixing orders into the WM/Reuters 16:00 London fix, pushing prices
in the order-flow direction during the hour before the fix; the temporary price
pressure tends to reverse once the fix window has passed. Decision at 16:15 London
(close of the candle that contains the fix): if 15:00-16:15 London moved at least
0.25 daily ATR, fade it. Stop beyond the pre-fix extreme; 2.2R objective; flat after
three hours or the next broker gap.

Daily ATR from H4 broker days (Monday-safe). Pure functions only.
"""

WINDOW_START = 15 * 60     # London local minutes
DECISION = 16 * 60 + 15
MOVE_ATR = 0.25
STOP_BUFFER = 0.2          # M15 ATRs beyond the window extreme
TARGET_R = 2.2
HORIZON = 3 * 3600
FX = {'EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'NZDUSD', 'USDCAD', 'USDCHF', 'EURJPY', 'GBPJPY', 'XAUUSD', 'XAGUSD'}

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
    if symbol not in FX:
        return []
    bars = snapshot['frames'].get('M15', ())
    h4 = snapshot['frames'].get('H4', ())
    if len(bars) < 30 or len(h4) < 60:
        return []
    now = bars[-1]['utc'] + 900
    offset = utc_offset('UK', now)
    day = (now + offset) // 86400
    if weekday(day) in (0, 6):
        return []
    start = day * 86400 + WINDOW_START * 60 - offset
    if now != day * 86400 + DECISION * 60 - offset:
        return []
    window = [b for b in bars if start <= b['utc'] < now]
    if len(window) != (DECISION - WINDOW_START) // 15 or window[0]['utc'] != start:
        return []
    days = [d for d in broker_days(h4, 14400, start) if d['bars'] >= 4]
    if len(days) < 15:
        return []
    trs = []
    for i in range(len(days) - 14, len(days)):
        d, pc = days[i], days[i - 1]['close']
        trs.append(max(d['high'] - d['low'], abs(d['high'] - pc), abs(d['low'] - pc)))
    atr_d = sum(trs) / len(trs)
    atr = atr_of(bars, 14)
    if atr_d <= 0 or atr <= 0:
        return []
    move = window[-1]['close'] - window[0]['open']
    if abs(move) < MOVE_ATR * atr_d:
        return []
    quote = snapshot['quote']
    if move > 0:
        direction, entry, stop = 'SHORT', quote['bid'], max(b['high'] for b in window) + STOP_BUFFER * atr
    else:
        direction, entry, stop = 'LONG', quote['ask'], min(b['low'] for b in window) - STOP_BUFFER * atr
    long = direction == 'LONG'
    risk = entry - stop if long else stop - entry
    if risk <= 0:
        return []
    horizon = min(HORIZON, seconds_to_cutoff(symbol, now))
    if horizon < 3600:
        return []
    target = entry + TARGET_R * risk if long else entry - TARGET_R * risk
    return [{'direction': direction, 'stop_loss': stop, 'take_profit': target, 'horizon_seconds': horizon, 'atr': atr,
             'rationale': 'Pre-fix move of %.2f daily ATR into the 16:00 London fix; fade after the fix, stop beyond the pre-fix extreme, 2.2R objective.' % (abs(move) / atr_d)}]
