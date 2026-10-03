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

    candidate_identity = None
    # Descending resistance: reversal below the line, or a clean break above it.
    if len(highs) >= 2:
        h1, h2 = highs[-2], highs[-1]
        if h2[1] < h1[1]:
            candidate_identity = {"orientation": "DESCENDING_RESISTANCE", "anchors": [
                {"time": rows[h1[0]].get("time"), "price": h1[1]},
                {"time": rows[h2[0]].get("time"), "price": h2[1]}]}
            line = _line_y(h1, h2, idx)
            if atr:
                distance = abs(close - line)
                if distance <= atr * 0.8:
                    if close > line + atr * 0.08:
                        return {"family": "BREAK", "direction": "LONG", "line": line, "label": "Trendline resistance break", "identity": candidate_identity}
                    if high >= line and close < line:
                        return {"family": "REVERSAL", "direction": "SHORT", "line": line, "label": "Trendline resistance rejection", "identity": candidate_identity}

    # Ascending support: reversal above the line, or a clean break below it.
    if len(lows) >= 2:
        l1, l2 = lows[-2], lows[-1]
        if l2[1] > l1[1]:
            candidate_identity = {"orientation": "ASCENDING_SUPPORT", "anchors": [
                {"time": rows[l1[0]].get("time"), "price": l1[1]},
                {"time": rows[l2[0]].get("time"), "price": l2[1]}]}
            line = _line_y(l1, l2, idx)
            if atr:
                distance = abs(close - line)
                if distance <= atr * 0.8:
                    if close < line - atr * 0.08:
                        return {"family": "BREAK", "direction": "SHORT", "line": line, "label": "Trendline support break", "identity": candidate_identity}
                    if low <= line and close > line:
                        return {"family": "REVERSAL", "direction": "LONG", "line": line, "label": "Trendline support rejection", "identity": candidate_identity}

    return {"family": None, "direction": None, "line": None, "label": "Trendline sequence developing", "identity": candidate_identity}


# Break-and-retest confirmation (trendline-first-v5.1, break_confirmation="retest-rejection").
# Parameters are round values chosen before looking at any outcome; nothing is fitted.
RETEST_WINDOW = 12             # closed M15 bars after the break in which the retest must confirm
RETEST_TOUCH_ATR = 0.15        # a retest reaches within this many ATR of the broken line
BREAK_FAIL_ATR = 0.08          # a close this far back through the line fails the break (= the break threshold)


def _break_events(rows: list[Any]) -> dict[str, Any] | None:
    """The most recent genuine trendline break among the last RETEST_WINDOW + 1 closed bars.

    A bar j is a break when _trendline_signal, evaluated on the bars up to j only (its own
    swings and ATR, so nothing after j is used), returns BREAK and the previous close was
    not yet beyond that same line (a crossing, not price merely riding above it). The
    line is fixed by its two anchors at j, so later swings cannot redraw it.
    """
    last = len(rows) - 1
    for j in range(last, max(last - RETEST_WINDOW, 60) - 1, -1):
        prefix = rows[:j + 1]
        atr = _atr(prefix)
        highs, lows = _swings(prefix)
        signal = _trendline_signal(prefix, highs, lows, atr)
        if signal["family"] != "BREAK":
            continue
        a, b = (highs[-2], highs[-1]) if signal["direction"] == "LONG" else (lows[-2], lows[-1])
        prev_close = float(rows[j - 1]["close"])
        line_prev = _line_y(a, b, j - 1)
        crossed = prev_close <= line_prev if signal["direction"] == "LONG" else prev_close >= line_prev
        if crossed:
            return {"index": j, "direction": signal["direction"], "anchors": (a, b), "atr": atr,
                    "label": signal["label"], "identity": signal["identity"]}
    return None


