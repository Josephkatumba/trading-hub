"""Phase 11: Trend / Momentum stop-model A/B replay (read-only, deterministic).

A = tm-pullback-v1 (fixed 0.25 ATR(H1) buffer beyond the pullback extreme)
B = tm-pullback-v2 (structure + clamp(1.0 ATR(M15), 0.25-0.5 ATR(H1)) buffer, explicit risk guard)

The setup rules (trend, impulse, pullback, trigger, target) are identical in both
versions: a bar's state and direction never differ, only the stop and whatever
follows from it (risk, R:R, the stop_ok / min_rr gates, the market path).

Replay, per symbol, walking every M15 bar k of the history:
  - the strategy sees exactly the bars it would have seen live when bar k opened:
    for each timeframe the bars that had opened by then, the last one forming. The
    forming M15 bar is a flat bar at bar k's open (the price at that moment), so no
    part of bar k's future range is visible. The strategy drops every forming bar
    except for that price (closed bars only).
  - a confirmation (strategy_valid) opens a simulated setup unless one in the same
    direction is still open for that model (it would be the same live episode). An
    opposite-direction confirmation opens a separate, competing setup.
  - the setup is resolved on the M15 bars from k on (entry at bar k's open, so bar
    k's range is after entry): TARGET if the target is touched first, STOP if the stop
    is touched first, AMBIGUOUS if both in one bar (order unknown), EXPIRED if
    neither within HORIZON_BARS. This is a market path, not a trade result: no spread,
    slippage or commission.
Nothing here is fitted: the replay only measures the two fixed models.
"""
from __future__ import annotations

import bisect
from statistics import mean, median
from typing import Any, Iterable, Mapping, Sequence

from strategies import MarketInput
from strategies import trend_momentum as tm

MODELS = (tm.LEGACY_VERSION, tm.STRATEGY_VERSION)          # A, B
WINDOW = {"M15": 300, "H1": 160, "H4": 200, "D1": 200}      # the live collector's bar counts
HORIZON_BARS = 480                                          # 5 trading days of M15 bars
TIGHT_RISK_ATR = 0.75                                       # "extremely tight" reporting threshold, ATR(H1)


def _window(rows: Sequence[Mapping[str, Any]], times: Sequence[float], at: float, count: int) -> list[Mapping[str, Any]]:
    """Bars that had opened by `at` (the last one is the forming bar)."""
    end = bisect.bisect_right(times, at)
    return list(rows[max(0, end - count):end])


def market_at(symbol: str, frames: Mapping[str, Sequence[Mapping[str, Any]]], times: Mapping[str, Sequence[float]],
              k: int) -> MarketInput:
    """The MarketInput the live collector would have produced when M15 bar k opened."""
    m15 = frames["M15"]
    bar = m15[k]
    forming = {"time": bar["time"], "open": bar["open"], "high": bar["open"], "low": bar["open"], "close": bar["open"]}
    bars = {"M15": list(m15[max(0, k - WINDOW["M15"] + 1):k]) + [forming]}
    for tf in ("H1", "H4", "D1"):
        if tf in frames:
            bars[tf] = _window(frames[tf], times[tf], float(bar["time"]), WINDOW[tf])
    return MarketInput(symbol, bars["M15"], higher_rows=bars.get("H1"), bars=bars)


def resolve(direction: str, entry: float, stop: float, target: float, path: Sequence[Mapping[str, Any]],
            horizon: int = HORIZON_BARS) -> dict[str, Any]:
    """First barrier touched on the M15 path (bar 0 is the entry bar)."""
    long = direction == "LONG"
    risk = abs(entry - stop)
    worst = best = 0.0
    for i, bar in enumerate(path[:horizon]):
        high, low = float(bar["high"]), float(bar["low"])
        best = max(best, (high - entry) if long else (entry - low))
        worst = max(worst, (entry - low) if long else (high - entry))
        hit_target = high >= target if long else low <= target
        hit_stop = low <= stop if long else high >= stop
        if hit_target and hit_stop:
            return {"outcome": "AMBIGUOUS", "bars": i + 1, "mfe_r": best / risk, "mae_r": worst / risk}
        if hit_target:
            return {"outcome": "TARGET", "bars": i + 1, "mfe_r": best / risk, "mae_r": worst / risk}
        if hit_stop:
            return {"outcome": "STOP", "bars": i + 1, "mfe_r": best / risk, "mae_r": worst / risk}
    complete = len(path) >= horizon
    return {"outcome": "EXPIRED" if complete else "OPEN", "bars": min(len(path), horizon),
            "mfe_r": best / risk if risk else None, "mae_r": worst / risk if risk else None}


def _risk_class(result: Mapping[str, Any]) -> str | None:
    """Why a triggered (CONFIRMING) setup was or was not confirmed, from its stored gates."""
    evidence = result.get("strategy_evidence") or {}
    failed = set((evidence.get("confirmation") or {}).get("failed") or [])
    plan = evidence.get("plan") or {}
    unit = (evidence.get("atr") or {}).get("H1") or result.get("atr")
    if not failed:
        return "CONFIRMED"
    if "stop_ok" in failed and plan.get("risk") is not None and unit:
        return "RISK_TOO_WIDE" if plan["risk"] > tm.MAX_RISK_ATR * unit else "RISK_TOO_TIGHT"
    if "min_rr" in failed:
        return "RR_BELOW_MIN"
    return "OTHER_GATE"


