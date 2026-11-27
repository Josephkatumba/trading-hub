"""ICT (Inner Circle Trader) strategy family: objective, measurable, independently testable setups.

ICT concepts are usually described discretionarily. Here every concept is a fixed rule on CLOSED bars
(value at bar i uses bars <= i only), so each setup can be scanned live, replayed historically with the
bank's confirmation gates and costs, and judged on evidence. Nothing here places orders: the family
registers in the Strategy Bank as RESEARCH (shadow: recorded and outcome-tracked, never alerted).

Primitives (all on the execution timeframe M15 unless stated):
  clock            New York time of each bar; the NY trading day rolls at 17:00 New York (DST-aware)
  liquidity        buy-side (BSL) / sell-side (SSL) pools: previous day high/low (PDH/PDL), previous week
                   high/low (PWH/PWL, from H1), Asian range high/low (20:00-00:00 NY), London kill-zone
                   high/low (02:00-05:00 NY), equal highs/lows (two confirmed swings within 0.1 ATR,
                   unswept), and the last confirmed swing high/low (internal liquidity)
  sweep            a candle trades beyond an unswept pool and CLOSES back inside it (stop hunt), on the same
                   candle or the next one (two-candle reclaim)
  structure        3-bar swing pivots; BULLISH = higher high + higher low, BEARISH = lower high + lower low
  MSS / BOS        a close beyond the swing point that preceded a sweep (market structure shift); a BOS is
                   a close beyond the last swing in the direction of the prevailing structure
  displacement     body >= 0.8 ATR and >= 55% of the candle's range
  FVG              three-candle imbalance >= 0.2 ATR whose middle candle is a displacement; mitigated when
                   price trades into it, invalidated by a close beyond its far edge; CE = its midpoint
  order block      (H1) the last opposite candle before a displacement that closes beyond the last swing
                   (BOS). Broken order blocks become breakers; failed swings leave mitigation blocks
  dealing range    (H1) last confirmed swing high and low; equilibrium = 50%; premium above, discount
                   below; optimal trade entry (OTE) = 62-79% retracement of the impulse leg
  bias             (H4) swing structure (D1 is not used: live D1 context is stale every Monday)
  kill zones       London 02:00-05:00, New York AM 07:00-10:00 (to 11:00 for entries), Silver Bullet
                   03:00-04:00 / 10:00-11:00 / 14:00-15:00, all New York time

Every setup has explicit stages WATCHING -> DEVELOPING -> CONFIRMING -> CONFIRMED; only CONFIRMED
returns a Decision. The same evaluation drives decide() (bank / backtest) and the live stage report
(Market Radar / AI Analyst), so the two can never disagree. A pool, FVG or order block on its own is
never a signal: each setup requires a sweep and/or structure shift plus a closed-candle confirmation.

Parameters were fixed before any backtest (pre-registered in PARAMS) and are not tuned on results.
The Silver Bullet is canonically traded on M1-M5; the bank's minimum timeframe is M15, so it is an
M15 approximation of the time window model.
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

import numpy as np

from strategy_bank import rules
from strategy_bank.rules import ALL, Ctx, Decision, _ok

VERSION = "ict-family-v1.1"
# v1.1 (before the first full evaluation): a sweep may reclaim on the next candle, and the Judas Swing
# requires only a non-opposing H4 bias. Motivated by trade-frequency diagnostics on XAUUSD, not by P&L.
NY = ZoneInfo("America/New_York")
TF = "M15"
PARAMS: dict[str, float] = {
    "swing_k": 3, "displacement_body_atr": 0.8, "displacement_body_share": 0.55, "fvg_min_atr": 0.2,
    "equal_tolerance_atr": 0.1, "equal_lookback_bars": 96, "stop_buffer_atr": 0.1, "min_stop_atr": 0.5,
    "max_stop_atr": 3.0, "min_rr": 2.0, "max_target_r": 5.0, "fallback_target_r": 2.5,
    "ote_low": 0.62, "ote_high": 0.79, "min_leg_atr_h1": 2.0,
}
STAGES = ("NONE", "WATCHING", "DEVELOPING", "CONFIRMING", "CONFIRMED")
RANK = {s: n for n, s in enumerate(STAGES)}
EXTERNAL = ("PDH", "PDL", "PWH", "PWL", "ASIA_H", "ASIA_L", "LONDON_H", "LONDON_L", "EQH", "EQL")
LABELS = {"PDH": "Previous day high", "PDL": "Previous day low", "PWH": "Previous week high", "PWL": "Previous week low",
          "ASIA_H": "Asian session high", "ASIA_L": "Asian session low", "LONDON_H": "London kill-zone high",
          "LONDON_L": "London kill-zone low", "EQH": "Equal highs", "EQL": "Equal lows", "SWING_H": "Last swing high",
          "SWING_L": "Last swing low"}
KILL_ZONES = (("Asian range", 20 * 60, 24 * 60), ("London kill zone", 2 * 60, 5 * 60),
              ("New York AM kill zone", 7 * 60, 10 * 60), ("New York lunch", 12 * 60, 13 * 60))
SILVER_BULLET = ((3 * 60, 4 * 60, "London Silver Bullet"), (10 * 60, 11 * 60, "AM Silver Bullet"),
                 (14 * 60, 15 * 60, "PM Silver Bullet"))
ENTRY_WINDOWS = ((2 * 60, 5 * 60), (7 * 60, 11 * 60))       # London and New York AM, NY minutes


@dataclass
class Eval:
    stage: str = "NONE"
    direction: str | None = None
    evidence: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    invalidation: float | None = None
    blocked: str | None = None
    decision: Decision | None = None
    levels: dict[str, float] = field(default_factory=dict)


# ----- clock and sessions --------------------------------------------------------------------------------

def clock(ctx: Ctx, tf: str = TF) -> dict[str, np.ndarray]:
    """New York minute-of-day, trading day (17:00 NY rollover) and day blocks for every bar open."""
    key = (tf, "ict_clock")
    if key not in ctx._cache:
        utc = ctx.a[tf]["utc"].astype(np.int64)
        hours, inv = np.unique(utc // 3600, return_inverse=True)
        offsets = np.array([datetime.fromtimestamp(int(h) * 3600, timezone.utc).astimezone(NY).utcoffset().total_seconds()
                            for h in hours], dtype=np.int64)
        local = utc + offsets[inv]
        day = (local + 7 * 3600) // 86400
        new = np.r_[True, day[1:] != day[:-1]]
        starts = np.flatnonzero(new)
        a = ctx.a[tf]
        ctx._cache[key] = {"ny_min": (local % 86400) // 60, "day": day, "block": np.cumsum(new) - 1, "starts": starts,
                           "ends": np.r_[starts[1:], len(day)], "week": (day + 3) // 7,
                           "day_high": np.maximum.reduceat(a["high"], starts) if len(starts) else np.array([]),
                           "day_low": np.minimum.reduceat(a["low"], starts) if len(starts) else np.array([])}
    return ctx._cache[key]


def _window_range(ctx: Ctx, k: int, lo_min: int, hi_min: int) -> tuple[float, float, int, int] | None:
    """(high, low, bars, end index) of trading-day block k restricted to NY minutes [lo, hi)."""
    key = (TF, "ict_window", k, lo_min, hi_min)
    if key not in ctx._cache:
        ck = clock(ctx)
        s, e = int(ck["starts"][k]), int(ck["ends"][k])
        m = ck["ny_min"][s:e]
        mask = (m >= lo_min) & (m < hi_min)
        if not mask.any():
            ctx._cache[key] = None
        else:
            idx = np.flatnonzero(mask) + s
            a = ctx.a[TF]
            ctx._cache[key] = (float(a["high"][idx].max()), float(a["low"][idx].min()), int(len(idx)), int(idx[-1]) + 1)
    return ctx._cache[key]


def kill_zone(ny_min: int) -> str | None:
    for name, lo, hi in KILL_ZONES:
        if lo <= ny_min < hi:
            return name
    for lo, hi, name in SILVER_BULLET:
        if lo <= ny_min < hi:
            return name
    return None


def ny_time(ctx: Ctx, i: int) -> str:
    m = int(clock(ctx)["ny_min"][i])
    return f"{m // 60:02d}:{m % 60:02d}"


# ----- candles, structure ----------------------------------------------------------------------------------

def _ohlc(ctx: Ctx, tf: str = TF):
    a = ctx.a[tf]
    return a["open"], a["high"], a["low"], a["close"]


def displacement(ctx: Ctx, m: int, long: bool, tf: str = TF) -> bool:
    o, h, l, c = _ohlc(ctx, tf)
    atr = ctx.get(tf, "atr")[m]
    body = (c[m] - o[m]) if long else (o[m] - c[m])
    rng = h[m] - l[m]
    return bool(_ok(atr) and rng > 0 and body >= PARAMS["displacement_body_atr"] * atr
                and body >= PARAMS["displacement_body_share"] * rng)


def known_swings(ctx: Ctx, tf: str, i: int) -> tuple[list, list]:
    """Swing highs / lows [(pivot, confirmed, price)] confirmed by bar i."""
    highs, lows = ctx.get(tf, "swing_points", int(PARAMS["swing_k"]))
    hc = ctx._cache.setdefault((tf, "ict_conf", "h"), [p[1] for p in highs])
    lc = ctx._cache.setdefault((tf, "ict_conf", "l"), [p[1] for p in lows])
    return highs[:bisect.bisect_right(hc, i)], lows[:bisect.bisect_right(lc, i)]


def trend(ctx: Ctx, tf: str, i: int) -> str:
    if i < 0:
        return "NEUTRAL"
    highs, lows = known_swings(ctx, tf, i)
    if len(highs) < 2 or len(lows) < 2:
        return "NEUTRAL"
    hh, hl = highs[-1][2] > highs[-2][2], lows[-1][2] > lows[-2][2]
    if hh and hl:
        return "BULLISH"
    if not hh and not hl:
        return "BEARISH"
    return "NEUTRAL"


def bias(ctx: Ctx, at_utc: float) -> str:
    """Higher-timeframe directional bias from H4 swing structure."""
    if "H4" not in ctx.a:
        return "NEUTRAL"
    return trend(ctx, "H4", ctx.last_closed("H4", at_utc))


def _swing_before(ctx: Ctx, i: int, pivot_before: int, high: bool) -> float | None:
    """Most recent confirmed (by i) swing high/low whose pivot is before `pivot_before`."""
    highs, lows = known_swings(ctx, TF, i)
    for p in reversed(highs if high else lows):
        if p[0] < pivot_before:
            return p[2]
    return None


# ----- liquidity ------------------------------------------------------------------------------------------

def liquidity(ctx: Ctx, i: int) -> list[dict[str, Any]]:
    """Liquidity pools known at the close of bar i: {kind, side, price, origin, swept_at}."""
    key = (TF, "ict_liq", i)
    if key in ctx._cache:
        return ctx._cache[key]
    o, h, l, c = _ohlc(ctx)
    ck = clock(ctx)
    k = int(ck["block"][i])
    pools: list[tuple[str, str, float, int]] = []
    start = int(ck["starts"][k])
    if k >= 2:                                        # block 0 may be a partial day
        pools += [("PDH", "BSL", float(ck["day_high"][k - 1]), start), ("PDL", "SSL", float(ck["day_low"][k - 1]), start)]
    asia = _window_range(ctx, k, 20 * 60, 24 * 60)
    if asia and asia[2] >= 8 and asia[3] <= i:
        pools += [("ASIA_H", "BSL", asia[0], asia[3]), ("ASIA_L", "SSL", asia[1], asia[3])]
    london = _window_range(ctx, k, 2 * 60, 5 * 60)
    if london and london[2] >= 10 and london[3] <= i and ck["ny_min"][i] >= 5 * 60:
        pools += [("LONDON_H", "BSL", london[0], london[3]), ("LONDON_L", "SSL", london[1], london[3])]
    pools += _previous_week(ctx, i)
    atr = ctx.get(TF, "atr")[i]
    highs, lows = known_swings(ctx, TF, i)
    if _ok(atr):
        tol = PARAMS["equal_tolerance_atr"] * atr
        for side, pts, kind in (("BSL", highs, "EQH"), ("SSL", lows, "EQL")):
            recent = [p for p in pts[-6:] if i - p[0] <= PARAMS["equal_lookback_bars"]]
            seen: list[float] = []
            for x in range(len(recent)):
                for y in range(x + 1, len(recent)):
                    if abs(recent[x][2] - recent[y][2]) <= tol:
                        level = max(recent[x][2], recent[y][2]) if side == "BSL" else min(recent[x][2], recent[y][2])
                        if all(abs(level - s) > tol for s in seen):
                            seen.append(level)
                            pools.append((kind, side, level, recent[y][0] + 1))
    if highs:
        pools.append(("SWING_H", "BSL", highs[-1][2], highs[-1][0] + 1))
    if lows:
        pools.append(("SWING_L", "SSL", lows[-1][2], lows[-1][0] + 1))
    out = []
    for kind, side, price, origin in pools:
        swept_at = None
        if origin <= i:
            seg = h[origin:i + 1] if side == "BSL" else l[origin:i + 1]
            hit = np.flatnonzero(seg > price) if side == "BSL" else np.flatnonzero(seg < price)
            swept_at = int(hit[0]) + origin if len(hit) else None
        out.append({"kind": kind, "side": side, "price": price, "origin": origin, "swept_at": swept_at})
    ctx._cache[key] = out
    return out


def _previous_week(ctx: Ctx, i: int) -> list[tuple[str, str, float, int]]:
    if "H1" not in ctx.a:
        return []
    j = ctx.last_closed("H1", ctx.close_utc(TF, i))
    if j < 0:
        return []
    ck = clock(ctx, "H1")
    week = ck["week"]
    w = week[j]
    prev = np.flatnonzero(week[:j + 1] == w - 1)
    if len(prev) < 60 or prev[0] == 0:                  # need a (nearly) complete, fully loaded prior week
        return []
    a = ctx.a["H1"]
    first_this = int(np.searchsorted(week[:j + 1], w, side="left"))
    week_start_utc = float(a["utc"][first_this]) if first_this <= j else ctx.close_utc(TF, i)
    origin = int(np.searchsorted(ctx.a[TF]["utc"], week_start_utc, side="left"))
    return [("PWH", "BSL", float(a["high"][prev].max()), origin), ("PWL", "SSL", float(a["low"][prev].min()), origin)]


def sweeps_at(ctx: Ctx, s: int) -> list[dict[str, Any]]:
    """Pools (known and unswept at s-1) that candle s traded through and closed back inside."""
    key = (TF, "ict_sweep", s)
    if key not in ctx._cache:
        o, h, l, c = _ohlc(ctx)
        out = []
        if s >= 2:
            for p in liquidity(ctx, s - 1):
                if p["swept_at"] is not None:
                    continue
                if p["side"] == "BSL" and h[s] > p["price"] and c[s] < p["price"]:
                    out.append({**p, "at": s, "extreme": float(h[s])})
                elif p["side"] == "SSL" and l[s] < p["price"] and c[s] > p["price"]:
                    out.append({**p, "at": s, "extreme": float(l[s])})
            seen = {(e["kind"], e["price"]) for e in out}
            for p in liquidity(ctx, s - 2):                  # two-candle reclaim: s-1 closed beyond, s closed back
                if p["swept_at"] is not None or (p["kind"], p["price"]) in seen or p["origin"] > s - 1:
                    continue
                if p["side"] == "BSL" and c[s - 1] > p["price"] and c[s] < p["price"]:
                    out.append({**p, "at": s, "extreme": float(max(h[s - 1], h[s]))})
                elif p["side"] == "SSL" and c[s - 1] < p["price"] and c[s] > p["price"]:
                    out.append({**p, "at": s, "extreme": float(min(l[s - 1], l[s]))})
        ctx._cache[key] = out
    return ctx._cache[key]


def recent_sweep(ctx: Ctx, i: int, side: str, back: int, until: int = 0, kinds=None) -> dict[str, Any] | None:
    """Most recent sweep of `side` liquidity in bars [i-back, i-until]."""
    for s in range(i - until, max(0, i - back) - 1, -1):
        hits = [e for e in sweeps_at(ctx, s) if e["side"] == side and (kinds is None or e["kind"] in kinds)]
        if hits:
            return min(hits, key=lambda e: e["extreme"]) if side == "SSL" else max(hits, key=lambda e: e["extreme"])
    return None


# ----- fair value gaps, order blocks, dealing range -------------------------------------------------------------

def fvg_at(ctx: Ctx, j: int, long: bool, tf: str = TF) -> dict[str, float] | None:
    """FVG formed by candles j-2, j-1, j (j has closed)."""
    if j < 2:
        return None
    o, h, l, c = _ohlc(ctx, tf)
    atr = ctx.get(tf, "atr")[j]
    if not _ok(atr):
        return None
    if long and l[j] > h[j - 2] and l[j] - h[j - 2] >= PARAMS["fvg_min_atr"] * atr and displacement(ctx, j - 1, True, tf):
        return {"bottom": float(h[j - 2]), "top": float(l[j]), "ce": float((h[j - 2] + l[j]) / 2), "anchor": float(l[j - 2]), "at": j}
    if not long and h[j] < l[j - 2] and l[j - 2] - h[j] >= PARAMS["fvg_min_atr"] * atr and displacement(ctx, j - 1, False, tf):
        return {"bottom": float(h[j]), "top": float(l[j - 2]), "ce": float((h[j] + l[j - 2]) / 2), "anchor": float(h[j - 2]), "at": j}
    return None


def fvg_state(ctx: Ctx, g: dict[str, float], i: int, long: bool, tf: str = TF) -> dict[str, Any]:
    """Status of FVG g at bar i: first touch (mitigation), CE reached, invalidation (close beyond far edge)."""
    o, h, l, c = _ohlc(ctx, tf)
    j = int(g["at"])
    seg = slice(j + 1, i + 1)
    if long:
        touch = np.flatnonzero(l[seg] <= g["top"]); ce = np.flatnonzero(l[seg] <= g["ce"]); bad = np.flatnonzero(c[seg] < g["bottom"])
    else:
        touch = np.flatnonzero(h[seg] >= g["bottom"]); ce = np.flatnonzero(h[seg] >= g["ce"]); bad = np.flatnonzero(c[seg] > g["top"])
    first = int(touch[0]) + j + 1 if len(touch) else None
    return {"first_touch": first, "ce_touched": bool(len(ce)), "invalidated": bool(len(bad)),
            "status": "INVALIDATED" if len(bad) else "MITIGATED" if first is not None else "OPEN"}


def order_blocks(ctx: Ctx, j: int, lookback: int = 60, tf: str = "H1") -> list[dict[str, Any]]:
    """Order blocks on `tf` formed within `lookback` bars of closed bar j, newest first."""
    if tf not in ctx.a or j < 10:
        return []
    key = (tf, "ict_ob", j, lookback)
    if key in ctx._cache:
        return ctx._cache[key]
    o, h, l, c = _ohlc(ctx, tf)
    out = []
    ctx._cache[key] = out
    for k in range(j - 2, max(5, j - lookback) - 1, -1):
        for long in (True, False):
            if (c[k] >= o[k]) if long else (c[k] <= o[k]):
                continue
            highs, lows = known_swings(ctx, tf, k)
            level = highs[-1][2] if long and highs else lows[-1][2] if not long and lows else None
            if level is None:
                continue
            for m in range(k + 1, min(k + 4, j + 1)):
                if displacement(ctx, m, long, tf) and ((c[m] > level) if long else (c[m] < level)):
                    out.append({"long": long, "low": float(l[k]), "high": float(h[k]), "at": k, "displaced_at": m,
                                "broke": float(level)})
                    break
    return out


def ob_state(ctx: Ctx, ob: dict[str, Any], j: int, tf: str = "H1") -> str:
    o, h, l, c = _ohlc(ctx, tf)
    seg = slice(ob["displaced_at"] + 1, j + 1)
    if ob["long"]:
        broken, touched = (c[seg] < ob["low"]).any(), (l[seg] <= ob["high"]).any()
    else:
        broken, touched = (c[seg] > ob["high"]).any(), (h[seg] >= ob["low"]).any()
    return "BREAKER" if broken else "MITIGATED" if touched else "FRESH"


def dealing_range(ctx: Ctx, j: int, tf: str = "H1") -> dict[str, Any] | None:
    highs, lows = known_swings(ctx, tf, j)
    if not highs or not lows:
        return None
    hi, lo = highs[-1], lows[-1]
    if hi[2] <= lo[2]:
        return None
    up_leg = hi[0] > lo[0]                      # the most recent swing is the high: an impulse up
    rng = hi[2] - lo[2]
    return {"high": hi[2], "low": lo[2], "equilibrium": (hi[2] + lo[2]) / 2, "leg": "UP" if up_leg else "DOWN",
            "high_pivot": hi[0], "low_pivot": lo[0],
            "ote_long": (hi[2] - PARAMS["ote_high"] * rng, hi[2] - PARAMS["ote_low"] * rng),
            "ote_short": (lo[2] + PARAMS["ote_low"] * rng, lo[2] + PARAMS["ote_high"] * rng)}


# ----- risk helpers ---------------------------------------------------------------------------------------

def _stop(long: bool, extreme: float, close: float, atr: float) -> float | None:
    s = extreme - PARAMS["stop_buffer_atr"] * atr if long else extreme + PARAMS["stop_buffer_atr"] * atr
    dist = (close - s) if long else (s - close)
    if dist < PARAMS["min_stop_atr"] * atr:
        s = close - PARAMS["min_stop_atr"] * atr if long else close + PARAMS["min_stop_atr"] * atr
    elif dist > PARAMS["max_stop_atr"] * atr:
        return None
    return float(s)


def draw_on_liquidity(ctx: Ctx, i: int, long: bool, entry: float, stop: float) -> tuple[float, str]:
    """Target: the nearest unswept opposing pool at 2-5R (H1 swings included), else a fixed 2.5R."""
    risk = abs(entry - stop)
    side = "BSL" if long else "SSL"
    cands = [(p["price"], LABELS.get(p["kind"], p["kind"])) for p in liquidity(ctx, i) if p["side"] == side and p["swept_at"] is None]
    if "H1" in ctx.a:
        hs, ls = known_swings(ctx, "H1", ctx.last_closed("H1", ctx.close_utc(TF, i)))
        cands += [(p[2], "H1 swing " + ("high" if long else "low")) for p in (hs[-4:] if long else ls[-4:])]
    best = None
    for price, label in cands:
        r = ((price - entry) if long else (entry - price)) / risk if risk else 0
        if PARAMS["min_rr"] <= r <= PARAMS["max_target_r"] and (best is None or r < best[0]):
            best = (r, price, label)
    if best:
        return float(best[1]), f"{best[2]} ({best[0]:.1f}R)"
    r = PARAMS["fallback_target_r"]
    return float(entry + r * risk if long else entry - r * risk), f"fixed {r}R (no liquidity pool at 2-5R)"


def _confirmed(ctx: Ctx, i: int, long: bool, extreme: float, key: str, why: str, max_bars: int, ev: Eval,
               target: float | None = None) -> Eval:
    c = ctx.a[TF]["close"][i]
    atr = float(ctx.get(TF, "atr")[i])
    stop = _stop(long, extreme, float(c), atr)
    if stop is None:
        ev.stage, ev.blocked = "CONFIRMING", "structural stop is more than 3 ATR away"
        return ev
    basis = "structural"
    if target is None:
        target, basis = draw_on_liquidity(ctx, i, long, float(c), stop)
    ev.stage = "CONFIRMED"
    ev.missing = []
    ev.invalidation = stop
    ev.levels.update({"stop": stop, "target": target})
    ev.decision = Decision("LONG" if long else "SHORT", stop=stop, target=target, target_r=None, max_bars=max_bars,
                           evidence={"family": "ICT", "setup": key, "target_basis": basis, **{k: v for k, v in ev.levels.items()}},
                           explanation=f"{why} Target: {basis}. [{VERSION}]")
    return ev


def _dirname(long: bool) -> str:
    return "LONG" if long else "SHORT"


def _p(v: float) -> str:
    return f"{v:.5g}"


# ----- the eight setups ------------------------------------------------------------------------------------
# Each _x(ctx, i, long) returns an Eval; long=False mirrors the rule.

def _sweep_reversal(ctx: Ctx, i: int, long: bool) -> Eval:
    """1. Liquidity Sweep Reversal: external pool swept (close back inside) within 3 bars, then a
    displacement candle closing beyond the sweep candle's opposite extreme. H4 bias must not oppose."""
    o, h, l, c = _ohlc(ctx)
    atr = ctx.get(TF, "atr")[i]
    ev = Eval(direction=_dirname(long))
    if not _ok(atr):
        return ev
    side = "SSL" if long else "BSL"
    sw = recent_sweep(ctx, i, side, 3, kinds=EXTERNAL)
    if sw is None:
        near = [p for p in liquidity(ctx, i) if p["side"] == side and p["swept_at"] is None and p["kind"] in EXTERNAL
                and abs(c[i] - p["price"]) <= atr]
        if near:
            p = min(near, key=lambda p: abs(c[i] - p["price"]))
            ev.stage = "WATCHING"
            ev.evidence = [f"{LABELS[p['kind']]} {_p(p['price'])} is {abs(c[i] - p['price']) / atr:.1f} ATR away (unswept)"]
            ev.missing = ["a sweep: wick through the pool and a close back inside",
                          f"a displacement close {'above' if long else 'below'} the sweep candle"]
        return ev
    s = sw["at"]
    seg = c[s + 1:i + 1]
    if len(seg) and ((seg < sw["price"]).any() if long else (seg > sw["price"]).any()):
        return Eval(direction=ev.direction)                   # price accepted beyond the pool: sweep failed
    ev.evidence = [f"{LABELS[sw['kind']]} {_p(sw['price'])} swept at {ny_time(ctx, s)} NY (extreme {_p(sw['extreme'])}), closed back inside"]
    ev.invalidation = float(l[s:i + 1].min() if long else h[s:i + 1].max())
    b = bias(ctx, ctx.close_utc(TF, i))
    if b == ("BEARISH" if long else "BULLISH"):
        ev.stage, ev.blocked = "DEVELOPING", f"H4 bias is {b.lower()}, against the reversal"
        return ev
    trigger = h[s] if long else l[s]
    for k in range(s + 1, i):
        if ((c[k] > trigger) if long else (c[k] < trigger)) and displacement(ctx, k, long):
            return Eval(direction=ev.direction)               # already triggered on an earlier bar
    if s < i and ((c[i] > trigger) if long else (c[i] < trigger)) and displacement(ctx, i, long):
        ev.evidence.append(f"displacement candle closed {'above' if long else 'below'} the sweep candle at {_p(c[i])}")
        return _confirmed(ctx, i, long, ev.invalidation, "ict_sweep_reversal",
                          f"{LABELS[sw['kind']]} was swept and rejected; a displacement candle confirmed the reversal.", 32, ev)
    ev.stage = "CONFIRMING" if s < i and ((c[i] > sw["price"]) if long else (c[i] < sw["price"])) else "DEVELOPING"
    ev.missing = [f"a displacement close {'above' if long else 'below'} {_p(trigger)} (sweep candle {'high' if long else 'low'}) within 3 bars"]
    return ev