def _retest_state(rows: list[Any], brk: dict[str, Any], atr: float) -> dict[str, Any]:
    """Whether the broken line has been retested and the retest rejected (see _break_events).

    LONG (resistance broken upward; SHORT mirrors):
      failed    : any close after the break more than BREAK_FAIL_ATR x ATR back below the line
      touched(i): bar i (after the break bar) traded down to within RETEST_TOUCH_ATR x ATR
                  of the line, or through it
      confirmed : the last closed bar closes above the line AND shows a candle rejection
                  (strategies/price_action.py: wick_rejection / engulfing / close_away)
                  with the touch after the break bar.
    """
    from strategies.price_action import confirm_rejection   # local: strategies imports scanner

    long = brk["direction"] == "LONG"
    a, b = brk["anchors"]
    j, last = brk["index"], len(rows) - 1
    line = lambda i: _line_y(a, b, i)  # noqa: E731
    failed = any((float(rows[i]["close"]) < line(i) - BREAK_FAIL_ATR * atr) if long
                 else (float(rows[i]["close"]) > line(i) + BREAK_FAIL_ATR * atr) for i in range(j + 1, last + 1))
    touched = lambda i: i > j and ((float(rows[i]["low"]) <= line(i) + RETEST_TOUCH_ATR * atr) if long  # noqa: E731
                                   else (float(rows[i]["high"]) >= line(i) - RETEST_TOUCH_ATR * atr))
    retested = any(touched(i) for i in range(j + 1, last + 1))
    candle = {"confirmed": False, "pattern": None, "patterns": {}, "touch_index": None}
    if not failed and last > j:
        candle = confirm_rejection(
            rows, long, touched,
            closed_outside=lambda i: float(rows[i]["close"]) > line(i) if long else float(rows[i]["close"]) < line(i),
            earliest=j + 1)
    return {"break_index": j, "break_time": rows[j].get("time"), "bars_since_break": last - j,
            "line": line(last), "failed": failed, "retested": retested,
            "confirmed": bool(candle["confirmed"] and not failed), "pattern": candle["pattern"],
            "patterns": candle["patterns"],
            "touch_time": rows[candle["touch_index"]].get("time") if candle.get("touch_index") is not None else None}


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
    structural_levels: tuple[list[tuple[int, float]], list[tuple[int, float]]] | None = None,
) -> dict[str, Any]:
    """Entry/stop/target. Default (trendline v3/v4): target = the nearest M15 swing or
    level beyond 0.25 ATR, else a 2R projection. With `structural_levels` (the swing
    highs/lows of closed H1 bars, trendline v5) the target is the nearest such swing
    strictly beyond entry: M15 minor swings are not targets, an H1 swing just ahead
    is never jumped (no target through a structural barrier) and nothing is
    projected; without one there is no target (rr None, so the setup cannot confirm).
    The stop is the same in both models."""
    if not direction or entry <= 0 or atr <= 0:
        empty = {"entry": entry, "stop_loss": None, "take_profit": None, "risk_distance": None, "reward_distance": None, "rr": None}
        return empty if structural_levels is None else {**empty, "target_basis": None}

    recent_high = max((float(r["high"]) for r in rows[-20:]), default=entry)
    recent_low = min((float(r["low"]) for r in rows[-20:]), default=entry)

    if structural_levels is not None:
        return _structural_levels(direction, entry, atr, lows, highs, recent_low, recent_high, structural_levels)

    if direction == "LONG":
        swing = lows[-1][1] if lows else recent_low
        stop = min(swing - atr * 0.15, entry - atr * 0.9)
        risk = entry - stop
        resistance_candidates = [float(h[1]) for h in highs if float(h[1]) > entry + atr * 0.25]
        if nearest_level_type == "RESISTANCE" and nearest_level > entry + atr * 0.25:
            resistance_candidates.append(nearest_level)
        target = min(resistance_candidates) if resistance_candidates else entry + risk * 2.0
    else:
        swing = highs[-1][1] if highs else recent_high
        stop = max(swing + atr * 0.15, entry + atr * 0.9)
        risk = stop - entry
        support_candidates = [float(l[1]) for l in lows if float(l[1]) < entry - atr * 0.25]
        if nearest_level_type == "SUPPORT" and nearest_level < entry - atr * 0.25:
            support_candidates.append(nearest_level)
        target = max(support_candidates) if support_candidates else entry - risk * 2.0

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


