"""Deterministic synthetic markets for the Support & Resistance tests.

Prices follow piecewise-linear close paths; each bar opens 10% of the way from
the previous close (so adjacent extremes are never tied) and carries a fixed
wick. Levels are therefore known exactly: a range between 100 and 110 produces
repeated swing lows just under 100 and swing highs just over 110.
"""
from __future__ import annotations

M15_SECONDS, H1_SECONDS = 900.0, 3600.0


def path(*points: tuple[float, int]) -> list[float]:
    """Closes moving linearly: path((100, 0), (110, 10)) = 100 then 10 steps to 110."""
    closes = [float(points[0][0])]
    for value, steps in points[1:]:
        start = closes[-1]
        closes.extend(start + (value - start) * (i + 1) / steps for i in range(steps))
    return closes


def zigzag(low: float, high: float, legs: int, steps: int, start_high: bool = False) -> list[tuple[float, int]]:
    points = []
    for leg in range(legs):
        up = (leg % 2 == 0) != start_high
        points.append((high if up else low, steps))
    return points


def bars(closes: list[float], wick: float, step_seconds: float, start: float = 1_790_000_000.0) -> list[dict]:
    rows, previous = [], closes[0]
    for index, close in enumerate(closes):
        open_ = previous + (close - previous) * 0.1
        rows.append({"time": start + index * step_seconds, "open": open_, "high": max(open_, close) + wick,
                     "low": min(open_, close) - wick, "close": close, "tick_volume": 100 + index % 17})
        previous = close
    return rows


def candle(time: float, open_: float, high: float, low: float, close: float) -> dict:
    return {"time": time, "open": open_, "high": high, "low": low, "close": close, "tick_volume": 150}


def scaled(rows: list[dict], factor: float) -> list[dict]:
    return [{**row, **{key: row[key] * factor for key in ("open", "high", "low", "close")}} for row in rows]


def range_m15(bars_count: int = 280) -> list[dict]:
    """M15 range between 100 and 110 (period 20 bars), ending on the way down near 104."""
    closes = path((105.0, 0), (110.0, 5), *zigzag(100.0, 110.0, 40, 10, start_high=True))
    return bars(closes[:bars_count], 0.2, M15_SECONDS)


def range_h1() -> list[dict]:
    closes = path((105.0, 0), (110.0, 3), *zigzag(100.0, 110.0, 40, 5, start_high=True))
    return bars(closes[:160], 0.4, H1_SECONDS)


def htf_bars(step_seconds: float, count: int = 120) -> list[dict]:
    closes = path((105.0, 0), (110.0, 2), *zigzag(100.0, 110.0, 60, 3, start_high=True))
    return bars(closes[:count], 0.6, step_seconds)


