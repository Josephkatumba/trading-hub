"""Support & Resistance strategy (deterministic, rule-based; registered in SHADOW mode).

Nothing here is decided by an AI model: every decision below is a fixed rule
over MT5 bars, and every rule's outcome is written to `strategy_evidence`.

All distances are ATR-normalised (M15 and H1 ATR of the instrument itself), so
the same rules apply to XAUUSD, BTCUSD, EURUSD, USDJPY, NAS100, GER40, ...
without per-instrument price constants.

LEVELS
1. Reactions: fractal swing highs/lows (same rule as scanner._swings) on every available
   timeframe, excluding each timeframe's still-forming last bar. Pivot strength
   (bars each side): M15 3, H1 3, H4 2, D1 2.
2. Clustering: reactions (any timeframe) whose prices lie within one zone
   diameter (2 x tolerance, tolerance = 0.35 x ATR(H1)) form one level. Level
   price = timeframe-weighted mean; zone = [min, max] of its reactions, at
   least +/- tolerance/2 around the price.
3. Strength: timeframe weights M15 1, H1 2, H4 3, D1 4. A level is meaningful
   with >= 3 reactions (strength >= 4), or >= 2 reactions of which at least one
   is on H4/D1 (higher-timeframe confluence). Two small M15 swings are not a
   level. H4/D1 reactions add strength and evidence but are never required.

SETUPS (evaluated on the last CLOSED M15 candle; the forming candle is price only)
- LONG from the nearest meaningful level at/below price (support); SHORT from the
  nearest at/above price (resistance). Both are evaluated; the stronger result wins.
- Family SR_BREAK_RETEST when the level was decisively crossed in the other
  direction within the last 19 closed M15 bars (the touch window plus the approach
  window: a break precedes the approach that precedes the test; resistance turned support, or
  support turned resistance); otherwise SR_BOUNCE.
- A touch is a TEST only when price came from at least 1.0 ATR(H1) away from the
  zone (on the trade side) within the 16 closed bars before the touch. Price
  drifting around a level is consolidation, not a test: it stays WATCHING.
- States: WATCHING (within 1.0 ATR(H1) of the zone), DEVELOPING (a clean test in
  the last 3 closed bars, holding), CONFIRMING (rejection + momentum).
  A close more than 0.25 ATR(M15) through the zone is a failed rejection: no
  setup from that level in that direction.

CONFIRMATION (all required for strategy_valid; see CONFIRMATION_RULES)
  touched     : a closed bar in the last 3 reached the zone
  clean_test  : price approached from >= 1.0 ATR(H1) away before that touch
  held        : no close in the last 3 bars more than 0.25 ATR(M15) through the zone
  rejection   : last closed candle closes outside the zone, in the direction of the
                trade, in the favourable 40% of its range (close position >= 0.6)
  momentum    : last closed candle closes beyond the previous close, in the trade direction
  not_chasing : entry within 1.0 ATR(H1) of the zone edge
  stop_ok     : risk between 0.5 ATR(M15) and 2.5 ATR(H1)
  target      : a further meaningful level exists in the trade direction
  min_rr      : reward / risk >= 1.5

PLAN
  entry  = current price (the forming bar's close, after the confirmed rejection)
  stop   = beyond the zone by 0.5 ATR(M15)
  target = the near edge of the next meaningful level in the trade direction
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from episode_identity import MATCHER_VERSION
from scanner import _atr

from .base import MarketInput, Strategy

STRATEGY_VERSION = "sr-levels-v1"

PIVOT_STRENGTH = {"M15": 3, "H1": 3, "H4": 2, "D1": 2}
TIMEFRAME_WEIGHT = {"M15": 1, "H1": 2, "H4": 3, "D1": 4}
HIGHER_TIMEFRAMES = ("H4", "D1")
TOLERANCE_ATR_H1 = 0.35
MIN_REACTIONS = 3            # ... or HTF_MIN_REACTIONS with H4/D1 confluence
MIN_STRENGTH = 4
HTF_MIN_REACTIONS = 2
TOUCH_LOOKBACK = 3
TEST_LOOKBACK = 16
TEST_DISTANCE_ATR_H1 = 1.0
BREAK_LOOKBACK = TOUCH_LOOKBACK + TEST_LOOKBACK   # a break precedes the approach that precedes the touch
APPROACH_ATR_H1 = 1.0
MAX_CHASE_ATR_H1 = 1.0
BREAK_BUFFER_ATR_M15 = 0.25
STOP_BUFFER_ATR_M15 = 0.5
MIN_RISK_ATR_M15 = 0.5
MAX_RISK_ATR_H1 = 2.5
REJECTION_CLOSE_POSITION = 0.6
MIN_RR = 1.5
MIN_M15_BARS = 60

CONFIRMATION_RULES = ("touched", "clean_test", "held", "rejection", "momentum", "not_chasing", "stop_ok", "target", "min_rr")
STATE_RANK = {"NO SETUP": 0, "WATCHING": 1, "DEVELOPING": 2, "CONFIRMING": 3}


def _f(bar: Mapping[str, Any], key: str) -> float:
    return float(bar[key])


def swing_pivots(rows: Sequence[Mapping[str, Any]], strength: int) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    """Fractal swings, identical to scanner._swings (strictly beyond `strength` bars on
    each side), computed on pre-extracted float lists with slice max/min for speed."""
    highs = [float(row["high"]) for row in rows]
    lows = [float(row["low"]) for row in rows]
    swing_highs, swing_lows = [], []
    for i in range(strength, len(rows) - strength):
        high, low = highs[i], lows[i]
        if high > max(highs[i - strength:i]) and high > max(highs[i + 1:i + strength + 1]):
            swing_highs.append((i, high))
        if low < min(lows[i - strength:i]) and low < min(lows[i + 1:i + strength + 1]):
            swing_lows.append((i, low))
    return swing_highs, swing_lows


def find_levels(bars: Mapping[str, Sequence[Mapping[str, Any]]], tolerance: float) -> list[dict[str, Any]]:
    """Meaningful S/R levels from swing reactions on all available timeframes, sorted by price."""
    pivots = []
    for timeframe, strength in PIVOT_STRENGTH.items():
        rows = list(bars.get(timeframe) or [])[:-1]          # drop the forming bar
        if len(rows) < 2 * strength + 1:
            continue
        highs, lows = swing_pivots(rows, strength)
        for kind, points in (("high", highs), ("low", lows)):
            for index, price in points:
                pivots.append({"timeframe": timeframe, "price": float(price), "kind": kind, "time": rows[index]["time"]})
    pivots.sort(key=lambda pivot: (pivot["price"], pivot["timeframe"], pivot["kind"]))
    clusters: list[list[dict[str, Any]]] = []
    for pivot in pivots:
        if clusters and pivot["price"] - clusters[-1][0]["price"] <= 2 * tolerance:
            clusters[-1].append(pivot)
        else:
            clusters.append([pivot])
    levels = []
    for cluster in clusters:
        weights = [TIMEFRAME_WEIGHT[p["timeframe"]] for p in cluster]
        strength = sum(weights)
        higher = sum(1 for p in cluster if p["timeframe"] in HIGHER_TIMEFRAMES)
        repeated = len(cluster) >= MIN_REACTIONS and strength >= MIN_STRENGTH
        confluence = len(cluster) >= HTF_MIN_REACTIONS and higher >= 1
        if not (repeated or confluence):
            continue
        price = sum(p["price"] * w for p, w in zip(cluster, weights)) / strength
        by_timeframe = {tf: sum(1 for p in cluster if p["timeframe"] == tf) for tf in PIVOT_STRENGTH if any(p["timeframe"] == tf for p in cluster)}
        htf = sum(by_timeframe.get(tf, 0) for tf in HIGHER_TIMEFRAMES)
        levels.append({
            "price": price,
            "zone_low": min(min(p["price"] for p in cluster), price - tolerance / 2),
            "zone_high": max(max(p["price"] for p in cluster), price + tolerance / 2),
            "reactions": len(cluster), "strength": strength, "reactions_by_timeframe": by_timeframe,
            "higher_timeframe_reactions": htf,
            "swing_highs": sum(1 for p in cluster if p["kind"] == "high"),
            "swing_lows": sum(1 for p in cluster if p["kind"] == "low"),
            "last_reaction_time": max(p["time"] for p in cluster),
        })
    return levels


def _crossed(closed: Sequence[Mapping[str, Any]], level: dict[str, Any], direction: str, buffer: float) -> bool:
    """A decisive break within the break window: price closed on the far side of the
    whole zone (below it for an UP break, above it for DOWN) and later closed more
    than `buffer` beyond the other edge. Leaving the zone after a touch is not a break."""
    window = closed[-BREAK_LOOKBACK:]
    beyond_start = False
    for bar in window:
        close = _f(bar, "close")
        if direction == "UP":
            if close < level["zone_low"]:
                beyond_start = True
            elif beyond_start and close > level["zone_high"] + buffer:
                return True
        else:
            if close > level["zone_high"]:
                beyond_start = True
            elif beyond_start and close < level["zone_low"] - buffer:
                return True
    return False


def evaluate_level(level: dict[str, Any], side: str, levels: list[dict[str, Any]], closed: Sequence[Mapping[str, Any]],
                   price: float, atr_m15: float, atr_h1: float) -> dict[str, Any]:
    """All S/R rules for one level in one direction ("LONG" at support, "SHORT" at resistance)."""
    long = side == "LONG"
    zl, zh = level["zone_low"], level["zone_high"]
    buffer = BREAK_BUFFER_ATR_M15 * atr_m15
    recent = closed[-TOUCH_LOOKBACK:]
    confirm, previous = closed[-1], closed[-2]
    distance = (price - zh) if long else (zl - price)          # <0 means price is inside the zone
    gates: dict[str, bool] = {}
    gates["near_level"] = distance <= APPROACH_ATR_H1 * atr_h1
    touch_bars = [i for i, bar in enumerate(reversed(recent)) if (_f(bar, "low") <= zh if long else _f(bar, "high") >= zl)]
    gates["touched"] = bool(touch_bars)
    # A test needs an approach: before the earliest touch in the window, price closed
    # at least TEST_DISTANCE away from the zone on the trade side.
    first_touch = len(closed) - 1 - max(touch_bars) if touch_bars else len(closed) - 1
    before = closed[max(0, first_touch - TEST_LOOKBACK):first_touch]
    excursion = max((((_f(bar, "close") - zh) if long else (zl - _f(bar, "close"))) for bar in before), default=0.0)
    gates["clean_test"] = excursion >= TEST_DISTANCE_ATR_H1 * atr_h1
    gates["held"] = not any((_f(bar, "close") < zl - buffer) if long else (_f(bar, "close") > zh + buffer) for bar in recent)
    high, low, open_, close = (_f(confirm, key) for key in ("high", "low", "open", "close"))
    span = high - low
    position = ((close - low) / span if long else (high - close) / span) if span > 0 else 0.0
    gates["rejection"] = bool(span > 0 and (close > zh if long else close < zl) and (close > open_ if long else close < open_)
                              and position >= REJECTION_CLOSE_POSITION)
    gates["momentum"] = close > _f(previous, "close") if long else close < _f(previous, "close")
    entry = price
    gates["not_chasing"] = ((entry - zh) if long else (zl - entry)) <= MAX_CHASE_ATR_H1 * atr_h1
    stop = (zl - STOP_BUFFER_ATR_M15 * atr_m15) if long else (zh + STOP_BUFFER_ATR_M15 * atr_m15)
    risk = (entry - stop) if long else (stop - entry)
    gates["stop_ok"] = MIN_RISK_ATR_M15 * atr_m15 <= risk <= MAX_RISK_ATR_H1 * atr_h1
    beyond = [other for other in levels if other is not level
              and ((other["zone_low"] > entry) if long else (other["zone_high"] < entry))]
    target_level = (min(beyond, key=lambda other: other["zone_low"]) if long else max(beyond, key=lambda other: other["zone_high"])) if beyond else None
    target = (target_level["zone_low"] if long else target_level["zone_high"]) if target_level else None
    reward = ((target - entry) if long else (entry - target)) if target is not None else None
    rr = round(reward / risk, 2) if reward is not None and risk > 0 else None
    gates["target"] = target is not None and reward is not None and reward > 0
    gates["min_rr"] = rr is not None and rr >= MIN_RR
    family = "SR_BREAK_RETEST" if _crossed(closed, level, "UP" if long else "DOWN", buffer) else "SR_BOUNCE"

    if not gates["near_level"] or not gates["held"]:
        state = "NO SETUP"
    elif not (gates["touched"] and gates["clean_test"]):
        state = "WATCHING"
    elif gates["rejection"] and gates["momentum"]:
        state = "CONFIRMING"
    else:
        state = "DEVELOPING"
    valid = state == "CONFIRMING" and all(gates[name] for name in CONFIRMATION_RULES)
    planned = state in {"DEVELOPING", "CONFIRMING"} and gates["target"] and risk > 0
    return {"side": side, "level": level, "family": family, "state": state, "valid": valid, "gates": gates,
            "distance": distance, "touch_bars_ago": touch_bars[0] if touch_bars else None,
            "approach_atr_h1": round(excursion / atr_h1, 3),
            "close_position": round(position, 3), "entry": entry, "stop": stop if planned else None,
            "target": target if planned else None, "target_level": target_level, "risk": risk if planned else None,
            "reward": reward if planned else None, "rr": rr if planned else None, "confirm_time": confirm["time"]}


def failed_level(levels: list[dict[str, Any]], closed: Sequence[Mapping[str, Any]], price: float,
                 buffer: float) -> dict[str, Any] | None:
    """The level price just closed through (a failed rejection): the nearest level, with a
    close on its original side within the touch window and price now more than `buffer`
    beyond it. SUPPORT failed = price broke down; RESISTANCE failed = price broke up."""
    if not levels:
        return None
    level = min(levels, key=lambda item: abs(item["price"] - price))
    earlier = [_f(bar, "close") for bar in closed[-TOUCH_LOOKBACK - 1:-1]]
    if price < level["zone_low"] - buffer and any(close >= level["zone_low"] for close in earlier):
        return {"type": "SUPPORT", "price": level["price"], "zone_low": level["zone_low"], "zone_high": level["zone_high"]}
    if price > level["zone_high"] + buffer and any(close <= level["zone_high"] for close in earlier):
        return {"type": "RESISTANCE", "price": level["price"], "zone_low": level["zone_low"], "zone_high": level["zone_high"]}
    return None


def _rank(candidate: dict[str, Any]) -> tuple:
    return (candidate["valid"], STATE_RANK[candidate["state"]], candidate["level"]["strength"], -candidate["distance"])


def _no_setup(reason: str, **extra: Any) -> dict[str, Any]:
    return {"strategy_version": STRATEGY_VERSION, "timeframe": "M15", "higher_timeframes": ["H1", "H4", "D1"],
            "state": "NO SETUP", "direction": None, "setup": "No S/R setup", "setup_family": None,
            "strategy_valid": False, "reason": reason, "score": 0, "score_breakdown": {},
            "entry": None, "stop_loss": None, "take_profit": None, "invalidation_hint": None, "rr": None, **extra}


def analyze_support_resistance(market: MarketInput) -> dict[str, Any]:
    bars = dict(market.bars) if market.bars else {"M15": list(market.rows), "H1": list(market.higher_rows or [])}
    m15 = list(bars.get("M15") or [])
    if len(m15) < MIN_M15_BARS:
        return _no_setup("Insufficient M15 history for S/R levels.")
    closed = m15[:-1]
    price = _f(m15[-1], "close")
    atr_m15 = _atr(m15)
    h1 = list(bars.get("H1") or [])
    atr_h1 = _atr(h1) if len(h1) > 15 else 0.0
    atr_basis = "H1"
    if atr_h1 <= 0:
        atr_h1, atr_basis = 2 * atr_m15, "2xM15 (H1 unavailable)"
    if atr_m15 <= 0 or atr_h1 <= 0:
        return _no_setup("No volatility (ATR) available to size S/R zones.", atr=atr_m15)
    tolerance = TOLERANCE_ATR_H1 * atr_h1
    levels = find_levels(bars, tolerance)
    supports = [level for level in levels if level["price"] <= price + tolerance / 2]
    resistances = [level for level in levels if level["price"] >= price - tolerance / 2]
    candidates = []
    if supports:
        candidates.append(evaluate_level(max(supports, key=lambda level: level["price"]), "LONG", levels, closed, price, atr_m15, atr_h1))
    if resistances:
        candidates.append(evaluate_level(min(resistances, key=lambda level: level["price"]), "SHORT", levels, closed, price, atr_m15, atr_h1))
    context = {"levels_found": len(levels), "tolerance": tolerance, "atr": {"M15": atr_m15, "H1": atr_h1, "H1_basis": atr_basis},
               "timeframes_used": sorted(tf for tf in PIVOT_STRENGTH if bars.get(tf)),
               "unavailable_timeframes": dict(market.unavailable_timeframes)}
    best = max(candidates, key=_rank) if candidates else None
    if best is None or best["state"] == "NO SETUP":
        failed = failed_level(levels, closed, price, BREAK_BUFFER_ATR_M15 * atr_m15)
        reason = (f"Price closed through {failed['type'].lower()} at {failed['price']:.8g} (failed rejection)." if failed
                  else "No meaningful level near price." if levels else "No repeated reactions form a meaningful level.")
        return _no_setup(reason, atr=atr_m15, strategy_evidence={"method": STRATEGY_VERSION, **context,
                         "failed_level": failed})

    level, long = best["level"], best["side"] == "LONG"
    kind = ("SUPPORT" if long else "RESISTANCE")
    breakdown = {
        "level_strength": min(30, level["strength"] * 5),
        "higher_timeframe": min(20, level["higher_timeframe_reactions"] * 10),
        "rejection": 20 if best["gates"]["rejection"] else 10 if best["gates"]["touched"] else 0,
        "momentum": 10 if best["gates"]["momentum"] else 0,
        "risk_reward": 20 if best["gates"]["min_rr"] else 10 if (best["rr"] or 0) >= 1.0 else 0,
    }
    setup = {"SR_BOUNCE": "Support bounce" if long else "Resistance rejection",
             "SR_BREAK_RETEST": "Resistance break/retest" if long else "Support break/retest"}[best["family"]]
    failed_gates = [name for name in CONFIRMATION_RULES if not best["gates"][name]]
    reason = (f"{setup} at {kind.lower()} {level['price']:.8g} ({level['reactions']} reactions, strength {level['strength']}"
              + (f", {level['higher_timeframe_reactions']} H4/D1" if level["higher_timeframe_reactions"] else "") + ")"
              + ("; all confirmation rules passed" if best["valid"] else "; waiting for: " + ", ".join(failed_gates)))
    evidence = {
        "method": STRATEGY_VERSION, **context,
        "level": {"type": kind, "price": level["price"], "zone_low": level["zone_low"], "zone_high": level["zone_high"],
                  "reactions": level["reactions"], "strength": level["strength"],
                  "reactions_by_timeframe": level["reactions_by_timeframe"],
                  "higher_timeframe_reactions": level["higher_timeframe_reactions"],
                  "higher_timeframe_confluence": level["higher_timeframe_reactions"] > 0,
                  "role_reversal": level["swing_highs"] > 0 and level["swing_lows"] > 0,
                  "last_reaction_time": level["last_reaction_time"]},
        "family": best["family"], "distance_atr_h1": round(best["distance"] / atr_h1, 3),
        "touch": {"touched": best["gates"]["touched"], "bars_ago": best["touch_bars_ago"],
                  "clean_test": best["gates"]["clean_test"], "approach_atr_h1": best["approach_atr_h1"]},
        "rejection": {"confirmed": best["gates"]["rejection"], "close_position": best["close_position"],
                      "candle_time": best["confirm_time"]},
        "confirmation": {"rules": {name: best["gates"][name] for name in CONFIRMATION_RULES},
                         "near_level": best["gates"]["near_level"], "passed": best["valid"], "failed": failed_gates},
        "plan": {"entry": best["entry"], "stop": best["stop"], "target": best["target"],
                 "target_level_price": best["target_level"]["price"] if best["target_level"] else None,
                 "risk": best["risk"], "reward": best["reward"], "rr": best["rr"], "min_rr": MIN_RR},
    }
    return {"strategy_version": STRATEGY_VERSION, "timeframe": "M15", "higher_timeframes": ["H1", "H4", "D1"],
            "state": best["state"], "direction": best["side"], "setup": setup, "setup_family": best["family"],
            "strategy_valid": best["valid"], "reason": reason,
            "trigger": "Close back " + ("above" if long else "below") + " the zone with momentum" if not best["valid"] else None,
            "entry": best["entry"] if best["stop"] is not None else None,
            "stop_loss": best["stop"], "take_profit": best["target"], "invalidation_hint": best["stop"],
            "rr": best["rr"], "risk_distance": best["risk"], "reward_distance": best["reward"], "atr": atr_m15,
            "score": min(100, sum(breakdown.values())), "score_breakdown": breakdown, "strategy_evidence": evidence}


class SupportResistanceStrategy(Strategy):
    strategy_id = "support_resistance"
    version = STRATEGY_VERSION
    timeframe = "M15"
    higher_timeframes = ("H1", "H4", "D1")
    lifecycle = MATCHER_VERSION         # the existing episode matcher/lifecycle, scoped to this strategy
    data_requirements = {"M15": 300, "H1": 160}   # H4/D1 context is used when available, never required

    def evaluate(self, market: MarketInput) -> dict[str, Any]:
        return analyze_support_resistance(market)
