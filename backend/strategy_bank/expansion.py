"""Bank expansion strategies (T-036). Candidates are researched with the lab protocol
(research/bank_expansion.py); a candidate is REGISTERED in the bank only when the qualification
registry admits it (FORWARD_TESTING or QUALIFIED), and then always as RESEARCH (shadow: recorded,
never alerted until an evidence-based promotion). Rejected candidates stay here with their recorded
results in the registry, so the research is reproducible and never silently repeated.

Every decide() reads closed bars <= i only (bar i has just closed), like rules.py.
"""
from __future__ import annotations

from datetime import datetime, timezone
from functools import partial
from typing import Any

import numpy as np

from strategy_bank import rules
from strategy_bank.rules import ALL, FX, INDICES, METALS, Ctx, Decision, _ok

COMMON = rules.COMMON_INVALIDATION


def _other_atr(ctx: Ctx, tf: str, at_utc: float) -> float | None:
    j = ctx.last_closed(tf, at_utc)
    return float(ctx.get(tf, "atr")[j]) if j >= 0 and _ok(ctx.get(tf, "atr")[j]) else None


# ----- A. FX session momentum ---------------------------------------------------------------------------

def fx_session_momentum(ctx: Ctx, i: int, tf: str = "M15", k: float = 1.5) -> Decision | None:
    """London-morning (07:00-13:00 UTC) move >= k x H1 ATR is followed in the same direction until 16:00 UTC."""
    a = ctx.a[tf]
    open_t = a["utc"][i]
    day = open_t - open_t % 86400
    if open_t != day + 12 * 3600 + 45 * 60:            # the bar closing at 13:00 UTC
        return None
    s = int(np.searchsorted(a["utc"], day + 7 * 3600, side="left"))
    if s >= i or a["utc"][s] != day + 7 * 3600:
        return None
    move = a["close"][i] - a["open"][s]
    atr = _other_atr(ctx, "H1", ctx.close_utc(tf, i))
    if not atr or abs(move) < k * atr:
        return None
    long = move > 0
    c = a["close"][i]
    return Decision("LONG" if long else "SHORT", stop=c - 1.5 * atr if long else c + 1.5 * atr, target_r=3.0, max_bars=12,
                    evidence={"london_move_atr": move / atr},
                    explanation=f"The London morning moved {abs(move) / atr:.1f} H1 ATR {'up' if long else 'down'}; follow it into the New York overlap, exit 16:00 UTC.")


# ----- B. weekend gap fade -------------------------------------------------------------------------------

