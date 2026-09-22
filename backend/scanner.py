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


def _price_action(rows: list[Any], atr: float) -> dict[str, Any]:
    last = rows[-1]
    prev = rows[-2]
    close = float(last["close"])
    open_ = float(last["open"])
    high = float(last["high"])
    low = float(last["low"])
    prev_close = float(prev["close"])
    body = abs(close - open_)
    upper = high - max(open_, close)
    lower = min(open_, close) - low
    rng = max(high - low, 0.0)

    if rng == 0:
        return {"state": "NEUTRAL", "label": "Compressed candle", "direction": None}

    if close > open_ and lower >= body * 1.5 and close >= low + rng * 0.65:
        return {"state": "BULLISH_REJECTION", "label": "Bullish rejection wick", "direction": "LONG"}
    if close < open_ and upper >= body * 1.5 and close <= high - rng * 0.65:
        return {"state": "BEARISH_REJECTION", "label": "Bearish rejection wick", "direction": "SHORT"}

    if atr and body >= atr * 0.75 and close > prev_close and close >= high - rng * 0.2:
        return {"state": "BULLISH_DISPLACEMENT", "label": "Bullish displacement", "direction": "LONG"}
    if atr and body >= atr * 0.75 and close < prev_close and close <= low + rng * 0.2:
        return {"state": "BEARISH_DISPLACEMENT", "label": "Bearish displacement", "direction": "SHORT"}

    if close > prev_close:
        return {"state": "BULLISH", "label": "Bullish price action", "direction": "LONG"}
    if close < prev_close:
        return {"state": "BEARISH", "label": "Bearish price action", "direction": "SHORT"}
    return {"state": "NEUTRAL", "label": "Neutral price action", "direction": None}


def _trendline_signal(rows: list[Any], highs, lows, atr: float) -> dict[str, Any]:
    idx = len(rows) - 1
    close = float(rows[-1]["close"])
    high = float(rows[-1]["high"])
    low = float(rows[-1]["low"])

    # Descending resistance: reversal below the line, or a clean break above it.
    if len(highs) >= 2:
        h1, h2 = highs[-2], highs[-1]
        if h2[1] < h1[1]:
            line = _line_y(h1, h2, idx)
            if atr:
                distance = abs(close - line)
                if distance <= atr * 0.8:
                    if close > line + atr * 0.08:
                        return {"family": "BREAK", "direction": "LONG", "line": line, "label": "Trendline resistance break"}
                    if high >= line and close < line:
                        return {"family": "REVERSAL", "direction": "SHORT", "line": line, "label": "Trendline resistance rejection"}

    # Ascending support: reversal above the line, or a clean break below it.
    if len(lows) >= 2:
        l1, l2 = lows[-2], lows[-1]
        if l2[1] > l1[1]:
            line = _line_y(l1, l2, idx)
            if atr:
                distance = abs(close - line)
                if distance <= atr * 0.8:
                    if close < line - atr * 0.08:
                        return {"family": "BREAK", "direction": "SHORT", "line": line, "label": "Trendline support break"}
                    if low <= line and close > line:
                        return {"family": "REVERSAL", "direction": "LONG", "line": line, "label": "Trendline support rejection"}

    return {"family": None, "direction": None, "line": None, "label": "Trendline sequence developing"}


def _crt_context(rows: list[Any], atr: float) -> dict[str, Any]:
    if len(rows) < 4:
        return {"state": "UNKNOWN", "label": "Waiting for range context", "direction": None}

    window = rows[-4:-1]
    range_high = max(float(r["high"]) for r in window)
    range_low = min(float(r["low"]) for r in window)
    close = float(rows[-1]["close"])
    high = float(rows[-1]["high"])
    low = float(rows[-1]["low"])
    span = max(range_high - range_low, 0.0)

    if span == 0:
        return {"state": "NEUTRAL", "label": "Compressed range context", "direction": None}

    if high > range_high and close < range_high:
        return {"state": "BEARISH_SWEEP", "label": "Range high sweep and rejection", "direction": "SHORT"}
    if low < range_low and close > range_low:
        return {"state": "BULLISH_SWEEP", "label": "Range low sweep and rejection", "direction": "LONG"}
    if close > range_high:
        return {"state": "BULLISH_EXPANSION", "label": "Range expansion higher", "direction": "LONG"}
    if close < range_low:
        return {"state": "BEARISH_EXPANSION", "label": "Range expansion lower", "direction": "SHORT"}
    return {"state": "RANGE", "label": "Price remains inside the recent candle range", "direction": None}


