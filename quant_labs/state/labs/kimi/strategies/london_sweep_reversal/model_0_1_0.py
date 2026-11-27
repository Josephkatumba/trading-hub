"""London Sweep Reversal 0.1.0 - Kimi Quant Lab.

Family: session liquidity sweep reversal (time-of-day mechanism).

Hypothesis: during the London open (07:00-09:00 UTC bar closes), price frequently
sweeps the Asian session range boundary to trigger resting stops, then closes back
inside the range. Fading that sweep toward the opposite Asian boundary offers an
asymmetric payoff because the sweep extreme is a structural invalidation level and
the opposite boundary is an objective liquidity target.

Pure detect(snapshot) per the live provider contract. Only completed bars in the
snapshot are used. No imports beyond math/statistics; no I/O; deterministic.
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
    hour = (int(t) // 3600) % 24
    if hour < 7 or hour > 9:
        return []
    wd = weekdayof(t)
    if wd == 5 or wd == 6:
        return []
    atr = atrcalc(m15, 14)
    if atr <= 0.0:
        return []
    day0 = float(int(t) - int(t) % 86400)
    asianhi = None
    asianlo = None
    nb = 0
    for b in m15:
        c = float(b["utc"]) + 900.0
        if float(b["utc"]) >= day0 and c <= day0 + 21600.0:
            if asianhi is None:
                asianhi = float(b["high"])
                asianlo = float(b["low"])
            else:
                asianhi = max(asianhi, float(b["high"]))
                asianlo = min(asianlo, float(b["low"]))
            nb += 1
    if nb < 20 or asianhi is None:
        return []
    arng = asianhi - asianlo
    if arng <= 0.0 or arng > 4.0 * atr:
        return []
    # one sweep fade per day: if an earlier bar today already swept, stand down
    for i in range(len(m15) - 1):
        b = m15[i]
        c = float(b["utc"]) + 900.0
        if c < day0 + 21600.0:
            continue
        if c >= t:
            break
        if float(b["low"]) < asianlo - 0.05 * atr and float(b["close"]) > asianlo:
            return []
        if float(b["high"]) > asianhi + 0.05 * atr and float(b["close"]) < asianhi:
            return []
    rng = float(bar["high"]) - float(bar["low"])
    if rng <= 0.0:
        return []
    entryref = float(bar["close"])
    longsig = (float(bar["low"]) < asianlo - 0.05 * atr
               and entryref > asianlo
               and (entryref - float(bar["low"])) >= 0.5 * rng)
    shortsig = (float(bar["high"]) > asianhi + 0.05 * atr
                and entryref < asianhi
                and (float(bar["high"]) - entryref) >= 0.5 * rng)
    out = []
    horizon = 18 * 3600
    if longsig:
        stop = float(bar["low"]) - 0.15 * atr
        target = asianhi
        risk = entryref - stop
        reward = target - entryref
        if risk >= 0.6 * atr and reward / risk >= 2.0:
            out.append({
                "direction": "LONG",
                "stop_loss": stop,
                "take_profit": target,
                "horizon_seconds": horizon,
                "atr": atr,
                "rationale": "London sweep of Asian low; close back inside range; fade to Asian high.",
            })
    if shortsig:
        stop = float(bar["high"]) + 0.15 * atr
        target = asianlo
        risk = stop - entryref
        reward = entryref - target
        if risk >= 0.6 * atr and reward / risk >= 2.0:
            out.append({
                "direction": "SHORT",
                "stop_loss": stop,
                "take_profit": target,
                "horizon_seconds": horizon,
                "atr": atr,
                "rationale": "London sweep of Asian high; close back inside range; fade to Asian low.",
            })
    return out[:1]
