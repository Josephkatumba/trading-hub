"""TRADEden V6 research: baseline, random-entry control, conflict analysis, new strategy
families, train -> validation selection and a single test scoring.

Protocol (fixed before any V6 result was seen):
  TRAIN       2024-10-15 .. 2025-10-01   explore; parameter grids are ranked here only
  VALIDATION  2025-10-01 .. 2026-04-01   choose ONE configuration per family from the train shortlist
  TEST        2026-04-01 .. 2026-10-12   scored once, for the chosen finalists only; never used to choose
The T-032 holdout is the same window as TEST; T-032 scored its variants there once, but no V6
parameter or filter is chosen with it.

Every configuration evaluated is written to the ledger (data/research/ledger.jsonl, kind "v6-*"),
including the ones that failed. Results are in R after costs (simulate.py).

    python -m research.v6 all       run every stage and write data/research/v6_results.json
"""
from __future__ import annotations

import bisect
import json
import math
import random
import sys
from collections import defaultdict
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
from typing import Any, Callable, Iterable

from research import experiments as ex
from research import lab
from research.metrics import summarize

UTC = timezone.utc
TRAIN = (datetime(2024, 10, 15, tzinfo=UTC), datetime(2025, 10, 1, tzinfo=UTC))
VALID = (datetime(2025, 10, 1, tzinfo=UTC), datetime(2026, 4, 1, tzinfo=UTC))
TEST = (datetime(2026, 4, 1, tzinfo=UTC), datetime(2026, 10, 12, tzinfo=UTC))
MIN_TRAIN, MIN_VALID = 60, 30
KEEP = ("trades", "win_rate", "expectancy_r", "expectancy_ci95", "p_expectancy_positive", "profit_factor",
        "total_r", "max_drawdown_r", "trades_per_month", "avg_hold_hours", "ambiguous")


def months(window) -> float:
    return lab.months(*window)


def stats(trade_list: list[dict[str, Any]], window=None) -> dict[str, Any]:
    s = summarize(trade_list, months(window) if window else None)
    return {k: s[k] for k in KEEP}


def run(signals: list[dict[str, Any]], window, transform=None, **kw) -> list[dict[str, Any]]:
    return lab.trades(signals, transform, *window, **kw)


# ----- 1. baseline (corrected simulator) and random-entry control ----------------------------------------

def baseline() -> dict[str, Any]:
    out = {}
    for sid in ex.PRODUCTION:
        sig = lab.load_signals(sid)
        out[sid] = {name: stats(run(sig, w), w) for name, w in (("train", TRAIN), ("validation", VALID), ("test", TEST))}
        dev = run(sig, (TRAIN[0], VALID[1]))
        out[sid]["development_gross"] = stats(run(sig, (TRAIN[0], VALID[1]), cost_multiplier=0.0))
        out[sid]["development_x2_costs"] = stats(run(sig, (TRAIN[0], VALID[1]), cost_multiplier=2.0))
        out[sid]["development"] = stats(dev)
    return out


def random_twins(signals: list[dict[str, Any]], seed: int) -> list[dict[str, Any]]:
    """For each signal, an entry on a random M15 bar of the same symbol within +-15 days, random
    direction, same stop distance in ATR and same planned R. Same instruments, timing density,
    geometry and costs; no information."""
    rng = random.Random(seed)
    twins = []
    for s in signals:
        h = lab.history_for(s["symbol"])
        f = ex.features(h)
        atr0 = f["atr"][s["index"]]
        r = ex.plan_r(s)
        if not atr0 or not r:
            continue
        k_atr = abs(s["entry"] - s["stop_loss"]) / atr0
        bars = h.full["M15"]
        for _ in range(5):
            j = s["index"] + rng.randint(-1440, 1440)
            if 300 <= j < len(bars) and f["atr"][j]:
                break
        else:
            continue
        long = rng.random() < 0.5
        bid, spread = bars[j]["open"], bars[j]["spread"]
        entry = bid + spread if long else bid
        risk = k_atr * f["atr"][j]
        twins.append({"index": j, "utc": bars[j]["utc"], "symbol": s["symbol"], "strategy_id": "random:" + s["strategy_id"],
                      "direction": "LONG" if long else "SHORT", "entry": entry,
                      "stop_loss": entry - risk if long else entry + risk,
                      "take_profit": entry + r * risk if long else entry - r * risk, "spread": spread, "evidence": {}})
    return sorted(twins, key=lambda t: (t["utc"], t["symbol"]))


