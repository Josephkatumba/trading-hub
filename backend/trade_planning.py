"""Conservative executable plans. Never extend a target or tighten a structural stop."""
from decimal import Decimal, ROUND_FLOOR, ROUND_CEILING
import math
import json
import os


def quantize_level(value, tick, upward=False):
    if value is None:
        return None
    number, unit = Decimal(str(value)), Decimal(str(tick))
    if not number.is_finite() or not unit.is_finite() or unit <= 0:
        raise ValueError("Invalid price/tick size")
    return float((number / unit).to_integral_value(rounding=ROUND_CEILING if upward else ROUND_FLOOR) * unit)


def apply_plan(market, bars=None):
    long = market.get("direction") == "LONG"
    if market.get("direction") not in ("LONG", "SHORT"):
        return market
    strategy = market.get("strategy_id")
    if strategy not in {"trendline_v5", "support_resistance", "smc", "trend_momentum"}:
        return market  # Preserve retired versions and their historical golden contracts.
    basis = {"trendline_v5": "H1 swing target / M15 structural invalidation",
             "support_resistance": "Next S/R zone edge / rejection zone invalidation",
             "smc": "H1 liquidity swing / order-block origin invalidation",
             "trend_momentum": "Measured impulse capped at intervening H1 swing / pullback invalidation"}.get(strategy)
    # Preserve every strategy's closed-bar plan as evidence; only executable/display plans change.
    original = {k: market.get(k) for k in ("entry", "stop_loss", "take_profit")}
    original_invalidation = market.get("invalidation_hint")
    target = original["take_profit"]
    if strategy == "trend_momentum" and target is not None and original["entry"] is not None:
        closed = list((bars or {}).get("H1") or [])[:-1]
        swings = []
        for i in range(2, len(closed) - 2):
            key = "high" if long else "low"
            price = closed[i][key]
            if all(price >= b[key] if long else price <= b[key] for b in closed[i-2:i+3]):
                if original["entry"] < price < target if long else target < price < original["entry"]:
                    swings.append(price)
        if swings:
            target = min(swings) if long else max(swings)
    tick = market.get("tick_size") or market.get("point")
    if tick is not None and math.isfinite(float(tick)) and float(tick) > 0:
        # Long stop down / target down; short stop up / target up. Both conservative.
        market["stop_loss"] = quantize_level(original["stop_loss"], tick, not long)
        target = quantize_level(target, tick, not long)
    market["take_profit"] = target
    if market.get("stop_loss") is not None:
        market["invalidation_hint"] = market["stop_loss"]
    executable = market.get("ask") if long else market.get("bid")
    if executable and original["entry"] is not None:
        market["entry"] = executable
    market["plan_evidence"] = {"version": "structure-executable-v1", "basis": basis,
        "pattern_plan": original, "tick_size": tick,
        "pattern_invalidation": original_invalidation,
        "target_capped": target is not None and original["take_profit"] is not None and target != original["take_profit"]}
    breakdown = market.get("score_breakdown") or {}
    pattern = {k: v for k, v in breakdown.items() if k not in {"risk_reward", "rr"}}
    market["pattern_strength"] = sum(v for v in pattern.values() if isinstance(v, (int, float)))
    market["pattern_strength_breakdown"] = pattern
    rules = ((market.get("strategy_evidence") or {}).get("confirmation") or {}).get("rules") or {}
    pattern_rules = {k: v for k, v in rules.items() if k not in {"min_rr", "target", "stop_ok", "not_chasing"}}
    market["pattern_confirmed"] = bool(market.get("state") == "CONFIRMING" and
        (all(pattern_rules.values()) if pattern_rules else market.get("trendline_gate") and market.get("confirmation_alignment")))
    costs = json.loads(os.getenv("TRADING_HUB_COSTS_BY_SYMBOL", "{}"))
    if market.get("symbol") in costs:
        market["round_trip_cost_price"] = costs[market["symbol"]]
    market["strategy_evidence"] = {**(market.get("strategy_evidence") or {}),
        "trade_plan": market["plan_evidence"], "pattern_strength": market["pattern_strength"],
        "pattern_confirmed": market["pattern_confirmed"]}
    return market
