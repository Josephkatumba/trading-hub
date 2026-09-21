from __future__ import annotations

from math import inf
from typing import Any


def _atr(rows: list[Any], period: int = 14) -> float:
    if len(rows) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(rows)):
        high = float(rows[i]["high"])
        low = float(rows[i]["low"])
        prev_close = float(rows[i - 1]["close"])
        trs.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    window = trs[-period:]
    return sum(window) / len(window) if window else 0.0


def _swings(rows: list[Any], strength: int = 2) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    highs, lows = [], []
    for i in range(strength, len(rows) - strength):
        high = float(rows[i]["high"])
        low = float(rows[i]["low"])
        left_highs = [float(rows[j]["high"]) for j in range(i - strength, i)]
        right_highs = [float(rows[j]["high"]) for j in range(i + 1, i + strength + 1)]
        left_lows = [float(rows[j]["low"]) for j in range(i - strength, i)]
        right_lows = [float(rows[j]["low"]) for j in range(i + 1, i + strength + 1)]
        if high > max(left_highs + right_highs):
            highs.append((i, high))
        if low < min(left_lows + right_lows):
            lows.append((i, low))
    return highs, lows


def _line_y(a: tuple[int, float], b: tuple[int, float], x: int) -> float:
    if b[0] == a[0]:
        return b[1]
    slope = (b[1] - a[1]) / (b[0] - a[0])
    return a[1] + slope * (x - a[0])


def _nearest_level(rows: list[Any], price: float, atr: float) -> tuple[float, float]:
    lookback = rows[-60:]
    highs = [float(r["high"]) for r in lookback]
    lows = [float(r["low"]) for r in lookback]
    levels = highs + lows
    if not levels:
        return 0.0, inf
    level = min(levels, key=lambda x: abs(x - price))
    distance = abs(level - price)
    return level, distance / atr if atr else inf


def analyze_symbol(symbol: str, rows: list[Any]) -> dict[str, Any]:
    if len(rows) < 60:
        return {"state": "NO SETUP", "score": 0, "setup": "Insufficient data", "reason": "Waiting for more candles."}

    atr = _atr(rows)
    highs, lows = _swings(rows)
    idx = len(rows) - 1
    last = rows[-1]
    close = float(last["close"])
    high = float(last["high"])
    low = float(last["low"])

    score = 0
    direction = None
    reasons: list[str] = []

    if len(highs) >= 2:
        h1, h2 = highs[-2], highs[-1]
        if h2[1] < h1[1]:
            line = _line_y(h1, h2, idx)
            distance = abs(close - line)
            if atr and distance <= atr * 0.45:
                score += 25
                direction = "SHORT"
                reasons.append("descending resistance is being tested")
            if direction == "SHORT" and high >= line and close < line:
                score += 20
                reasons.append("rejection candle closed back below trendline")

    if len(lows) >= 2:
        l1, l2 = lows[-2], lows[-1]
        if l2[1] > l1[1]:
            line = _line_y(l1, l2, idx)
            distance = abs(close - line)
            if atr and distance <= atr * 0.45:
                score += 25
                direction = "LONG"
                reasons.append("ascending support is being tested")
            if direction == "LONG" and low <= line and close > line:
                score += 20
                reasons.append("rejection candle closed back above trendline")

    level, level_atr_distance = _nearest_level(rows, close, atr)
    if level_atr_distance <= 0.65:
        score += 15
        reasons.append("nearby support/resistance adds confluence")

    candle_range = max(high - low, 0.0)
    if atr and candle_range >= atr * 0.8:
        score += 10
        reasons.append("current candle has meaningful volatility")

    # Avoid calling an unconfirmed trendline touch a trade signal.
    if direction is None:
        state = "NO SETUP"
        setup = "None"
    elif score >= 82:
        state = "CONFIRMING"
        setup = "Trendline reversal"
    elif score >= 65:
        state = "DEVELOPING"
        setup = "Trendline reversal"
    elif score >= 50:
        state = "WATCHING"
        setup = "Trendline reversal"
    else:
        state = "NO SETUP"
        setup = "None"

    reason = "; ".join(reasons) if reasons else "No clean trendline sequence detected."
    return {
        "state": state,
        "score": min(score, 100),
        "setup": setup,
        "direction": direction,
        "reason": reason,
        "atr": atr,
        "nearest_level": level,
    }
