"""Bucketed, causal features describing one setup at its entry instant.

All features are read from bars CLOSED at or before the entry time (`ctx.last_closed`), so the same
function serves the live engine and historical research without look-ahead. Each feature is a small
categorical bucket: an additive scorecard over buckets is robust, explainable and hard to overfit.

Direction-relative features are expressed as "with" / "against" the trade so longs and shorts share
evidence. Tick volume is broker tick activity, not traded volume; it is labelled as such and the
model only uses it if historical evidence supports it.
"""
from __future__ import annotations

import bisect
import math
from datetime import datetime, timezone
from typing import Any

from signal_quality import regime as regime_mod

FAMILIES = {
    # trend-following / continuation
    "ema_crossover": "trend", "ema_pullback": "trend", "macd_momentum": "trend", "ichimoku": "trend",
    "trend_momentum": "trend", "fair_value_gap": "trend", "order_block_retest": "trend", "smc": "trend",
    # breakout
    "breakout": "breakout", "donchian": "breakout", "london_breakout": "breakout", "opening_range_breakout": "breakout",
    "atr_breakout": "breakout", "inside_bar_breakout": "breakout", "trendline_break_retest": "breakout",
    # mean reversion / level rejection
    "bollinger_reversion": "reversion", "rsi_divergence": "reversion", "liquidity_sweep": "reversion",
    "support_resistance": "reversion", "trendline_bounce": "reversion",
    # structure reversal
    "market_structure_break": "reversal",
}


def family(strategy: str) -> str:
    return FAMILIES.get(strategy, "other")


def session(utc: float) -> str:
    hour = datetime.fromtimestamp(utc, timezone.utc).hour
    return ("ASIA" if hour < 7 else "LONDON" if hour < 12 else "LONDON_NY_OVERLAP" if hour < 16
            else "NEW_YORK" if hour < 21 else "LATE_US")


def bucket(value: float | None, edges: tuple[float, ...], labels: tuple[str, ...]) -> str:
    """labels has len(edges) + 1 entries: (-inf, e0), [e0, e1), ..., [e_last, inf)."""
    if value is None or not math.isfinite(value):
        return "unknown"
    for edge, label in zip(edges, labels):
        if value < edge:
            return label
    return labels[-1]


def _side(value: float, long: bool) -> str:
    if not math.isfinite(value) or value == 0:
        return "neutral"
    return "with" if (value > 0) == long else "against"


def _known_swings(ctx: Any, i: int, keep: int = 40) -> tuple[list, list]:
    """The last `keep` H1 swing highs / lows already CONFIRMED at bar i (pivot index, confirm index, price)."""
    key = ("H1", "swing_confirm_index", ())
    highs, lows = ctx.get("H1", "swing_points")
    if key not in ctx._cache:
        ctx._cache[key] = ([p[1] for p in highs], [p[1] for p in lows])
    hc, lc = ctx._cache[key]
    h_end, l_end = bisect.bisect_right(hc, i), bisect.bisect_right(lc, i)
    return highs[max(0, h_end - keep):h_end], lows[max(0, l_end - keep):l_end]


