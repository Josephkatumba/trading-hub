"""Strategies and experiments of the research lab.

Production strategies are instantiated from their own classes (never modified). Every
experiment is registered below with its hypothesis and trading rationale BEFORE it is run,
and its result is recorded in the ledger whatever it is. Parameterised experiments are
evaluated with lab.walk_forward (parameters chosen only on the 6 months before each fold).

Evidence that motivated the experiments (SIGNAL_AUDIT_2026-10-19.md, signal_outcomes):
  - stops sit ~1 M15 ATR from entry; 47% of live stops were hit within an hour
  - Trend/Momentum targets median 5.6 ATR / 4.8R away: 1 target in 13 live signals
  - stop-outs cluster around the 21:00-00:00 UTC rollover; live BUY signals did worse than SELLs
All features below use closed bars before the signal bar only (no look-ahead).
"""
from __future__ import annotations

import bisect
from typing import Any, Callable

from research import lab

PRODUCTION = ("trendline_v5", "support_resistance", "trend_momentum", "smc")
GENERATED = list(PRODUCTION)


def strategy(strategy_id: str) -> Any:
    from strategies import SmcStrategy, SupportResistanceStrategy, TrendMomentumStrategy, TrendlineV51Strategy
    factories = {"trendline_v5": TrendlineV51Strategy, "support_resistance": SupportResistanceStrategy,
                 "trend_momentum": TrendMomentumStrategy, "smc": SmcStrategy}
    return factories[strategy_id]()


# ----- features (closed bars only) -------------------------------------------------------------

_FEATURES: dict[str, dict[str, Any]] = {}


def _ema(values: list[float], period: int) -> list[float]:
    out, k = [], 2 / (period + 1)
    for value in values:
        out.append(value if not out else out[-1] + k * (value - out[-1]))
    return out


def features(history_: Any) -> dict[str, Any]:
    symbol = history_.symbol
    if symbol in _FEATURES:
        return _FEATURES[symbol]
    m15 = history_.full["M15"]
    tr = [0.0] + [max(b["high"] - b["low"], abs(b["high"] - m15[k - 1]["close"]), abs(b["low"] - m15[k - 1]["close"]))
                  for k, b in enumerate(m15) if k > 0]
    atr = [None] * len(m15)                     # atr[i]: ATR14 of the 14 bars CLOSED before bar i
    running = 0.0
    for i in range(1, len(m15)):
        running += tr[i - 1]
        if i > 15:
            running -= tr[i - 15]
        if i >= 15:
            atr[i] = running / 14
    h4 = history_.full["H4"]
    closes = [b["close"] for b in h4]
    ema = _ema(closes, 50)
    feats = {"atr": atr, "h4_time": [b["time"] for b in h4], "h4_close": closes, "h4_ema": ema}
    _FEATURES[symbol] = feats
    return feats


def h4_trend(history_: Any, index: int) -> str:
    """UP / DOWN / FLAT from H4 bars closed before M15 bar `index` opened."""
    f = features(history_)
    now = history_.full["M15"][index]["time"]
    j = bisect.bisect_right(f["h4_time"], now - 14400) - 1      # last H4 bar with open + 4h <= now
    if j < 55:
        return "FLAT"
    close, ema, ema_before = f["h4_close"][j], f["h4_ema"][j], f["h4_ema"][j - 5]
    if close > ema and ema > ema_before:
        return "UP"
    if close < ema and ema < ema_before:
        return "DOWN"
    return "FLAT"


def utc_hour(signal: dict[str, Any]) -> float:
    return (signal["utc"] % 86400) / 3600


def plan_r(signal: dict[str, Any]) -> float | None:
    entry, sl, tp = signal["entry"], signal["stop_loss"], signal["take_profit"]
    try:
        risk = abs(entry - sl)
        return abs(tp - entry) / risk if risk > 0 else None
    except TypeError:
        return None


# ----- overlay transforms --------------------------------------------------------------------------

Transform = Callable[[dict[str, Any], Any], "dict[str, Any] | None"]


def keep(signal, history_):
    return {}


def htf_aligned(signal, history_):
    trend = h4_trend(history_, signal["index"])
    return {} if (trend == "UP" and signal["direction"] == "LONG") or (trend == "DOWN" and signal["direction"] == "SHORT") else None


