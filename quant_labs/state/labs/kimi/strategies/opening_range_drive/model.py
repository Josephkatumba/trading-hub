"""Opening Range Drive 0.2.0 - Kimi Quant Lab.

Family: opening-range breakout with tick-volume confirmation (microstructure
confirmation mechanism).

Changes from 0.1.0 (pre-registered motivations, not outcome-fitted):
  * London session windows are DST-aware (approximate Europe/London clock time;
    0.1.0 used fixed UTC and was one hour late in summer).
  * Tick-volume confirmation raised 1.4x -> 1.8x median.
  * Opening-range width cap tightened 3.0 -> 2.5 ATR and body requirement
    raised 0.35 -> 0.4 ATR (higher-quality compressions only).

Hypothesis: when the first hour of the London session builds a tight opening
range, a later M15 close beyond that range on clearly elevated tick volume and
a decisive body, with the last H1 bar aligned, signals genuine participation
rather than noise; the breakout then travels multiples of the measured range.
The opening-range midpoint (or an ATR floor) is structural invalidation.

Pure detect(snapshot) per the live provider contract. Only completed bars.
No imports beyond math/statistics; no I/O; deterministic.
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
    h1 = frames.get("H1", [])
    if len(m15) < 60 or len(h1) < 2:
        return []
    bar = m15[-1]
    t = float(bar["utc"]) + 900.0
    off = londonoffset(t)
    lt = t + off * 3600.0
    lhour = (int(lt) // 3600) % 24
    if lhour < 8 or lhour > 11:
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
    if orw <= 0.0 or orw > 2.5 * atr:
        return []
    for i in range(len(m15) - 1):
        b = m15[i]
        lc = float(b["utc"]) + 900.0 + off * 3600.0
        if lc < lday0 + 28800.0:
            continue
        if lc >= lt:
            break
        if float(b["close"]) > orhi or float(b["close"]) < orlo:
            return []
    rng = float(bar["high"]) - float(bar["low"])
    if rng <= 0.0:
        return []
    vols = []
    for b in m15[-21:-1]:
        vols.append(float(b["tick_volume"]))
    vmed = median(vols)
    if float(bar["tick_volume"]) < 1.8 * vmed:
        return []
    body = abs(float(bar["close"]) - float(bar["open"]))
    if body < 0.4 * atr:
        return []
    entryref = float(bar["close"])
    ormid = (orhi + orlo) / 2.0
    h1up = float(h1[-1]["close"]) >= float(h1[-1]["open"])
    h1dn = float(h1[-1]["close"]) <= float(h1[-1]["open"])
    out = []
    horizon = 12 * 3600
    longsig = (entryref > orhi and (entryref - float(bar["low"])) >= 0.7 * rng and h1up)
    shortsig = (entryref < orlo and (float(bar["high"]) - entryref) >= 0.7 * rng and h1dn)
    if longsig:
        stop = ormid if (entryref - ormid) >= 0.6 * atr else entryref - 0.8 * atr
        risk = entryref - stop
        target = entryref + 2.5 * risk
        if risk >= 0.6 * atr and target > entryref:
            out.append({
                "direction": "LONG",
                "stop_loss": stop,
                "take_profit": target,
                "horizon_seconds": horizon,
                "atr": atr,
                "rationale": "DST-aware tight London opening range broken on 1.8x volume with H1 agreement.",
            })
    if shortsig:
        stop = ormid if (ormid - entryref) >= 0.6 * atr else entryref + 0.8 * atr
        risk = stop - entryref
        target = entryref - 2.5 * risk
        if risk >= 0.6 * atr and target < entryref:
            out.append({
                "direction": "SHORT",
                "stop_loss": stop,
                "take_profit": target,
                "horizon_seconds": horizon,
                "atr": atr,
                "rationale": "DST-aware tight London opening range broken on 1.8x volume with H1 agreement.",
            })
    return out[:1]
