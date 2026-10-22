"""Opening Range Drive 0.1.0 - Kimi Quant Lab.

Family: opening-range breakout with tick-volume confirmation (microstructure
confirmation mechanism).

Hypothesis: when the first hour of the London session (07:00-08:00 UTC) builds a
tight opening range, a later M15 close beyond that range on clearly elevated tick
volume and a decisive body, with the last H1 bar aligned, signals genuine
participation rather than noise. The breakout then tends to travel multiples of
the measured range. The opening-range midpoint (or an ATR floor) is structural
invalidation; the target is a planned 2.5R extension.

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


def weekdayof(t):
    return ((int(t) // 86400) + 4) % 7


def detect(snapshot):
    frames = snapshot.get("frames", {})
    m15 = frames.get("M15", [])
    h1 = frames.get("H1", [])
    if len(m15) < 60 or len(h1) < 2:
        return []
    bar = m15[-1]
    t = float(bar["utc"]) + 900.0
    hour = (int(t) // 3600) % 24
    if hour < 8 or hour > 11:
        return []
    wd = weekdayof(t)
    if wd == 5 or wd == 6:
        return []
    atr = atrcalc(m15, 14)
    if atr <= 0.0:
        return []
    day0 = float(int(t) - int(t) % 86400)
    orhi = None
    orlo = None
    nb = 0
    for b in m15:
        u = float(b["utc"])
        if u >= day0 + 25200.0 and u + 900.0 <= day0 + 28800.0:
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
    if orw <= 0.0 or orw > 3.0 * atr:
        return []
    # one trigger per day per direction
    for i in range(len(m15) - 1):
        b = m15[i]
        c = float(b["utc"]) + 900.0
        if c < day0 + 28800.0:
            continue
        if c >= t:
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
    if float(bar["tick_volume"]) < 1.4 * vmed:
        return []
    body = abs(float(bar["close"]) - float(bar["open"]))
    if body < 0.35 * atr:
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
                "rationale": "Tight London opening range broken on elevated tick volume with H1 agreement; drive continuation.",
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
                "rationale": "Tight London opening range broken on elevated tick volume with H1 agreement; drive continuation.",
            })
    return out[:1]
