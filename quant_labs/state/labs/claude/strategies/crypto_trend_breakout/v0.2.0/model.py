"""Claude-authored experimental model: Crypto 20-Day Trend Breakout. No verified edge.

Hypothesis (time-series momentum in crypto, e.g. Liu & Tsyvinski 2021): fresh
20-day closing breakouts in the direction of a rising/falling 50-day baseline in
BTC/ETH are followed by continuation over the following days, because crypto
flows are momentum- and attention-driven. Holds up to seven days but always exits before the broker's weekly Friday
~21:00 UTC crypto maintenance gap (v0.2.0),
volatility-scaled stop, fixed 3R objective.

Uses only closed H4 candles from the supplied snapshot. Pure functions only.
"""

CHANNEL = 120        # H4 bars = 20 days
BASELINE = 300       # H4 bars = 50 days
SLOPE_LAG = 30       # baseline slope measured over 5 days
ATR_N = 30
STOP_ATR = 3.0
TARGET_R = 3.0
HORIZON = 7 * 86400
MIN_HORIZON = 86400
WEEKLY_BREAK = 5 * 86400 + 20 * 3600 + 45 * 60  # Friday 20:45 UTC, seconds after Sunday 00:00 UTC


def detect(snapshot):
    bars = snapshot['frames'].get('H4', ())
    if len(bars) < BASELINE + SLOPE_LAG + 2:
        return []
    closes = [b['close'] for b in bars]
    trs = []
    for i in range(len(bars) - ATR_N, len(bars)):
        b, pc = bars[i], bars[i - 1]['close']
        trs.append(max(b['high'] - b['low'], abs(b['high'] - pc), abs(b['low'] - pc)))
    atr = sum(trs) / len(trs)
    if atr <= 0:
        return []
    base_now = sum(closes[-BASELINE:]) / BASELINE
    base_then = sum(closes[-BASELINE - SLOPE_LAG:-SLOPE_LAG]) / BASELINE
    last = closes[-1]
    prev = closes[-2]
    upper = max(b['high'] for b in bars[-CHANNEL - 1:-1])
    lower = min(b['low'] for b in bars[-CHANNEL - 1:-1])
    upper_prev = max(b['high'] for b in bars[-CHANNEL - 2:-2])
    lower_prev = min(b['low'] for b in bars[-CHANNEL - 2:-2])
    direction = None
    if last > upper and prev <= upper_prev and last > base_now and base_now > base_then:
        direction = 'LONG'
    elif last < lower and prev >= lower_prev and last < base_now and base_now < base_then:
        direction = 'SHORT'
    if direction is None:
        return []
    now = bars[-1]['utc'] + 14400
    since_sunday = (now // 86400 + 4) % 7 * 86400 + now % 86400
    to_break = (WEEKLY_BREAK - since_sunday) % (7 * 86400)
    horizon = min(HORIZON, to_break)
    if horizon < MIN_HORIZON:
        return []  # broker crypto maintenance gap every Friday ~21:00 UTC; do not straddle it
    quote = snapshot['quote']
    long = direction == 'LONG'
    entry = quote['ask'] if long else quote['bid']
    risk = STOP_ATR * atr
    stop = entry - risk if long else entry + risk
    target = entry + TARGET_R * risk if long else entry - TARGET_R * risk
    return [{'direction': direction, 'stop_loss': stop, 'take_profit': target, 'horizon_seconds': horizon, 'atr': atr,
             'rationale': 'Fresh 20-day H4 closing breakout aligned with a sloping 50-day baseline; 3 ATR stop, 3R objective, exit by the Friday maintenance break (max 7 days).'}]
