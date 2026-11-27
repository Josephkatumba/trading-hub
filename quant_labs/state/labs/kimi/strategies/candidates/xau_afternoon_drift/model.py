"""Candidate: XAU Afternoon Drift - screening version.

New mechanism (session time-of-day, single instrument): gold's London-morning
directional move tends to persist into the early New York afternoon
(intraday-momentum style regularity). The move from the London open to local
noon, when large enough, is carried with a structural stop and a 2R objective,
exiting before the late-US session.
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
    if lhour != 12:
        return []
    ldays = int(lt) // 86400
    if (ldays + 4) % 7 >= 5:
        return []
    atr = atrcalc(m15, 14)
    if atr <= 0.0:
        return []
    lday0 = float(int(lt) - int(lt) % 86400)
    open7 = None
    close12 = float(bar["close"])
    for b in m15:
        lc = float(b["utc"]) + 900.0 + off * 3600.0
        if lday0 + 25200.0 <= lc <= lday0 + 43200.0 and lc <= lt:
            if open7 is None:
                open7 = float(b["open"])
            if lc == lt:
                close12 = float(b["close"])
    if open7 is None:
        return []
    move = close12 - open7
    if abs(move) < 0.8 * atr:
        return []
    entryref = close12
    out = []
    horizon = 9 * 3600
    if move > 0:
        stop = min(float(bar["low"]) - 0.1 * atr, entryref - 0.5 * atr)
        risk = entryref - stop
        target = entryref + 2.0 * risk
        if 0.5 * atr <= risk <= 5 * atr:
            out.append({"direction": "LONG", "stop_loss": stop, "take_profit": target,
                        "horizon_seconds": horizon, "atr": atr,
                        "rationale": "Gold London-morning up-move persistence into the US afternoon."})
    else:
        stop = max(float(bar["high"]) + 0.1 * atr, entryref + 0.5 * atr)
        risk = stop - entryref
        target = entryref - 2.0 * risk
        if 0.5 * atr <= risk <= 5 * atr:
            out.append({"direction": "SHORT", "stop_loss": stop, "take_profit": target,
                        "horizon_seconds": horizon, "atr": atr,
                        "rationale": "Gold London-morning down-move persistence into the US afternoon."})
    return out[:1]
