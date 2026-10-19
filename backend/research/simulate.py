"""First-barrier simulation of one signal, with trading costs.

Fills (MT5 bars are bid prices):
  entry   at the signal bar's open: ask for LONG, bid for SHORT (the replay's quote)
  LONG    exits at the bid:  stop when low <= SL, target when high >= TP
  SHORT   exits at the ask:  stop when high + spread >= SL, target when low + spread <= TP
  gap     a bar that OPENS beyond a level fills at that open (worse for stops, better for targets)
  stop    exits slip STOP_SLIPPAGE_SPREADS x the bar's spread beyond the stop
  time    still open after max_bars M15 bars: exit at that bar's close (bid/ask side)

When one M15 bar touches both levels, the M1 bars inside it decide (same rules per
minute). If one minute touches both, or no M1 history covers the bar, the result is
AMBIGUOUS: metrics report it separately and count it as a stop in the pessimistic case.

Costs: the spread is paid through the fills; commission (round trip, price units) comes
from COMMISSION_PRICE (IC Markets Raw-style $7/lot FX and metals; indices and crypto are
spread-only CFDs). Results are in R = the planned risk |entry - stop|, net of costs.
"""
from __future__ import annotations

import bisect
from typing import Any

STOP_SLIPPAGE_SPREADS = 0.5
MAX_BARS = 5 * 96                     # 5 trading days of M15 bars
COMMISSION_PRICE = {
    "EURUSD": 0.00007, "GBPUSD": 0.00007, "AUDUSD": 0.00007, "NZDUSD": 0.00007, "USDCHF": 0.00007,
    "USDCAD": 0.00007, "USDJPY": 0.007, "EURJPY": 0.007, "GBPJPY": 0.007,
    "XAUUSD": 0.07, "XAGUSD": 0.0014,
    "NAS100": 0.0, "US500": 0.0, "GER40": 0.0, "BTCUSD": 0.0, "ETHUSD": 0.0,
}


_NEW_YORK = None


def rollovers(start_utc: float, end_utc: float, triple_weekday: int | None) -> int:
    """Swap nights charged between two instants: each 17:00 New York rollover crossed counts 1, the
    broker's triple-swap day 3 (MT5 day numbering 0=Sunday .. 6=Saturday; 7 or None = no triple)."""
    global _NEW_YORK
    from datetime import datetime, timedelta, timezone
    from zoneinfo import ZoneInfo
    if _NEW_YORK is None:
        _NEW_YORK = ZoneInfo("America/New_York")
    if end_utc <= start_utc:
        return 0
    start = datetime.fromtimestamp(start_utc, timezone.utc).astimezone(_NEW_YORK)
    end = datetime.fromtimestamp(end_utc, timezone.utc).astimezone(_NEW_YORK)
    nights, day = 0, start.date()
    while day <= end.date():
        boundary = datetime(day.year, day.month, day.day, 17, 0, tzinfo=_NEW_YORK)
        if start < boundary <= end:
            mt5_weekday = (boundary.weekday() + 1) % 7          # Python Monday=0 -> MT5 Monday=1
            nights += 3 if triple_weekday is not None and mt5_weekday == triple_weekday else 1
        day += timedelta(days=1)
    return nights


def financing_per_night(meta: dict[str, Any], long: bool, price: float) -> float:
    """Overnight financing in price units per night (positive = a cost), from the broker's CURRENT
    swap specification (an approximation of historical rates)."""
    mode = meta.get("swap_mode")
    swap = meta.get("swap_long" if long else "swap_short")
    if not mode or swap is None:
        return 0.0
    if mode == 1:                                   # points
        value = swap * (meta.get("point") or 0.0)
    elif mode in (2, 3, 4):                         # money per lot (symbol / margin / deposit currency)
        value = swap / (meta.get("contract_size") or 1.0)
    elif mode in (5, 6):                            # annual interest in percent of the price
        value = price * swap / 100.0 / 360.0
    else:
        value = 0.0
    return -value                                   # MT5 swap: negative = charged


def _touch(long: bool, high: float, low: float, spread: float, sl: float, tp: float) -> tuple[bool, bool]:
    if long:
        return low <= sl, high >= tp
    return high + spread >= sl, low + spread <= tp


def _m1_order(history_: Any, start_utc: float, long: bool, sl: float, tp: float, after_utc: float | None = None) -> str | None:
    """'SL' / 'TP' from M1 bars inside [start_utc, start_utc + 15m), or None if unresolved."""
    m1, times = history_.full.get("M1") or [], history_.m1_utc
    lo, hi = bisect.bisect_left(times, start_utc), bisect.bisect_left(times, start_utc + 900)
    minutes = [bar for bar in m1[lo:hi] if after_utc is None or bar["utc"] >= after_utc]
    if not minutes:
        return None
    for bar in minutes:
        stop, target = _touch(long, bar["high"], bar["low"], bar["spread"], sl, tp)
        if stop and target:
            return None
        if stop:
            return "SL"
        if target:
            return "TP"
    return None          # M1 bars disagree with the M15 bar (should not happen): unresolved