def _mss(ctx: Ctx, i: int, long: bool) -> Eval:
    """2. Market Structure Shift: in an opposing M15 structure, a sweep (any pool, incl. the last swing)
    within 12 bars, then the first close beyond the swing point that preceded the sweep, with displacement."""
    o, h, l, c = _ohlc(ctx)
    atr = ctx.get(TF, "atr")[i]
    ev = Eval(direction=_dirname(long))
    if not _ok(atr) or i < 30:
        return ev
    if trend(ctx, TF, i - 1) != ("BEARISH" if long else "BULLISH"):
        return ev
    side = "SSL" if long else "BSL"
    sw = recent_sweep(ctx, i, side, 12, until=1)
    if sw is None:
        ev.stage = "WATCHING"
        ev.evidence = [f"M15 structure is {'bearish' if long else 'bullish'}; a shift needs a liquidity grab first"]
        ev.missing = [f"sweep of {'sell' if long else 'buy'}-side liquidity", "close beyond the prior swing with displacement"]
        return ev
    s = sw["at"]
    ext = float(l[s:i + 1].min() if long else h[s:i + 1].max())
    if (ext < sw["extreme"]) if long else (ext > sw["extreme"]):
        return Eval(direction=ev.direction)                   # a new extreme after the sweep: not a shift yet
    level = _swing_before(ctx, i - 1, s, high=long)
    if level is None:
        return ev
    ev.evidence = [f"{LABELS[sw['kind']]} {_p(sw['price'])} swept at {ny_time(ctx, s)} NY",
                   f"shift level: swing {'high' if long else 'low'} {_p(level)}"]
    ev.invalidation = ext
    ev.levels["shift_level"] = level
    broke = (c[i] > level and c[i - 1] <= level) if long else (c[i] < level and c[i - 1] >= level)
    disp = any(displacement(ctx, m, long) for m in range(s + 1, i + 1))
    if broke and disp:
        b = bias(ctx, ctx.close_utc(TF, i))
        if b == ("BEARISH" if long else "BULLISH"):
            ev.stage, ev.blocked = "CONFIRMING", f"H4 bias is {b.lower()}"
            return ev
        ev.evidence.append(f"close {_p(c[i])} broke the swing with displacement (change of character)")
        return _confirmed(ctx, i, long, ext, "ict_mss", "A liquidity sweep was followed by a displacement close through the prior swing.", 32, ev)
    if (c[i] > level) if long else (c[i] < level):
        return Eval(direction=ev.direction)                   # broke earlier (or without displacement): stale
    ev.stage = "CONFIRMING" if abs(c[i] - level) <= 0.5 * atr else "DEVELOPING"
    ev.missing = [f"close {'above' if long else 'below'} {_p(level)}" + ("" if disp else " with a displacement candle")]
    return ev


