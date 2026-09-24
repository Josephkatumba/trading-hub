"""Trend / Momentum research strategy: trend continuation after a controlled pullback.

Registered in SHADOW (research) mode. Deterministic and rule-based: nothing is
decided by an AI model, every rule below is a fixed calculation over MT5 bars,
and every rule's outcome is written to `strategy_evidence`. It is independent
of the trendline and S/R strategies: it imports neither, and computes its own
indicators (EMA, ATR, swing pivots) in this module.

All distances are ATR-normalised (the instrument's own ATR on the timeframe in
question), so the same rules apply to every instrument. Every calculation uses
CLOSED bars only (the last bar of each timeframe is still forming); the forming
M15 close is used as the current price.

TIMEFRAMES
  D1   context only: may veto a setup when it clearly opposes the H4 trend
  H4   trend bias (required)
  H1   the setup structure: alignment, impulse and pullback
  M15  the continuation trigger and entry. Records carry timeframe "M15" (the bars
       entries, stops and outcomes are measured on; the outcome engine reads
       outcome bars at the snapshot timeframe) and setup_timeframe "H1" in the
       evidence; H1/H4/D1 are the higher timeframes.

SETUP (LONG described; SHORT is the exact mirror)
1. H4 trend: the last two H4 swing highs AND the last two H4 swing lows are rising
   (fractal pivots, 2 bars each side), the H4 EMA50 rose by >= 0.2 ATR(H4) over the
   last 5 H4 bars, and the last H4 close is above the EMA50. No H4 trend -> NO SETUP.
2. D1 context: D1 opposes when its close is below its EMA50 AND the EMA50 fell over
   the last 5 D1 bars. Opposing -> NO SETUP. Too little D1 history -> "unavailable",
   which never vetoes (recorded as such).
3. H1 alignment: EMA20 above EMA50 and the EMA50 higher than 10 H1 bars ago.
   Misaligned -> NO SETUP.
4. Momentum (the impulse leg): the highest H1 high of the last 30 closed H1 bars is
   the impulse high H; the lowest low of the 30 bars before it is the impulse origin
   L. Required: H - L >= 2.0 ATR(H1) (impulse) and a Kaufman efficiency ratio of the
   closes from L to H >= 0.35 (persistence: net move / total path). Otherwise the
   trend is not proven to have momentum -> WATCHING.
5. Pullback: the lowest low after H is the pullback low P, at least 2 and at most 15
   H1 bars after H. Retracement r = (H - P) / (H - L).
   - r < 0.236, or fewer than 2 bars: no pullback yet -> WATCHING
   - more than 15 bars: the impulse is stale -> WATCHING
   - controlled: 0.236 <= r <= 0.618, P not more than 0.5 ATR(H1) below the H1 EMA50,
     and no pullback bar is a collapse (a bearish H1 bar with range > 2.5 ATR(H1)).
   - r > 0.618, P below the EMA50 buffer, or a collapse bar: failed pullback -> NO SETUP.
   A controlled pullback without a trigger yet is DEVELOPING.
6. Continuation trigger (M15): the last closed M15 bar opened at/after the pullback
   low's H1 bar, is bullish, closes above the highs of the 4 closed M15 bars before it
   and above the M15 EMA20 -> CONFIRMING.

CONFIRMATION (strategy_valid needs every rule in CONFIRMATION_RULES):
  h4_trend, d1_not_opposed, h1_aligned, impulse, persistence, pullback_controlled,
  resumption, not_chasing (entry still below H: a pullback entry, not a breakout chase),
  stop_ok (risk between 0.5 and 3.0 ATR(H1)), target (reward > 0), min_rr (>= 1.5).

PLAN
  entry  = current price (the forming M15 close)
  stop   = P - 0.25 ATR(H1)                 (beyond the pullback low: the structure that
                                             invalidates the continuation idea)
  target = P + (H - L)                       (measured move: the impulse projected from P)
  invalidation = stop

SCORE (0-100): a transparent quality measure of a setup that already meets the
definition; it never decides a state or a confirmation (the rules above do). Each
component is stored with its raw measurement (strategy_evidence.score_components).
  h4_trend     0-20  20 x min(1, H4 EMA50 slope over 5 bars / 1.0 ATR(H4))
  persistence  0-25  25 x min(1, efficiency ratio / 0.7)
  impulse      0-15  15 x min(1, impulse / 4.0 ATR(H1))
  pullback     0-20  20 for r in [0.382, 0.5], 12 elsewhere in [0.236, 0.618], 0 otherwise
  d1_context   0-10  10 agrees, 5 unavailable/neutral, 0 opposes
  risk_reward  0-10  10 for R >= 2.0, 5 for R >= 1.5, 0 otherwise

Parameters are conventional, round starting values (EMA 20/50, ATR 14, Fibonacci
0.236/0.382/0.5/0.618, 2-bar fractals). They were chosen before looking at any
outcome and were NOT fitted to historical data. This is a research strategy: it
makes no claim of profitability.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from episode_identity import MATCHER_VERSION

from .base import MarketInput, Strategy

STRATEGY_VERSION = "tm-pullback-v1"
SETUP_FAMILY = "TM_PULLBACK_CONTINUATION"

EMA_FAST, EMA_SLOW, ATR_PERIOD = 20, 50, 14
# H4 trend bias
H4_PIVOT_STRENGTH = 2
H4_SLOPE_BARS = 5
MIN_H4_SLOPE_ATR = 0.2
# D1 context
D1_SLOPE_BARS = 5
# H1 alignment, impulse and pullback
H1_SLOPE_BARS = 10
IMPULSE_WINDOW = 30
ORIGIN_WINDOW = 30
MIN_IMPULSE_ATR = 2.0
MIN_EFFICIENCY = 0.35
MIN_PULLBACK_BARS = 2
MAX_PULLBACK_BARS = 15
MIN_RETRACEMENT = 0.236
MAX_RETRACEMENT = 0.618
IDEAL_RETRACEMENT = (0.382, 0.5)
HOLD_BUFFER_ATR = 0.5
COLLAPSE_BAR_ATR = 2.5
# M15 trigger
TRIGGER_BREAK_BARS = 4
# Plan
STOP_BUFFER_ATR = 0.25
MIN_RISK_ATR = 0.5
MAX_RISK_ATR = 3.0
MIN_RR = 1.5
# History needed (closed bars) for the EMAs/pivots to be meaningful.
MIN_BARS = {"M15": 60, "H1": 100, "H4": 60, "D1": 60}

CONFIRMATION_RULES = ("h4_trend", "d1_not_opposed", "h1_aligned", "impulse", "persistence", "pullback_controlled",
                      "resumption", "not_chasing", "stop_ok", "target", "min_rr")
PARAMETERS = {"ema": [EMA_FAST, EMA_SLOW], "atr_period": ATR_PERIOD, "min_h4_slope_atr": MIN_H4_SLOPE_ATR,
              "min_impulse_atr": MIN_IMPULSE_ATR, "min_efficiency": MIN_EFFICIENCY,
              "retracement": [MIN_RETRACEMENT, MAX_RETRACEMENT], "pullback_bars": [MIN_PULLBACK_BARS, MAX_PULLBACK_BARS],
              "stop_buffer_atr": STOP_BUFFER_ATR, "risk_atr": [MIN_RISK_ATR, MAX_RISK_ATR], "min_rr": MIN_RR}


# ---------------------------------------------------------------- indicators

def _f(bar: Mapping[str, Any], key: str) -> float:
    return float(bar[key])


def ema(values: Sequence[float], period: int) -> list[float | None]:
    """Exponential moving average, seeded with the simple mean of the first `period`
    values; None until then."""
    out: list[float | None] = [None] * len(values)
    if len(values) < period:
        return out
    alpha = 2.0 / (period + 1)
    current = sum(values[:period]) / period
    out[period - 1] = current
    for i in range(period, len(values)):
        current = alpha * values[i] + (1 - alpha) * current
        out[i] = current
    return out


def atr(rows: Sequence[Mapping[str, Any]], period: int = ATR_PERIOD) -> float:
    """Mean true range of the last `period` bars (0.0 without enough bars)."""
    if len(rows) < period + 1:
        return 0.0
    ranges = []
    for i in range(len(rows) - period, len(rows)):
        high, low, prev_close = _f(rows[i], "high"), _f(rows[i], "low"), _f(rows[i - 1], "close")
        ranges.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    return sum(ranges) / period


def pivots(rows: Sequence[Mapping[str, Any]], strength: int) -> tuple[list[float], list[float]]:
    """Fractal swing highs / lows: strictly beyond `strength` bars on each side."""
    highs = [_f(row, "high") for row in rows]
    lows = [_f(row, "low") for row in rows]
    swing_highs, swing_lows = [], []
    for i in range(strength, len(rows) - strength):
        if highs[i] > max(highs[i - strength:i]) and highs[i] > max(highs[i + 1:i + strength + 1]):
            swing_highs.append(highs[i])
        if lows[i] < min(lows[i - strength:i]) and lows[i] < min(lows[i + 1:i + strength + 1]):
            swing_lows.append(lows[i])
    return swing_highs, swing_lows


def efficiency_ratio(closes: Sequence[float]) -> float:
    """|net move| / total absolute bar-to-bar movement (1.0 = a straight line)."""
    if len(closes) < 2:
        return 0.0
    path = sum(abs(closes[i] - closes[i - 1]) for i in range(1, len(closes)))
    return abs(closes[-1] - closes[0]) / path if path > 0 else 0.0


# ------------------------------------------------------------------- rules

def h4_trend(closed: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """H4 bias: rising (falling) swing highs and lows, EMA50 slope and close vs EMA50."""
    closes = [_f(bar, "close") for bar in closed]
    slow = ema(closes, EMA_SLOW)
    unit = atr(closed)
    highs, lows = pivots(closed, H4_PIVOT_STRENGTH)
    if len(highs) >= 2 and len(lows) >= 2 and highs[-1] > highs[-2] and lows[-1] > lows[-2]:
        structure = "HIGHER_HIGHS_HIGHER_LOWS"
    elif len(highs) >= 2 and len(lows) >= 2 and highs[-1] < highs[-2] and lows[-1] < lows[-2]:
        structure = "LOWER_HIGHS_LOWER_LOWS"
    else:
        structure = "MIXED"
    slope = ((slow[-1] - slow[-1 - H4_SLOPE_BARS]) / unit) if unit > 0 and slow[-1 - H4_SLOPE_BARS] is not None else 0.0
    above = closes[-1] > slow[-1]
    if structure == "HIGHER_HIGHS_HIGHER_LOWS" and slope >= MIN_H4_SLOPE_ATR and above:
        direction = "LONG"
    elif structure == "LOWER_HIGHS_LOWER_LOWS" and slope <= -MIN_H4_SLOPE_ATR and not above:
        direction = "SHORT"
    else:
        direction = None
    return {"direction": direction, "structure": structure, "ema50_slope_atr": round(slope, 4),
            "close_above_ema50": above, "atr": unit,
            "last_swing_highs": highs[-2:], "last_swing_lows": lows[-2:]}


def d1_context(closed: Sequence[Mapping[str, Any]], direction: str) -> dict[str, Any]:
    """D1 opposes a LONG when close < EMA50 and the EMA50 is falling (mirror for SHORT)."""
    if len(closed) < MIN_BARS["D1"]:
        return {"status": "UNAVAILABLE", "opposes": False, "bars": len(closed)}
    closes = [_f(bar, "close") for bar in closed]
    slow = ema(closes, EMA_SLOW)
    slope = slow[-1] - slow[-1 - D1_SLOPE_BARS]
    below, falling = closes[-1] < slow[-1], slope < 0
    bearish, bullish = below and falling, (not below) and slope > 0
    opposes = bearish if direction == "LONG" else bullish
    agrees = bullish if direction == "LONG" else bearish
    return {"status": "OPPOSES" if opposes else "AGREES" if agrees else "NEUTRAL", "opposes": opposes,
            "close_above_ema50": not below, "ema50_slope": round(slope, 10), "bars": len(closed)}


def h1_setup(closed: Sequence[Mapping[str, Any]], direction: str, unit: float) -> dict[str, Any]:
    """H1 alignment, the impulse leg and the pullback that follows it."""
    long = direction == "LONG"
    closes = [_f(bar, "close") for bar in closed]
    fast, slow = ema(closes, EMA_FAST), ema(closes, EMA_SLOW)
    rising, falling = slow[-1] > slow[-1 - H1_SLOPE_BARS], slow[-1] < slow[-1 - H1_SLOPE_BARS]
    aligned = (fast[-1] > slow[-1] and rising) if long else (fast[-1] < slow[-1] and falling)
    n = len(closed)
    extreme_key, origin_key = ("high", "low") if long else ("low", "high")
    pick = max if long else min
    window = range(n - IMPULSE_WINDOW, n)
    extreme_value = pick(_f(closed[i], extreme_key) for i in window)
    ih = max(i for i in window if _f(closed[i], extreme_key) == extreme_value)       # most recent extreme
    origin_range = range(max(0, ih - ORIGIN_WINDOW), ih)
    origin_pick = min if long else max
    if origin_range:
        origin_value = origin_pick(_f(closed[i], origin_key) for i in origin_range)
        il = max(i for i in origin_range if _f(closed[i], origin_key) == origin_value)
    else:
        origin_value, il = extreme_value, ih
    impulse = (extreme_value - origin_value) if long else (origin_value - extreme_value)
    leg = closes[il:ih + 1]
    directional = len(leg) >= 2 and ((leg[-1] > leg[0]) if long else (leg[-1] < leg[0]))
    efficiency = efficiency_ratio(leg) if directional else 0.0
    impulse_atr = impulse / unit if unit > 0 else 0.0
    after = list(range(ih + 1, n))
    bars_since = n - 1 - ih
    if after:
        pullback_value = (min if long else max)(_f(closed[i], origin_key) for i in after)
        ip = max(i for i in after if _f(closed[i], origin_key) == pullback_value)
    else:
        pullback_value, ip = extreme_value, ih
    retracement = ((extreme_value - pullback_value) if long else (pullback_value - extreme_value)) / impulse if impulse > 0 else 0.0
    held = (pullback_value >= slow[-1] - HOLD_BUFFER_ATR * unit) if long else (pullback_value <= slow[-1] + HOLD_BUFFER_ATR * unit)
    collapse = any((_f(closed[i], "high") - _f(closed[i], "low")) > COLLAPSE_BAR_ATR * unit
                   and ((_f(closed[i], "close") < _f(closed[i], "open")) if long else (_f(closed[i], "close") > _f(closed[i], "open")))
                   for i in after)
    return {"aligned": aligned, "ema20": fast[-1], "ema50": slow[-1], "ema50_rising": rising,
            "impulse_extreme": extreme_value, "impulse_origin": origin_value, "impulse_extreme_time": closed[ih]["time"],
            "impulse_origin_time": closed[il]["time"], "impulse_bars": ih - il, "impulse": impulse,
            "impulse_atr": round(impulse_atr, 4), "efficiency": round(efficiency, 4),
            "pullback_extreme": pullback_value, "pullback_time": closed[ip]["time"], "pullback_bars": bars_since,
            "retracement": round(retracement, 4), "held_above_ema50": held, "collapse_bar": collapse}


def m15_trigger(closed: Sequence[Mapping[str, Any]], direction: str, since_time: float) -> dict[str, Any]:
    """Continuation: the last closed M15 bar breaks the previous bars' extreme, in trend direction."""
    long = direction == "LONG"
    closes = [_f(bar, "close") for bar in closed]
    fast = ema(closes, EMA_FAST)
    bar = closed[-1]
    prior = closed[-1 - TRIGGER_BREAK_BARS:-1]
    close, open_ = _f(bar, "close"), _f(bar, "open")
    if long:
        level = max(_f(row, "high") for row in prior)
        broke, beyond_ema, body = close > level, close > fast[-1], close > open_
    else:
        level = min(_f(row, "low") for row in prior)
        broke, beyond_ema, body = close < level, close < fast[-1], close < open_
    after_pullback = float(bar["time"]) >= float(since_time)
    return {"resumption": bool(broke and beyond_ema and body and after_pullback), "break_level": level, "broke": broke,
            "beyond_ema20": beyond_ema, "candle_in_direction": body, "after_pullback_low": after_pullback,
            "candle_time": bar["time"], "ema20": fast[-1]}


