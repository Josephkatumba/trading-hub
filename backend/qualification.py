"""Trade qualification at the executable price, for every strategy.

Strategies plan entry/stop/target from the close of the last CLOSED bar and gate on
reward/risk >= 1.5 measured from that close. The setup is observed later, at the live
quote, and a position could only be opened at the ask (LONG) or the bid (SHORT). Between
the two the price can have moved, so a setup the strategy confirms can already be
unattractive, or even past its target or stop, when it is recorded. Audit of the live
store (2026-10-12): of 368 confirmations with a snapshot, 2 were recorded with price
already beyond the stop, 29 had an executable R:R below 1.5, and one was issued on a
38-hour-old tick while the market was closed.

qualify() re-checks the strategy's own plan (nothing is re-planned) at the quote:

  levels_present   stop and target are numbers
  quote_available  a bid and an ask (ask >= bid)
  quote_fresh      the verified tick is at most MAX_QUOTE_AGE_SECONDS old; an unknown
                   (unverified) tick age fails closed: a closed market or a stalled feed
                   cannot confirm
  levels_ordered   LONG stop < entry < target; SHORT target < entry < stop
  inside_barriers  the exit-side price has not reached the stop or target yet
                   (LONG exits at the bid: stop < bid < target; SHORT at the ask: target < ask < stop)
  min_rr           executable R:R >= MIN_RR, unrounded. LONG: buy at the ask, exit at
                   the bid = target / stop, so reward = target - ask and risk = ask - stop
                   (SHORT mirrors). The full spread is therefore paid.

apply() turns a confirmed setup that fails into an unconfirmed one: strategy_valid
becomes False, the strategy's own decision is kept as strategy_signal_valid, and the
checks are recorded under `qualification`. A setup the strategy did not confirm is never
promoted.
"""
from __future__ import annotations

import math
import os
from typing import Any

QUALIFICATION_VERSION = "net-structure-qualification-v2"
MIN_RR = 1.5                      # every live strategy's own threshold (trendline, S/R, T/M, SMC)
MAX_QUOTE_AGE_SECONDS = 300.0
QUOTE_FUTURE_TOLERANCE_SECONDS = 5.0   # a verified tick may be stamped slightly ahead (clock skew)


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _fresh(age: Any) -> bool:
    try:
        age = float(age)
    except (TypeError, ValueError):
        return False
    return math.isfinite(age) and -QUOTE_FUTURE_TOLERANCE_SECONDS <= age <= MAX_QUOTE_AGE_SECONDS


def configured_min_rr():
    value = float(os.getenv("TRADING_HUB_MIN_NET_RR", "1.5"))
    if not math.isfinite(value) or value < 1.5:
        raise ValueError("TRADING_HUB_MIN_NET_RR must be finite and at least 1.5")
    return value


def qualify(market: dict[str, Any], min_rr: float | None = None) -> dict[str, Any] | None:
    """The qualification checks for one market/setup payload, or None without a direction."""
    min_rr = configured_min_rr() if min_rr is None else max(MIN_RR, min_rr)
    direction = market.get("direction")
    if direction not in ("LONG", "SHORT"):
        return None
    long = direction == "LONG"
    entry, stop, target = (_number(market.get(key)) for key in ("entry", "stop_loss", "take_profit"))
    bid, ask = _number(market.get("bid")), _number(market.get("ask"))
    checks = {"levels_present": stop is not None and target is not None,
              "quote_available": bid is not None and ask is not None and ask >= bid,
              "quote_fresh": _fresh(market.get("tick_age_seconds"))}
    checks["levels_ordered"] = bool(checks["levels_present"] and entry is not None and
                                    ((stop < entry < target) if long else (target < entry < stop)))
    executable = (ask if long else bid) if checks["quote_available"] else None
    rr = risk = reward = None
    if checks["levels_present"] and checks["quote_available"]:
        # A LONG exits by selling at the bid, a SHORT by buying at the ask.
        checks["inside_barriers"] = (stop < bid < target) if long else (target < ask < stop)
        reward = (target - ask) if long else (bid - target)
        risk = (ask - stop) if long else (stop - bid)
        try:
            cost = float(market.get("round_trip_cost_price", os.getenv("TRADING_HUB_ROUND_TRIP_COST_PRICE", "0")))
        except (ValueError, TypeError):
            cost = float("nan")
        checks["costs_valid"] = math.isfinite(cost) and cost >= 0
        if checks["costs_valid"]:
            reward -= cost
            risk += cost
        rr = reward / risk if checks["costs_valid"] and risk > 0 and reward > 0 else None
    else:
        checks["inside_barriers"] = False
    checks["min_rr"] = rr is not None and rr >= min_rr
    qualified = all(checks.values())
    failed = [name for name, ok in checks.items() if not ok]
    return {"version": QUALIFICATION_VERSION, "qualified": qualified, "failed": failed, "checks": checks,
            "executable_price": executable, "executable_risk": risk, "executable_reward": reward,
            "executable_rr": round(rr, 4) if rr is not None else None, "min_rr": min_rr,
            "preferred_rr": 2.0, "preferred": rr is not None and rr >= 2.0,
            "cost_basis": "spread plus configured round-trip commission/slippage in price units",
            "additional_cost_price": cost if checks.get("costs_valid") else None,
            "cost_assumption": "Configured commission/slippage" if checks.get("costs_valid") and cost else "No additional commission/slippage assumed; configure broker costs",
            "spread": (ask - bid) if checks["quote_available"] else None,
            "quote_age_seconds": market.get("tick_age_seconds"), "max_quote_age_seconds": MAX_QUOTE_AGE_SECONDS}


_REASONS = {"levels_present": "no stop or target", "quote_available": "no live quote",
            "costs_valid": "invalid configured execution costs",
            "quote_fresh": "the live quote is stale or its age is unverified",
            "levels_ordered": "stop/target not on the correct sides of entry",
            "inside_barriers": "price already reached the stop or target",
            "min_rr": "executable risk/reward below the 1.5R minimum (spread included)"}


def apply(market: dict[str, Any], min_rr: float | None = None) -> dict[str, Any]:
    """Record the qualification on `market` (in place) and gate its confirmation."""
    result = qualify(market, min_rr)
    if result is None:
        return market
    market["qualification"] = result
    market["trade_qualified"] = bool(market.get("strategy_valid") and result["qualified"])
    market["rr_executable"] = result["executable_rr"]
    market["rr"] = result["executable_rr"]
    market["risk_distance"] = result["executable_risk"]
    market["reward_distance"] = result["executable_reward"]
    if market.get("strategy_valid") is True and not result["qualified"]:
        market["strategy_signal_valid"] = True
        market["strategy_valid"] = False
        why = "; ".join(f"net risk/reward below the {result['min_rr']:g}R minimum" if name == "min_rr"
                        else _REASONS[name] for name in result["failed"])
        market["reason"] = (str(market.get("reason") or "").rstrip("; ") +
                            ("; " if market.get("reason") else "") + "not qualified at the executable price: " + why)
    return market