def _fvg_continuation(ctx: Ctx, i: int, long: bool) -> Eval:
    """3. FVG Continuation: H4 bias and H1 structure aligned; a displacement FVG that broke M15 structure
    (BOS), 2-24 bars old, never invalidated; the FIRST retest closes beyond its consequent encroachment."""
    o, h, l, c = _ohlc(ctx)
    atr = ctx.get(TF, "atr")[i]
    ev = Eval(direction=_dirname(long))
    if not _ok(atr) or i < 40:
        return ev
    want = "BULLISH" if long else "BEARISH"
    t = ctx.close_utc(TF, i)
    if bias(ctx, t) != want:
        return ev
    h1 = trend(ctx, "H1", ctx.last_closed("H1", t)) if "H1" in ctx.a else "NEUTRAL"
    ev.evidence = [f"H4 bias {want.lower()}"]
    if h1 != want:
        ev.stage = "WATCHING"
        ev.missing = [f"H1 structure {want.lower()} (now {h1.lower()})"]
        return ev
    ev.evidence.append(f"H1 structure {want.lower()}")
    for j in range(i - 1, i - 25, -1):
        g = fvg_at(ctx, j, long)
        if g is None:
            continue
        highs, lows = known_swings(ctx, TF, j - 2)
        lvl = highs[-1][2] if long and highs else lows[-1][2] if not long and lows else None
        if lvl is None or not ((max(c[j - 1], c[j]) > lvl) if long else (min(c[j - 1], c[j]) < lvl)):
            continue
        st = fvg_state(ctx, g, i, long)
        if st["invalidated"]:
            return ev
        ev.evidence.append(f"{'bullish' if long else 'bearish'} FVG {_p(g['bottom'])}-{_p(g['top'])} from a displacement that broke {_p(lvl)}")
        ev.invalidation = g["bottom"] if long else g["top"]
        ev.levels.update({"fvg_top": g["top"], "fvg_bottom": g["bottom"], "ce": g["ce"]})
        if st["first_touch"] is not None and st["first_touch"] < i:
            return Eval(direction=ev.direction)               # not the first retest any more
        if st["first_touch"] == i:
            if ((c[i] > g["ce"]) if long else (c[i] < g["ce"])) and ((c[i] > o[i]) if long else (c[i] < o[i])):
                ev.evidence.append(f"first retest closed {'above' if long else 'below'} CE {_p(g['ce'])}")
                return _confirmed(ctx, i, long, g["bottom"] if long else g["top"], "ict_fvg_continuation",
                                  "Trend-aligned FVG retested for the first time and held its consequent encroachment.", 48, ev)
            ev.stage, ev.missing = "CONFIRMING", [f"close {'above' if long else 'below'} CE {_p(g['ce'])}"]
            return ev
        dist = (l[i] - g["top"]) if long else (g["bottom"] - h[i])
        ev.stage = "CONFIRMING" if dist <= 0.3 * atr else "DEVELOPING"
        ev.missing = [f"retrace into the FVG ({_p(g['top'] if long else g['bottom'])})", "close beyond CE on that candle"]
        return ev
    ev.stage = "WATCHING"
    ev.missing = ["displacement that breaks M15 structure and leaves an FVG"]
    return ev