def weekend_gap(ctx: Ctx, i: int, tf: str = "M15", k: float = 0.5) -> Decision | None:
    """At the close of the week's first M15 bar, fade a weekend gap >= k x H1 ATR back to Friday's close."""
    a = ctx.a[tf]
    if i < 1 or a["utc"][i] - a["utc"][i - 1] < 24 * 3600:
        return None
    friday = a["close"][i - 1]
    gap = a["open"][i] - friday
    atr = _other_atr(ctx, "H1", ctx.close_utc(tf, i))
    c = a["close"][i]
    if not atr or abs(gap) < k * atr or (c - friday) * gap <= 0:      # already filled: nothing to fade
        return None
    long = gap < 0
    extreme = a["low"][i] if long else a["high"][i]
    stop = extreme - abs(gap) if long else extreme + abs(gap)
    open_t = a["utc"][i]
    noon = open_t - open_t % 86400 + 12 * 3600
    return Decision("LONG" if long else "SHORT", stop=stop, target=friday, target_r=None,
                    max_bars=max(1, int((noon - (open_t + 900)) // 900)), evidence={"gap_atr": gap / atr},
                    explanation=f"Weekend gap of {abs(gap) / atr:.1f} H1 ATR still open after the first M15 bar; fade it toward Friday's close (exit by 12:00 UTC).")


# ----- C. Turtle Soup (failed breakout) --------------------------------------------------------------------

def turtle_soup(ctx: Ctx, i: int, tf: str = "H1", n: int = 20) -> Decision | None:
    """New n-bar low whose previous low is >= 4 bars old, closing back above it -> buy (mirror: highs)."""
    a = ctx.a[tf]
    h, l, c = a["high"], a["low"], a["close"]
    atr = ctx.get(tf, "atr")[i]
    if i < n + 5 or not _ok(atr):
        return None
    lows, highs = l[i - n:i], h[i - n:i]
    lo_k, hi_k = int(np.argmin(lows)), int(np.argmax(highs))
    lo, hi = lows[lo_k], highs[hi_k]
    if l[i] < lo and n - lo_k >= 4 and c[i] > lo:
        return Decision("LONG", stop=l[i] - 0.2 * atr, explanation=f"The {tf} candle broke the {n}-bar low (set at least 4 bars earlier) and closed back above it: a failed breakdown.")
    if h[i] > hi and n - hi_k >= 4 and c[i] < hi:
        return Decision("SHORT", stop=h[i] + 0.2 * atr, explanation=f"The {tf} candle broke the {n}-bar high (set at least 4 bars earlier) and closed back below it: a failed breakout.")
    return None


# ----- D. Heikin-Ashi trend ------------------------------------------------------------------------------

def _heikin_ashi(ctx: Ctx, tf: str):
    key = (tf, "heikin_ashi")
    if key not in ctx._cache:
        a = ctx.a[tf]
        o, h, l, c = a["open"], a["high"], a["low"], a["close"]
        hc = (o + h + l + c) / 4
        ho = np.empty_like(hc)
        ho[0] = (o[0] + c[0]) / 2
        for i in range(1, len(hc)):
            ho[i] = (ho[i - 1] + hc[i - 1]) / 2
        ctx._cache[key] = (ho, np.maximum(h, np.maximum(ho, hc)), np.minimum(l, np.minimum(ho, hc)), hc)
    return ctx._cache[key]


def heikin_ashi_trend(ctx: Ctx, i: int, tf: str = "H1", m: int = 3) -> Decision | None:
    """First Heikin-Ashi candle with no wick against it after >= m opposite HA candles, with the close on the EMA50 side."""
    ho, hh, hl, hc = _heikin_ashi(ctx, tf)
    c, e50 = ctx.a[tf]["close"], ctx.get(tf, "ema", 50)
    if i < 60:
        return None
    tol = 1e-9 * abs(hc[i])
    if hc[i] > ho[i] and hl[i] >= min(ho[i], hc[i]) - tol and all(hc[k] < ho[k] for k in range(i - m, i)) and c[i] > e50[i]:
        return Decision("LONG", stop_atr=1.5, explanation=f"Heikin-Ashi turned bullish with no lower wick after {m}+ bearish candles, above EMA50.")
    if hc[i] < ho[i] and hh[i] <= max(ho[i], hc[i]) + tol and all(hc[k] > ho[k] for k in range(i - m, i)) and c[i] < e50[i]:
        return Decision("SHORT", stop_atr=1.5, explanation=f"Heikin-Ashi turned bearish with no upper wick after {m}+ bullish candles, below EMA50.")
    return None


# ----- E. Kaufman adaptive trend ---------------------------------------------------------------------------

def _kama(ctx: Ctx, tf: str, n: int = 10, fast: int = 2, slow: int = 30):
    key = (tf, "kama", n)
    if key not in ctx._cache:
        c = ctx.a[tf]["close"]
        er = np.full_like(c, np.nan)
        kama = np.full_like(c, np.nan)
        fsc, ssc = 2 / (fast + 1), 2 / (slow + 1)
        for i in range(n, len(c)):
            vol = np.abs(np.diff(c[i - n:i + 1])).sum()
            er[i] = abs(c[i] - c[i - n]) / vol if vol else 0.0
            sc = (er[i] * (fsc - ssc) + ssc) ** 2
            kama[i] = c[i] if np.isnan(kama[i - 1]) else kama[i - 1] + sc * (c[i] - kama[i - 1])
        ctx._cache[key] = (kama, er)
    return ctx._cache[key]


def kama_trend(ctx: Ctx, i: int, tf: str = "H1", er_min: float = 0.3) -> Decision | None:
    """KAMA(10,2,30) turns up (down) with efficiency ratio >= er_min and the close above (below) KAMA."""
    kama, er = _kama(ctx, tf)
    c = ctx.a[tf]["close"]
    if i < 15 or not _ok(kama[i], kama[i - 1], kama[i - 2], er[i]) or er[i] < er_min:
        return None
    if kama[i] > kama[i - 1] and kama[i - 1] <= kama[i - 2] and c[i] > kama[i]:
        return Decision("LONG", stop_atr=2.0, explanation=f"Kaufman's adaptive average turned up with an efficiency ratio of {er[i]:.2f}.")
    if kama[i] < kama[i - 1] and kama[i - 1] >= kama[i - 2] and c[i] < kama[i]:
        return Decision("SHORT", stop_atr=2.0, explanation=f"Kaufman's adaptive average turned down with an efficiency ratio of {er[i]:.2f}.")
    return None


# ----- F. prior-close reversion ---------------------------------------------------------------------------

def prior_close_reversion(ctx: Ctx, i: int, tf: str = "H1", k: float = 1.0) -> Decision | None:
    """After today's price extends >= k x D1 ATR from the previous daily close, an H1 reversal candle
    (close beyond the previous H1 candle's low/high) targets the previous close."""
    a = ctx.a[tf]
    o, h, l, c = a["open"], a["high"], a["low"], a["close"]
    close_t = ctx.close_utc(tf, i)
    d = ctx.last_closed("D1", close_t - 1)
    if d < 15 or i < 2:
        return None
    prev_close = float(ctx.a["D1"]["close"][d])
    atr_d = ctx.get("D1", "atr")[d]
    atr = ctx.get(tf, "atr")[i]
    if not _ok(atr_d, atr):
        return None
    day_start = ctx.a["D1"]["utc"][d] + 86400
    s = int(np.searchsorted(a["utc"], day_start, side="left"))
    if s > i:
        return None
    day_high, day_low = h[s:i + 1].max(), l[s:i + 1].min()
    if day_high - prev_close >= k * atr_d and c[i] < o[i] and c[i] < l[i - 1] and c[i] > prev_close:
        return Decision("SHORT", stop=day_high + 0.3 * atr, target=prev_close, target_r=None,
                        explanation=f"Price stretched {(day_high - prev_close) / atr_d:.1f} daily ATR above yesterday's close and the {tf} candle reversed; target yesterday's close.")
    if prev_close - day_low >= k * atr_d and c[i] > o[i] and c[i] > h[i - 1] and c[i] < prev_close:
        return Decision("LONG", stop=day_low - 0.3 * atr, target=prev_close, target_r=None,
                        explanation=f"Price stretched {(prev_close - day_low) / atr_d:.1f} daily ATR below yesterday's close and the {tf} candle reversed; target yesterday's close.")
    return None


# ----- candidate registry -------------------------------------------------------------------------------

def _spec(key, name, decide, timeframe, instruments, entry, indicators, confirmation, stop, take_profit, min_rr, data):
    return {"key": key, "name": name, "status": rules.RESEARCH, "decide": decide, "timeframe": timeframe,
            "instruments": instruments, "entry": entry, "indicators": indicators, "confirmation": confirmation,
            "stop": stop, "take_profit": take_profit, "min_rr": min_rr, "invalidation": COMMON, "data": data}


FAMILIES: dict[str, dict[str, Any]] = {
    "fx_session_momentum": {
        "source": "Elaut, Frommel & Lampaert (2018), 'Intraday momentum in FX markets', Journal of Financial Markets",
        "rationale": "Informed order flow early in the most liquid session continues into the next session.",
        "configs": {f"fx_session_momentum_k{k}": _spec(
            f"fx_session_momentum_k{k}", f"FX Session Momentum (k={k})", partial(fx_session_momentum, k=k), "M15", FX,
            f"London-morning move (07:00 open to 13:00 close UTC) of at least {k} H1-ATR; enter at 13:00 in its direction.",
            "Session return, H1 ATR(14)", "Completed 12:45-13:00 UTC M15 candle.", "1.5 H1-ATR from the confirming close.",
            "3R or the 16:00 UTC time exit.", 1.5, ["M15", "H1"]) for k in (1.5, 3.0)}},
    "weekend_gap": {
        "source": "Practitioner 'weekend gap fill' (e.g. FX and index CFD trading literature); no peer-reviewed evidence found",
        "rationale": "Weekend gaps in liquid markets reflect thin-liquidity repricing that partially reverses when trading resumes.",
        "configs": {f"weekend_gap_k{k}": _spec(
            f"weekend_gap_k{k}", f"Weekend Gap Fade (k={k})", partial(weekend_gap, k=k), "M15", FX + METALS + INDICES,
            f"Monday's first M15 candle opens at least {k} H1-ATR away from Friday's close and closes without filling it; fade toward Friday's close.",
            "Weekend gap, H1 ATR(14)", "Completed first M15 candle of the week.", "One gap-size beyond the first candle's extreme.",
            "Friday's close; time exit 12:00 UTC.", 0.5, ["M15", "H1"]) for k in (0.5, 1.0)}},
    "turtle_soup": {
        "source": "Raschke & Connors (1995), 'Street Smarts: High Probability Short-Term Trading Strategies'",
        "rationale": "Breakouts of well-watched prior extremes that immediately fail trap breakout traders and reverse.",
        "configs": {f"turtle_soup_n{n}": _spec(
            f"turtle_soup_n{n}", f"Turtle Soup ({n}-bar)", partial(turtle_soup, n=n), "H1", ALL,
            f"An H1 candle breaks the prior {n}-bar low (set >= 4 bars earlier) and closes back above it (mirror for highs).",
            f"{n}-bar extremes, ATR(14)", "Completed close back inside the range.", "0.2 ATR beyond the failed-breakout extreme.",
            "2R.", 1.5, ["H1"]) for n in (20, 55)}},
    "heikin_ashi_trend": {
        "source": "Heikin-Ashi trend continuation (popular TradingView public strategy); no credible independent evidence found",
        "rationale": "Smoothed candles filter noise; a wickless HA candle after a counter-move marks trend resumption.",
        "configs": {f"heikin_ashi_m{m}": _spec(
            f"heikin_ashi_m{m}", f"Heikin-Ashi Trend (after {m})", partial(heikin_ashi_trend, m=m), "H1", ALL,
            f"First wickless (against-direction) Heikin-Ashi candle after >= {m} opposite HA candles, close on the EMA50 side.",
            "Heikin-Ashi candles, EMA50, ATR(14)", "Completed H1 candle.", "1.5 ATR.", "2R.", 1.5, ["H1"]) for m in (3, 5)}},
    "kama_trend": {
        "source": "Kaufman, 'Trading Systems and Methods' (adaptive moving average, efficiency ratio)",
        "rationale": "Adapting the average's speed to the market's efficiency reduces whipsaw in ranges.",
        "configs": {f"kama_er{int(er * 10)}": _spec(
            f"kama_er{int(er * 10)}", f"KAMA Trend (ER >= {er})", partial(kama_trend, er_min=er), "H1", ALL,
            f"KAMA(10,2,30) slope turns with efficiency ratio >= {er}, close on the KAMA side.",
            "KAMA(10,2,30), efficiency ratio(10), ATR(14)", "Completed H1 candle.", "2 ATR.", "2R.", 1.5, ["H1"]) for er in (0.3, 0.5)}},
    "prior_close_reversion": {
        "source": "Statistical mean reversion to the prior session close (intraday overreaction literature, e.g. Lehmann 1990)",
        "rationale": "Large intraday extensions from the previous close partly reverse once the initial order imbalance is absorbed.",
        "configs": {f"prior_close_reversion_k{k}": _spec(
            f"prior_close_reversion_k{k}", f"Prior-Close Reversion (k={k})", partial(prior_close_reversion, k=k), "H1", ALL,
            f"Today's extreme at least {k} D1-ATR from yesterday's close; an H1 reversal candle closing beyond the previous candle's range.",
            "Previous D1 close, D1 ATR(14), H1 ATR(14)", "Completed H1 reversal candle.", "0.3 H1-ATR beyond today's extreme.",
            "Yesterday's close.", 0.5, ["H1", "D1"]) for k in (1.0, 1.5)}},
}
CANDIDATES = {key: spec for fam in FAMILIES.values() for key, spec in fam["configs"].items()}


def register_admitted() -> list[str]:
    """Register (as RESEARCH) every candidate the qualification registry admits; idempotent."""
    from strategy_bank import qualification
    added = []
    for key, spec in CANDIDATES.items():
        if qualification.current_status(key) in (qualification.FORWARD_TESTING, qualification.QUALIFIED) and key not in rules.BY_KEY:
            rules.register(spec)
            added.append(key)
    return added
