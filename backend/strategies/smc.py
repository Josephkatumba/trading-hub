"""Smart Money Concepts (SMC) strategy: deterministic, rule-based, TradeDen signals only.

Nothing here is decided by an AI model: every concept below is a fixed calculation
over CLOSED MT5 bars (each timeframe's last bar is still forming; the forming M15
close is used as the current price), and every rule's outcome is written to
`strategy_evidence`. Distances are ATR-normalised, so the same rules apply to every
instrument. Scope: SMC produces TradeDen setups/signals only. It is not connected to
Company HQ, the Trading Floor or any paper/real execution (evidence.scope).

CONCEPTS (machine-readable; LONG described, SHORT is the exact mirror)
  swing          fractal pivot, 2 bars each side (same rule as scanner._swings). A pivot
                 at bar i is only KNOWN from bar i + 2 on (no look-ahead).
  structure      walk the closed bars in order, keeping the latest known swing high and
                 swing low. A CLOSE above the swing high is a bullish structure break:
                   BOS    when the structure was already bullish (or not yet defined)
                   CHoCH  when the structure was bearish (a change of character)
                 The broken swing is consumed. Trend = direction of the latest break.
                 Swing labels HH/LH and HL/LL are reported for the last two pivots.
  HTF context    the same structure engine on closed H4 bars (H1 when H4 is
                 unavailable; recorded as `basis`). Trend BULLISH -> only LONG setups.
  FVG            three-candle imbalance: bullish when low[m+1] > high[m-1]; the gap
                 [high[m-1], low[m+1]] must be >= 0.1 ATR(M15).
  order block    the last bearish candle (close < open) before the displacement leg:
                 searched from the bar before the leg's first FVG back to 3 bars
                 before the leg origin. Zone = that candle's [low, high].
  liquidity      a sell-side sweep: the leg-origin bar trades below an earlier,
  sweep          still-untaken swing low (confirmed pivot within the last 40 bars, no
                 low below it since), and that bar or the next closes back above it.

SETUP (all required; a single FVG, order block or sweep is never a signal)
  1. htf_aligned     H4 structure trend is bullish.
  2. structure_shift M15 structure trend is bullish: its latest break is a bullish BOS
                     or CHoCH, within the last 48 closed M15 bars (12 h).
  3. displacement    the leg that broke structure (lowest low between the broken swing
                     high and the break bar = the leg origin, up to the break bar)
                     contains at least one bullish FVG.
  4. order_block     an order block exists for that leg.
  5. liquidity       a CHoCH (reversal) additionally needs a liquidity sweep at the leg
                     origin. A BOS (continuation with the HTF trend) does not.
  Not yet retraced into the order block           -> WATCHING
  6. poi_retest      price traded back into the order block after the break (first tap),
                     with no close below the order block (that invalidates it).
                     The reaction must come within 3 closed bars of the first tap;
                     after that the order block is treated as mitigated (NO SETUP).
  In the order block, no reaction candle yet      -> DEVELOPING
  7. reaction        the last closed candle closes back above the order block with a
                     rejection candle: wick_rejection / engulfing / close_away
                     (strategies/price_action.py), touch after the break bar.
                                                  -> CONFIRMING
  strategy_valid additionally needs the plan gates:
     not_chasing   entry within 1.0 ATR(H1) of the order block's top
     stop_ok       risk between 0.5 ATR(M15) and 2.5 ATR(H1)
     target        an H1 swing high (buy-side liquidity) above entry
     min_rr        reward / risk >= 1.5

  Families: SMC_BOS_CONTINUATION (BOS) and SMC_CHOCH_SWEEP_REVERSAL (CHoCH + sweep).

PLAN
  entry  = current price (the forming M15 close, after the confirmed reaction)
  stop   = below min(order block low, leg origin low) by 0.5 ATR(M15)
  target = nearest closed-H1 swing high above entry (external liquidity)

SCORE (0-100) describes quality only; it never decides a state or a confirmation:
  htf_context 20, structure 20 (CHoCH + sweep) / 15 (BOS), displacement 15,
  fvg_order_block_overlap 5, liquidity_sweep 10, reaction 15, risk_reward 15 (>= 2R) / 10 (>= 1.5R).

Parameters are round, conventional values chosen before looking at any outcome; they
are NOT fitted to historical data. This makes no claim of profitability.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from episode_identity import CONFIRMED_EVENTS_LIFECYCLE
from scanner import _atr

from .base import MarketInput, Strategy
from .price_action import confirm_rejection

STRATEGY_VERSION = "smc-confluence-v1"
SCOPE = "TRADEDEN_SIGNAL_ONLY"        # not connected to Company HQ / Trading Floor / execution
SWING_STRENGTH = 2
SETUP_WINDOW = 48
FVG_MIN_ATR = 0.1
OB_LOOKBACK = 3
SWEEP_LOOKBACK = 40
POI_REACTION_BARS = 3
STOP_BUFFER_ATR_M15 = 0.5
MIN_RISK_ATR_M15 = 0.5
MAX_RISK_ATR_H1 = 2.5
MAX_CHASE_ATR_H1 = 1.0
MIN_RR = 1.5
MIN_BARS = {"M15": 100, "H1": 60, "H4": 30}
CONFIRMATION_RULES = ("htf_aligned", "structure_shift", "displacement", "order_block", "liquidity",
                      "poi_retest", "reaction", "not_chasing", "stop_ok", "target", "min_rr")
FAMILIES = {"BOS": "SMC_BOS_CONTINUATION", "CHOCH": "SMC_CHOCH_SWEEP_REVERSAL"}
PARAMETERS = {"swing_strength": SWING_STRENGTH, "setup_window_m15": SETUP_WINDOW, "fvg_min_atr_m15": FVG_MIN_ATR,
              "order_block_lookback": OB_LOOKBACK, "sweep_lookback": SWEEP_LOOKBACK,
              "poi_reaction_bars": POI_REACTION_BARS, "stop_buffer_atr_m15": STOP_BUFFER_ATR_M15,
              "risk": [f"{MIN_RISK_ATR_M15} ATR(M15)", f"{MAX_RISK_ATR_H1} ATR(H1)"],
              "max_chase_atr_h1": MAX_CHASE_ATR_H1, "min_rr": MIN_RR}


def _f(bar: Mapping[str, Any], key: str) -> float:
    return float(bar[key])


# ------------------------------------------------------------------ detection

def swing_points(rows: Sequence[Mapping[str, Any]], strength: int = SWING_STRENGTH) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    """Fractal swings (index, price): strictly beyond `strength` bars on each side."""
    highs = [_f(row, "high") for row in rows]
    lows = [_f(row, "low") for row in rows]
    swing_highs, swing_lows = [], []
    for i in range(strength, len(rows) - strength):
        if highs[i] > max(highs[i - strength:i]) and highs[i] > max(highs[i + 1:i + strength + 1]):
            swing_highs.append((i, highs[i]))
        if lows[i] < min(lows[i - strength:i]) and lows[i] < min(lows[i + 1:i + strength + 1]):
            swing_lows.append((i, lows[i]))
    return swing_highs, swing_lows


def market_structure(rows: Sequence[Mapping[str, Any]], strength: int = SWING_STRENGTH) -> dict[str, Any]:
    """BOS / CHoCH events over closed bars, in order, using only swings known at each bar."""
    swing_highs, swing_lows = swing_points(rows, strength)
    known_high = {i + strength: (i, price) for i, price in swing_highs}
    known_low = {i + strength: (i, price) for i, price in swing_lows}
    ref_high = ref_low = None
    trend = None
    events: list[dict[str, Any]] = []
    for k, bar in enumerate(rows):
        ref_high = known_high.get(k, ref_high)
        ref_low = known_low.get(k, ref_low)
        close = _f(bar, "close")
        if ref_high is not None and close > ref_high[1]:
            events.append({"kind": "CHOCH" if trend == "BEARISH" else "BOS", "direction": "BULLISH", "index": k,
                           "level": ref_high[1], "swing_index": ref_high[0]})
            trend, ref_high = "BULLISH", None
        elif ref_low is not None and close < ref_low[1]:
            events.append({"kind": "CHOCH" if trend == "BULLISH" else "BOS", "direction": "BEARISH", "index": k,
                           "level": ref_low[1], "swing_index": ref_low[0]})
            trend, ref_low = "BEARISH", None
    labels = {}
    if len(swing_highs) >= 2:
        labels["high"] = "HH" if swing_highs[-1][1] > swing_highs[-2][1] else "LH"
    if len(swing_lows) >= 2:
        labels["low"] = "HL" if swing_lows[-1][1] > swing_lows[-2][1] else "LL"
    return {"trend": trend, "events": events, "swing_highs": swing_highs, "swing_lows": swing_lows, "labels": labels}


def fair_value_gaps(rows: Sequence[Mapping[str, Any]], start: int, end: int, long: bool, min_size: float) -> list[dict[str, Any]]:
    """FVGs whose middle candle m lies in [start, end] (m + 1 must be a closed bar)."""
    gaps = []
    for m in range(max(1, start), min(end, len(rows) - 2) + 1):
        before, after = rows[m - 1], rows[m + 1]
        low, high = ((_f(before, "high"), _f(after, "low")) if long else (_f(after, "high"), _f(before, "low")))
        if high - low >= min_size and high > low:
            gaps.append({"index": m, "low": low, "high": high, "size": high - low})
    return gaps


def order_block(rows: Sequence[Mapping[str, Any]], origin: int, first_gap: int, long: bool) -> dict[str, Any] | None:
    """The last opposite-colour candle before the displacement (see module docstring)."""
    for i in range(first_gap - 1, max(0, origin - OB_LOOKBACK) - 1, -1):
        bar = rows[i]
        if (_f(bar, "close") < _f(bar, "open")) if long else (_f(bar, "close") > _f(bar, "open")):
            return {"index": i, "low": _f(bar, "low"), "high": _f(bar, "high")}
    return None


def liquidity_sweep(rows: Sequence[Mapping[str, Any]], origin: int, swings: Sequence[tuple[int, float]], long: bool,
                    end: int, strength: int = SWING_STRENGTH) -> dict[str, Any] | None:
    """Whether the leg-origin bar swept an earlier untaken swing low (high for SHORT)."""
    extreme = _f(rows[origin], "low" if long else "high")
    for index, price in reversed(swings):
        if index + strength > origin or origin - index > SWEEP_LOOKBACK:
            continue
        between = rows[index + 1:origin]
        untaken = all((_f(bar, "low") >= price) if long else (_f(bar, "high") <= price) for bar in between)
        pierced = extreme < price if long else extreme > price
        closes = [_f(rows[i], "close") for i in range(origin, min(origin + 1, end) + 1)]
        reclaimed = any((close > price) if long else (close < price) for close in closes)
        if untaken and pierced and reclaimed:
            return {"swept_level": price, "swept_swing_index": index, "sweep_index": origin, "sweep_extreme": extreme}
    return None


# ---------------------------------------------------------------- the setup

def _no_setup(reason: str, **extra: Any) -> dict[str, Any]:
    return {"strategy_version": STRATEGY_VERSION, "timeframe": "M15", "higher_timeframes": ["H1", "H4"],
            "state": "NO SETUP", "direction": None, "setup": "No SMC setup", "setup_family": None,
            "strategy_valid": False, "reason": reason, "score": 0, "score_breakdown": {},
            "entry": None, "stop_loss": None, "take_profit": None, "invalidation_hint": None, "rr": None, **extra}


def _time(rows: Sequence[Mapping[str, Any]], index: int | None) -> Any:
    return rows[index]["time"] if index is not None else None


def analyze_smc(market: MarketInput) -> dict[str, Any]:
    bars = dict(market.bars) if market.bars else {"M15": list(market.rows), "H1": list(market.higher_rows or [])}
    closed = {tf: list(bars.get(tf) or [])[:-1] for tf in ("M15", "H1", "H4")}
    context: dict[str, Any] = {"method": STRATEGY_VERSION, "scope": SCOPE, "parameters": PARAMETERS,
                               "timeframes_used": sorted(tf for tf in closed if closed[tf]),
                               "unavailable_timeframes": dict(market.unavailable_timeframes)}
    for tf in ("M15", "H1"):
        if len(closed[tf]) < MIN_BARS[tf]:
            return _no_setup(f"Insufficient {tf} history for SMC ({len(closed[tf])} closed bars, needs {MIN_BARS[tf]}).",
                             strategy_evidence=context)
    m15 = closed["M15"]
    n = len(m15)
    price = _f(bars["M15"][-1], "close")
    atr_m15, atr_h1 = _atr(m15), _atr(closed["H1"])
    if atr_m15 <= 0 or atr_h1 <= 0:
        return _no_setup("No volatility (ATR) available.", strategy_evidence=context)
    context["atr"] = {"M15": atr_m15, "H1": atr_h1}

    # 1. Higher-timeframe directional context.
    htf_tf = "H4" if len(closed["H4"]) >= MIN_BARS["H4"] else "H1"
    htf = market_structure(closed[htf_tf])
    last_htf = htf["events"][-1] if htf["events"] else None
    context["htf"] = {"basis": htf_tf, "trend": htf["trend"], "labels": htf["labels"],
                      "last_break": ({"kind": last_htf["kind"], "direction": last_htf["direction"], "level": last_htf["level"],
                                      "time": _time(closed[htf_tf], last_htf["index"])} if last_htf else None)}
    if htf["trend"] is None:
        return _no_setup(f"No {htf_tf} structure trend yet.", atr=atr_m15, strategy_evidence=context)
    long = htf["trend"] == "BULLISH"
    direction = "LONG" if long else "SHORT"

    # 2. M15 structure shift in the HTF direction.
    ms = market_structure(m15)
    event = ms["events"][-1] if ms["events"] else None
    context["structure"] = {"trend": ms["trend"], "labels": ms["labels"],
                            "last_break": ({"kind": event["kind"], "direction": event["direction"], "level": event["level"],
                                            "time": _time(m15, event["index"]), "broken_swing_time": _time(m15, event["swing_index"]),
                                            "bars_ago": n - 1 - event["index"]} if event else None)}
    if event is None or ms["trend"] != htf["trend"]:
        return _no_setup(f"M15 structure is not {htf['trend'].lower()} ({htf_tf} context is {htf['trend'].lower()}).",
                         atr=atr_m15, strategy_evidence=context)
    k, swing = event["index"], event["swing_index"]
    if n - 1 - k > SETUP_WINDOW:
        return _no_setup(f"Last M15 {event['kind']} is {n - 1 - k} bars old (max {SETUP_WINDOW}).", atr=atr_m15,
                         strategy_evidence=context)

    # 3-5. Displacement leg, FVG, order block, liquidity sweep.
    leg = range(swing, k + 1)
    origin = (min(leg, key=lambda i: (_f(m15[i], "low"), -i)) if long else max(leg, key=lambda i: (_f(m15[i], "high"), i)))
    gaps = fair_value_gaps(m15, origin + 1, k, long, FVG_MIN_ATR * atr_m15)
    ob = order_block(m15, origin, gaps[0]["index"], long) if gaps else None
    sweep = liquidity_sweep(m15, origin, ms["swing_lows"] if long else ms["swing_highs"], long, k)
    family = FAMILIES[event["kind"]]
    gates: dict[str, bool] = {"htf_aligned": True, "structure_shift": True, "displacement": bool(gaps),
                              "order_block": ob is not None,
                              "liquidity": sweep is not None if event["kind"] == "CHOCH" else True}
    overlap = bool(ob and gaps and any(gap["low"] <= ob["high"] and gap["high"] >= ob["low"] for gap in gaps))
    context["displacement"] = {"leg_origin_time": _time(m15, origin), "leg_origin_price": _f(m15[origin], "low" if long else "high"),
                               "fvgs": [{"time": _time(m15, gap["index"]), "low": gap["low"], "high": gap["high"],
                                         "size_atr_m15": round(gap["size"] / atr_m15, 3)} for gap in gaps]}
    context["order_block"] = ({"time": _time(m15, ob["index"]), "low": ob["low"], "high": ob["high"], "fvg_overlap": overlap}
                              if ob else None)
    context["liquidity_sweep"] = ({"swept_level": sweep["swept_level"], "swept_swing_time": _time(m15, sweep["swept_swing_index"]),
                                   "sweep_time": _time(m15, sweep["sweep_index"]), "sweep_extreme": sweep["sweep_extreme"]}
                                  if sweep else None)
    context["family"] = family
    unmet = [name for name in ("displacement", "order_block", "liquidity") if not gates[name]]
    if unmet:
        why = {"displacement": "no fair value gap in the break leg", "order_block": "no order block before the displacement",
               "liquidity": "CHoCH without a liquidity sweep"}
        return _no_setup(f"M15 {event['kind']} does not qualify: " + "; ".join(why[name] for name in unmet) + ".",
                         atr=atr_m15, strategy_evidence={**context, "confirmation": {"rules": gates, "failed": unmet}})

    # 6. Retest of the order block (point of interest).
    zone_low, zone_high = ob["low"], ob["high"]
    after = range(k + 1, n)
    invalidated = any((_f(m15[i], "close") < zone_low) if long else (_f(m15[i], "close") > zone_high) for i in after)
    touched = lambda i: i > k and ((_f(m15[i], "low") <= zone_high) if long else (_f(m15[i], "high") >= zone_low))  # noqa: E731
    taps = [i for i in after if touched(i)]
    first_tap = taps[0] if taps else None
    context["poi"] = {"type": "ORDER_BLOCK", "zone_low": zone_low, "zone_high": zone_high, "invalidated": invalidated,
                      "first_tap_time": _time(m15, first_tap), "bars_since_first_tap": (n - 1 - first_tap) if taps else None}
    if invalidated:
        return _no_setup("Order block invalidated: price closed through it after the structure break.", atr=atr_m15,
                         strategy_evidence=context)
    if first_tap is not None and n - 1 - first_tap >= POI_REACTION_BARS:
        return _no_setup(f"Order block mitigated: no confirmed reaction within {POI_REACTION_BARS} bars of the first retest.",
                         atr=atr_m15, strategy_evidence=context)
    gates["poi_retest"] = first_tap is not None

    # 7. Reaction candle.
    candle = confirm_rejection(m15, long, touched,
                               closed_outside=lambda i: (_f(m15[i], "close") > zone_high) if long else (_f(m15[i], "close") < zone_low),
                               earliest=k + 1) if first_tap is not None else None
    gates["reaction"] = bool(candle and candle["confirmed"])
    context["candle_confirmation"] = ({"confirmed": candle["confirmed"], "pattern": candle["pattern"], "patterns": candle["patterns"],
                                       "candle_time": candle["candle_time"],
                                       "touch_time": _time(m15, candle["touch_index"]),
                                       "rule": "any one of wick_rejection / engulfing / close_away at the order block"}
                                      if candle else None)

    # Plan.
    entry = price
    origin_extreme = _f(m15[origin], "low" if long else "high")
    stop = (min(zone_low, origin_extreme) - STOP_BUFFER_ATR_M15 * atr_m15 if long
            else max(zone_high, origin_extreme) + STOP_BUFFER_ATR_M15 * atr_m15)
    risk = (entry - stop) if long else (stop - entry)
    h1_highs, h1_lows = swing_points(closed["H1"])
    beyond = [p for _, p in h1_highs if p > entry] if long else [p for _, p in h1_lows if p < entry]
    target = (min(beyond) if long else max(beyond)) if beyond else None
    reward = ((target - entry) if long else (entry - target)) if target is not None else None
    rr = round(reward / risk, 2) if reward is not None and risk > 0 else None
    gates["not_chasing"] = ((entry - zone_high) if long else (zone_low - entry)) <= MAX_CHASE_ATR_H1 * atr_h1
    gates["stop_ok"] = MIN_RISK_ATR_M15 * atr_m15 <= risk <= MAX_RISK_ATR_H1 * atr_h1
    gates["target"] = reward is not None and reward > 0
    gates["min_rr"] = rr is not None and rr >= MIN_RR

    if first_tap is None:
        state = "WATCHING"
        reason = f"{'Bullish' if long else 'Bearish'} M15 {event['kind']} with displacement; waiting for a retrace into the order block."
    elif not gates["reaction"]:
        state = "DEVELOPING"
        reason = "Price is in the order block; waiting for a rejection candle that closes back out of it."
    else:
        state = "CONFIRMING"
        reason = f"Order block rejection ({candle['pattern']}) after a {event['kind']}"
    valid = state == "CONFIRMING" and all(gates[name] for name in CONFIRMATION_RULES)
    failed = [name for name in CONFIRMATION_RULES if not gates.get(name, False)]
    if state == "CONFIRMING":
        reason += "; all confirmation rules passed." if valid else "; not confirmed: " + ", ".join(failed) + "."
    planned = state in {"DEVELOPING", "CONFIRMING"} and gates["target"] and risk > 0

    breakdown = {"htf_context": 20, "structure": 20 if event["kind"] == "CHOCH" else 15, "displacement": 15,
                 "fvg_order_block_overlap": 5 if overlap else 0, "liquidity_sweep": 10 if sweep else 0,
                 "reaction": 15 if gates["reaction"] else 0,
                 "risk_reward": (15 if (rr or 0) >= 2.0 else 10 if (rr or 0) >= MIN_RR else 0) if planned else 0}
    context["confirmation"] = {"rules": {name: gates.get(name, False) for name in CONFIRMATION_RULES}, "passed": valid,
                               "failed": failed}
    context["plan"] = {"entry": entry if planned else None, "stop": stop if planned else None, "target": target if planned else None,
                       "target_basis": "H1_SWING" if target is not None else None, "risk": risk if planned else None,
                       "reward": reward if planned else None, "rr": rr if planned else None, "min_rr": MIN_RR,
                       "structure_invalidation": min(zone_low, origin_extreme) if long else max(zone_high, origin_extreme)}
    kind = "BOS" if event["kind"] == "BOS" else "CHoCH"
    setup = f"{'Bullish' if long else 'Bearish'} order block retest after {kind}"
    return {"strategy_version": STRATEGY_VERSION, "timeframe": "M15", "higher_timeframes": ["H1", "H4"],
            "state": state, "direction": direction, "setup": setup, "setup_family": family,
            "strategy_valid": valid, "reason": reason,
            "trigger": None if valid else ("Rejection candle closing back above the order block" if long
                                           else "Rejection candle closing back below the order block"),
            "entry": entry if planned else None, "stop_loss": stop if planned else None,
            "take_profit": target if planned else None, "invalidation_hint": stop if planned else None,
            "rr": rr if planned else None, "risk_distance": risk if planned else None,
            "reward_distance": reward if planned else None, "atr": atr_m15,
            "score": min(100, sum(breakdown.values())), "score_breakdown": breakdown, "strategy_evidence": context}


class SmcStrategy(Strategy):
    strategy_id = "smc"
    version = STRATEGY_VERSION
    timeframe = "M15"
    higher_timeframes = ("H1", "H4")
    # Confirmed setups are historical events resolved only at their own stop or target.
    lifecycle = CONFIRMED_EVENTS_LIFECYCLE
    # H4 is the preferred HTF context, used when available; H1 is the recorded fallback.
    data_requirements = {"M15": 300, "H1": 160}

    def evaluate(self, market: MarketInput) -> dict[str, Any]:
        return analyze_smc(market)