def support_ending(kind: str) -> list[dict]:
    """Range history, then a descent into the ~100 support and a scenario-specific finish.

    kind: "bounce" (touch + bullish rejection + momentum), "no_rejection" (touch,
    bearish close inside the zone), "failed" (closes decisively through support),
    "approach" (still above the zone), "chop" (the bounce candles after drifting at the
    level instead of approaching it)."""
    history = range_m15(260)
    last = history[-1]["close"]
    descent = path((last, 0), (100.8, 8))[1:]
    rows = history + bars(descent, 0.2, M15_SECONDS, start=history[-1]["time"] + M15_SECONDS)
    t = rows[-1]["time"] + M15_SECONDS
    if kind == "approach":
        rows[-8:] = bars(path((104.0, 0), (102.6, 7)), 0.2, M15_SECONDS, start=rows[-8]["time"])
        return rows + [candle(t, 102.5, 102.6, 102.3, 102.4)]
    if kind == "bounce":
        return rows + [candle(t, 100.6, 100.7, 99.9, 100.2),
                       candle(t + M15_SECONDS, 100.3, 101.6, 99.95, 101.5),
                       candle(t + 2 * M15_SECONDS, 101.5, 101.7, 101.4, 101.6)]
    if kind == "weak_close":
        # Momentum (a higher close) but no rejection: the close stays inside the zone.
        return rows + [candle(t, 100.6, 100.7, 99.9, 99.95),
                       candle(t + M15_SECONDS, 100.0, 100.3, 99.9, 100.05),
                       candle(t + 2 * M15_SECONDS, 100.05, 100.2, 99.95, 100.1)]
    if kind == "no_rejection":
        return rows + [candle(t, 100.6, 100.7, 99.9, 100.2),
                       candle(t + M15_SECONDS, 100.3, 100.4, 99.9, 100.0),
                       candle(t + 2 * M15_SECONDS, 100.0, 100.2, 99.9, 100.1)]
    if kind == "chop":
        # Price drifts around just above the level for hours (no approach), then the same rejection.
        chop = [100.9 if index % 2 else 100.4 for index in range(18)]
        rows = rows + bars(chop, 0.2, M15_SECONDS, start=t)
        t = rows[-1]["time"] + M15_SECONDS
        return rows + [candle(t, 100.6, 100.7, 99.9, 100.2),
                       candle(t + M15_SECONDS, 100.3, 101.6, 99.95, 101.5),
                       candle(t + 2 * M15_SECONDS, 101.5, 101.7, 101.4, 101.6)]
    if kind == "failed":
        return rows + [candle(t, 100.6, 100.7, 99.9, 100.2),
                       candle(t + M15_SECONDS, 100.1, 100.2, 98.4, 98.5),
                       candle(t + 2 * M15_SECONDS, 98.5, 98.7, 98.3, 98.6)]
    raise ValueError(kind)


def resistance_rejection() -> list[dict]:
    """Mirror of the support bounce: rally into ~110 resistance, bearish rejection."""
    history = range_m15(270)
    last = history[-1]["close"]
    ascent = path((last, 0), (109.2, 8))[1:]
    rows = history + bars(ascent, 0.2, M15_SECONDS, start=history[-1]["time"] + M15_SECONDS)
    t = rows[-1]["time"] + M15_SECONDS
    return rows + [candle(t, 109.4, 110.1, 109.3, 109.8),
                   candle(t + M15_SECONDS, 109.7, 110.05, 108.4, 108.5),
                   candle(t + 2 * M15_SECONDS, 108.5, 108.6, 108.3, 108.4)]


def break_retest() -> tuple[list[dict], list[dict]]:
    """History ranged 110-120, then 100-110; price breaks above 110, retests it and
    rejects upward: resistance turned support. Returns (M15, H1)."""
    upper = path((115.0, 0), (120.0, 5), *zigzag(110.0, 120.0, 12, 10, start_high=True))
    lower = path((110.0, 0), *zigzag(100.0, 110.0, 12, 10))
    closes = upper + lower[1:]
    rows = bars(closes, 0.2, M15_SECONDS)[-270:]
    # Breakout that clears the old resistance by more than 1 ATR(H1), then pulls back to it.
    rally = path((rows[-1]["close"], 0), (106.0, 4), (108.5, 3), (112.5, 4), (114.8, 3), (113.0, 3))[1:]
    rows = rows + bars(rally, 0.2, M15_SECONDS, start=rows[-1]["time"] + M15_SECONDS)
    t = rows[-1]["time"] + M15_SECONDS
    rows = rows + [candle(t, 112.6, 112.7, 111.2, 111.3),
                   candle(t + M15_SECONDS, 111.2, 111.4, 110.2, 110.5),
                   candle(t + 2 * M15_SECONDS, 110.6, 111.9, 110.3, 111.8),
                   candle(t + 3 * M15_SECONDS, 111.8, 111.95, 111.7, 111.9)]
    h1_upper = path((115.0, 0), (120.0, 3), *zigzag(110.0, 120.0, 20, 5, start_high=True))
    h1_lower = path((110.0, 0), *zigzag(100.0, 110.0, 12, 5))
    h1 = bars((h1_upper + h1_lower[1:])[-160:], 0.4, H1_SECONDS)
    return rows, h1
