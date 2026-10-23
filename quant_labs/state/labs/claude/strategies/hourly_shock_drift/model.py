"""Claude-authored experimental model: Hour-Adjusted Shock Drift. No verified edge.

Hypothesis: an H1 candle whose range is abnormally large *for that hour of the day*
(normalised against the same UTC hour on the previous 20 trading days, which strips
out ordinary session-open volatility) and that closes decisively at one extreme
usually reflects new information (data releases, flows). Slow incorporation of that
information produces drift in the shock direction over the following hours; a true
information shock should not retrace beyond half of its candle.

Exits before known broker data gaps (daily break for metals, weekly close for FX
and the Friday crypto maintenance break) so outcomes stay measurable.
Uses only closed H1 candles from the supplied snapshot. Pure functions only.
"""

LOOKBACK_DAYS = 20
SHOCK_MULT = 2.5     # range vs median same-hour range
BODY_FRAC = 0.6      # |close-open| / range
CLOSE_FRAC = 0.8     # close location in the candle range
TARGET_R = 2.5
HORIZON = 24 * 3600
MIN_HORIZON = 4 * 3600
CUTOFF = 20 * 3600 + 45 * 60   # 20:45 UTC, ahead of the 21:00/22:00 UTC broker break

DAILY_BREAK = {'XAUUSD', 'XAGUSD'}
WEEKLY_BREAK = {'EURUSD', 'GBPUSD', 'GBPJPY', 'USDJPY', 'AUDUSD', 'EURJPY', 'USDCAD', 'USDCHF', 'NZDUSD', 'BTCUSD', 'ETHUSD'}


def seconds_to_cutoff(symbol, now):
    if symbol in DAILY_BREAK:
        return (CUTOFF - now % 86400) % 86400
    since_sunday = (now // 86400 + 4) % 7 * 86400 + now % 86400
    return (5 * 86400 + CUTOFF - since_sunday) % (7 * 86400)


def median(values):
    s = sorted(values)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def detect(snapshot):
    symbol = snapshot['symbol']
    if symbol not in DAILY_BREAK and symbol not in WEEKLY_BREAK:
        return []
    bars = snapshot['frames'].get('H1', ())
    if len(bars) < 200:
        return []
    last = bars[-1]
    hour = last['utc'] % 86400
    same_hour = [b['high'] - b['low'] for b in bars[:-1] if b['utc'] % 86400 == hour]
    same_hour = same_hour[-LOOKBACK_DAYS:]
    if len(same_hour) < LOOKBACK_DAYS:
        return []
    base = median(same_hour)
    rng = last['high'] - last['low']
    if base <= 0 or rng < SHOCK_MULT * base:
        return []
    body = last['close'] - last['open']
    if abs(body) < BODY_FRAC * rng:
        return []
    location = (last['close'] - last['low']) / rng
    if body > 0 and location >= CLOSE_FRAC:
        direction = 'LONG'
    elif body < 0 and location <= 1 - CLOSE_FRAC:
        direction = 'SHORT'
    else:
        return []
    trs = []
    for i in range(len(bars) - 24, len(bars)):
        b, pc = bars[i], bars[i - 1]['close']
        trs.append(max(b['high'] - b['low'], abs(b['high'] - pc), abs(b['low'] - pc)))
    atr = sum(trs) / len(trs)
    now = last['utc'] + 3600
    horizon = min(HORIZON, seconds_to_cutoff(symbol, now))
    if horizon < MIN_HORIZON or atr <= 0:
        return []
    quote = snapshot['quote']
    long = direction == 'LONG'
    entry = quote['ask'] if long else quote['bid']
    stop = (last['high'] + last['low']) / 2
    risk = entry - stop if long else stop - entry
    if risk <= 0:
        return []
    target = entry + TARGET_R * risk if long else entry - TARGET_R * risk
    return [{'direction': direction, 'stop_loss': stop, 'take_profit': target, 'horizon_seconds': horizon, 'atr': atr,
             'rationale': 'H1 shock %.1fx the median same-hour range, closing at its extreme; stop at the shock midpoint, %.1fR objective.' % (rng / base, TARGET_R)}]
