"""Volatility Exhaustion Fade 0.2.0 - Kimi Quant Lab.

Family: volatility-climax mean reversion (volatility-behavior mechanism).

Changes from 0.1.0 (pre-registered motivations, not outcome-fitted):
  * H1 efficiency-ratio regime cap tightened 0.35 -> 0.28 (fewer trend fades).
  * Tick-volume confirmation raised 1.3x -> 1.6x median (climax quality).
  * Time horizon reduced 24h -> 18h (faster mean reversion assumption).

Hypothesis: in a non-trending H1 regime, an M15 bar that expands beyond 1.6x ATR
on elevated tick volume and closes at the extreme of its range, breaking the
prior 20-bar extreme after an extended 6-bar run, marks short-term exhaustion;
fading the climax back toward the recent mean profits when range-bound drift
dominates and the climax extreme is structural invalidation.

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
    if len(m15) < 60 or len(h1) < 12:
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
    net = abs(float(h1[-1]["close"]) - float(h1[-11]["close"]))
    path = 0.0
    for i in range(len(h1) - 10, len(h1)):
        path += abs(float(h1[i]["close"]) - float(h1[i - 1]["close"]))
    er = net / path if path > 0.0 else 1.0
    if er > 0.28:
        return []
    rng = float(bar["high"]) - float(bar["low"])
    if rng < 1.6 * atr:
        return []
    if len(m15) < 22:
        return []
    vols = []
    for b in m15[-21:-1]:
        vols.append(float(b["tick_volume"]))
    vmed = median(vols)
    if float(bar["tick_volume"]) < 1.6 * vmed:
        return []
    base = float(m15[-7]["open"])
    entryref = float(bar["close"])
    upmove = entryref - base
    dnmove = base - entryref
    hh20 = None
    ll20 = None
    for b in m15[-21:-1]:
        if hh20 is None:
            hh20 = float(b["high"])
            ll20 = float(b["low"])
        else:
            hh20 = max(hh20, float(b["high"]))
            ll20 = min(ll20, float(b["low"]))
    mean12 = 0.0
    for b in m15[-13:-1]:
        mean12 += float(b["close"])
    mean12 /= 12.0
    out = []
    horizon = 18 * 3600
    topclose = entryref >= float(bar["high"]) - 0.2 * rng
    botclose = entryref <= float(bar["low"]) + 0.2 * rng
    if topclose and entryref > hh20 and upmove >= 1.2 * atr:
        stop = float(bar["high"]) + 0.15 * atr
        risk = stop - entryref
        target = mean12 if mean12 < entryref else entryref - 2.2 * risk
        reward = entryref - target
        if risk >= 0.6 * atr and reward / risk >= 2.0:
            out.append({
                "direction": "SHORT",
                "stop_loss": stop,
                "take_profit": target,
                "horizon_seconds": horizon,
                "atr": atr,
                "rationale": "Range-regime volatility climax at 20-bar high on 1.6x volume; fade to mean.",
            })
    if botclose and entryref < ll20 and dnmove >= 1.2 * atr:
        stop = float(bar["low"]) - 0.15 * atr
        risk = entryref - stop
        target = mean12 if mean12 > entryref else entryref + 2.2 * risk
        reward = target - entryref
        if risk >= 0.6 * atr and reward / risk >= 2.0:
            out.append({
                "direction": "LONG",
                "stop_loss": stop,
                "take_profit": target,
                "horizon_seconds": horizon,
                "atr": atr,
                "rationale": "Range-regime volatility climax at 20-bar low on 1.6x volume; fade to mean.",
            })
    return out[:1]