def _ob_reversal(ctx: Ctx, i: int, long: bool) -> Eval:
    """4. Order Block Reversal: a fresh H1 order block in the discount (premium) half of the H1 dealing
    range; on the first M15 visit, a bullish (bearish) M15 candle closes beyond the prior two candles."""
    o, h, l, c = _ohlc(ctx)
    atr = ctx.get(TF, "atr")[i]
    ev = Eval(direction=_dirname(long))
    if not _ok(atr) or "H1" not in ctx.a:
        return ev
    t = ctx.close_utc(TF, i)
    jh = ctx.last_closed("H1", t)
    if jh < 60:
        return ev
    obs = [b for b in order_blocks(ctx, jh) if b["long"] == long]
    if not obs:
        return ev
    ob = obs[0]
    dr = dealing_range(ctx, jh)
    mid = (ob["low"] + ob["high"]) / 2
    if dr is None or ((mid > dr["equilibrium"]) if long else (mid < dr["equilibrium"])):
        return ev
    ha = ctx.a["H1"]
    e0 = int(np.searchsorted(ctx.a[TF]["utc"], ha["utc"][ob["displaced_at"]] + 3600, side="left"))
    if e0 > i:
        return ev
    seg = slice(e0, i + 1)
    if (c[seg] < ob["low"]).any() if long else (c[seg] > ob["high"]).any():
        return ev                                              # broken: now a breaker, not this setup
    touch = np.flatnonzero(l[seg] <= ob["high"]) if long else np.flatnonzero(h[seg] >= ob["low"])
    ev.evidence = [f"fresh H1 {'bullish' if long else 'bearish'} order block {_p(ob['low'])}-{_p(ob['high'])} "
                   f"in the {'discount' if long else 'premium'} of the H1 range (EQ {_p(dr['equilibrium'])})"]
    ev.invalidation = ob["low"] if long else ob["high"]
    ev.levels.update({"ob_low": ob["low"], "ob_high": ob["high"]})
    if not len(touch):
        dist = (l[i] - ob["high"]) if long else (ob["low"] - h[i])
        ha_atr = ctx.get("H1", "atr")[jh]
        if _ok(ha_atr) and dist <= 1.5 * ha_atr:
            ev.stage = "DEVELOPING" if dist <= 0.5 * ha_atr else "WATCHING"
            ev.missing = ["price trades into the order block", "M15 confirmation candle"]
            return ev
        return Eval(direction=ev.direction)
    e = int(touch[0]) + e0
    if i - e > 16:
        return Eval(direction=ev.direction)
    def ok(k: int) -> bool:
        return k >= 2 and (((c[k] > max(h[k - 1], h[k - 2])) and c[k] > o[k] and c[k] - o[k] >= 0.5 * atr) if long
                           else ((c[k] < min(l[k - 1], l[k - 2])) and c[k] < o[k] and o[k] - c[k] >= 0.5 * atr))
    if any(ok(k) for k in range(e, i)):
        return Eval(direction=ev.direction)
    ev.evidence.append(f"price entered the block at {ny_time(ctx, e)} NY")
    if ok(i):
        ext = float(l[e:i + 1].min() if long else h[e:i + 1].max())
        ev.evidence.append(f"M15 candle closed {'above' if long else 'below'} the prior two candles with a 0.5 ATR body")
        return _confirmed(ctx, i, long, ext, "ict_ob_reversal", "First visit to a fresh H1 order block in discount/premium, confirmed on M15.", 48, ev)
    ev.stage, ev.missing = "CONFIRMING", [f"M15 close {'above' if long else 'below'} the prior two candles"]
    return ev


