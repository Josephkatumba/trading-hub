"""Claude-authored experimental model: Index Opening-Gap Fade. No verified edge.

Hypothesis: large overnight gaps in equity indices are partly liquidity-driven
(thin overnight CFD/futures trading) and tend to be retraced towards the prior
cash close once the cash session opens and full liquidity arrives. To avoid
fading genuine information gaps, entry requires that the first cash-session M15
candle already moves against the gap. Target is the full gap fill (prior cash
close); stop beyond the first candle's extreme. Flat before the cash close.

Uses only closed candles from the supplied snapshot. Pure functions only.
"""

MIN_GAP_ATR = 0.5          # |cash open - prior cash close| in daily ATRs
MAX_GAP_ATR = 2.0          # ignore extreme event gaps
STOP_BUFFER_ATR = 0.05
MIN_RR = 2.0
EXIT_BEFORE_CLOSE = 900
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


def previous_weekday(day):
    day -= 1
    while weekday(day) in (0, 6):
        day -= 1
    return day


def detect(snapshot):
    symbol = snapshot['symbol']
    if symbol not in SESSIONS:
        return []
    zone, open_min, close_min = SESSIONS[symbol]
    bars = snapshot['frames'].get('M15', ())
    daily = snapshot['frames'].get('D1', ())
    if len(bars) < 40 or len(daily) < 16:
        return []
    now = bars[-1]['utc'] + 900
    offset = utc_offset(zone, now)
    local_day = (now + offset) // 86400
    if weekday(local_day) in (0, 6):
        return []
    session_open = local_day * 86400 + open_min * 60 - offset
    session_close = local_day * 86400 + close_min * 60 - offset
    first = bars[-1]
    if now != session_open + 900 or first['utc'] != session_open:
        return []
    prev_day = previous_weekday(local_day)
    prev_offset = utc_offset(zone, prev_day * 86400 + 43200)
    prev_close_at = prev_day * 86400 + close_min * 60 - prev_offset
    prior = [b for b in bars if b['utc'] + 900 == prev_close_at]
    if not prior:
        return []  # prior cash close not in the supplied history (holiday/gap): do not guess
    prev_close = prior[0]['close']
    prior_days = [d for d in daily if d['utc'] + 86400 <= session_open]
    if len(prior_days) < 15:
        return []
    trs = true_ranges(prior_days[-15:])
    atr_d = sum(trs) / len(trs)
    m15_tr = true_ranges(bars[-15:])
    atr_m15 = sum(m15_tr) / len(m15_tr)
    if atr_d <= 0 or atr_m15 <= 0:
        return []
    gap = first['open'] - prev_close
    if not MIN_GAP_ATR * atr_d <= abs(gap) <= MAX_GAP_ATR * atr_d:
        return []
    quote = snapshot['quote']
    if gap > 0 and first['close'] < first['open']:
        direction, entry = 'SHORT', quote['bid']
        stop = first['high'] + STOP_BUFFER_ATR * atr_d
        risk, reward = stop - entry, entry - prev_close
    elif gap < 0 and first['close'] > first['open']:
        direction, entry = 'LONG', quote['ask']
        stop = first['low'] - STOP_BUFFER_ATR * atr_d
        risk, reward = entry - stop, prev_close - entry
    else:
        return []
    if risk <= 0 or reward < MIN_RR * risk:
        return []
    horizon = session_close - EXIT_BEFORE_CLOSE - now
    if horizon < 3600:
        return []
    return [{'direction': direction, 'stop_loss': stop, 'take_profit': prev_close, 'horizon_seconds': horizon,
             'atr': atr_m15,
             'rationale': 'Opening gap of %.2f daily ATR rejected by the first cash candle; target the prior cash close (%.1fR), stop beyond the first candle.' % (abs(gap) / atr_d, reward / risk)}]