def compute(ctx: Any, at_utc: float, strategy: str, direction: str, entry: float, stop: float,
            target: float | None) -> dict[str, Any]:
    """Features (buckets) and the raw numbers behind them for a setup entered at `at_utc`."""
    long = direction == "LONG"
    sign = 1 if long else -1
    i = ctx.last_closed("H1", at_utc)
    reg = regime_mod.classify(ctx, at_utc)
    raw: dict[str, Any] = {"regime": reg}
    f: dict[str, str] = {"strategy": strategy, "family": family(strategy), "symbol": ctx.symbol,
                         "session": session(at_utc), "regime": reg["regime"]}
    f["family_regime"] = f"{f['family']}:{reg['regime']}"
    f["regime_trend"] = "flat" if not reg.get("trend") else ("with" if reg["trend"] == sign else "against")
    risk = abs(entry - stop)
    if i < 210 or risk <= 0:
        return {"features": f, "raw": raw}
    r = regime_mod.arrays(ctx, "H1")
    a = ctx.a["H1"]
    close, atr = float(a["close"][i]), float(r["atr"][i])
    # higher-timeframe trend
    if "H4" in ctx.a and (j4 := ctx.last_closed("H4", at_utc)) >= 200:
        e50, e200 = ctx.get("H4", "ema", 50)[j4], ctx.get("H4", "ema", 200)[j4]
        c4 = ctx.a["H4"]["close"][j4]
        votes = [_side(e50 - e200, long), _side(c4 - e50, long)]
        f["htf_h4"] = "with" if votes.count("with") == 2 else "against" if votes.count("against") == 2 else "mixed"
    else:
        f["htf_h4"] = "unknown"
    if "D1" in ctx.a and (jd := ctx.last_closed("D1", at_utc)) >= 60:
        f["htf_d1"] = _side(ctx.a["D1"]["close"][jd] - ctx.get("D1", "ema", 50)[jd], long)
    else:
        f["htf_d1"] = "unknown"
    # H1 market structure: the last two confirmed swing highs and lows
    highs, lows = _known_swings(ctx, i)
    hs, ls = highs[-2:], lows[-2:]
    if len(hs) == 2 and len(ls) == 2:
        up = hs[1][2] > hs[0][2] and ls[1][2] > ls[0][2]
        down = hs[1][2] < hs[0][2] and ls[1][2] < ls[0][2]
        f["structure"] = ("with" if up == long else "against") if (up or down) else "mixed"
    else:
        f["structure"] = "unknown"
    # momentum and trend strength
    adx, plus, minus = float(r["adx"][i]), float(r["plus_di"][i]), float(r["minus_di"][i])
    f["adx"] = bucket(adx, (18, 25, 35), ("<18", "18-25", "25-35", ">=35"))
    f["di"] = _side(plus - minus, long)
    rsi = float(ctx.get("H1", "rsi")[i])
    rsi_dir = rsi if long else 100 - rsi
    f["rsi"] = bucket(rsi_dir, (35, 50, 65, 75), ("<35", "35-50", "50-65", "65-75", ">=75"))
    line, sig = ctx.get("H1", "macd")
    hist, prev = float(line[i] - sig[i]), float(line[i - 1] - sig[i - 1])
    side = _side(hist, long)
    f["macd"] = side + ("_rising" if side == "with" and sign * (hist - prev) > 0 else "")
    # volatility
    raw.update(adx=adx, rsi=rsi, atr_h1=atr)
    f["atr_ratio"] = bucket(float(r["atr_ratio"][i]), (0.75, 1.0, 1.35), ("<0.75", "0.75-1", "1-1.35", ">=1.35"))
    f["bb_width"] = bucket(float(r["width_pct"][i]), (0.2, 0.5, 0.8), ("<20%", "20-50%", "50-80%", ">=80%"))
    # entry location: extension from EMA20 in ATR, stop size in ATR
    ext = sign * (close - float(r["ema20"][i])) / atr if atr > 0 else float("nan")
    f["extension"] = bucket(ext, (-0.5, 0.5, 1.5, 2.5), ("pullback", "at_mean", "0.5-1.5", "1.5-2.5", ">=2.5"))
    f["stop_atr"] = bucket(risk / atr if atr > 0 else None, (0.5, 1.0, 2.0), ("<0.5", "0.5-1", "1-2", ">=2"))
    # room to the nearest opposing confirmed H1 swing level (support / resistance), in R
    if long:
        levels = [p[2] for p in highs if i - p[0] <= 120 and p[2] > entry]
        room = (min(levels) - entry) / risk if levels else None
    else:
        levels = [p[2] for p in lows if i - p[0] <= 120 and p[2] < entry]
        room = (entry - max(levels)) / risk if levels else None
    f["room"] = "clear" if room is None else bucket(room, (0.5, 1.0, 2.0), ("<0.5R", "0.5-1R", "1-2R", ">=2R"))
    planned = abs(target - entry) / risk if target is not None else None
    f["planned_rr"] = "trailing" if planned is None else bucket(planned, (1.2, 1.8, 2.5, 3.5), ("<1.2", "1.2-1.8", "1.8-2.5", "2.5-3.5", ">=3.5"))
    if planned is not None and room is not None:
        f["target_vs_level"] = "beyond_level" if planned > room else "before_level"
    else:
        f["target_vs_level"] = "clear"
    vol = a["volume"]
    if i >= 21 and vol[i - 20:i].mean() > 0:
        f["tick_activity"] = bucket(float(vol[i] / vol[i - 20:i].mean()), (0.8, 1.3), ("low", "normal", "high"))
    else:
        f["tick_activity"] = "unknown"
    raw.update(room_r=room, planned_rr=planned, extension_atr=ext, stop_atr=risk / atr if atr > 0 else None)
    return {"features": f, "raw": raw}
