"""Candidate: Asian Range Drive (sweep continuation) - screening version.

Phase-2 inversion test: after the London open, a decisive close BEYOND the Asian
range (not a sweep-and-reclaim) is entered in the continuation direction, with
the Asian extreme as structural invalidation. Motivated by the failure analysis
of london_sweep_reversal, where fades of the same event were stopped beyond the
extreme ~75% of the time within 18 hours.
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
    if lhour < 7 or lhour > 10:
        return []
    ldays = int(lt) // 86400
    if (ldays + 4) % 7 >= 5:
        return []
    atr = atrcalc(m15, 14)
    if atr <= 0.0:
        return []
    day0 = float(int(t) - int(t) % 86400)
    ahi = None
    alo = None
    nb = 0
    for b in m15:
        c = float(b["utc"]) + 900.0
        if float(b["utc"]) >= day0 and c <= day0 + 21600.0:
            if ahi is None:
                ahi = float(b["high"])
                alo = float(b["low"])
            else:
                ahi = max(ahi, float(b["high"]))
                alo = min(alo, float(b["low"]))
            nb += 1
    if nb < 20 or ahi is None:
        return []
    arng = ahi - alo
    if arng <= 0.0 or arng > 4.0 * atr:
        return []
    # one drive per day
    for i in range(len(m15) - 1):
        b = m15[i]
        c = float(b["utc"]) + 900.0
        if c < day0 + 21600.0:
            continue
        if c >= t:
            break
        if float(b["close"]) > ahi + 0.1 * atr or float(b["close"]) < alo - 0.1 * atr:
            return []
    rng = float(bar["high"]) - float(bar["low"])
    if rng <= 0.0:
        return []
    entryref = float(bar["close"])
    vols = []
    for b in m15[-21:-1]:
        vols.append(float(b["tick_volume"]))
    vmed = median(vols)
    longsig = (entryref > ahi + 0.5 * atr and (entryref - float(bar["low"])) >= 0.6 * rng
               and float(bar["tick_volume"]) >= 1.3 * vmed)
    shortsig = (entryref < alo - 0.5 * atr and (float(bar["high"]) - entryref) >= 0.6 * rng
                and float(bar["tick_volume"]) >= 1.3 * vmed)
    out = []
    horizon = 18 * 3600
    if longsig:
        stop = ahi - 0.15 * atr
        risk = entryref - stop
        target = entryref + 2.0 * risk
        if 0.6 * atr <= risk <= 5 * atr:
            out.append({"direction": "LONG", "stop_loss": stop, "take_profit": target,
                        "horizon_seconds": horizon, "atr": atr,
                        "rationale": "Decisive London close beyond Asian high; continuation drive."})
    if shortsig:
        stop = alo + 0.15 * atr
        risk = stop - entryref
        target = entryref - 2.0 * risk
        if 0.6 * atr <= risk <= 5 * atr:
            out.append({"direction": "SHORT", "stop_loss": stop, "take_profit": target,
                        "horizon_seconds": horizon, "atr": atr,
                        "rationale": "Decisive London close beyond Asian low; continuation drive."})
    return out[:1]
