"""Candidate: H1 Momentum Persistence - screening version.

New mechanism (trend persistence): an H1 bar closing decisively beyond its
prior 20-hour extreme on elevated tick volume is entered in the momentum
direction at the next hour's open; the signal bar extreme is invalidation.
Higher timeframe than the failed M15 families to reduce noise-sensitivity.
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
    h1 = frames.get("H1", [])
    if len(h1) < 40:
        return []
    bar = h1[-1]
    t = float(bar["utc"]) + 3600.0
    if int(t) % 3600 != 0:
        return []
    wd = weekdayof(t)
    hour = (int(t) // 3600) % 24
    if wd == 6 or (wd == 5 and hour >= 20) or (wd == 0 and hour < 22):
        return []
    atr = atrcalc(h1, 14)
    if atr <= 0.0:
        return []
    rng = float(bar["high"]) - float(bar["low"])
    if rng <= 0.0 or rng < 0.8 * atr or len(h1) < 24:
        return []
    vols = []
    for b in h1[-21:-1]:
        vols.append(float(b["tick_volume"]))
    vmed = median(vols)
    if float(bar["tick_volume"]) < 1.3 * vmed:
        return []
    hh20 = None
    ll20 = None
    for b in h1[-21:-1]:
        if hh20 is None:
            hh20 = float(b["high"])
            ll20 = float(b["low"])
        else:
            hh20 = max(hh20, float(b["high"]))
            ll20 = min(ll20, float(b["low"]))
    entryref = float(bar["close"])
    body = abs(entryref - float(bar["open"]))
    if body < 0.55 * rng:
        return []
    out = []
    horizon = 24 * 3600
    if entryref > hh20:
        stop = float(bar["low"]) - 0.1 * atr
        risk = entryref - stop
        target = entryref + 2.0 * risk
        if 0.5 * atr <= risk <= 5 * atr:
            out.append({"direction": "LONG", "stop_loss": stop, "take_profit": target,
                        "horizon_seconds": horizon, "atr": atr,
                        "rationale": "Decisive H1 close beyond 20-hour high on volume; momentum persistence."})
    if entryref < ll20:
        stop = float(bar["high"]) + 0.1 * atr
        risk = stop - entryref
        target = entryref - 2.0 * risk
        if 0.5 * atr <= risk <= 5 * atr:
            out.append({"direction": "SHORT", "stop_loss": stop, "take_profit": target,
                        "horizon_seconds": horizon, "atr": atr,
                        "rationale": "Decisive H1 close beyond 20-hour low on volume; momentum persistence."})
    return out[:1]
