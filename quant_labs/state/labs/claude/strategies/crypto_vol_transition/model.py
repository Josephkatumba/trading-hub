"""Claude-authored experimental model (pre-registered 2026-10-23, commit 34bd776): Crypto Volatility-Regime Transition.

MODE 'pullback' (H7): D1 trend (T1) + H4 pullback below EMA20 within 6 candles + H4 close above the
previous high (mirror for down) -> follow; stop beyond the 6-candle extreme +/- 0.5 ATR(H4); 2.5R.
MODE 'vol' (H8): ATR(H1,24) in the lowest 20% of the prior 20 days + H4 close beyond the previous 18-candle
range -> follow; stop at the opposite side of that range, capped at 3 ATR(H4); 2.5R.
MODE 'extreme' (H9): 24h move >= 3 x mean daily range (14 days) + first H4 counter-close -> fade;
stop beyond the 24h extreme + 0.25 ATR(H4); 2.0R.
Exit by min(72h, Friday 20:45 UTC); no entry with < 24h to that gap. BASELINE=True: same decision times
and risk, always LONG. Pure functions only.
"""

MODE = 'vol'
BASELINE = False
SYMBOLS = {'BTCUSD', 'ETHUSD'}
HORIZON = 72 * 3600
MIN_TO_GAP = 24 * 3600

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


def ema_series(values, n):
    k, e, out = 2.0 / (n + 1), values[0], []
    for v in values:
        e = e + k * (v - e)
        out.append(e)
    return out


def d1_trend(d1):
    c = [b['close'] for b in d1]
    if len(c) < 60:
        return 0
    e20, e50 = ema_series(c, 20), ema_series(c, 50)
    if c[-1] > e50[-1] and e20[-1] > e50[-1] and e50[-1] > e50[-6]:
        return 1
    if c[-1] < e50[-1] and e20[-1] < e50[-1] and e50[-1] < e50[-6]:
        return -1
    return 0


def decide(h4, h1, d1, atr4):
    last, prev = h4[-1], h4[-2]
    if MODE == 'pullback':
        side = d1_trend(d1)
        if side == 0:
            return None
        ema = ema_series([b['close'] for b in h4[-80:]], 20)
        recent, ema_recent = h4[-7:-1], ema[-7:-1]
        if side > 0 and any(b['close'] < e for b, e in zip(recent, ema_recent)) and last['close'] > prev['high']:
            return 1, min(b['low'] for b in h4[-6:]) - 0.5 * atr4, 2.5
        if side < 0 and any(b['close'] > e for b, e in zip(recent, ema_recent)) and last['close'] < prev['low']:
            return -1, max(b['high'] for b in h4[-6:]) + 0.5 * atr4, 2.5
        return None
    if MODE == 'vol':
        if len(h1) < 24 * 21 + 2:
            return None
        now_atr = atr_of(h1, 24)
        hist = [atr_of(h1[:k], 24) for k in range(len(h1) - 24 * 20, len(h1), 6)]
        if sum(1 for h in hist if h < now_atr) / len(hist) >= 0.2:
            return None
        rng = h4[-19:-1]
        hi, lo = max(b['high'] for b in rng), min(b['low'] for b in rng)
        if last['close'] > hi:
            return 1, max(lo, last['close'] - 3 * atr4), 2.5
        if last['close'] < lo:
            return -1, min(hi, last['close'] + 3 * atr4), 2.5
        return None
    if MODE == 'extreme':
        days = [d for d in d1[-15:-1]]
        if len(days) < 14:
            return None
        adr = sum(d['high'] - d['low'] for d in days) / len(days)
        window = h4[-7:-1]
        move = window[-1]['close'] - window[0]['open']
        if abs(move) < 3 * adr:
            return None
        if move > 0 and last['close'] < last['open']:
            return -1, max(b['high'] for b in h4[-7:]) + 0.25 * atr4, 2.0
        if move < 0 and last['close'] > last['open']:
            return 1, min(b['low'] for b in h4[-7:]) - 0.25 * atr4, 2.0
        return None
    return None


def detect(snapshot):
    if snapshot['symbol'] not in SYMBOLS:
        return []
    h4 = snapshot['frames'].get('H4', ())
    h1 = snapshot['frames'].get('H1', ())
    d1 = snapshot['frames'].get('D1', ())
    if len(h4) < 80:
        return []
    atr4 = atr_of(h4, 14)
    if atr4 <= 0:
        return []
    found = decide(h4, h1, d1, atr4)
    if found is None:
        return []
    side, stop, target_r = found
    now = h4[-1]['utc'] + 14400
    to_gap = seconds_to_cutoff(snapshot['symbol'], now)
    if to_gap < MIN_TO_GAP:
        return []
    if BASELINE:
        risk_dist = abs(h4[-1]['close'] - stop)
        side, stop = 1, h4[-1]['close'] - risk_dist
    quote = snapshot['quote']
    long = side > 0
    entry = quote['ask'] if long else quote['bid']
    risk = entry - stop if long else stop - entry
    if risk <= 0:
        return []
    target = entry + target_r * risk if long else entry - target_r * risk
    why = ('Baseline: always long at the same decision time and risk. ' if BASELINE else '') + 'Compressed H1 volatility (lowest 20% of 20 days) followed by an H4 close beyond the 3-day range: regime transition.'
    return [{'direction': 'LONG' if long else 'SHORT', 'stop_loss': stop, 'take_profit': target, 'horizon_seconds': min(HORIZON, to_gap),
             'atr': atr4, 'rationale': why}]
