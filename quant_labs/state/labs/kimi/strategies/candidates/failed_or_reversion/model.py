"""Candidate: Failed Opening-Range Reversion - screening version.

Phase-2 inversion test: an opening-range breakout that closes back INSIDE the
range within the London morning is faded back through the range. Failure analysis
of opening_range_drive showed ~65% of breakout entries were stopped, i.e. most
breakouts failed; this candidate monetizes the failure itself once it is
confirmed by a close back inside the range.
"""

import math
from statistics import median


def atrcalc(bars, n):
    if len(bars) < n + 1:
        return 0.0
    total = 0.0
    for i in range(len(bars) - n, len(bars)):
        b = bars[i]
        p = bars[i - 1]
        up = b["high"] - p["close"]
        dn = p["close"] - b["low"]
        rng = b["high"] - b["low"]
        total += max(rng, max(up, dn))
    return total / n


def civil(t):
    z = int(t) // 86400 + 719468
    era = z // 146097
    doe = z - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    y = yoe + era * 400
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    d = doy - (153 * mp + 2) // 5 + 1
    m = mp + 3 if mp < 10 else mp - 9
    return y + (1 if m <= 2 else 0), m, d


def dow(y, m, d):
    t = [0, 3, 2, 5, 0, 3, 5, 1, 4, 6, 2, 4]
    yy = y - (1 if m < 3 else 0)
    return (yy + yy // 4 - yy // 100 + yy // 400 + t[m - 1] + d) % 7


def lastsun(y, m):
    dim = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    d = dim[m - 1]
    if m == 2 and y % 4 == 0 and (y % 100 != 0 or y % 400 == 0):
        d = 29
    while dow(y, m, d) != 0:
        d -= 1
    return d


def londonoffset(t):
    y, m, d = civil(t)
    h = (int(t) % 86400) // 3600
    sm = lastsun(y, 3)
    so = lastsun(y, 10)
    if m == 3 and (d > sm or (d == sm and h >= 1)):
        return 1
    if m == 10 and (d < so or (d == so and h < 1)):
        return 1
    if m > 3 and m < 10:
        return 1
    return 0


def detect(snapshot):
    frames = snapshot.get("frames", {})
    m15 = frames.get("M15", [])
    if len(m15) < 60:
        return []
    bar = m15[-1]
    t = float(bar["utc"]) + 900.0
    off = londonoffset(t)
    lt = t + off * 3600.0
    lhour = (int(lt) // 3600) % 24
    if lhour < 8 or lhour > 12:
        return []
    ldays = int(lt) // 86400
    if (ldays + 4) % 7 >= 5:
        return []
    atr = atrcalc(m15, 14)
    if atr <= 0.0:
        return []
    lday0 = float(int(lt) - int(lt) % 86400)
    orhi = None
    orlo = None
    nb = 0
    for b in m15:
        lc = float(b["utc"]) + 900.0 + off * 3600.0
        if lc >= lday0 + 25200.0 and lc <= lday0 + 28800.0:
            if orhi is None:
                orhi = float(b["high"])
                orlo = float(b["low"])
            else:
                orhi = max(orhi, float(b["high"]))
                orlo = min(orlo, float(b["low"]))
            nb += 1
    if nb < 4 or orhi is None:
        return []
    orw = orhi - orlo
    if orw <= 0.0 or orw > 4.0 * atr:
        return []
    entryref = float(bar["close"])
    out = []
    horizon = 12 * 3600
    # failed upside breakout: an earlier close above ORhi, now close back inside
    brokeup = False
    brokedn = False
    for i in range(len(m15) - 1):
        b = m15[i]
        lc = float(b["utc"]) + 900.0 + off * 3600.0
        if lc < lday0 + 28800.0:
            continue
        if lc >= lt:
            break
        if float(b["close"]) > orhi:
            brokeup = True
        if float(b["close"]) < orlo:
            brokedn = True
    if brokeup and orlo < entryref < orhi:
        stop = orhi + 0.15 * atr
        risk = stop - entryref
        target = orlo if (entryref - orlo) / max(risk, 1e-12) >= 2.0 else entryref - 2.0 * risk
        if risk >= 0.3 * atr and (entryref - target) / risk >= 2.0:
            out.append({"direction": "SHORT", "stop_loss": stop, "take_profit": target,
                        "horizon_seconds": horizon, "atr": atr,
                        "rationale": "Failed London opening-range breakout; fade back through the range."})
    if brokedn and orlo < entryref < orhi:
        stop = orlo - 0.15 * atr
        risk = entryref - stop
        target = orhi if (orhi - entryref) / max(risk, 1e-12) >= 2.0 else entryref + 2.0 * risk
        if risk >= 0.3 * atr and (target - entryref) / risk >= 2.0:
            out.append({"direction": "LONG", "stop_loss": stop, "take_profit": target,
                        "horizon_seconds": horizon, "atr": atr,
                        "rationale": "Failed London opening-range breakout; fade back through the range."})
    return out[:1]
