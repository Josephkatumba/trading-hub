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


def _ema(values: list[float], period: int) -> float:
    if not values:
        return 0.0
    if len(values) < period:
        return sum(values) / len(values)
    k = 2.0 / (period + 1)
    value = sum(values[:period]) / period
    for price in values[period:]:
        value = price * k + value * (1 - k)
    return value


def _rsi(rows: list[Any], period: int = 14) -> float:
    if len(rows) < period + 1:
        return 50.0
    closes = [float(r["close"]) for r in rows]
    gains, losses = [], []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0 if avg_gain else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


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


def _nearest_level(rows: list[Any], price: float, atr: float) -> tuple[float, float, str]:
    lookback = rows[-80:]
    if not lookback:
        return 0.0, inf, "NONE"
    highs = [float(r["high"]) for r in lookback]
    lows = [float(r["low"]) for r in lookback]
    levels = [(x, "RESISTANCE") for x in highs] + [(x, "SUPPORT") for x in lows]
    level, kind = min(levels, key=lambda item: abs(item[0] - price))
    distance = abs(level - price)
    return level, distance / atr if atr else inf, kind


def _structure_label(highs, lows) -> str:
    if len(highs) >= 2 and len(lows) >= 2:
        hh = highs[-1][1] > highs[-2][1]
        hl = lows[-1][1] > lows[-2][1]
        lh = highs[-1][1] < highs[-2][1]
        ll = lows[-1][1] < lows[-2][1]
        if hh and hl:
            return "Higher highs + higher lows"
        if lh and ll:
            return "Lower highs + lower lows"
    return "Mixed / range"


def _htf_bias(rows: list[Any]) -> str:
    if len(rows) < 60:
        return "UNKNOWN"
    closes = [float(r["close"]) for r in rows]
    fast = _ema(closes, 20)
    slow = _ema(closes, 50)
    if fast > slow * 1.001:
        return "BULLISH"
    if fast < slow * 0.999:
        return "BEARISH"
    return "NEUTRAL"