def london_ny(signal, history_):
    return {} if 7 <= utc_hour(signal) < 20 else None


def no_rollover(signal, history_):
    hour = utc_hour(signal)
    return None if hour >= 20.5 or hour < 0.5 else {}


def min_score(threshold: int) -> Transform:
    def transform(signal, history_):
        score = signal["evidence"].get("score")
        return {} if isinstance(score, (int, float)) and score >= threshold else None
    return transform


def stop_floor(k_atr: float, max_r: float | None = None) -> Transform:
    """Stop at least k ATR from entry; the target keeps the plan's R multiple (capped at max_r)."""
    def transform(signal, history_):
        atr = features(history_)["atr"][signal["index"]]
        r = plan_r(signal)
        if atr is None or r is None:
            return None
        entry, sl = signal["entry"], signal["stop_loss"]
        long = signal["direction"] == "LONG"
        risk = max(abs(entry - sl), k_atr * atr)
        r = min(r, max_r) if max_r else r
        return {"stop_loss": entry - risk if long else entry + risk,
                "take_profit": entry + r * risk if long else entry - r * risk}
    return transform


def target_cap(cap_r: float) -> Transform:
    def transform(signal, history_):
        r = plan_r(signal)
        if r is None:
            return None
        if r <= cap_r:
            return {}
        entry, sl = signal["entry"], signal["stop_loss"]
        risk = abs(entry - sl)
        return {"take_profit": entry + cap_r * risk if signal["direction"] == "LONG" else entry - cap_r * risk}
    return transform


def chain(*transforms: Transform) -> Transform:
    def transform(signal, history_):
        merged: dict[str, Any] = {}
        current = dict(signal)
        for step in transforms:
            out = step(current, history_)
            if out is None:
                return None
            merged.update(out)
            current.update(out)
        return merged
    return transform


# ----- a new generator: SMC V2 liquidity sweep and reclaim --------------------------------------------