def _ote(ctx: Ctx, i: int, long: bool) -> Eval:
    """5. Premium/Discount OTE: H4 bias aligned; the last H1 leg is an impulse (BOS, >= 2 H1 ATR); price
    retraces into the 62-79% OTE band (discount for longs) without a full retracement; an M15 candle
    closes beyond the previous candle within 8 bars of the first OTE touch. Target: the leg extreme."""
    o, h, l, c = _ohlc(ctx)
    atr = ctx.get(TF, "atr")[i]
    ev = Eval(direction=_dirname(long))
    if not _ok(atr) or "H1" not in ctx.a:
        return ev
    t = ctx.close_utc(TF, i)
    want = "BULLISH" if long else "BEARISH"
    if bias(ctx, t) != want:
        return ev
    jh = ctx.last_closed("H1", t)
    highs, lows = known_swings(ctx, "H1", jh)
    if len(highs) < 2 or len(lows) < 1:
        return ev
    if long:
        top, prev = highs[-1], highs[-2]
        base = [p for p in lows if p[0] < top[0]]
        if not base or lows[-1][0] > top[0] or top[2] <= prev[2]:
            return ev
        x0, x1 = base[-1][2], top[2]
    else:
        if len(lows) < 2:
            return ev
        top, prev = lows[-1], lows[-2]
        base = [p for p in highs if p[0] < top[0]]
        if not base or highs[-1][0] > top[0] or top[2] >= prev[2]:
            return ev
        x0, x1 = base[-1][2], top[2]
    leg = abs(x1 - x0)
    h1_atr = ctx.get("H1", "atr")[jh]
    if not _ok(h1_atr) or leg < PARAMS["min_leg_atr_h1"] * h1_atr:
        return ev
    sgn = 1 if long else -1
    band_near, band_far = x1 - sgn * PARAMS["ote_low"] * leg, x1 - sgn * PARAMS["ote_high"] * leg
    eq = (x0 + x1) / 2
    start = int(np.searchsorted(ctx.a[TF]["utc"], ctx.a["H1"]["utc"][top[0]] + 3600, side="left"))
    if start > i:
        return ev
    seg = slice(start, i + 1)
    if (l[seg] < x0).any() if long else (h[seg] > x0).any():
        return Eval(direction=ev.direction)                   # 100% retracement: the leg failed
    ev.evidence = [f"H4 bias {want.lower()}; H1 impulse {_p(x0)} -> {_p(x1)} ({leg / h1_atr:.1f} H1 ATR) broke {_p(prev[2])}"]
    ev.levels.update({"ote_near": band_near, "ote_far": band_far, "equilibrium": eq, "leg_extreme": x1})
    ev.invalidation = x0
    touch = np.flatnonzero(l[seg] <= band_near) if long else np.flatnonzero(h[seg] >= band_near)
    if not len(touch):
        in_discount = (l[i] < eq) if long else (h[i] > eq)
        ev.stage = "DEVELOPING" if in_discount else "WATCHING"
        ev.missing = [f"retracement into the OTE band {_p(band_far)}-{_p(band_near)}", "M15 confirmation candle"]
        return ev
    f = int(touch[0]) + start
    if i - f > 8:
        return Eval(direction=ev.direction)
    def ok(k: int) -> bool:
        return (c[k] > h[k - 1] and c[k] > o[k]) if long else (c[k] < l[k - 1] and c[k] < o[k])
    if any(ok(k) for k in range(f, i)):
        return Eval(direction=ev.direction)
    ev.evidence.append(f"price reached the OTE band at {ny_time(ctx, f)} NY")
    if ok(i):
        ext = float(l[f:i + 1].min() if long else h[f:i + 1].max())
        return _confirmed(ctx, i, long, ext, "ict_ote", "Retracement into the optimal trade entry band of a trend-aligned impulse, confirmed on M15.",
                          64, ev, target=float(x1))
    ev.stage, ev.missing = "CONFIRMING", [f"M15 close {'above the previous high' if long else 'below the previous low'}"]
    return ev


