"""London Sweep Reversal 0.2.0 - Kimi Quant Lab.

Family: session liquidity sweep reversal (time-of-day mechanism).

Changes from 0.1.0 (pre-registered motivations, not outcome-fitted):
  * London session window is DST-aware (approximate Europe/London clock time
    computed arithmetically; 0.1.0 used fixed UTC and was one hour late in
    summer, roughly half the sample).
  * Sweep depth requirement raised 0.05 -> 0.10 ATR (deeper liquidity runs
    revert more reliably) and a rejection-wick confirmation was added.
  * Asian range width cap tightened 4.0 -> 3.5 ATR.

Hypothesis: during the London open, price frequently sweeps the Asian session
range boundary to trigger resting stops, then closes back inside the range;
fading that sweep toward the opposite Asian boundary is asymmetric because the
sweep extreme is structural invalidation and the opposite boundary is an
objective liquidity target.

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
    if len(m15) < 60:
        return []
    bar = m15[-1]
    t = float(bar["utc"]) + 900.0
    off = londonoffset(t)
    lt = t + off * 3600.0
    lhour = (int(lt) // 3600) % 24
    if lhour < 7 or lhour > 9:
        return []
    ldays = int(lt) // 86400
    if (ldays + 4) % 7 >= 5:
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
    if arng <= 0.0 or arng > 3.5 * atr:
        return []
    for i in range(len(m15) - 1):
        b = m15[i]
        c = float(b["utc"]) + 900.0
        if c < day0 + 21600.0:
            continue
        if c >= t:
            break
        if float(b["low"]) < asianlo - 0.10 * atr and float(b["close"]) > asianlo:
            return []
        if float(b["high"]) > asianhi + 0.10 * atr and float(b["close"]) < asianhi:
            return []
    rng = float(bar["high"]) - float(bar["low"])
    if rng <= 0.0:
        return []
    entryref = float(bar["close"])
    longsig = (float(bar["low"]) < asianlo - 0.10 * atr
               and entryref > asianlo
               and (entryref - float(bar["low"])) >= 0.45 * rng
               and (float(bar["high"]) - entryref) <= 0.35 * rng)
    shortsig = (float(bar["high"]) > asianhi + 0.10 * atr
                and entryref < asianhi
                and (float(bar["high"]) - entryref) >= 0.45 * rng
                and (entryref - float(bar["low"])) <= 0.35 * rng)
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
                "rationale": "DST-aware London sweep of Asian low with rejection wick; fade to Asian high.",
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
                "rationale": "DST-aware London sweep of Asian high with rejection wick; fade to Asian low.",
            })
    return out[:1]