def _score(h4: dict[str, Any], h1: dict[str, Any] | None, d1: dict[str, Any], controlled: bool,
           rr: float | None) -> tuple[dict[str, int], dict[str, dict[str, Any]]]:
    slope = abs(h4["ema50_slope_atr"])
    efficiency = h1["efficiency"] if h1 else 0.0
    impulse_atr = h1["impulse_atr"] if h1 else 0.0
    retracement = h1["retracement"] if h1 else None
    ideal = controlled and IDEAL_RETRACEMENT[0] <= retracement <= IDEAL_RETRACEMENT[1]
    components = {
        "h4_trend": (round(20 * min(1.0, slope / 1.0)), 20, {"ema50_slope_atr": h4["ema50_slope_atr"]}),
        "persistence": (round(25 * min(1.0, efficiency / 0.7)), 25, {"efficiency_ratio": efficiency}),
        "impulse": (round(15 * min(1.0, impulse_atr / 4.0)), 15, {"impulse_atr": impulse_atr}),
        "pullback": (20 if ideal else 12 if controlled else 0, 20, {"retracement": retracement, "controlled": controlled}),
        "d1_context": ({"AGREES": 10, "OPPOSES": 0}.get(d1["status"], 5), 10, {"status": d1["status"]}),
        "risk_reward": (10 if (rr or 0) >= 2.0 else 5 if (rr or 0) >= MIN_RR else 0, 10, {"rr": rr}),
    }
    breakdown = {name: points for name, (points, _, _) in components.items()}
    detail = {name: {"points": points, "max": maximum, "measure": measure} for name, (points, maximum, measure) in components.items()}
    return breakdown, detail