def simulate(signal: dict[str, Any], history_: Any, stop: float | None = None, target: float | None = None,
             max_bars: int = MAX_BARS, commission: float | None = None, cost_multiplier: float = 1.0,
             trail: float | None = None, financing: bool = True) -> dict[str, Any]:
    """`trail`: optional trailing-stop distance in price units. After each M15 bar CLOSES the stop
    moves to (best price since entry - trail) if that is better; the new stop applies from the
    next bar (no intra-bar look-ahead). With a trail, `target` may be None (no fixed target)."""
    long = signal["direction"] == "LONG"
    entry = float(signal["entry"])
    sl = float(stop if stop is not None else signal["stop_loss"])
    raw_target = target if target is not None else signal.get("take_profit")
    if raw_target is None and trail is None:
        return {"outcome": "INVALID_PLAN", "r": None}
    tp = float(raw_target) if raw_target is not None else (float("inf") if long else float("-inf"))
    risk = (entry - sl) if long else (sl - entry)
    if not (risk > 0) or (long and tp <= entry) or (not long and tp >= entry):
        return {"outcome": "INVALID_PLAN", "r": None}
    bars = history_.full["M15"]
    i0 = signal["index"]
    fee = (COMMISSION_PRICE.get(history_.symbol, 0.0) if commission is None else commission) * cost_multiplier
    sign = 1 if long else -1
    # A BUY pays the spread at entry (ask): scale that part with the cost multiplier too, so
    # stress (x2) and gross (x0) runs are symmetric for BUY and SELL. R stays per planned risk.
    if long and cost_multiplier != 1.0:
        entry += (cost_multiplier - 1.0) * bars[i0]["spread"]
    initial_sl = sl
    best = None
    mfe = mae = 0.0
    outcome, exit_price, exit_index = None, None, None
    for k in range(i0, min(len(bars), i0 + max_bars)):
        bar = bars[k]
        spread = bar["spread"] * cost_multiplier
        if k > i0:                                     # gap at the open
            open_exit = bar["open"] if long else bar["open"] + spread
            if (open_exit <= sl) if long else (open_exit >= sl):
                outcome, exit_price, exit_index = "SL", open_exit, k
                break
            if (open_exit >= tp) if long else (open_exit <= tp):
                outcome, exit_price, exit_index = "TP", open_exit, k
                break
        high, low = bar["high"], bar["low"]
        favourable = (high - entry) if long else (entry - (low + spread))
        adverse = (entry - low) if long else ((high + spread) - entry)
        mfe, mae = max(mfe, favourable / risk), max(mae, adverse / risk)
        stop_hit, target_hit = _touch(long, high, low, spread, sl, tp)
        if stop_hit and target_hit:
            first = _m1_order(history_, bar["utc"], long, sl, tp)
            if first is None:
                outcome, exit_index = "AMBIGUOUS", k
                break
            stop_hit, target_hit = first == "SL", first == "TP"
        if stop_hit:
            slip = STOP_SLIPPAGE_SPREADS * spread
            outcome, exit_price, exit_index = "SL", (sl - slip) if long else (sl + slip), k
            break
        if target_hit:
            outcome, exit_price, exit_index = "TP", tp, k
            break
        if trail is not None:                          # at this bar's close, for the next bar
            best = max(best if best is not None else high, high) if long else min(best if best is not None else low + spread, low + spread)
            moved = best - trail if long else best + trail
            sl = max(sl, moved) if long else min(sl, moved)
    if outcome is None:
        if i0 + max_bars > len(bars):                # history ends before the trade could finish
            return {"outcome": "OPEN", "r": None, "exit_index": len(bars) - 1}
        k = i0 + max_bars - 1
        bar = bars[k]
        outcome, exit_index = "TIMEOUT", k
        exit_price = bar["close"] if long else bar["close"] + bar["spread"] * cost_multiplier
    hold = (bars[exit_index]["utc"] - bars[i0]["utc"]) / 3600.0
    if outcome == "AMBIGUOUS":
        swap = _swap_cost(history_, long, entry, bars[i0]["utc"], bars[exit_index]["utc"], financing, cost_multiplier)
        stop_r = -1.0 - (STOP_SLIPPAGE_SPREADS * bars[exit_index]["spread"] * cost_multiplier + fee + swap) / risk
        target_r = (abs(tp - entry) - fee - swap) / risk
        return {"outcome": outcome, "r": stop_r, "r_if_target": round(target_r, 4), "exit_index": exit_index,
                "hold_hours": hold, "mfe_r": mfe, "mae_r": mae, "risk": risk}
    if outcome == "SL" and sl != initial_sl:
        outcome = "TRAIL"                              # the stop that closed it had been trailed
    swap = _swap_cost(history_, long, entry, bars[i0]["utc"], bars[exit_index]["utc"], financing, cost_multiplier)
    r = (sign * (exit_price - entry) - fee - swap) / risk
    return {"outcome": outcome, "r": round(r, 4), "exit_index": exit_index, "exit_price": exit_price,
            "hold_hours": round(hold, 2), "mfe_r": round(mfe, 3), "mae_r": round(mae, 3), "risk": risk,
            "planned_r": round(abs(tp - entry) / risk, 3) if raw_target is not None else None,
            "financing_r": round(swap / risk, 4)}


def _swap_cost(history_: Any, long: bool, price: float, start_utc: float, end_utc: float, financing: bool,
               cost_multiplier: float) -> float:
    meta = getattr(history_, "meta", None) or {}
    if not financing or not meta.get("swap_mode"):
        return 0.0
    triple = meta.get("swap_rollover3days")
    nights = rollovers(start_utc, end_utc, triple if triple in range(7) else None)
    return nights * financing_per_night(meta, long, price) * cost_multiplier