def random_control(seeds: int = 20) -> dict[str, Any]:
    window = (TRAIN[0], VALID[1])
    out = {}
    for sid in ex.PRODUCTION:
        sig = [s for s in lab.load_signals(sid) if window[0].timestamp() <= s["utc"] < window[1].timestamp()]
        actual = summarize(run(sig, window))["expectancy_r"]
        draws = sorted(summarize(run(random_twins(sig, seed), window))["expectancy_r"] for seed in range(seeds))
        below = sum(d < actual for d in draws)
        out[sid] = {"strategy_expectancy_r": actual, "random_median_r": draws[len(draws) // 2],
                    "random_range_r": [draws[0], draws[-1]], "strategy_percentile_vs_random": round(below / len(draws), 2),
                    "seeds": seeds}
    return out


# ----- 2. contradictory conditions (trendline evidence) -------------------------------------------------------

CONFLICTS = ("h1_bias", "structure", "momentum", "opposing_level")


def conflicts(signal: dict[str, Any]) -> dict[str, bool]:
    """The T-031B definition (signal_presentation._trendline_cautions), from recorded evidence only."""
    e, buy = signal["evidence"], signal["direction"] == "LONG"
    structure = str(e.get("structure") or "")
    level_atr = e.get("nearest_level_atr")
    return {
        "h1_bias": e.get("higher_timeframe_bias") == ("BEARISH" if buy else "BULLISH"),
        "structure": structure.startswith("Lower highs") if buy else structure.startswith("Higher highs"),
        "momentum": e.get("momentum") == ("BEARISH" if buy else "BULLISH"),
        "opposing_level": (e.get("nearest_level_type") == ("RESISTANCE" if buy else "SUPPORT")
                           and isinstance(level_atr, (int, float)) and level_atr < 0.5),
    }


def conflict_analysis(strategy_id: str = "trendline_v5") -> dict[str, Any]:
    sig = lab.load_signals(strategy_id)
    by_key = {(s["symbol"], s["index"]): s for s in sig}
    result: dict[str, Any] = {}
    for name, window in (("train", TRAIN), ("validation", VALID)):
        tr = run(sig, window)
        for t in tr:
            t["conflicts"] = conflicts(by_key[(t["symbol"], t["index"])])
        part: dict[str, Any] = {"all": stats(tr)}
        for c in CONFLICTS:
            part[f"{c}: present"] = stats([t for t in tr if t["conflicts"][c]])
            part[f"{c}: absent"] = stats([t for t in tr if not t["conflicts"][c]])
        for n, label in ((0, "0 conflicts"), (1, "1 conflict"), (2, "2+ conflicts")):
            part[label] = stats([t for t in tr if (sum(t["conflicts"].values()) == n if n < 2 else sum(t["conflicts"].values()) >= 2)])
        # Supporting evidence (the opposite of a conflict): aligned H1 bias, structure and momentum.
        def aligned(t):
            e = by_key[(t["symbol"], t["index"])]["evidence"]
            buy = t["direction"] == "LONG"
            return (e.get("higher_timeframe_bias") == ("BULLISH" if buy else "BEARISH") and
                    e.get("momentum") == ("BULLISH" if buy else "BEARISH"))
        part["H1 bias and momentum both aligned"] = stats([t for t in tr if aligned(t)])
        result[name] = part
    return result


# ----- 3. new strategy families (research generators; closed bars only, entry at next open) -----------------

def _ema(values: list[float], period: int) -> list[float]:
    return ex._ema(values, period)


def _atr(bars: list[dict[str, Any]], period: int = 14) -> list[float | None]:
    """atr[i] = ATR of the `period` bars closed up to and including bar i."""
    out: list[float | None] = [None] * len(bars)
    trs = []
    for i, b in enumerate(bars):
        prev = bars[i - 1]["close"] if i else b["open"]
        trs.append(max(b["high"] - b["low"], abs(b["high"] - prev), abs(b["low"] - prev)))
        if i >= period:
            out[i] = sum(trs[i - period + 1:i + 1]) / period
    return out


_H1: dict[str, Any] = {}


def h1_context(h) -> dict[str, Any]:
    """H1 arrays plus the M15 index at which each H1 bar's successor opens (entry bar)."""
    if h.symbol in _H1:
        return _H1[h.symbol]
    h1 = h.full["H1"]
    m15_by_utc = {b["utc"]: i for i, b in enumerate(h.full["M15"])}
    closes = [b["close"] for b in h1]
    ctx = {"bars": h1, "atr": _atr(h1), "ema20": _ema(closes, 20), "ema50": _ema(closes, 50),
           "ema200": _ema(closes, 200),
           "entry_index": [m15_by_utc.get(b["utc"] + 3600) for b in h1]}
    _H1[h.symbol] = ctx
    return ctx


def _signal(h, i15: int, family: str, long: bool, stop_distance: float, target_r: float | None,
            trail: float | None, max_bars: int, evidence: dict[str, Any]) -> dict[str, Any] | None:
    bars = h.full["M15"]
    bid, spread = bars[i15]["open"], bars[i15]["spread"]
    entry = bid + spread if long else bid
    if not stop_distance or stop_distance <= 0:
        return None
    stop = entry - stop_distance if long else entry + stop_distance
    target = None if target_r is None else (entry + target_r * stop_distance if long else entry - target_r * stop_distance)
    return {"index": i15, "utc": bars[i15]["utc"], "symbol": h.symbol, "strategy_id": family,
            "direction": "LONG" if long else "SHORT", "entry": entry, "stop_loss": stop, "take_profit": target,
            "trail": trail, "max_bars": max_bars, "spread": spread, "evidence": {"score": None, **evidence}}


def donchian_trend(h, lookback: int, stop_atr: float, exit_: str, htf: bool) -> list[dict[str, Any]]:
    """H1 Donchian breakout in the direction of the H1 EMA50/EMA200 trend.
    Rationale: time-series momentum / trend following is one of the most persistent documented
    effects across FX, indices and commodities; H1 stops are several M15 ATRs wide, so costs are a
    small fraction of R. exit_: 'trail2'/'trail3' (ATR trailing, no target) or 'fixed2'/'fixed3' (R)."""
    c = h1_context(h)
    bars, atr = c["bars"], c["atr"]
    out = []
    for i in range(max(lookback, 210), len(bars)):
        j = c["entry_index"][i]
        a = atr[i]
        if j is None or not a:
            continue
        window = bars[i - lookback:i]
        hi, lo = max(b["high"] for b in window), min(b["low"] for b in window)
        close = bars[i]["close"]
        up_trend = c["ema50"][i] > c["ema200"][i]
        for long in (True, False):
            broke = close > hi if long else close < lo
            if not broke or (htf and up_trend != long):
                continue
            trail = (2.0 if exit_ == "trail2" else 3.0) * a if exit_.startswith("trail") else None
            target = None if trail else float(exit_[-1])
            s = _signal(h, j, "donchian", long, stop_atr * a, target, trail, 10 * 96, {"lookback": lookback})
            if s:
                out.append(s)
    return out


def trend_pullback(h, stop_atr: float, exit_: str) -> list[dict[str, Any]]:
    """H1 pullback-and-resume: EMA50 above EMA200 (trend), the previous H1 close below EMA20 and the
    current close back above it with a bullish candle (mirror for shorts).
    Rationale: buying a pause inside an established trend gives a nearer, structural stop than a
    breakout and avoids chasing extended moves."""
    c = h1_context(h)
    bars, atr = c["bars"], c["atr"]
    out = []
    for i in range(210, len(bars)):
        j, a = c["entry_index"][i], atr[i]
        if j is None or not a:
            continue
        b, p = bars[i], bars[i - 1]
        up = c["ema50"][i] > c["ema200"][i] and c["ema50"][i] > c["ema50"][i - 10]
        down = c["ema50"][i] < c["ema200"][i] and c["ema50"][i] < c["ema50"][i - 10]
        for long, ok in ((True, up), (False, down)):
            if not ok:
                continue
            e20 = c["ema20"][i]
            resumed = (p["close"] < c["ema20"][i - 1] and b["close"] > e20 and b["close"] > b["open"]) if long else \
                      (p["close"] > c["ema20"][i - 1] and b["close"] < e20 and b["close"] < b["open"])
            if not resumed:
                continue
            trail = (2.0 if exit_ == "trail2" else 3.0) * a if exit_.startswith("trail") else None
            target = None if trail else float(exit_[-1])
            s = _signal(h, j, "pullback", long, stop_atr * a, target, trail, 10 * 96, {})
            if s:
                out.append(s)
    return out


def opening_range_breakout(h, target_r: float, stop_mode: str, max_range_atr: float) -> list[dict[str, Any]]:
    """London opening-range breakout: the 07:00-08:00 UTC M15 range; the first M15 close beyond it
    before 12:00 UTC triggers an entry at the next bar's open; stop at the opposite side ('far') or
    the middle ('mid') of the range; time exit at 20:00 UTC; ranges wider than max_range_atr x H1 ATR
    are skipped. Rationale: the London open concentrates order flow; a break of the early range
    often starts the day's directional move."""
    m15 = h.full["M15"]
    c = h1_context(h)
    h1_utc = [b["utc"] for b in c["bars"]]
    out = []
    i = 0
    n = len(m15)
    while i < n:
        day = int(m15[i]["utc"] // 86400)
        start, end = day * 86400 + 7 * 3600, day * 86400 + 8 * 3600
        j = i
        while j < n and int(m15[j]["utc"] // 86400) == day:
            j += 1
        bars = m15[i:j]
        rng = [b for b in bars if start <= b["utc"] < end]
        if len(rng) == 4:
            hi, lo = max(b["high"] for b in rng), min(b["low"] for b in rng)
            k = bisect.bisect_right(h1_utc, start - 3600) - 1
            a = c["atr"][k] if k >= 0 else None
            if a and (hi - lo) <= max_range_atr * a and hi > lo:
                for idx in range(i, j - 1):
                    b = m15[idx]
                    if b["utc"] < end or b["utc"] >= day * 86400 + 12 * 3600:
                        continue
                    long = b["close"] > hi
                    if long or b["close"] < lo:
                        entry_bid = m15[idx + 1]["open"]
                        level = (lo if long else hi) if stop_mode == "far" else (hi + lo) / 2
                        ref = entry_bid + m15[idx + 1]["spread"] if long else entry_bid
                        dist = (ref - level) if long else (level - ref)
                        bars_to_exit = max(1, int((day * 86400 + 20 * 3600 - m15[idx + 1]["utc"]) // 900))
                        s = _signal(h, idx + 1, "orb", long, dist, target_r, None, bars_to_exit, {"range_atr": (hi - lo) / a})
                        if s and dist > 0:
                            out.append(s)
                        break
        i = j
    return out


def bollinger_reversion(h, z: float, target: str) -> list[dict[str, Any]]:
    """H1 mean reversion in quiet regimes: EMA50 flat (|slope over 10 bars| < 0.3 ATR), the previous
    close outside the z-sigma band and the current close back inside; target the 20-bar mean
    ('mean') or 1.5R; stop 1 ATR beyond the extreme of the two bars.
    Rationale: without a trend, stretched prices tend to revert; the regime gate avoids fading trends."""
    c = h1_context(h)
    bars, atr = c["bars"], c["atr"]
    closes = [b["close"] for b in bars]
    out = []
    for i in range(210, len(bars)):
        j, a = c["entry_index"][i], atr[i]
        if j is None or not a or abs(c["ema50"][i] - c["ema50"][i - 10]) > 0.3 * a:
            continue
        window = closes[i - 20:i]
        mean = sum(window) / 20
        sd = math.sqrt(sum((x - mean) ** 2 for x in window) / 20)
        if not sd:
            continue
        prev, cur = bars[i - 1], bars[i]
        for long in (True, False):
            outside = prev["close"] < mean - z * sd if long else prev["close"] > mean + z * sd
            back = cur["close"] > mean - z * sd if long else cur["close"] < mean + z * sd
            if not (outside and back):
                continue
            extreme = min(prev["low"], cur["low"]) if long else max(prev["high"], cur["high"])
            m = h.full["M15"][j]
            entry = m["open"] + m["spread"] if long else m["open"]
            dist = (entry - (extreme - a)) if long else ((extreme + a) - entry)
            if dist <= 0:
                continue
            if target == "mean":
                reward = (mean - entry) if long else (entry - mean)
                if reward <= 0.5 * dist:
                    continue
                target_r = reward / dist
            else:
                target_r = 1.5
            s = _signal(h, j, "reversion", long, dist, target_r, None, 2 * 96, {})
            if s:
                out.append(s)
    return out


# ----- 3b. round 2 (pre-registered after round 1; no mean-reversion variant, whose test score is known) -----

_TF: dict[tuple[str, str], Any] = {}


def tf_context(h, timeframe: str) -> dict[str, Any]:
    """Bars of `timeframe` with ATR/EMAs and the M15 index of the first bar opening at or after each
    bar's close (the entry bar; None when the next M15 bar is more than 3 days later)."""
    key = (h.symbol, timeframe)
    if key in _TF:
        return _TF[key]
    from research.history import TIMEFRAME_SECONDS
    bars = h.full[timeframe]
    m15_utc = [b["utc"] for b in h.full["M15"]]
    seconds = TIMEFRAME_SECONDS[timeframe]
    entry = []
    for b in bars:
        j = bisect.bisect_left(m15_utc, b["utc"] + seconds)
        entry.append(j if j < len(m15_utc) and m15_utc[j] - (b["utc"] + seconds) <= 3 * 86400 else None)
    closes = [b["close"] for b in bars]
    ctx = {"bars": bars, "atr": _atr(bars), "ema20": _ema(closes, 20), "ema50": _ema(closes, 50),
           "ema200": _ema(closes, 200), "entry_index": entry, "seconds": seconds}
    _TF[key] = ctx
    return ctx


def weekly_tsmom(h, lookback: int, stop_atr: float, exit_: str) -> list[dict[str, Any]]:
    """D1 time-series momentum, rebalanced weekly: at the first D1 close of each week, go long if the
    close is above the close `lookback` days earlier, short otherwise; stop k x D1 ATR; exit after one
    week ('week') or by a 3 x D1 ATR trail ('trail3').
    Rationale: time-series momentum is among the most persistent documented return anomalies across
    asset classes; daily stops make spreads and commission a tiny fraction of R."""
    c = tf_context(h, "D1")
    bars, atr = c["bars"], c["atr"]
    out = []
    for i in range(max(lookback, 20) + 1, len(bars) - 1):
        j, a = c["entry_index"][i], atr[i]
        if j is None or not a:
            continue
        this_week = datetime.fromtimestamp(bars[i]["utc"] + 86400, UTC).isocalendar()[:2]
        last_week = datetime.fromtimestamp(bars[i - 1]["utc"] + 86400, UTC).isocalendar()[:2]
        if this_week == last_week:
            continue
        long = bars[i]["close"] > bars[i - lookback]["close"]
        trail = 3.0 * a if exit_ == "trail3" else None
        s = _signal(h, j, "tsmom", long, stop_atr * a, None if trail else 50.0, trail,
                    5 * 96 if exit_ == "week" else 20 * 96, {"lookback": lookback})
        if s:
            out.append(s)
    return out


def h4_donchian(h, lookback: int, stop_atr: float, exit_: str) -> list[dict[str, Any]]:
    """H4 Donchian breakout with the D1 EMA50 > EMA200 trend; stop k x H4 ATR; exit by 3 x H4 ATR trail
    or a fixed 2R.
    Rationale: trend following on a slower clock than H1 (round 1 found H1 breakouts roughly break
    even after costs), so each trade carries more movement relative to its costs."""
    c, d = tf_context(h, "H4"), tf_context(h, "D1")
    bars, atr = c["bars"], c["atr"]
    d_utc = [b["utc"] for b in d["bars"]]
    out = []
    for i in range(max(lookback, 210), len(bars)):
        j, a = c["entry_index"][i], atr[i]
        if j is None or not a:
            continue
        k = bisect.bisect_right(d_utc, bars[i]["utc"] + c["seconds"] - 86400) - 1   # last D1 closed by then
        if k < 200:
            continue
        up = d["ema50"][k] > d["ema200"][k]
        window = bars[i - lookback:i]
        close = bars[i]["close"]
        for long in (True, False):
            if up != long or not (close > max(b["high"] for b in window) if long else close < min(b["low"] for b in window)):
                continue
            trail = 3.0 * a if exit_ == "trail3" else None
            s = _signal(h, j, "h4donchian", long, stop_atr * a, None if trail else 2.0, trail, 20 * 96, {})
            if s:
                out.append(s)
    return out


def squeeze_breakout(h, percentile: float, exit_: str) -> list[dict[str, Any]]:
    """H1 volatility squeeze: Bollinger(20, 2) width in the lowest `percentile` of its last 120 bars,
    then a close outside the band; trade the break, stop 1.5 x H1 ATR, exit fixed 2R or 3 x ATR trail.
    Rationale: volatility clusters; compressed ranges tend to resolve into expansion moves."""
    c = h1_context(h)
    bars, atr = c["bars"], c["atr"]
    closes = [b["close"] for b in bars]
    widths: list[float | None] = [None] * len(bars)
    for i in range(20, len(bars)):
        w = closes[i - 20:i]
        mean = sum(w) / 20
        widths[i] = math.sqrt(sum((x - mean) ** 2 for x in w) / 20) / mean if mean else None
    out = []
    for i in range(240, len(bars)):
        j, a = c["entry_index"][i], atr[i]
        hist = [x for x in widths[i - 120:i] if x is not None]
        if j is None or not a or widths[i] is None or len(hist) < 100:
            continue
        rank = sum(x < widths[i - 1] for x in hist) / len(hist) if widths[i - 1] is not None else 1.0
        if rank > percentile:
            continue
        w = closes[i - 20:i]
        mean = sum(w) / 20
        sd = math.sqrt(sum((x - mean) ** 2 for x in w) / 20)
        close = bars[i]["close"]
        for long in (True, False):
            if not (close > mean + 2 * sd if long else close < mean - 2 * sd):
                continue
            trail = 3.0 * a if exit_ == "trail3" else None
            s = _signal(h, j, "squeeze", long, 1.5 * a, None if trail else 2.0, trail, 5 * 96, {})
            if s:
                out.append(s)
    return out


def _rationale(fn) -> str:
    doc = fn.__doc__ or ""
    return doc[doc.index("Rationale:"):].replace("\n", " ").strip() if "Rationale:" in doc else doc.strip()


def round2_families() -> dict[str, dict[str, Any]]:
    return {
        "D1 time-series momentum (weekly)": {
            "rationale": _rationale(weekly_tsmom),
            "grid": {f"lookback {n}d, stop {k} ATR, exit {e}": (lambda n=n, k=k, e=e: generate(lambda h: weekly_tsmom(h, n, k, e)))
                     for n, k, e in product((20, 60), (1.5, 3.0), ("week", "trail3"))}},
        "H4 Donchian + D1 trend": {
            "rationale": _rationale(h4_donchian),
            "grid": {f"N={n}, stop {k} ATR, {e}": (lambda n=n, k=k, e=e: generate(lambda h: h4_donchian(h, n, k, e)))
                     for n, k, e in product((20, 55), (2.0, 3.0), ("trail3", "fixed2"))}},
        "H1 volatility squeeze breakout": {
            "rationale": _rationale(squeeze_breakout),
            "grid": {f"width pct {p}, {e}": (lambda p=p, e=e: generate(lambda h: squeeze_breakout(h, p, e)))
                     for p, e in product((0.1, 0.2), ("fixed2", "trail3"))}},
    }


# ----- 4. registry of families and their grids ---------------------------------------------------------------

def production_family(strategy_id: str, transform_name: str) -> Callable[[], list[dict[str, Any]]]:
    def build():
        sig = lab.load_signals(strategy_id)
        t = PRODUCTION_TRANSFORMS[transform_name]
        out = []
        for s in sig:
            h = lab.history_for(s["symbol"])
            changed = t(s, h)
            if changed is not None:
                out.append({**s, **{k: v for k, v in changed.items() if k in ("stop_loss", "take_profit")}})
        return out
    return build


def _no_conflict(s, h):
    return {} if not any(conflicts(s).values()) else None


def _max_one_conflict(s, h):
    return {} if sum(conflicts(s).values()) <= 1 else None


PRODUCTION_TRANSFORMS: dict[str, Callable] = {
    "as deployed": ex.keep,
    "no conflicts": _no_conflict,
    "at most 1 conflict": _max_one_conflict,
    "no conflicts + 2 ATR stop": ex.chain(_no_conflict, ex.stop_floor(2.0)),
    "London/NY + no rollover + 2 ATR stop": ex.chain(ex.london_ny, ex.no_rollover, ex.stop_floor(2.0)),
    "London/NY + no rollover + 1.5 ATR stop": ex.chain(ex.london_ny, ex.no_rollover, ex.stop_floor(1.5)),
}


def families() -> dict[str, dict[str, Any]]:
    """{family: {"grid": {config_name: builder}, "rationale": str}}. Builders return signals."""
    fam: dict[str, dict[str, Any]] = {}
    fam["Donchian H1 trend breakout"] = {
        "rationale": donchian_trend.__doc__.split("\n")[1].strip() + " " + " ".join(donchian_trend.__doc__.split("\n")[2:4]).strip(),
        "grid": {f"N={n}, stop {k} ATR, {e}, {'with' if t else 'no'} EMA trend":
                 (lambda n=n, k=k, e=e, t=t: generate(lambda h: donchian_trend(h, n, k, e, t)))
                 for n, k, e, t in product((20, 55), (1.5, 2.0, 3.0), ("trail2", "trail3", "fixed2", "fixed3"), (True, False))}}
    fam["H1 trend pullback"] = {
        "rationale": " ".join(trend_pullback.__doc__.split("\n")[3:5]).strip(),
        "grid": {f"stop {k} ATR, {e}": (lambda k=k, e=e: generate(lambda h: trend_pullback(h, k, e)))
                 for k, e in product((1.0, 1.5, 2.0), ("trail2", "trail3", "fixed2", "fixed3"))}}
    fam["London opening-range breakout"] = {
        "rationale": " ".join(opening_range_breakout.__doc__.split("\n")[4:6]).strip(),
        "grid": {f"target {r}R, stop {m}, range <= {x} ATR": (lambda r=r, m=m, x=x: generate(lambda h: opening_range_breakout(h, r, m, x)))
                 for r, m, x in product((1.0, 1.5, 2.0, 3.0), ("far", "mid"), (1.5, 3.0))}}
    fam["H1 Bollinger mean reversion"] = {
        "rationale": " ".join(bollinger_reversion.__doc__.split("\n")[4:5]).strip(),
        "grid": {f"z={z}, target {t}": (lambda z=z, t=t: generate(lambda h: bollinger_reversion(h, z, t)))
                 for z, t in product((2.0, 2.5), ("mean", "1.5R"))}}
    fam["Trendline (production) + conflict filters"] = {
        "rationale": "Tests whether removing contradictory evidence (opposing H1 bias, structure, momentum, nearby opposing level) turns the production trendline signal positive.",
        "grid": {name: production_family("trendline_v5", name) for name in
                 ("as deployed", "no conflicts", "at most 1 conflict", "no conflicts + 2 ATR stop")}}
    fam["Support & Resistance (production) + session/stop"] = {
        "rationale": "T-032's closest-to-viable line: S/R rejections/breakouts in liquid hours with a volatility stop.",
        "grid": {name: production_family("support_resistance", name) for name in
                 ("as deployed", "London/NY + no rollover + 2 ATR stop", "London/NY + no rollover + 1.5 ATR stop")}}
    fam["SMC (production)"] = {"rationale": "Reference: production SMC as deployed.",
                               "grid": {"as deployed": production_family("smc", "as deployed")}}
    fam["Trend/Momentum (production)"] = {"rationale": "Reference: production Trend/Momentum as deployed.",
                                          "grid": {"as deployed": production_family("trend_momentum", "as deployed")}}
    return fam


def generate(builder: Callable[[Any], list[dict[str, Any]]]) -> list[dict[str, Any]]:
    rows = []
    for symbol in lab.SYMBOLS:
        rows += builder(lab.history_for(symbol))
    return sorted(rows, key=lambda r: (r["utc"], r["symbol"]))


# ----- 5. selection protocol ------------------------------------------------------------------------------

def _neighbours(name: str, names: Iterable[str]) -> list[str]:
    """Configurations differing in exactly one parameter (comma-separated parts)."""
    parts = name.split(", ")
    if len(parts) < 2:
        return []          # a named variant, not a point on a parameter grid: no neighbours
    return [o for o in names if o != name and len(o.split(", ")) == len(parts)
            and sum(a != b for a, b in zip(parts, o.split(", "))) == 1]


def select(family: str, spec: dict[str, Any], log: Callable[[str], None]) -> dict[str, Any]:
    grid = spec["grid"]
    built = {name: builder() for name, builder in grid.items()}
    train = {name: run(sig, TRAIN) for name, sig in built.items()}
    train_stats = {name: stats(t, TRAIN) for name, t in train.items()}
    for name, s in train_stats.items():
        lab.record({"name": f"V6 {family}: {name}", "kind": "v6-train", "family": family, "config": name,
                    "train": s, "hypothesis": spec["rationale"], "verdict": "train-only"})
    # Shortlist: enough trades, positive train expectancy, and robust: at least half of the
    # one-parameter neighbours also positive on train (no isolated lucky spikes).
    shortlist = []
    for name, s in train_stats.items():
        if s["trades"] < MIN_TRAIN or (s["expectancy_r"] or 0) <= 0:
            continue
        nb = _neighbours(name, train_stats)
        robust = not nb or sum((train_stats[o]["expectancy_r"] or 0) > 0 for o in nb) >= len(nb) / 2
        if robust:
            shortlist.append(name)
    shortlist = sorted(shortlist, key=lambda n: -(train_stats[n]["expectancy_r"] or 0))[:5]
    valid_stats = {name: stats(run(built[name], VALID), VALID) for name in shortlist}
    chosen, best = None, None
    for name in shortlist:
        v = valid_stats[name]
        if v["trades"] >= MIN_VALID and (best is None or (v["expectancy_r"] or -9) > best):
            chosen, best = name, v["expectancy_r"]
    # A family with a single configuration (references) is reported but never "chosen" by luck.
    if len(grid) == 1:
        only = next(iter(grid))
        valid_stats.setdefault(only, stats(run(built[only], VALID), VALID))
    log(f"  {family}: {len(grid)} configs, {len(shortlist)} shortlisted on train, chosen on validation: {chosen}")
    return {"family": family, "configs_tried": len(grid), "train": train_stats, "shortlist": shortlist,
            "validation": valid_stats, "chosen": chosen,
            "chosen_validation_positive": bool(chosen and (best or 0) > 0), "_signals": built}


def score_test(result: dict[str, Any]) -> dict[str, Any] | None:
    name = result["chosen"]
    if not name or not result["chosen_validation_positive"]:
        return None
    sig = result["_signals"][name]
    dev_window = (TRAIN[0], VALID[1])
    test_trades = run(sig, TEST)
    folds = []
    for start, end in lab.FOLDS:
        fold = run(sig, (start, end))
        s = summarize(fold)
        folds.append({"from": start.date().isoformat(), "trades": s["trades"], "expectancy_r": s["expectancy_r"]})
    by_symbol = defaultdict(list)
    for t in run(sig, dev_window):
        by_symbol[t["symbol"]].append(t)
    return {"config": name, "test": stats(test_trades, TEST),
            "test_x2_costs": stats(run(sig, TEST, cost_multiplier=2.0), TEST),
            "development": stats(run(sig, dev_window), dev_window),
            "development_x2_costs": stats(run(sig, dev_window, cost_multiplier=2.0), dev_window),
            "positive_folds": f"{sum((f['expectancy_r'] or 0) > 0 for f in folds)}/{len(folds)}", "folds": folds,
            "symbols_positive_in_development": f"{sum(summarize(v)['expectancy_r'] > 0 for v in by_symbol.values())}/{len(by_symbol)}",
            "_test_trades": test_trades}


def verdict(t: dict[str, Any]) -> str:
    test, dev2, test2 = t["test"], t["development_x2_costs"], t["test_x2_costs"]
    lo = (test["expectancy_ci95"] or [None])[0]
    if test["trades"] < 30:
        return "INSUFFICIENT TEST SAMPLE"
    if (test["expectancy_r"] or 0) > 0 and lo is not None and lo > 0 and (dev2["expectancy_r"] or 0) > 0 \
            and (test2["expectancy_r"] or 0) > 0 and int(t["positive_folds"].split("/")[0]) >= 4:
        return "CREDIBLE IMPROVEMENT"
    if (test["expectancy_r"] or 0) > 0 and (test["profit_factor"] or 0) > 1:
        return "PROMISING, NOT PROVEN (test positive but CI includes 0 or stress/fold stability fails)"
    return "FAILED ON TEST"


def portfolio(trade_lists: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Equal 1R per trade, all finalists together, in exit-time order: drawdown and monthly R."""
    merged = sorted((dict(t, family=f) for f, ts in trade_lists.items() for t in ts if t.get("r") is not None),
                    key=lambda t: t["utc"] + 3600 * (t.get("hold_hours") or 0))
    equity = peak = dd = 0.0
    monthly: dict[str, float] = defaultdict(float)
    worst_streak = streak = 0
    for t in merged:
        equity += t["r"]
        peak = max(peak, equity)
        dd = max(dd, peak - equity)
        monthly[datetime.fromtimestamp(t["utc"], UTC).strftime("%Y-%m")] += t["r"]
        streak = streak + 1 if t["r"] < 0 else 0
        worst_streak = max(worst_streak, streak)
    return {"trades": len(merged), "total_r": round(equity, 2), "max_drawdown_r": round(dd, 2),
            "longest_losing_streak": worst_streak, "monthly_r": {k: round(v, 2) for k, v in sorted(monthly.items())},
            "positive_months": f"{sum(v > 0 for v in monthly.values())}/{len(monthly)}"}


def main() -> None:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    stage = sys.argv[1] if len(sys.argv) > 1 else "all"
    out_path = lab.root() / "v6_results.json"
    results: dict[str, Any] = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else {}

    def save():
        out_path.write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")

    def log(msg):
        print(msg, flush=True)

    if stage in ("all", "baseline"):
        log("baseline...")
        results["baseline"] = baseline(); save()
        log("random-entry control...")
        results["random_control"] = random_control(); save()
        log(json.dumps(results["random_control"], indent=1))
    if stage in ("all", "conflicts"):
        log("conflict analysis...")
        results["conflicts"] = conflict_analysis(); save()
    if stage in ("all", "families", "round2"):
        log("families (train -> validation)...")
        selections = results.get("selections", {}) if stage == "round2" else {}
        finalists = {}
        specs = round2_families() if stage == "round2" else families()
        for family, spec in specs.items():
            sel = select(family, spec, log)
            selections[family] = {k: v for k, v in sel.items() if not k.startswith("_")}
            scored = score_test(sel)
            if scored:
                scored["verdict"] = verdict(scored)
                finalists[family] = scored
                lab.record({"name": f"V6 FINALIST {family}: {scored['config']}", "kind": "v6-test", "family": family,
                            **{k: v for k, v in scored.items() if not k.startswith("_")}})
                log(f"    TEST {family} [{scored['config']}]: {json.dumps(scored['test'])} -> {scored['verdict']}")
        results["selections"] = selections
        key = "finalists_round2" if stage == "round2" else "finalists"
        results[key] = {k: {kk: vv for kk, vv in v.items() if not kk.startswith("_")} for k, v in finalists.items()}
        positive = {k: v["_test_trades"] for k, v in finalists.items() if not v["verdict"].startswith("FAILED")}
        results["portfolio_test" + ("_round2" if stage == "round2" else "")] = portfolio(positive) if positive else None
        save()
    log(f"written {out_path}")


if __name__ == "__main__":
    main()