def _structural_levels(direction: str, entry: float, atr: float, lows, highs, recent_low: float, recent_high: float,
                       structural_levels) -> dict[str, Any]:
    """Stop exactly as the default model; target = nearest structural (H1) swing beyond entry, or none."""
    structural_highs, structural_lows = structural_levels
    if direction == "LONG":
        swing = lows[-1][1] if lows else recent_low
        stop = min(swing - atr * 0.15, entry - atr * 0.9)
        risk = entry - stop
        beyond = [float(price) for _, price in structural_highs if float(price) > entry]
        target = min(beyond) if beyond else None
    else:
        swing = highs[-1][1] if highs else recent_high
        stop = max(swing + atr * 0.15, entry + atr * 0.9)
        risk = stop - entry
        beyond = [float(price) for _, price in structural_lows if float(price) < entry]
        target = max(beyond) if beyond else None
    reward = abs(target - entry) if target is not None else None
    rr = reward / risk if reward is not None and risk > 0 else None
    return {
        "entry": round(entry, 8),
        "stop_loss": round(stop, 8),
        "take_profit": round(target, 8) if target is not None else None,
        "risk_distance": round(risk, 8),
        "reward_distance": round(reward, 8) if reward is not None else None,
        "rr": round(rr, 2) if rr is not None else None,
        "target_basis": "H1_SWING" if target is not None else None,
    }