def replay_symbol(symbol: str, frames: Mapping[str, Sequence[Mapping[str, Any]]], start_time: float | None = None,
                  models: Iterable[str] = MODELS) -> dict[str, Any]:
    """Walk one symbol's M15 history under every model. Pure: same input, same output."""
    models = tuple(models)
    times = {tf: [float(bar["time"]) for bar in rows] for tf, rows in frames.items()}
    m15 = frames["M15"]
    first = max(WINDOW["M15"], bisect.bisect_left(times["M15"], start_time) if start_time is not None else 0)
    open_until: dict[tuple[str, str], int] = {}
    setups: dict[str, list[dict[str, Any]]] = {model: [] for model in models}
    triggers: dict[str, list[dict[str, Any]]] = {model: [] for model in models}
    counts = {"evaluated_bars": 0, "developing_bars": 0, "confirming_bars": 0}
    for k in range(first, len(m15)):
        market = market_at(symbol, frames, times, k)
        base = tm.analyze_trend_momentum(market, models[0])
        counts["evaluated_bars"] += 1
        state = base["state"]
        if state == "DEVELOPING":
            counts["developing_bars"] += 1
        if state != "CONFIRMING":
            continue                               # state never depends on the stop model
        counts["confirming_bars"] += 1
        for model in models:
            result = base if model == models[0] else tm.analyze_trend_momentum(market, model)
            assert result["state"] == state and result["direction"] == base["direction"]
            evidence = result["strategy_evidence"]
            unit = evidence["atr"]["H1"]
            plan = evidence.get("plan") or {}
            classification = _risk_class(result)
            triggers[model].append({"k": k, "time": m15[k]["time"], "direction": result["direction"],
                                    "class": classification, "risk": plan.get("risk"), "atr_h1": unit,
                                    "rr": plan.get("rr")})
            if not result["strategy_valid"]:
                continue
            key = (model, result["direction"])
            if open_until.get(key, -1) >= k:
                continue                           # the same live episode would still be open
            entry, stop, target = result["entry"], result["stop_loss"], result["take_profit"]
            outcome = resolve(result["direction"], entry, stop, target, m15[k:])
            open_until[key] = k + outcome["bars"] - 1
            setups[model].append({"symbol": symbol, "k": k, "time": m15[k]["time"], "direction": result["direction"],
                                  "entry": entry, "stop": stop, "target": target, "risk": abs(entry - stop),
                                  "risk_atr_h1": abs(entry - stop) / unit, "atr_h1": unit, "rr": result["rr"],
                                  "risk_quality": (evidence.get("stop") or {}).get("risk_quality"),
                                  "score": result["score"], **outcome})
    return {"symbol": symbol, "counts": counts, "setups": setups, "triggers": triggers}


def _r(setup: Mapping[str, Any]) -> float | None:
    return {"TARGET": setup["rr"], "STOP": -1.0}.get(setup["outcome"])


def summarize(setups: Sequence[Mapping[str, Any]], triggers: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate statistics for one model. Rates only where they are defined."""
    outcomes = {name: sum(1 for s in setups if s["outcome"] == name) for name in ("TARGET", "STOP", "AMBIGUOUS", "EXPIRED", "OPEN")}
    risks = [s["risk_atr_h1"] for s in setups]
    rrs = [s["rr"] for s in setups if s["rr"] is not None]
    decided = outcomes["TARGET"] + outcomes["STOP"]
    realised = [_r(s) for s in setups if _r(s) is not None]
    classes = {}
    for trigger in triggers:
        classes[trigger["class"]] = classes.get(trigger["class"], 0) + 1
    quality = {}
    for s in setups:
        if s.get("risk_quality"):
            quality[s["risk_quality"]] = quality.get(s["risk_quality"], 0) + 1
    stat = lambda values, fn: round(fn(values), 3) if values else None  # noqa: E731
    return {"triggers": len(triggers), "trigger_classes": classes, "confirmations": len(setups), "outcomes": outcomes,
            "target_share_of_decided": round(outcomes["TARGET"] / decided, 3) if decided else None, "decided": decided,
            "stop_distance_atr_h1": {"mean": stat(risks, mean), "median": stat(risks, median),
                                     "min": stat(risks, min), "max": stat(risks, max)},
            "rr": {"mean": stat(rrs, mean), "median": stat(rrs, median), "min": stat(rrs, min), "max": stat(rrs, max)},
            "extremely_tight": sum(1 for r in risks if r < TIGHT_RISK_ATR),
            "risk_quality": quality,
            "mean_r_decided": stat(realised, mean), "sum_r_decided": round(sum(realised), 2) if realised else None,
            "mean_bars_to_outcome": stat([s["bars"] for s in setups if s["outcome"] in ("TARGET", "STOP")], mean)}


def compare(a: Sequence[Mapping[str, Any]], b: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Pairs setups confirmed on the same symbol, bar and direction under both models."""
    key = lambda s: (s["symbol"], s["k"], s["direction"])  # noqa: E731
    left, right = {key(s): s for s in a}, {key(s): s for s in b}
    both = sorted(set(left) & set(right))
    survived_new = [k for k in both if left[k]["outcome"] == "STOP" and right[k]["outcome"] != "STOP"]
    survived_old = [k for k in both if right[k]["outcome"] == "STOP" and left[k]["outcome"] != "STOP"]
    def row(k):
        return {"symbol": k[0], "time": left[k]["time"], "direction": k[2],
                "A": {f: left[k][f] for f in ("stop", "rr", "outcome", "risk_atr_h1")},
                "B": {f: right[k][f] for f in ("stop", "rr", "outcome", "risk_atr_h1")}}
    return {"paired": len(both), "only_A": len(set(left) - set(right)), "only_B": len(set(right) - set(left)),
            "survived_B_failed_A": len(survived_new), "survived_A_failed_B": len(survived_old),
            "survived_B_failed_A_examples": [row(k) for k in survived_new[:25]],
            "survived_A_failed_B_examples": [row(k) for k in survived_old[:25]],
            "same_outcome": sum(1 for k in both if left[k]["outcome"] == right[k]["outcome"])}
