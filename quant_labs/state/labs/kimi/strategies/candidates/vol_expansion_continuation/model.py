"""Candidate: Volatility Expansion Continuation - screening version.

Phase-2 inversion test: the same M15 climax detection as vol_exhaustion_fade is
entered in the CLIMAX direction (not faded). Failure analysis showed fades of
these bars were run over within 18 hours in ~75% of cases; if the extreme is a
liquidity event that fuels continuation, entering with the move and using the
extreme as invalidation should capture the post-climax leg.
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
    if len(m15) < 60:
        return []
    bar = m15[-1]
    t = float(bar["utc"]) + 900.0
    wd = weekdayof(t)
    hour = (int(t) // 3600) % 24
    if wd == 6 or (wd == 5 and hour >= 20) or (wd == 0 and hour < 22):
        return []
    atr = atrcalc(m15, 14)
    if atr <= 0.0:
        return []
    rng = float(bar["high"]) - float(bar["low"])
    if rng < 1.6 * atr or len(m15) < 22:
        return []
    vols = []
    for b in m15[-21:-1]:
        vols.append(float(b["tick_volume"]))
    vmed = median(vols)
    if float(bar["tick_volume"]) < 1.5 * vmed:
        return []
    base = float(m15[-7]["open"])
    entryref = float(bar["close"])
    hh20 = None
    ll20 = None
    for b in m15[-21:-1]:
        if hh20 is None:
            hh20 = float(b["high"])
            ll20 = float(b["low"])
        else:
            hh20 = max(hh20, float(b["high"]))
            ll20 = min(ll20, float(b["low"]))
    out = []
    horizon = 24 * 3600
    topclose = entryref >= float(bar["high"]) - 0.25 * rng
    botclose = entryref <= float(bar["low"]) + 0.25 * rng
    if topclose and entryref > hh20 and (entryref - base) >= 1.2 * atr:
        stop = entryref - 0.5 * atr
        risk = entryref - stop
        target = entryref + 2.5 * risk
        if 0.5 * atr <= risk <= 5 * atr:
            out.append({"direction": "LONG", "stop_loss": stop, "take_profit": target,
                        "horizon_seconds": horizon, "atr": atr,
                        "rationale": "Volume climax beyond 20-bar high; continuation entry, half-ATR invalidation."})
    if botclose and entryref < ll20 and (base - entryref) >= 1.2 * atr:
        stop = entryref + 0.5 * atr
        risk = stop - entryref
        target = entryref - 2.5 * risk
        if 0.5 * atr <= risk <= 5 * atr:
            out.append({"direction": "SHORT", "stop_loss": stop, "take_profit": target,
                        "horizon_seconds": horizon, "atr": atr,
                        "rationale": "Volume climax beyond 20-bar low; continuation entry, half-ATR invalidation."})
    return out[:1]