def _silver_bullet(ctx: Ctx, i: int, long: bool) -> Eval:
    """6. Silver Bullet (M15 approximation): inside a Silver Bullet hour (03-04, 10-11, 14-15 NY), an FVG
    formed after a sweep of the opposite liquidity in the prior 4 hours; first retest closes beyond CE."""
    o, h, l, c = _ohlc(ctx)
    atr = ctx.get(TF, "atr")[i]
    ev = Eval(direction=_dirname(long))
    if not _ok(atr):
        return ev
    nm = int(clock(ctx)["ny_min"][i])
    win = next(((lo, hi, name) for lo, hi, name in SILVER_BULLET if lo <= nm < hi + 15), None)
    if win is None:
        upcoming = next((name for lo, hi, name in SILVER_BULLET if 0 < lo - nm <= 60), None)
        if upcoming:
            ev.stage, ev.evidence = "WATCHING", [f"{upcoming} opens within the hour"]
            ev.missing = ["liquidity sweep", "FVG inside the window", "retrace into the FVG"]
        return ev
    lo_m, hi_m, name = win
    ev.evidence = [f"{name} window active ({ny_time(ctx, i)} NY)"]
    side = "SSL" if long else "BSL"
    ny_min = clock(ctx)["ny_min"]
    for j in range(i - 1, max(2, i - 6) - 1, -1):
        if not (lo_m - 30 <= ny_min[j] < hi_m):
            continue
        g = fvg_at(ctx, j, long)
        if g is None:
            continue
        sw = recent_sweep(ctx, j - 1, side, 16)
        if sw is None:
            continue
        st = fvg_state(ctx, g, i, long)
        if st["invalidated"] or (st["first_touch"] is not None and st["first_touch"] < i):
            return Eval(direction=ev.direction)
        ev.evidence += [f"{LABELS.get(sw['kind'], sw['kind'])} {_p(sw['price'])} swept at {ny_time(ctx, sw['at'])} NY",
                        f"FVG {_p(g['bottom'])}-{_p(g['top'])} formed in the window"]
        ev.levels.update({"fvg_top": g["top"], "fvg_bottom": g["bottom"], "ce": g["ce"]})
        ev.invalidation = g["anchor"]
        if st["first_touch"] == i and ((c[i] > g["ce"]) if long else (c[i] < g["ce"])) and ((c[i] > o[i]) if long else (c[i] < o[i])):
            return _confirmed(ctx, i, long, g["anchor"], "ict_silver_bullet",
                              f"{name}: FVG after a liquidity sweep, retested and held its consequent encroachment.", 8, ev)
        ev.stage = "CONFIRMING"
        ev.missing = ["first retrace into the FVG closing beyond CE"]
        return ev
    if recent_sweep(ctx, i, side, 16):
        ev.stage, ev.missing = "DEVELOPING", ["displacement leaving an FVG inside the window"]
    else:
        ev.stage, ev.missing = "WATCHING", [f"sweep of {'sell' if long else 'buy'}-side liquidity", "FVG inside the window"]
    return ev