def analyze_symbol(
    symbol: str,
    rows: list[Any],
    spread: float = 0.0,
    session_context: dict[str, Any] | None = None,
    higher_rows: list[Any] | None = None,
    strategy_version: str = "trendline-first-v3",
    target_model: str = "nearest-swing",
    break_confirmation: str = "break-bar",
) -> dict[str, Any]:
    # strategy_version only labels the output; it changes no calculation. The
    # trendline strategy passes its own version (strategies/trendline.py).
    # target_model: "nearest-swing" (v3/v4, default) or "h1-structure" (v5): see _trade_levels.
    # break_confirmation: "break-bar" (v3/v4/v5, default: a BREAK can confirm on the break
    # candle itself) or "retest-rejection" (v5.1: a BREAK confirms only when a later candle
    # retests the broken line and rejects it; see _break_events / _retest_state).
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
    retest = None
    if break_confirmation == "retest-rejection" and trend["family"] != "REVERSAL":
        brk = _break_events(rows)
        if brk is not None:
            retest = _retest_state(rows, brk, atr)
            if retest["failed"]:
                trend = {"family": None, "direction": None, "line": None, "identity": brk["identity"],
                         "label": "Trendline break failed: price closed back through the broken line"}
            else:
                suffix = (" retest rejected" if retest["confirmed"] else
                          " retest touched, waiting for a rejection candle" if retest["retested"] else
                          " - waiting for a retest of the broken line")
                trend = {"family": "BREAK", "direction": brk["direction"], "line": retest["line"],
                         "label": brk["label"] + suffix, "identity": brk["identity"]}
        elif trend["family"] == "BREAK":
            # Price sits beyond the line but did not cross it within the retest window: no fresh break.
            trend = {"family": None, "direction": None, "line": None, "identity": trend["identity"],
                     "label": f"No trendline crossing in the last {RETEST_WINDOW} bars"}
    crt = _crt_context(rows, atr)
    level, level_atr_distance, level_kind = _nearest_level(rows, close, atr)

    # Trendline-first strategy gate. Generic directional bias can describe
    # the market, but cannot become a trade setup without a trendline event.
    trendline_direction = trend["direction"]
    direction = trendline_direction or pa["direction"] or crt["direction"]
    if direction is None:
        if htf_bias == "BULLISH" and ema20 > ema50:
            direction = "LONG"
        elif htf_bias == "BEARISH" and ema20 < ema50:
            direction = "SHORT"

    trendline_gate = bool(trend["family"] and trendline_direction)

    # Flexible confirmation gate:
    # A clean trendline event is mandatory, but we deliberately do NOT require
    # every evidence layer to agree. Price action must agree with the event,
    # then at least one of HTF bias, nearby S/R, or CRT context should support it.
    # This keeps the scanner selective without starving it of valid setups.
    htf_alignment = (
        (trendline_direction == "LONG" and htf_bias == "BULLISH")
        or (trendline_direction == "SHORT" and htf_bias == "BEARISH")
    )
    sr_alignment = level_atr_distance <= 0.85
    crt_alignment = crt["direction"] == trendline_direction
    confirmation_support = htf_alignment or sr_alignment or crt_alignment
    confirmation_alignment = bool(
        trendline_gate
        and pa["direction"] == trendline_direction
        and confirmation_support
    )

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
    elif (
        trend["family"] in {"BREAK", "REVERSAL"}
        and score >= 65
        and pa["direction"] == trendline_direction
        and confirmation_support
        and (break_confirmation != "retest-rejection" or trend["family"] != "BREAK"
             or bool(retest and retest["confirmed"]))
    ):
        state, setup = "CONFIRMING", (
            "Trendline break" if trend["family"] == "BREAK" else "Trendline reversal"
        )
    elif trendline_gate and score >= 50:
        state, setup = "DEVELOPING", f"Trendline {trend['family'].lower()}"
    elif trendline_gate:
        state, setup = "WATCHING", f"Trendline {trend['family'].lower()} watch"
    elif direction:
        state, setup = "WATCHING", "Directional context only"
    else:
        state, setup = "NO SETUP", "None"

    if trendline_gate and not confirmation_alignment:
        reasons.append("trendline event is not fully aligned with price action and higher-timeframe bias")
    if break_confirmation == "retest-rejection" and trend["family"] == "BREAK" and not (retest and retest["confirmed"]):
        reasons.append("break is not confirmed until a retest of the broken line rejects it")

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
    elif trend["family"] == "REVERSAL" and direction == "LONG":
        trigger = "Trendline support rejection + bullish close + S/R confirmation"
    elif trend["family"] == "REVERSAL" and direction == "SHORT":
        trigger = "Trendline resistance rejection + bearish close + S/R confirmation"
    elif direction == "LONG":
        trigger = "Directional context only; wait for a clean trendline event"
    elif direction == "SHORT":
        trigger = "Directional context only; wait for a clean trendline event"
    else:
        trigger = "Wait for clean trendline structure"

    structural = None
    if target_model == "h1-structure":
        structural = _swings(higher_rows) if higher_rows else ([], [])
    levels = _trade_levels(rows, direction, close, atr, highs, lows, level, level_kind, structural_levels=structural)

    # Levels are useful for planning, but the UI should not imply they are
    # actionable while the scanner is only watching directional context.
    if state == "WATCHING" and not trendline_gate:
        levels["stop_loss"] = None
        levels["take_profit"] = None
        levels["risk_distance"] = None
        levels["reward_distance"] = None
        levels["rr"] = None
        if "target_basis" in levels:
            levels["target_basis"] = None
    if state in {"CONFIRMING", "DEVELOPING"} and direction and levels["rr"] is not None and levels["rr"] < 1.5:
        # A nearby opposing level can create poor asymmetry. Keep the levels
        # visible, but downgrade the setup rather than pretending the target is attractive.
        reasons.append("risk/reward is below the preferred 1.5R threshold")
    if (structural is not None and state in {"CONFIRMING", "DEVELOPING"} and trendline_gate
            and levels["stop_loss"] is not None and levels["take_profit"] is None):
        reasons.append("no higher-timeframe structural target in the trade direction")

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
        "strategy_version": strategy_version,
        "timeframe": "M15",
        "higher_timeframes": ["H1"],
        "state": state,
        "action": action,
        "score": score,
        "setup": setup,
        "trendline_gate": trendline_gate,
        "confirmation_alignment": confirmation_alignment,
        "strategy_valid": (
            state == "CONFIRMING"
            and trendline_gate
            and confirmation_alignment
            and (levels["rr"] or 0) >= 1.5
        ),
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
        "trendline_line": trend["line"],
        "trendline_identity": trend.get("identity"),
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
        **({"target_basis": levels.get("target_basis")} if structural is not None else {}),
        **({"trendline_retest": retest} if break_confirmation == "retest-rejection" else {}),
    }