def smc_v2_signals(history_: Any, target_r: float = 2.0, displacement_atr: float = 0.6,
                   require_htf: bool = True) -> list[dict[str, Any]]:
    """Previous-day high/low sweep, reclaimed on the same closed M15 candle with displacement.

    Rationale: obvious liquidity (the previous day's high/low) attracts stop orders; a sweep
    that is immediately rejected (close back inside the range, large body) shows the
    breakout was absorbed. The trade fades the sweep in the H4 trend direction, stop beyond
    the sweep extreme (+0.1 ATR), target a fixed R multiple. Decided on closed bar i-1,
    entered at bar i's open; at most one signal per side per day.
    """
    m15, d1 = history_.full["M15"], history_.full["D1"]
    d1_times = [b["time"] for b in d1]
    atr = features(history_)["atr"]
    out, taken = [], set()
    for i in range(300, len(m15)):
        bar, prev = m15[i], m15[i - 1]
        a = atr[i]
        if a is None or a <= 0:
            continue
        j = bisect.bisect_right(d1_times, bar["time"] - 86400) - 1          # last D1 closed before now
        if j < 0:
            continue
        pdh, pdl = d1[j]["high"], d1[j]["low"]
        day = int(bar["time"] // 86400)
        body = abs(prev["close"] - prev["open"])
        trend = h4_trend(history_, i) if require_htf else None
        spread = bar["spread"]
        if prev["high"] > pdh and prev["close"] < pdh and prev["close"] < prev["open"] and body >= displacement_atr * a \
                and (not require_htf or trend == "DOWN") and (day, "S") not in taken:
            entry = bar["open"]                                              # SELL at the bid
            stop = prev["high"] + 0.1 * a + spread
            risk = stop - entry
            if risk > 0:
                taken.add((day, "S"))
                out.append({"index": i, "utc": bar["utc"], "symbol": history_.symbol, "strategy_id": "smc_v2",
                            "direction": "SHORT", "entry": entry, "stop_loss": stop, "take_profit": entry - target_r * risk,
                            "spread": spread, "evidence": {"score": None, "pdh": pdh, "sweep_high": prev["high"]}})
        if prev["low"] < pdl and prev["close"] > pdl and prev["close"] > prev["open"] and body >= displacement_atr * a \
                and (not require_htf or trend == "UP") and (day, "L") not in taken:
            entry = bar["open"] + spread                                     # BUY at the ask
            stop = prev["low"] - 0.1 * a
            risk = entry - stop
            if risk > 0:
                taken.add((day, "L"))
                out.append({"index": i, "utc": bar["utc"], "symbol": history_.symbol, "strategy_id": "smc_v2",
                            "direction": "LONG", "entry": entry, "stop_loss": stop, "take_profit": entry + target_r * risk,
                            "spread": spread, "evidence": {"score": None, "pdl": pdl, "sweep_low": prev["low"]}})
    return out


def generated_signals(generator: Callable[[Any], list[dict[str, Any]]]) -> list[dict[str, Any]]:
    rows = []
    for symbol in lab.SYMBOLS:
        rows += generator(lab.history_for(symbol))
    return sorted(rows, key=lambda r: (r["utc"], r["symbol"]))


# ----- the registered experiments -----------------------------------------------------------------------

STOP_FAMILY = {"stop 1.0 ATR": stop_floor(1.0), "stop 1.5 ATR": stop_floor(1.5), "stop 2.0 ATR": stop_floor(2.0)}
CAP_FAMILY = {"cap 1.5R": target_cap(1.5), "cap 2R": target_cap(2.0), "cap 2.5R": target_cap(2.5), "cap 3R": target_cap(3.0)}


def overlays() -> list[dict[str, Any]]:
    """(name, hypothesis, rationale, transform or family) applied to each production strategy."""
    return [
        {"name": "H4 trend alignment", "transform": htf_aligned,
         "hypothesis": "Signals in the H4 trend direction have higher expectancy than counter-trend ones.",
         "rationale": "Intraday setups against the higher-timeframe trend fight the dominant order flow."},
        {"name": "London/New York hours only", "transform": london_ny,
         "hypothesis": "Signals 07:00-20:00 UTC outperform Asian/off-hours signals.",
         "rationale": "Liquidity and follow-through concentrate in the London and New York sessions; spreads are tighter."},
        {"name": "Exclude rollover", "transform": no_rollover,
         "hypothesis": "Excluding signals between 20:30 and 00:30 UTC removes spread-driven stop-outs.",
         "rationale": "Broker rollover widens spreads; audit found stop-outs clustered at 00:00 and 21:00 UTC."},
        {"name": "Score >= 80", "transform": min_score(80),
         "hypothesis": "The rule-point score ranks setups: score >= 80 has higher expectancy.",
         "rationale": "Live data showed target-first rates rising with score (10% below 70, 38% at 90+)."},
        {"name": "Volatility stop floor (walk-forward)", "family": STOP_FAMILY, "default": "stop 1.5 ATR",
         "hypothesis": "A stop at least k x ATR(14, M15) away (same R multiple) reduces noise stop-outs enough to raise expectancy.",
         "rationale": "Stops at ~1 ATR are inside one candle's normal range; 47% of live stops hit within an hour."},
        {"name": "Target cap (walk-forward)", "family": CAP_FAMILY, "default": "cap 2R",
         "hypothesis": "Capping targets at a realistic R multiple raises expectancy when far targets are rarely reached.",
         "rationale": "Trend/Momentum targets sat 4-6R away; median MFE within 24h was far below them."},
    ]


COMPOSITES = [
    {"name": "Trendline V6 (experimental)", "base": "trendline_v5",
     "transform": chain(htf_aligned, no_rollover), "family_suffix": STOP_FAMILY, "default": "stop 1.5 ATR",
     "hypothesis": "Break-and-retest signals only with the H4 trend, outside rollover, with a volatility stop floor.",
     "rationale": "Combines the three independently motivated filters; tests whether the trendline edge exists at all once noise and counter-trend trades are removed."},
    {"name": "S&R V2 (experimental)", "base": "support_resistance",
     "transform": chain(no_rollover, london_ny), "family_suffix": STOP_FAMILY, "default": "stop 1.5 ATR",
     "hypothesis": "Level rejections/breakouts confirmed in liquid hours with a volatility stop floor (false-breakout buffer).",
     "rationale": "False breakouts are most common in thin liquidity; a wider stop beyond the zone absorbs the probe."},
    {"name": "Momentum V2 (experimental)", "base": "trend_momentum",
     "transform": chain(no_rollover), "family_suffix": CAP_FAMILY, "default": "cap 2R",
     "hypothesis": "Trend/Momentum with realistic targets (walk-forward cap) has positive expectancy.",
     "rationale": "The production target is a measured impulse capped by H1 swings, often 4-6R; the entry logic may be sound while the target is unreachable."},
]


def _record(result: dict[str, Any], **meta: Any) -> dict[str, Any]:
    d, h = result["development"], result["holdout"]
    sufficient = d["sufficient"]
    low = (d["expectancy_ci95"] or [None])[0]
    if not sufficient:
        verdict = f"INSUFFICIENT SAMPLE ({d['trades']} development trades)"
    elif low is not None and low > 0 and d["profit_factor"] and d["profit_factor"] > 1 and (h["expectancy_r"] or 0) > 0 \
            and (result["development_double_costs"]["expectancy_r"] or 0) > 0:
        verdict = "CANDIDATE (positive out-of-sample, CI above 0, holdout positive, survives double costs)"
    elif (d["expectancy_r"] or 0) > 0:
        verdict = "INCONCLUSIVE (positive point estimate, CI includes 0 or holdout/cost stress fails)"
    else:
        verdict = "REJECTED (non-positive out-of-sample expectancy)"
    entry = {**result, **meta, "verdict": verdict}
    lab.record(entry)
    print(f"{meta['name'][:58]:58} dev n={d['trades']:4} WR={d['win_rate']} E={d['expectancy_r']} CI={d['expectancy_ci95']} "
          f"PF={d['profit_factor']} folds+={result['positive_folds']} x2cost E={result['development_double_costs']['expectancy_r']} "
          f"| hold n={h['trades']} E={h['expectancy_r']} -> {verdict.split(' (')[0]}", flush=True)
    return entry


def run_baseline() -> dict[str, Any]:
    results = {}
    for strategy_id in PRODUCTION:
        result = lab.evaluate(lab.load_signals(strategy_id))
        results[strategy_id] = _record(result, name=f"BASELINE {strategy_id}", kind="baseline", strategy_id=strategy_id,
                                       hypothesis="Production strategy as deployed (apply_plan + executable qualification), with costs.",
                                       rationale="Reference for every experiment on the same periods.")
    return results


def run_all() -> list[dict[str, Any]]:
    entries = []
    for strategy_id in PRODUCTION:
        signals = lab.load_signals(strategy_id)
        for overlay in overlays():
            name = f"{strategy_id}: {overlay['name']}"
            if "family" in overlay:
                result = lab.walk_forward(signals, overlay["family"], overlay["default"])
            else:
                result = lab.evaluate(signals, overlay["transform"])
            entries.append(_record(result, name=name, kind="overlay", strategy_id=strategy_id,
                                   hypothesis=overlay["hypothesis"], rationale=overlay["rationale"]))
    for composite in COMPOSITES:
        signals = lab.load_signals(composite["base"])
        family = {name: chain(composite["transform"], step) for name, step in composite["family_suffix"].items()}
        result = lab.walk_forward(signals, family, composite["default"])
        entries.append(_record(result, name=composite["name"], kind="composite", strategy_id=composite["base"],
                               hypothesis=composite["hypothesis"], rationale=composite["rationale"]))
    smc_v2 = {f"target {r}R, displacement {d} ATR": generated_signals(lambda h, r=r, d=d: smc_v2_signals(h, r, d))
              for r in (1.5, 2.0, 3.0) for d in (0.6, 1.0)}
    pooled = sorted((dict(s, strategy_id="smc_v2:" + name) for name, rows in smc_v2.items() for s in rows),
                    key=lambda s: (s["utc"], s["symbol"]))
    family = {name: (lambda n: (lambda s, h: {} if s["strategy_id"] == "smc_v2:" + n else None))(name) for name in smc_v2}
    result = lab.walk_forward(pooled, family, "target 2.0R, displacement 0.6 ATR")
    entries.append(_record(result, name="SMC V2: previous-day liquidity sweep + reclaim (experimental)", kind="new_strategy",
                           strategy_id="smc_v2", hypothesis="A previous-day high/low sweep rejected on the same M15 candle "
                           "with displacement, traded with the H4 trend, has positive expectancy.",
                           rationale=smc_v2_signals.__doc__.split("\n\n")[1].strip()))
    return entries