def _judas(ctx: Ctx, i: int, long: bool) -> Eval:
    """7. Judas Swing: with H4 bias not opposing, the London / New York AM session first runs the Asian range
    against the bias (sweep of the Asian low for longs), then shifts structure back with displacement."""
    o, h, l, c = _ohlc(ctx)
    atr = ctx.get(TF, "atr")[i]
    ev = Eval(direction=_dirname(long))
    if not _ok(atr) or i < 40:
        return ev
    want = "BULLISH" if long else "BEARISH"
    b = bias(ctx, ctx.close_utc(TF, i))
    if b == ("BEARISH" if long else "BULLISH"):
        return ev
    ck = clock(ctx)
    nm = int(ck["ny_min"][i])
    if not (2 * 60 <= nm < 10 * 60):
        return ev
    k = int(ck["block"][i])
    asia = _window_range(ctx, k, 20 * 60, 24 * 60)
    if not asia or asia[2] < 8 or asia[3] > i:
        return ev
    level = asia[1] if long else asia[0]
    ev.evidence = [f"H4 bias {b.lower()} (not opposing); Asian range {_p(asia[1])}-{_p(asia[0])}"]
    sw = None
    for s in range(asia[3], i):
        if 2 * 60 <= ck["ny_min"][s] < 10 * 60:
            hit = [e for e in sweeps_at(ctx, s) if e["kind"] == ("ASIA_L" if long else "ASIA_H")]
            if hit:
                sw = hit[0]
                break
    if sw is None:
        ev.stage = "WATCHING"
        ev.missing = [f"false move {'below the Asian low' if long else 'above the Asian high'} {_p(level)} in a kill zone", "structure shift back"]
        return ev
    s = sw["at"]
    ext = float(l[s:i + 1].min() if long else h[s:i + 1].max())
    if (ext < sw["extreme"]) if long else (ext > sw["extreme"]):
        return Eval(direction=ev.direction)
    shift = _swing_before(ctx, i - 1, s, high=long)
    ev.evidence.append(f"Judas move swept the Asian {'low' if long else 'high'} at {ny_time(ctx, s)} NY (extreme {_p(sw['extreme'])})")
    ev.invalidation = ext
    if shift is None:
        ev.stage = "DEVELOPING"
        return ev
    ev.levels["shift_level"] = shift
    broke = (c[i] > shift and c[i - 1] <= shift) if long else (c[i] < shift and c[i - 1] >= shift)
    back = (c[i] > level) if long else (c[i] < level)
    if broke and back and any(displacement(ctx, m, long) for m in range(s + 1, i + 1)):
        bars_to_noon = max(4, (12 * 60 - nm) // 15)
        return _confirmed(ctx, i, long, ext, "ict_judas", "Early-session false move through the Asian range reversed with a structure shift.",
                          int(bars_to_noon), ev)
    if (c[i] > shift) if long else (c[i] < shift):
        return Eval(direction=ev.direction)
    ev.stage = "CONFIRMING" if back else "DEVELOPING"
    ev.missing = [f"displacement close {'above' if long else 'below'} {_p(shift)}"]
    return ev


def _sweep_fvg(ctx: Ctx, i: int, long: bool) -> Eval:
    """8. Sweep + Displacement + FVG confluence (the full model): inside London or New York AM, an
    external pool is swept, a displacement shifts structure (MSS) and leaves an FVG; the first retest
    of that FVG closes beyond its CE. Stop beyond the sweep extreme."""
    o, h, l, c = _ohlc(ctx)
    atr = ctx.get(TF, "atr")[i]
    ev = Eval(direction=_dirname(long))
    if not _ok(atr) or i < 40:
        return ev
    nm = int(clock(ctx)["ny_min"][i])
    if not any(lo <= nm < hi for lo, hi in ENTRY_WINDOWS):
        return ev
    side = "SSL" if long else "BSL"
    sw = recent_sweep(ctx, i, side, 16, until=3, kinds=EXTERNAL)
    if sw is None:
        if recent_sweep(ctx, i, side, 2, kinds=EXTERNAL):
            ev.stage = "DEVELOPING"
            ev.missing = ["displacement that shifts structure", "FVG", "retrace into the FVG"]
        return ev
    s = sw["at"]
    ext = float(l[s:i + 1].min() if long else h[s:i + 1].max())
    if (ext < sw["extreme"]) if long else (ext > sw["extreme"]):
        return Eval(direction=ev.direction)
    ev.evidence = [f"{LABELS[sw['kind']]} {_p(sw['price'])} swept at {ny_time(ctx, s)} NY"]
    ev.invalidation = ext
    level = _swing_before(ctx, s, s, high=long)
    if level is None:
        return ev
    m = next((m for m in range(s + 1, i) if (c[m] > level if long else c[m] < level)), None)
    if m is None or not any(displacement(ctx, k, long) for k in range(s + 1, m + 1)):
        ev.stage, ev.missing = "DEVELOPING", [f"displacement close {'above' if long else 'below'} {_p(level)} (MSS)"]
        return ev
    ev.evidence.append(f"structure shifted at {ny_time(ctx, m)} NY (close beyond {_p(level)})")
    for j in range(i - 1, s + 1, -1):
        if j > m + 2:
            continue
        g = fvg_at(ctx, j, long)
        if g is None:
            continue
        st = fvg_state(ctx, g, i, long)
        if st["invalidated"] or (st["first_touch"] is not None and st["first_touch"] < i):
            return Eval(direction=ev.direction)
        ev.evidence.append(f"FVG {_p(g['bottom'])}-{_p(g['top'])} left by the displacement")
        ev.levels.update({"fvg_top": g["top"], "fvg_bottom": g["bottom"], "ce": g["ce"]})
        if st["first_touch"] == i and ((c[i] > g["ce"]) if long else (c[i] < g["ce"])) and ((c[i] > o[i]) if long else (c[i] < o[i])):
            ev.evidence.append(f"first retest held CE {_p(g['ce'])}")
            return _confirmed(ctx, i, long, ext, "ict_sweep_fvg", "Liquidity sweep, displacement with market structure shift, and an FVG retest.", 32, ev)
        ev.stage, ev.missing = "CONFIRMING", ["first retrace into the FVG closing beyond CE"]
        return ev
    ev.stage, ev.missing = "CONFIRMING", ["the displacement left no FVG yet"]
    return ev


# ----- registration ----------------------------------------------------------------------------------------

def _decide(fn: Callable[[Ctx, int, bool], Eval]) -> Callable[[Ctx, int], Decision | None]:
    def decide(ctx: Ctx, i: int) -> Decision | None:
        if "M15" not in ctx.a or i < 30:
            return None
        found = [e.decision for e in (fn(ctx, i, True), fn(ctx, i, False)) if e.decision is not None]
        return found[0] if len(found) == 1 else None       # both directions at once: conflicting, skip
    decide.__name__ = fn.__name__.lstrip("_")
    return decide


SETUPS: list[dict[str, Any]] = [
    {"key": "ict_sweep_reversal", "name": "ICT Liquidity Sweep Reversal", "fn": _sweep_reversal, "group": "liquidity",
     "entry": "An external pool (PDH/PDL, PWH/PWL, Asian or London high/low, equal highs/lows) is swept: a candle trades beyond it and closes back inside. Within 3 bars, a displacement candle closes beyond the sweep candle's opposite extreme.",
     "confirmation": "Displacement close (body >= 0.8 ATR, >= 55% of range) beyond the sweep candle; no close back beyond the pool; H4 bias not opposing.",
     "stop": "0.1 ATR beyond the sweep extreme (min 0.5 ATR, skipped beyond 3 ATR).",
     "take_profit": "Nearest unswept opposing pool at 2-5R, else 2.5R; time exit after 8 hours.",
     "invalidation": "A close back beyond the swept pool, or a new extreme beyond the sweep."},
    {"key": "ict_mss", "name": "ICT Market Structure Shift", "fn": _mss, "group": "liquidity",
     "entry": "M15 structure opposing (lower highs and lows for longs). A sweep of liquidity (incl. the last swing) within 12 bars, then the first close beyond the swing point that preceded the sweep.",
     "confirmation": "First close through the shift level with a displacement candle since the sweep; H4 bias not opposing.",
     "stop": "0.1 ATR beyond the post-sweep extreme (min 0.5 ATR, max 3 ATR).", "take_profit": "Nearest opposing pool at 2-5R, else 2.5R; 8-hour time exit.",
     "invalidation": "A new extreme beyond the sweep before the shift."},
    {"key": "ict_fvg_continuation", "name": "ICT Fair Value Gap Continuation", "fn": _fvg_continuation, "group": "imbalance",
     "entry": "H4 bias and H1 structure aligned. A displacement leaves an FVG (>= 0.2 ATR) while breaking M15 structure; 2-24 bars later the first retest of the FVG closes beyond its consequent encroachment (50%) in the trend direction.",
     "confirmation": "First-touch candle closing beyond CE, candle colour in the trend direction.",
     "stop": "0.1 ATR beyond the FVG's far edge (min 0.5 ATR).", "take_profit": "Nearest opposing pool at 2-5R, else 2.5R; 12-hour time exit.",
     "invalidation": "A close beyond the FVG's far edge."},
    {"key": "ict_ob_reversal", "name": "ICT Order Block Reversal", "fn": _ob_reversal, "group": "imbalance",
     "entry": "A fresh H1 order block (last opposite candle before a displacement that broke the last H1 swing) whose midpoint lies in the discount (longs) or premium (shorts) half of the H1 dealing range. On the first M15 visit (within 16 bars), an M15 candle closes beyond the prior two candles with a body >= 0.5 ATR.",
     "confirmation": "M15 confirmation candle during the first visit; no M15 close through the block.",
     "stop": "0.1 ATR beyond the visit extreme (min 0.5 ATR, max 3 ATR).", "take_profit": "Nearest opposing pool at 2-5R, else 2.5R; 12-hour time exit.",
     "invalidation": "A close through the order block (it becomes a breaker)."},
    {"key": "ict_ote", "name": "ICT Premium/Discount OTE", "fn": _ote, "group": "premium_discount",
     "entry": "H4 bias aligned; the last H1 leg is an impulse that broke the previous swing and spans >= 2 H1 ATR. Price retraces into the 62-79% optimal trade entry band (discount for longs) without retracing 100%; within 8 M15 bars of the first touch an M15 candle closes beyond the previous candle.",
     "confirmation": "M15 close beyond the previous candle's extreme in the bias direction after the OTE touch.",
     "stop": "0.1 ATR beyond the retracement extreme (min 0.5 ATR, max 3 ATR).", "take_profit": "The impulse leg's extreme (buy-side / sell-side liquidity); 16-hour time exit.",
     "invalidation": "A full (100%) retracement of the impulse leg."},
    {"key": "ict_silver_bullet", "name": "ICT Silver Bullet", "fn": _silver_bullet, "group": "time",
     "entry": "M15 approximation of the Silver Bullet: in the 03:00-04:00, 10:00-11:00 or 14:00-15:00 New York hour, an FVG forms after a sweep of the opposite liquidity in the prior 16 bars; the first retest of the FVG closes beyond CE.",
     "confirmation": "First-touch candle closing beyond CE inside the window (or the bar after it).",
     "stop": "0.1 ATR beyond the FVG's first candle (min 0.5 ATR).", "take_profit": "Nearest opposing pool at 2-5R, else 2.5R; 2-hour time exit.",
     "invalidation": "A close through the FVG."},
    {"key": "ict_judas", "name": "ICT Judas Swing", "fn": _judas, "group": "time",
     "entry": "H4 bias not opposing; between 02:00 and 10:00 New York the session first sweeps the Asian range against the bias (Asian low for longs), then closes back through the Asian level and beyond the swing that preceded the sweep, with displacement.",
     "confirmation": "First close beyond the shift level and back inside the Asian range, with a displacement candle since the sweep.",
     "stop": "0.1 ATR beyond the Judas extreme (min 0.5 ATR, max 3 ATR).", "take_profit": "Nearest opposing pool at 2-5R, else 2.5R; exit by 12:00 New York.",
     "invalidation": "A new extreme beyond the Judas sweep."},
    {"key": "ict_sweep_fvg", "name": "ICT Sweep + Displacement + FVG", "fn": _sweep_fvg, "group": "liquidity",
     "entry": "Inside the London (02:00-05:00) or New York AM (07:00-11:00) window: an external pool is swept (3-16 bars ago), a displacement closes beyond the swing that preceded the sweep (MSS) and leaves an FVG, and the first retest of that FVG closes beyond its CE.",
     "confirmation": "All three events in order plus the closed retest candle.",
     "stop": "0.1 ATR beyond the sweep extreme (min 0.5 ATR, max 3 ATR).", "take_profit": "Nearest opposing pool at 2-5R, else 2.5R; 8-hour time exit.",
     "invalidation": "A new extreme beyond the sweep, or a close through the FVG."},
]
BY_KEY = {s["key"]: s for s in SETUPS}


def specs() -> list[dict[str, Any]]:
    out = []
    for s in SETUPS:
        out.append({"key": s["key"], "name": s["name"], "status": rules.RESEARCH, "decide": _decide(s["fn"]), "timeframe": TF,
                    "instruments": ALL, "entry": s["entry"], "indicators": "ICT primitives (strategy_bank/ict.py): liquidity pools, sweeps, swing structure, displacement, FVG, order blocks, dealing range, New York session clock, ATR(14)",
                    "confirmation": s["confirmation"], "stop": s["stop"], "take_profit": s["take_profit"],
                    "min_rr": PARAMS["min_rr"], "invalidation": s["invalidation"] + " " + rules.COMMON_INVALIDATION,
                    "data": ["M15", "H1", "H4"], "family": "ICT", "group": s["group"], "version": VERSION})
    return out


def register() -> list[str]:
    """Register the family in the bank as RESEARCH (shadow); idempotent."""
    added = []
    for spec in specs():
        if spec["key"] not in rules.BY_KEY:
            rules.register(spec)
            added.append(spec["key"])
    return added


# ----- live snapshot (Market Radar / AI Analyst) ------------------------------------------------------------

def evaluate(ctx: Ctx, i: int | None = None) -> list[dict[str, Any]]:
    """Stage report for every setup on the last closed bar: the more advanced direction per setup."""
    i = len(ctx.a[TF]["close"]) - 1 if i is None else i
    out = []
    for s in SETUPS:
        best, tie = None, False
        for long in (True, False):
            try:
                e = s["fn"](ctx, i, long)
            except (IndexError, ValueError):
                continue
            if best is None or RANK[e.stage] > RANK[best.stage]:
                best, tie = e, False
            elif RANK[e.stage] == RANK[best.stage]:
                tie = True                                  # equally advanced both ways: no direction
        if best is None:
            continue
        out.append({"key": s["key"], "name": s["name"], "group": s["group"], "stage": best.stage,
                    "direction": best.direction if best.stage != "NONE" and not tie else None, "evidence": best.evidence,
                    "missing": best.missing, "invalidation": best.invalidation, "blocked": best.blocked,
                    "levels": best.levels})
    return out


def snapshot(ctx: Ctx) -> dict[str, Any]:
    """Objective ICT context for the last closed M15 bar. Every number comes from closed broker bars."""
    o, h, l, c = _ohlc(ctx)
    i = len(c) - 1
    atr = float(ctx.get(TF, "atr")[i])
    price = float(c[i])
    pools = []
    for p in liquidity(ctx, i):
        pools.append({"kind": p["kind"], "label": LABELS.get(p["kind"], p["kind"]), "side": p["side"], "price": p["price"],
                      "swept": p["swept_at"] is not None,
                      "swept_at": datetime.fromtimestamp(ctx.close_utc(TF, p["swept_at"]), timezone.utc).isoformat() if p["swept_at"] is not None else None,
                      "distance_atr": round((p["price"] - price) / atr, 2) if _ok(atr) and atr else None})
    pools.sort(key=lambda p: -p["price"])
    events = []
    for s in range(max(1, i - 23), i + 1):
        for e in sweeps_at(ctx, s):
            events.append({"type": "SWEEP", "at": datetime.fromtimestamp(ctx.close_utc(TF, s), timezone.utc).isoformat(),
                           "text": f"{LABELS.get(e['kind'], e['kind'])} {_p(e['price'])} swept ({'buy' if e['side'] == 'BSL' else 'sell'}-side), closed back inside"})
    gaps = []
    for j in range(i, max(2, i - 48), -1):
        for long in (True, False):
            g = fvg_at(ctx, j, long)
            if g:
                st = fvg_state(ctx, g, i, long)
                if st["status"] != "INVALIDATED":
                    gaps.append({"direction": "BULLISH" if long else "BEARISH", "top": g["top"], "bottom": g["bottom"], "ce": g["ce"],
                                 "status": st["status"], "ce_touched": st["ce_touched"],
                                 "formed_at": datetime.fromtimestamp(ctx.close_utc(TF, j), timezone.utc).isoformat()})
    blocks = []
    jh = ctx.last_closed("H1", ctx.close_utc(TF, i)) if "H1" in ctx.a else -1
    if jh >= 20:
        for ob in order_blocks(ctx, jh)[:8]:
            state = ob_state(ctx, ob, jh)
            kind = ("BEARISH BREAKER" if ob["long"] else "BULLISH BREAKER") if state == "BREAKER" else ("BULLISH" if ob["long"] else "BEARISH") + " ORDER BLOCK"
            blocks.append({"type": kind, "state": state, "low": ob["low"], "high": ob["high"],
                           "formed_at": datetime.fromtimestamp(ctx.close_utc("H1", ob["at"]), timezone.utc).isoformat()})
    dr = dealing_range(ctx, jh) if jh >= 0 else None
    if dr:
        pos = (price - dr["low"]) / (dr["high"] - dr["low"])
        dr = {**dr, "position": round(pos, 3), "zone": "PREMIUM" if pos > 0.55 else "DISCOUNT" if pos < 0.45 else "EQUILIBRIUM"}
    ck = clock(ctx)
    nm = int(ck["ny_min"][i])
    t = ctx.close_utc(TF, i)
    structure = {"M15": trend(ctx, TF, i), "H1": trend(ctx, "H1", jh) if jh >= 0 else "NEUTRAL", "H4": bias(ctx, t)}
    return {"version": VERSION, "bar_closed_at": datetime.fromtimestamp(t, timezone.utc).isoformat(), "price": price,
            "atr_m15": atr, "ny_time": f"{nm // 60:02d}:{nm % 60:02d}", "kill_zone": kill_zone(nm),
            "structure": structure, "bias": structure["H4"], "liquidity": pools, "events": events[-8:],
            "fvgs": gaps[:8], "order_blocks": blocks, "dealing_range": dr, "setups": evaluate(ctx, i),
            "params": PARAMS, "basis": "Closed MT5 broker bars (M15/H1/H4); the forming bar is excluded."}