def analyze_symbol(
    symbol: str,
    rows: list[Any],
    spread: float = 0.0,
    session_context: dict[str, Any] | None = None,
    higher_rows: list[Any] | None = None,
) -> dict[str, Any]:
    if len(rows) < 60:
        return {
            "state": "NO SETUP", "score": 0, "setup": "Insufficient data",
            "direction": None, "reason": "Waiting for more candles.",
            "score_breakdown": {}, "market_bias": "UNKNOWN",
        }

    atr = _atr(rows)
    highs, lows = _swings(rows)
    idx = len(rows) - 1
    last = rows[-1]
    close = float(last["close"])
    high = float(last["high"])
    low = float(last["low"])
    closes = [float(r["close"]) for r in rows]
    ema20 = _ema(closes, 20)
    ema50 = _ema(closes, 50)
    rsi = _rsi(rows)
    structure = _structure_label(highs, lows)
    htf_bias = _htf_bias(higher_rows or rows)

    direction = None
    reasons: list[str] = []
    breakdown = {
        "trendline": 0, "structure": 0, "support_resistance": 0,
        "rejection": 0, "session": 0, "volatility": 0,
        "momentum": 0, "higher_timeframe": 0,
    }

    if len(highs) >= 2:
        h1, h2 = highs[-2], highs[-1]
        if h2[1] < h1[1]:
            line = _line_y(h1, h2, idx)
            distance = abs(close - line)
            if atr and distance <= atr * 0.65:
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
            if atr and distance <= atr * 0.65:
                if direction is None:
                    direction = "LONG"
                if direction == "LONG":
                    breakdown["trendline"] = max(breakdown["trendline"], 20)
                    reasons.append("ascending support is being tested")
                    if low <= line and close > line:
                        breakdown["rejection"] = 15
                        reasons.append("bullish rejection closed back above support")

    if direction == "SHORT" and structure == "Lower highs + lower lows":
        breakdown["structure"] = 15
        reasons.append("market structure agrees with the short")
    elif direction == "LONG" and structure == "Higher highs + higher lows":
        breakdown["structure"] = 15
        reasons.append("market structure agrees with the long")
    elif direction:
        breakdown["structure"] = 7

    level, level_atr_distance, level_kind = _nearest_level(rows, close, atr)
    if level_atr_distance <= 0.65:
        breakdown["support_resistance"] = 15
        reasons.append(f"price is close to {level_kind.lower()} at a key reaction level")
    elif level_atr_distance <= 1.0:
        breakdown["support_resistance"] = 8

    candle_range = max(high - low, 0.0)
    if atr:
        if candle_range >= atr * 0.8:
            breakdown["volatility"] = 10
        elif candle_range >= atr * 0.5:
            breakdown["volatility"] = 5

    if direction == "LONG":
        if ema20 > ema50 and rsi >= 52:
            breakdown["momentum"] = 10
            reasons.append("bullish momentum agrees with the setup")
        elif rsi >= 50:
            breakdown["momentum"] = 5
    elif direction == "SHORT":
        if ema20 < ema50 and rsi <= 48:
            breakdown["momentum"] = 10
            reasons.append("bearish momentum agrees with the setup")
        elif rsi <= 50:
            breakdown["momentum"] = 5

    if direction == "LONG" and htf_bias == "BULLISH":
        breakdown["higher_timeframe"] = 5
        reasons.append("higher timeframe bias is bullish")
    elif direction == "SHORT" and htf_bias == "BEARISH":
        breakdown["higher_timeframe"] = 5
        reasons.append("higher timeframe bias is bearish")

    if session_context:
        if session_context.get("session_alignment"):
            breakdown["session"] = 10
            reasons.append(session_context["session_alignment"])
        elif session_context.get("session") in {"London", "New York", "London / New York Overlap"}:
            breakdown["session"] = 5

    score = min(sum(breakdown.values()), 100)

    if direction is None:
        state, setup = "NO SETUP", "None"
    elif breakdown["rejection"] >= 15 and score >= 75:
        state, setup = "CONFIRMING", "Trendline reversal"
    elif score >= 60:
        state, setup = "DEVELOPING", "Trendline reversal"
    elif score >= 40:
        state, setup = "WATCHING", "Trendline reversal"
    else:
        state, setup = "NO SETUP", "None"

    if direction:
        momentum = "BULLISH" if rsi >= 55 else "BEARISH" if rsi <= 45 else "NEUTRAL"
    else:
        momentum = "BULLISH" if ema20 > ema50 and rsi >= 55 else "BEARISH" if ema20 < ema50 and rsi <= 45 else "NEUTRAL"

    if state == "CONFIRMING":
        stage = "CONFIRMATION"
    elif direction and breakdown["trendline"]:
        stage = "TRENDLINE TEST"
    elif direction:
        stage = "STRUCTURE BIAS"
    else:
        stage = "NO SETUP"

    if state == "NO SETUP":
        reason = "; ".join(reasons[:2]) if reasons else "No clean trendline sequence detected."
    else:
        reason = "; ".join(reasons) if reasons else "Potential structure developing."

    insight = (
        f"{structure}. M15 momentum {momentum} with RSI {rsi:.0f}; "
        f"H1 bias {htf_bias.lower()}. "
        f"{'Waiting for rejection confirmation.' if direction and breakdown['rejection'] < 15 else 'Rejection condition is present.' if direction else 'Waiting for a directional trendline sequence.'}"
    )

    if state == "CONFIRMING" and direction == "LONG":
        action = "BUY SETUP"
    elif state == "CONFIRMING" and direction == "SHORT":
        action = "SELL SETUP"
    elif state == "DEVELOPING" and direction == "LONG":
        action = "BUY DEVELOPING"
    elif state == "DEVELOPING" and direction == "SHORT":
        action = "SELL DEVELOPING"
    elif direction == "LONG":
        action = "BUY WATCH"
    elif direction == "SHORT":
        action = "SELL WATCH"
    else:
        action = "WAIT"

    trigger = "Bullish rejection + close confirmation" if direction == "LONG" else "Bearish rejection + close confirmation" if direction == "SHORT" else "Wait for clean trendline structure"

    if direction == "LONG" and lows and atr:
        invalidation = lows[-1][1] - atr * 0.10
    elif direction == "SHORT" and highs and atr:
        invalidation = highs[-1][1] + atr * 0.10
    else:
        invalidation = None

    return {
        "state": state,
        "action": action,
        "score": score,
        "setup": setup,
        "direction": direction,
        "reason": reason,
        "insight": insight,
        "stage": stage,
        "trigger": trigger,
        "invalidation_hint": invalidation,
        "market_bias": "BULLISH" if ema20 > ema50 and rsi >= 52 else "BEARISH" if ema20 < ema50 and rsi <= 48 else "RANGE / NEUTRAL",
        "momentum": momentum,
        "rsi": rsi,
        "ema20": ema20,
        "ema50": ema50,
        "higher_timeframe_bias": htf_bias,
        "structure": structure,
        "atr": atr,
        "nearest_level": level,
        "nearest_level_type": level_kind,
        "nearest_level_atr": level_atr_distance,
        "spread": spread,
        "spread_atr": spread / atr if atr else 0.0,
        "score_breakdown": breakdown,
    }
