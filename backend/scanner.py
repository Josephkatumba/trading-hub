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
        if high > max(float(rows[j]["high"]) for j in range(i - strength, i)) and high > max(float(rows[j]["high"]) for j in range(i + 1, i + strength + 1)):
            highs.append((i, high))
        if low < min(float(rows[j]["low"]) for j in range(i - strength, i)) and low < min(float(rows[j]["low"]) for j in range(i + 1, i + strength + 1)):
            lows.append((i, low))
    return highs, lows


def _line_y(a: tuple[int, float], b: tuple[int, float], x: int) -> float:
    if b[0] == a[0]:
        return b[1]
    return a[1] + (b[1] - a[1]) / (b[0] - a[0]) * (x - a[0])


def _nearest_level(rows: list[Any], price: float, atr: float) -> tuple[float, float]:
    lookback = rows[-80:]
    levels = [float(r["high"]) for r in lookback] + [float(r["low"]) for r in lookback]
    if not levels:
        return 0.0, inf
    level = min(levels, key=lambda x: abs(x - price))
    distance = abs(level - price)
    return level, distance / atr if atr else inf


def _structure_score(highs, lows, direction):
    if direction == "SHORT" and len(highs) >= 3:
        return 10 if highs[-1][1] < highs[-2][1] < highs[-3][1] else 4
    if direction == "LONG" and len(lows) >= 3:
        return 10 if lows[-1][1] > lows[-2][1] > lows[-3][1] else 4
    return 0


def analyze_symbol(symbol: str, rows: list[Any], spread: float = 0.0, session_context: dict[str, Any] | None = None) -> dict[str, Any]:
    if len(rows) < 60:
        return {
            "state": "NO SETUP", "score": 0, "setup": "Insufficient data",
            "direction": None, "reason": "Waiting for more candles.", "score_breakdown": {},
        }

    atr = _atr(rows)
    highs, lows = _swings(rows)
    idx = len(rows) - 1
    last = rows[-1]
    close = float(last["close"])
    high = float(last["high"])
    low = float(last["low"])

    direction = None
    reasons: list[str] = []
    breakdown = {
        "trendline": 0, "structure": 0, "support_resistance": 0,
        "rejection": 0, "session": 0, "volatility": 0,
    }

    if len(highs) >= 2:
        h1, h2 = highs[-2], highs[-1]
        if h2[1] < h1[1]:
            line = _line_y(h1, h2, idx)
            distance = abs(close - line)
            if atr and distance <= atr * 0.55:
                direction = "SHORT"
                breakdown["trendline"] = 20
                reasons.append("descending resistance is being tested")
                if high >= line and close < line:
                    breakdown["rejection"] = 15
                    reasons.append("bearish rejection closed back below resistance")

    if len(lows) >= 2:
        l1, l2 = lows[-2], lows[-1]
        if l2[1] > l1[1]:
            line = _line_y(l1, l2, idx)
            distance = abs(close - line)
            if atr and distance <= atr * 0.55:
                if direction is None:
                    direction = "LONG"
                if direction == "LONG":
                    breakdown["trendline"] = max(breakdown["trendline"], 20)
                    reasons.append("ascending support is being tested")
                    if low <= line and close > line:
                        breakdown["rejection"] = 15
                        reasons.append("bullish rejection closed back above support")

    breakdown["structure"] = _structure_score(highs, lows, direction)

    level, level_atr_distance = _nearest_level(rows, close, atr)
    if level_atr_distance <= 0.65:
        breakdown["support_resistance"] = 15
        reasons.append("nearby support/resistance adds confluence")
    elif level_atr_distance <= 1.0:
        breakdown["support_resistance"] = 8

    candle_range = max(high - low, 0.0)
    if atr:
        if candle_range >= atr * 0.8:
            breakdown["volatility"] = 10
            reasons.append("current candle has meaningful volatility")
        elif candle_range >= atr * 0.5:
            breakdown["volatility"] = 5

    if session_context:
        if session_context.get("session_alignment"):
            breakdown["session"] = 10
            reasons.append(session_context["session_alignment"])
        elif session_context.get("session") in {"London", "New York"}:
            breakdown["session"] = 5

    score = min(sum(breakdown.values()), 100)

    if direction is None:
        state, setup = "NO SETUP", "None"
    elif breakdown["rejection"] >= 15 and score >= 82:
        state, setup = "CONFIRMING", "Trendline reversal"
    elif score >= 65:
        state, setup = "DEVELOPING", "Trendline reversal"
    elif score >= 50:
        state, setup = "WATCHING", "Trendline reversal"
    else:
        state, setup = "NO SETUP", "None"

    if state == "NO SETUP":
        reason = "; ".join(reasons[:2]) if reasons else "No clean trendline sequence detected."
    else:
        reason = "; ".join(reasons) if reasons else "Potential structure developing."

    return {
        "state": state,
        "score": score,
        "setup": setup,
        "direction": direction,
        "reason": reason,
        "atr": atr,
        "nearest_level": level,
        "nearest_level_atr": level_atr_distance,
        "spread": spread,
        "score_breakdown": breakdown,
    }