def _no_setup(reason: str, **extra: Any) -> dict[str, Any]:
    return {"strategy_version": STRATEGY_VERSION, "timeframe": "M15", "higher_timeframes": ["H1", "H4", "D1"],
            "state": "NO SETUP", "direction": None, "setup": "No trend/momentum setup", "setup_family": None,
            "strategy_valid": False, "reason": reason, "score": 0, "score_breakdown": {},
            "entry": None, "stop_loss": None, "take_profit": None, "invalidation_hint": None, "rr": None, **extra}


def analyze_trend_momentum(market: MarketInput) -> dict[str, Any]:
    bars = dict(market.bars) if market.bars else {"M15": list(market.rows), "H1": list(market.higher_rows or [])}
    closed = {tf: list(bars.get(tf) or [])[:-1] for tf in ("M15", "H1", "H4", "D1")}
    context = {"method": STRATEGY_VERSION, "setup_timeframe": "H1", "trigger_timeframe": "M15", "parameters": PARAMETERS,
               "timeframes_used": sorted(tf for tf in closed if closed[tf]),
               "unavailable_timeframes": dict(market.unavailable_timeframes)}
    for tf in ("M15", "H1", "H4"):
        if len(closed[tf]) < MIN_BARS[tf]:
            return _no_setup(f"Insufficient {tf} history for trend/momentum ({len(closed[tf])} closed bars, needs {MIN_BARS[tf]}).",
                             strategy_evidence=context)
    unit = atr(closed["H1"])
    if unit <= 0:
        return _no_setup("No H1 volatility (ATR) available.", strategy_evidence=context)
    price = _f(bars["M15"][-1], "close")
    h4 = h4_trend(closed["H4"])
    evidence: dict[str, Any] = {**context, "trend": {"h4": h4}, "atr": {"H1": unit, "H4": h4["atr"]}}
    if h4["direction"] is None:
        return _no_setup(f"No H4 trend (structure {h4['structure']}, EMA50 slope {h4['ema50_slope_atr']:.2f} ATR).",
                         atr=unit, strategy_evidence=evidence)
    direction = h4["direction"]
    long = direction == "LONG"
    d1 = d1_context(closed["D1"], direction)
    evidence["trend"]["d1"] = d1
    if d1["opposes"]:
        return _no_setup(f"D1 opposes the H4 {'up' if long else 'down'}trend.", atr=unit, strategy_evidence=evidence)
    h1 = h1_setup(closed["H1"], direction, unit)
    evidence["trend"]["h1"] = {key: h1[key] for key in ("aligned", "ema20", "ema50", "ema50_rising")}
    if not h1["aligned"]:
        return _no_setup(f"H1 is not aligned with the H4 {'up' if long else 'down'}trend (EMA20/EMA50).", atr=unit,
                         strategy_evidence=evidence)

    gates: dict[str, bool] = {"h4_trend": True, "d1_not_opposed": True, "h1_aligned": True}
    gates["impulse"] = h1["impulse_atr"] >= MIN_IMPULSE_ATR
    gates["persistence"] = h1["efficiency"] >= MIN_EFFICIENCY
    pullback_started = h1["pullback_bars"] >= MIN_PULLBACK_BARS and h1["retracement"] >= MIN_RETRACEMENT
    stale = h1["pullback_bars"] > MAX_PULLBACK_BARS
    failed_reasons = [text for failed, text in (
        (h1["retracement"] > MAX_RETRACEMENT, f"retraced {h1['retracement']:.2f} of the impulse (max {MAX_RETRACEMENT})"),
        (not h1["held_above_ema50"], f"pullback extended beyond the H1 EMA50 by more than {HOLD_BUFFER_ATR} ATR"),
        (h1["collapse_bar"], f"a pullback bar exceeded {COLLAPSE_BAR_ATR} ATR against the trend")) if failed]
    gates["pullback_controlled"] = pullback_started and not stale and not failed_reasons
    evidence["momentum"] = {key: h1[key] for key in ("impulse_extreme", "impulse_origin", "impulse_extreme_time", "impulse_origin_time",
                                                     "impulse_bars", "impulse", "impulse_atr", "efficiency")}
    evidence["momentum"].update(min_impulse_atr=MIN_IMPULSE_ATR, min_efficiency=MIN_EFFICIENCY)
    evidence["pullback"] = {key: h1[key] for key in ("pullback_extreme", "pullback_time", "pullback_bars", "retracement",
                                                     "held_above_ema50", "collapse_bar")}
    evidence["pullback"].update(started=pullback_started, stale=stale, failed=failed_reasons,
                                controlled=gates["pullback_controlled"])
    trigger = m15_trigger(closed["M15"], direction, h1["pullback_time"])
    gates["resumption"] = trigger["resumption"] and gates["pullback_controlled"]
    evidence["trigger"] = trigger

    if gates["impulse"] and gates["persistence"] and pullback_started and not stale and failed_reasons:
        breakdown, detail = _score(h4, h1, d1, False, None)
        evidence["score_components"] = detail
        return _no_setup("Pullback failed: " + "; ".join(failed_reasons) + ".", atr=unit, strategy_evidence=evidence)

    extreme, pullback, impulse = h1["impulse_extreme"], h1["pullback_extreme"], h1["impulse"]
    entry = price
    stop = pullback - STOP_BUFFER_ATR * unit if long else pullback + STOP_BUFFER_ATR * unit
    target = pullback + impulse if long else pullback - impulse
    risk = (entry - stop) if long else (stop - entry)
    reward = (target - entry) if long else (entry - target)
    rr = round(reward / risk, 2) if risk > 0 else None
    gates["not_chasing"] = entry < extreme if long else entry > extreme
    gates["stop_ok"] = MIN_RISK_ATR * unit <= risk <= MAX_RISK_ATR * unit
    gates["target"] = reward > 0
    gates["min_rr"] = rr is not None and rr >= MIN_RR

    if not (gates["impulse"] and gates["persistence"]):
        state, reason = "WATCHING", (f"Trend aligned, momentum not proven: impulse {h1['impulse_atr']:.2f} ATR (min {MIN_IMPULSE_ATR}), "
                                     f"efficiency {h1['efficiency']:.2f} (min {MIN_EFFICIENCY}).")
    elif stale:
        state, reason = "WATCHING", f"Impulse is stale: {h1['pullback_bars']} H1 bars since the impulse extreme (max {MAX_PULLBACK_BARS})."
    elif not pullback_started:
        state, reason = "WATCHING", (f"Impulsive trend without a pullback yet (retracement {h1['retracement']:.2f}, "
                                     f"{h1['pullback_bars']} bars; needs {MIN_RETRACEMENT} and {MIN_PULLBACK_BARS} bars).")
    elif not gates["resumption"]:
        state, reason = "DEVELOPING", (f"Controlled pullback ({h1['retracement']:.2f} of the impulse) inside the H4 trend; "
                                       f"waiting for an M15 continuation trigger.")
    else:
        state, reason = "CONFIRMING", "M15 continuation after a controlled pullback"
    valid = state == "CONFIRMING" and all(gates[name] for name in CONFIRMATION_RULES)
    failed = [name for name in CONFIRMATION_RULES if not gates[name]]
    if state == "CONFIRMING":
        reason += "; all confirmation rules passed." if valid else "; not confirmed: " + ", ".join(failed) + "."
    planned = state in {"DEVELOPING", "CONFIRMING"} and gates["target"] and risk > 0
    breakdown, detail = _score(h4, h1, d1, gates["pullback_controlled"], rr if planned else None)
    evidence["score_components"] = detail
    evidence["confirmation"] = {"rules": {name: gates[name] for name in CONFIRMATION_RULES}, "passed": valid, "failed": failed}
    evidence["plan"] = {"entry": entry if planned else None, "stop": stop if planned else None, "target": target if planned else None,
                        "risk": risk if planned else None, "reward": reward if planned else None, "rr": rr if planned else None,
                        "min_rr": MIN_RR, "structure_invalidation": pullback,
                        "method": "stop beyond the pullback extreme by 0.25 ATR(H1); target = impulse projected from the pullback extreme"}
    setup = ("Bullish" if long else "Bearish") + " pullback continuation"
    return {"strategy_version": STRATEGY_VERSION, "timeframe": "M15", "higher_timeframes": ["H1", "H4", "D1"],
            "state": state, "direction": direction, "setup": setup, "setup_family": SETUP_FAMILY,
            "strategy_valid": valid, "reason": reason,
            "trigger": None if valid else ("M15 close above the last 4 highs and EMA20 after the pullback low" if long
                                           else "M15 close below the last 4 lows and EMA20 after the pullback high"),
            "entry": entry if planned else None, "stop_loss": stop if planned else None,
            "take_profit": target if planned else None, "invalidation_hint": stop if planned else None,
            "rr": rr if planned else None, "risk_distance": risk if planned else None,
            "reward_distance": reward if planned else None,
            "atr": unit,              # ATR(H1): the setup's scale (episode continuity tolerance uses it)
            "score": min(100, sum(breakdown.values())), "score_breakdown": breakdown, "strategy_evidence": evidence}


class TrendMomentumStrategy(Strategy):
    strategy_id = "trend_momentum"
    version = STRATEGY_VERSION
    timeframe = "M15"                   # trigger/entry bars (see TIMEFRAMES); the setup structure is H1
    higher_timeframes = ("H1", "H4", "D1")
    lifecycle = MATCHER_VERSION         # the existing episode matcher/lifecycle, scoped to this strategy
    # H4 is required (the trend bias); D1 is context, used when available, never required.
    data_requirements = {"M15": 300, "H1": 160, "H4": 200}

    def evaluate(self, market: MarketInput) -> dict[str, Any]:
        return analyze_trend_momentum(market)
