"""Claude-authored experimental model: Index Trend-Day Continuation. No verified edge.

Hypothesis (intraday momentum literature, e.g. Gao/Han/Li/Zhou 2018 and
Baltussen/Da/Lammers/Martens 2021): when an equity index has moved decisively
away from its cash-session open during the first hours and is trading near its
session extreme, order-flow persistence and hedging demand tend to extend the move
into the cash close. One decision per index per day, at a fixed time after the
cash open; flat before the cash close (no overnight financing, no daily break).

v0.2.0 derives daily ranges from H4 because the live gate treats a D1 frame as stale
on Mondays (last D1 closed Friday). Uses only closed candles from the supplied snapshot. Pure functions only.
"""

DECISION_DELAY = 7200      # seconds after the cash open at which the day is judged
MOVE_ATR = 0.45            # |close - session open| in daily ATRs
EXTREME_FRAC = 0.75        # close location within the session range
STOP_ATR = 0.30            # stop distance in daily ATRs
TARGET_R = 2.2             # planned reward / risk
EXIT_BEFORE_CLOSE = 900    # flat 15 minutes before the cash close

# Cash session (local minutes after midnight) and DST zone per instrument.
SESSIONS = {'NAS100': ('US', 570, 960), 'US500': ('US', 570, 960), 'GER40': ('EU', 540, 1050)}


def days_from_civil(y, m, d):
    y = y - 1 if m <= 2 else y
    era = (y if y >= 0 else y - 399) // 400
    yoe = y - era * 400
    doy = (153 * (m + (-3 if m > 2 else 9)) + 2) // 5 + d - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def civil_from_days(z):
    z += 719468
    era = (z if z >= 0 else z - 146096) // 146097
    doe = z - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    y = yoe + era * 400
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    d = doy - (153 * mp + 2) // 5 + 1
    m = mp + 3 if mp < 10 else mp - 9
    return (y + 1 if m <= 2 else y), m, d


def weekday(days):
    return (days + 4) % 7  # 0 = Sunday


def nth_sunday(y, m, n):
    first = days_from_civil(y, m, 1)
    return first + (7 - weekday(first)) % 7 + 7 * (n - 1)


def last_sunday(y, m):
    nxt = days_from_civil(y + (m == 12), m % 12 + 1, 1) - 1
    return nxt - weekday(nxt)


def utc_offset(zone, t):
    """Local standard/daylight offset in seconds for US Eastern or Central Europe."""
    y = civil_from_days(t // 86400)[0]
    if zone == 'US':
        start = nth_sunday(y, 3, 2) * 86400 + 7 * 3600
        end = nth_sunday(y, 11, 1) * 86400 + 6 * 3600
        return -4 * 3600 if start <= t < end else -5 * 3600
    start = last_sunday(y, 3) * 86400 + 3600
    end = last_sunday(y, 10) * 86400 + 3600
    return 2 * 3600 if start <= t < end else 3600


def true_ranges(bars):
    out = []
    for i in range(1, len(bars)):
        b, pc = bars[i], bars[i - 1]['close']
        out.append(max(b['high'] - b['low'], abs(b['high'] - pc), abs(b['low'] - pc)))
    return out


def broker_daily(h4, before):
    """Aggregate completed H4 candles into broker days (17:00 New York roll) ending before `before`."""
    days = []
    for b in h4:
        if b['utc'] + 14400 > before:
            break
        key = (b['utc'] + utc_offset('US', b['utc']) + 7 * 3600) // 86400
        if days and days[-1]['key'] == key:
            d = days[-1]
            d['high'] = max(d['high'], b['high'])
            d['low'] = min(d['low'], b['low'])
            d['close'] = b['close']
        else:
            days.append({'key': key, 'high': b['high'], 'low': b['low'], 'close': b['close']})
    if days and days[-1]['key'] == (before + utc_offset('US', before) + 7 * 3600) // 86400:
        days.pop()  # the broker day containing `before` is not complete
    return days


def detect(snapshot):
    symbol = snapshot['symbol']
    if symbol not in SESSIONS:
        return []
    zone, open_min, close_min = SESSIONS[symbol]
    bars = snapshot['frames'].get('M15', ())
    h4 = snapshot['frames'].get('H4', ())
    if len(bars) < 40 or len(h4) < 60:
        return []
    now = bars[-1]['utc'] + 900  # decision time = close of the last completed candle
    offset = utc_offset(zone, now)
    local_day = (now + offset) // 86400
    if weekday(local_day) in (0, 6):
        return []
    session_open = local_day * 86400 + open_min * 60 - offset
    session_close = local_day * 86400 + close_min * 60 - offset
    if now != session_open + DECISION_DELAY:
        return []
    session = [b for b in bars if session_open <= b['utc'] < now]
    if len(session) != DECISION_DELAY // 900 or session[0]['utc'] != session_open:
        return []  # incomplete cash-session history: do not guess
    # Daily ATR from completed broker days (built from H4, v0.2.0) before today's session.
    prior_days = broker_daily(h4, session_open)
    if len(prior_days) < 15:
        return []
    trs = true_ranges(prior_days[-15:])
    atr_d = sum(trs) / len(trs)
    m15_tr = true_ranges(bars[-15:])
    atr_m15 = sum(m15_tr) / len(m15_tr)
    if atr_d <= 0 or atr_m15 <= 0:
        return []
    open_price = session[0]['open']
    hi = max(b['high'] for b in session)
    lo = min(b['low'] for b in session)
    last = session[-1]['close']
    rng = hi - lo
    if rng <= 0:
        return []
    location = (last - lo) / rng
    move = last - open_price
    direction = None
    if move >= MOVE_ATR * atr_d and location >= EXTREME_FRAC:
        direction = 'LONG'
    elif -move >= MOVE_ATR * atr_d and location <= 1 - EXTREME_FRAC:
        direction = 'SHORT'
    if direction is None:
        return []
    quote = snapshot['quote']
    long = direction == 'LONG'
    entry = quote['ask'] if long else quote['bid']
    risk = STOP_ATR * atr_d
    stop = entry - risk if long else entry + risk
    target = entry + TARGET_R * risk if long else entry - TARGET_R * risk
    horizon = session_close - EXIT_BEFORE_CLOSE - now
    if horizon < 3600:
        return []
    return [{'direction': direction, 'stop_loss': stop, 'take_profit': target, 'horizon_seconds': horizon,
             'atr': atr_m15,
             'rationale': 'Cash-session trend day: %.2f daily ATR from the open after %d minutes, closing in the outer quarter of the session range; flat before the cash close.' % (abs(move) / atr_d, DECISION_DELAY // 60)}]
