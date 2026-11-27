"""Claude-authored experimental model: Index Turn-of-Month Intraday Drift. No verified edge.

Hypothesis (calendar anomaly; Lakonishok & Smidt 1988, McConnell & Xu 2008):
equity-index returns concentrate around the turn of the month (last trading day
and first three trading days), attributed to pension/payroll inflows and
month-end rebalancing. Captured intraday only: long from shortly after the cash
open to before the cash close, so no overnight financing or daily-break exposure.

Weekday-based calendar only (exchange holidays are not known to the model).
Uses only closed candles from the supplied snapshot. Pure functions only.
"""

ENTRY_DELAY = 900          # decide at the close of the first cash-session M15 candle
STOP_ATR = 0.35            # stop distance in daily ATRs
TARGET_R = 2.2
EXIT_BEFORE_CLOSE = 900
FIRST_DAYS = 3             # first N weekdays of the month
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


def turn_of_month(local_day):
    """True on the last weekday of a month or one of its first FIRST_DAYS weekdays."""
    y, m, d = civil_from_days(local_day)
    nxt = local_day + 1
    while weekday(nxt) in (0, 6):
        nxt += 1
    if civil_from_days(nxt)[1] != m:
        return True
    count = 0
    day = days_from_civil(y, m, 1)
    while day <= local_day:
        if weekday(day) not in (0, 6):
            count += 1
        day += 1
    return count <= FIRST_DAYS


def detect(snapshot):
    symbol = snapshot['symbol']
    if symbol not in SESSIONS:
        return []
    zone, open_min, close_min = SESSIONS[symbol]
    bars = snapshot['frames'].get('M15', ())
    daily = snapshot['frames'].get('D1', ())
    if len(bars) < 16 or len(daily) < 16:
        return []
    now = bars[-1]['utc'] + 900
    offset = utc_offset(zone, now)
    local_day = (now + offset) // 86400
    if weekday(local_day) in (0, 6) or not turn_of_month(local_day):
        return []
    session_open = local_day * 86400 + open_min * 60 - offset
    session_close = local_day * 86400 + close_min * 60 - offset
    if now != session_open + ENTRY_DELAY or bars[-1]['utc'] != session_open:
        return []
    prior_days = [d for d in daily if d['utc'] + 86400 <= session_open]
    if len(prior_days) < 15:
        return []
    trs = true_ranges(prior_days[-15:])
    atr_d = sum(trs) / len(trs)
    m15_tr = true_ranges(bars[-15:])
    atr_m15 = sum(m15_tr) / len(m15_tr)
    if atr_d <= 0 or atr_m15 <= 0:
        return []
    entry = snapshot['quote']['ask']
    risk = STOP_ATR * atr_d
    horizon = session_close - EXIT_BEFORE_CLOSE - now
    if horizon < 3600:
        return []
    return [{'direction': 'LONG', 'stop_loss': entry - risk, 'take_profit': entry + TARGET_R * risk,
             'horizon_seconds': horizon, 'atr': atr_m15,
             'rationale': 'Turn-of-month session (last or first three weekdays): long after the first cash-session candle, 0.35 daily-ATR stop, flat before the cash close.'}]
