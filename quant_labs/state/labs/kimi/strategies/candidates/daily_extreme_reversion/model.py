"""Candidate: Daily Extreme Failed Auction - screening version.

New mechanism (higher-timeframe liquidity): a sweep of the prior day's high or
low that closes back inside the prior day's range rejects the auction at that
extreme; price then rotates back through the daily range. The sweep extreme is
structural invalidation; the opposite daily boundary (or 2R) is the objective.
"""

import math


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
    d1 = frames.get("D1", [])
    if len(m15) < 60 or len(d1) < 3:
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
    prior = d1[-2]
    pdh = float(prior["high"])
    pdl = float(prior["low"])
    day0 = float(int(t) - int(t) % 86400)
    rng = float(bar["high"]) - float(bar["low"])
    if rng <= 0.0:
        return []
    entryref = float(bar["close"])
    out = []
    horizon = 24 * 3600
    upsweep = float(bar["high"]) > pdh + 0.05 * atr and entryref < pdh and (float(bar["high"]) - entryref) >= 0.25 * atr
    dnsweep = float(bar["low"]) < pdl - 0.05 * atr and entryref > pdl and (entryref - float(bar["low"])) >= 0.25 * atr
    if upsweep:
        used = False
        for b in m15[:-1]:
            c = float(b["utc"]) + 900.0
            if c < day0:
                continue
            if c >= t:
                break
            if float(b["high"]) > pdh and float(b["close"]) < pdh:
                used = True
                break
        if not used:
            stop = float(bar["high"]) + 0.25 * atr
            risk = stop - entryref
            target = pdl if (entryref - pdl) / max(risk, 1e-12) >= 2.0 else entryref - 2.0 * risk
            if risk >= 0.5 * atr and (entryref - target) / risk >= 2.0:
                out.append({"direction": "SHORT", "stop_loss": stop, "take_profit": target,
                            "horizon_seconds": horizon, "atr": atr,
                            "rationale": "Sweep of prior day high rejected; rotate through the daily range."})
    if dnsweep:
        used = False
        for b in m15[:-1]:
            c = float(b["utc"]) + 900.0
            if c < day0:
                continue
            if c >= t:
                break
            if float(b["low"]) < pdl and float(b["close"]) > pdl:
                used = True
                break
        if not used:
            stop = float(bar["low"]) - 0.25 * atr
            risk = entryref - stop
            target = pdh if (pdh - entryref) / max(risk, 1e-12) >= 2.0 else entryref + 2.0 * risk
            if risk >= 0.5 * atr and (target - entryref) / risk >= 2.0:
                out.append({"direction": "LONG", "stop_loss": stop, "take_profit": target,
                            "horizon_seconds": horizon, "atr": atr,
                            "rationale": "Sweep of prior day low rejected; rotate through the daily range."})
    return out[:1]