def _trade_levels(
    rows: list[Any],
    direction: str | None,
    entry: float,
    atr: float,
    highs,
    lows,
    nearest_level: float,
    nearest_level_type: str,
) -> dict[str, Any]:
    if not direction or entry <= 0 or atr <= 0:
        return {"entry": entry, "stop_loss": None, "take_profit": None, "risk_distance": None, "reward_distance": None, "rr": None}

    recent_high = max((float(r["high"]) for r in rows[-20:]), default=entry)
    recent_low = min((float(r["low"]) for r in rows[-20:]), default=entry)

    if direction == "LONG":
        swing = lows[-1][1] if lows else recent_low
        stop = min(swing - atr * 0.15, entry - atr * 0.9)
        risk = entry - stop
        resistance_candidates = [float(h[1]) for h in highs if float(h[1]) > entry + atr * 0.25]
        if nearest_level_type == "RESISTANCE" and nearest_level > entry + atr * 0.25:
            resistance_candidates.append(nearest_level)
        target = min(resistance_candidates) if resistance_candidates else entry + risk * 2.0
        if target <= entry + risk:
            target = entry + risk * 2.0
    else:
        swing = highs[-1][1] if highs else recent_high
        stop = max(swing + atr * 0.15, entry + atr * 0.9)
        risk = stop - entry
        support_candidates = [float(l[1]) for l in lows if float(l[1]) < entry - atr * 0.25]
        if nearest_level_type == "SUPPORT" and nearest_level < entry - atr * 0.25:
            support_candidates.append(nearest_level)
        target = max(support_candidates) if support_candidates else entry - risk * 2.0
        if target >= entry - risk:
            target = entry - risk * 2.0

    reward = abs(target - entry)
    rr = reward / risk if risk > 0 else None
    return {
        "entry": round(entry, 8),
        "stop_loss": round(stop, 8),
        "take_profit": round(target, 8),
        "risk_distance": round(risk, 8),
        "reward_distance": round(reward, 8),
        "rr": round(rr, 2) if rr is not None else None,
    }


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

    pa = _price_action(rows, atr)
    trend = _trendline_signal(rows, highs, lows, atr)
    crt = _crt_context(rows, atr)
    level, level_atr_distance, level_kind = _nearest_level(rows, close, atr)

    direction = trend["direction"] or pa["direction"] or crt["direction"]
    if direction is None:
        if htf_bias == "BULLISH" and ema20 > ema50:
            direction = "LONG"
        elif htf_bias == "BEARISH" and ema20 < ema50:
            direction = "SHORT"

    breakdown = {
        "trendline": 0,
        "structure": 0,
        "support_resistance": 0,
        "price_action": 0,
        "session": 0,
        "momentum": 0,
        "higher_timeframe": 0,
        "crt": 0,
    }
    reasons: list[str] = []

    if trend["family"]:
        breakdown["trendline"] = 20
        reasons.append(trend["label"])
    elif direction:
        breakdown["trendline"] = 10
        reasons.append("trendline structure is being monitored")

    if direction == "LONG" and structure == "Higher highs + higher lows":
        breakdown["structure"] = 15
        reasons.append("higher highs and higher lows support the bullish structure")
    elif direction == "SHORT" and structure == "Lower highs + lower lows":
        breakdown["structure"] = 15
        reasons.append("lower highs and lower lows support the bearish structure")
    elif direction:
        breakdown["structure"] = 7

    if level_atr_distance <= 0.65:
        breakdown["support_resistance"] = 20
        reasons.append(f"price is close to {level_kind.lower()} at a key reaction level")
    elif level_atr_distance <= 1.0:
        breakdown["support_resistance"] = 10

    if direction and pa["direction"] == direction:
        breakdown["price_action"] = 10
        reasons.append(pa["label"])
    elif pa["state"] != "NEUTRAL":
        breakdown["price_action"] = 4

    if direction == "LONG" and htf_bias == "BULLISH":
        breakdown["higher_timeframe"] = 10
        reasons.append("higher timeframe bias is bullish")
    elif direction == "SHORT" and htf_bias == "BEARISH":
        breakdown["higher_timeframe"] = 10
        reasons.append("higher timeframe bias is bearish")
    elif direction:
        breakdown["higher_timeframe"] = 4

    if direction == "LONG" and ema20 > ema50 and rsi >= 52:
        breakdown["momentum"] = 10
        reasons.append("bullish momentum agrees with the setup")
    elif direction == "SHORT" and ema20 < ema50 and rsi <= 48:
        breakdown["momentum"] = 10
        reasons.append("bearish momentum agrees with the setup")
    elif direction:
        breakdown["momentum"] = 5

    if direction and crt["direction"] == direction:
        breakdown["crt"] = 10
        reasons.append(crt["label"])
    elif crt["state"] in {"BULLISH_EXPANSION", "BEARISH_EXPANSION"}:
        breakdown["crt"] = 5

    if session_context:
        if session_context.get("session_alignment"):
            breakdown["session"] = 5
            reasons.append(session_context["session_alignment"])
        elif session_context.get("session") in {"London", "New York", "London / New York Overlap"}:
            breakdown["session"] = 3

    score = min(sum(breakdown.values()), 100)

    if direction is None:
        state, setup = "NO SETUP", "None"
    elif trend["family"] == "BREAK" and score >= 70:
        state, setup = "CONFIRMING", "Trendline break"
    elif trend["family"] == "REVERSAL" and score >= 70:
        state, setup = "CONFIRMING", "Trendline reversal"
    elif trend["family"] and score >= 55:
        state, setup = "DEVELOPING", f"Trendline {trend['family'].lower()}"
    elif score >= 50:
        state, setup = "DEVELOPING", "Trendline setup"
    elif score >= 35:
        state, setup = "WATCHING", "Trendline setup"
    else:
        state, setup = "NO SETUP", "None"

    momentum = "BULLISH" if rsi >= 55 else "BEARISH" if rsi <= 45 else "NEUTRAL"

    if state == "CONFIRMING":
        stage = "CONFIRMATION"
    elif trend["family"] == "BREAK":
        stage = "BREAK DETECTED"
    elif trend["family"] == "REVERSAL":
        stage = "REACTION"
    elif direction:
        stage = "STRUCTURE BIAS"
    else:
        stage = "NO SETUP"

    if trend["family"] == "BREAK" and direction == "LONG":
        trigger = "Break above trendline + retest/close confirmation"
    elif trend["family"] == "BREAK" and direction == "SHORT":
        trigger = "Break below trendline + retest/close confirmation"
    elif direction == "LONG":
        trigger = "Bullish rejection + close confirmation"
    elif direction == "SHORT":
        trigger = "Bearish rejection + close confirmation"
    else:
        trigger = "Wait for clean trendline structure"

    levels = _trade_levels(rows, direction, close, atr, highs, lows, level, level_kind)
    if state in {"CONFIRMING", "DEVELOPING"} and direction and levels["rr"] is not None and levels["rr"] < 1.5:
        # A nearby opposing level can create poor asymmetry. Keep the levels
        # visible, but downgrade the setup rather than pretending the target is attractive.
        reasons.append("risk/reward is below the preferred 1.5R threshold")

    if state == "NO SETUP":
        reason = "; ".join(reasons[:2]) if reasons else "No clean trendline sequence detected."
    else:
        reason = "; ".join(reasons[:7]) if reasons else "Potential structure developing."

    action = (
        "BUY SETUP" if state == "CONFIRMING" and direction == "LONG" else
        "SELL SETUP" if state == "CONFIRMING" and direction == "SHORT" else
        "BUY DEVELOPING" if state == "DEVELOPING" and direction == "LONG" else
        "SELL DEVELOPING" if state == "DEVELOPING" and direction == "SHORT" else
        "BUY WATCH" if direction == "LONG" else
        "SELL WATCH" if direction == "SHORT" else
        "WAIT"
    )

    insight = (
        f"{structure}. H1 bias {htf_bias.lower()}, price action {pa['state'].lower()}, "
        f"trendline {trend['family'] or 'watching'}, CRT {crt['state'].lower()}. "
        f"RSI {rsi:.0f}. "
        f"{'Levels are calculated from structure and ATR.' if levels['stop_loss'] else 'Waiting for enough structure to calculate levels.'}"
    )

    invalidation = levels["stop_loss"]

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
        "entry": levels["entry"],
        "stop_loss": levels["stop_loss"],
        "take_profit": levels["take_profit"],
        "risk_distance": levels["risk_distance"],
        "reward_distance": levels["reward_distance"],
        "rr": levels["rr"],
        "market_bias": "BULLISH" if ema20 > ema50 and rsi >= 52 else "BEARISH" if ema20 < ema50 and rsi <= 48 else "RANGE / NEUTRAL",
        "momentum": momentum,
        "rsi": rsi,
        "ema20": ema20,
        "ema50": ema50,
        "higher_timeframe_bias": htf_bias,
        "structure": structure,
        "price_action": pa["label"],
        "price_action_state": pa["state"],
        "trendline": trend["label"],
        "trendline_state": trend["family"] or "WATCHING",
        "setup_family": trend["family"],
        "sr_context": f"{level_kind} {level:.8f}" if level else "No nearby level",
        "crt_context": crt["label"],
        "crt_state": crt["state"],
        "atr": atr,
        "nearest_level": level,
        "nearest_level_type": level_kind,
        "nearest_level_atr": level_atr_distance,
        "spread": spread,
        "spread_atr": spread / atr if atr else 0.0,
        "score_breakdown": breakdown,
    }

