"""Causal signal generators for the pre-registered edge-discovery families.

A generator receives a Market and one configuration and returns signals decided at the CLOSE of M15 bar `i`
(entry at the open of bar i + 1). A signal is {"i", "dir" (+1 long / -1 short), "stop" (absolute price),
"target" (absolute natural target or None), "max_bars" (M15 bars), "atr" (H1 ATR at the decision)}.
Generators read arrays only at indices <= i (and, for a higher timeframe, only buckets closed by bar i).
"""
from __future__ import annotations

import math
from typing import Any, Callable

import numpy as np

from research.edge.market import FRANKFURT, NEW_YORK, TF_MINUTES, Market

Signal = dict[str, Any]


def _sig(i: int, d: int, stop: float, target: float | None, max_bars: int, atr: float) -> Signal:
    return {"i": int(i), "dir": int(d), "stop": float(stop), "target": None if target is None else float(target),
            "max_bars": int(max_bars), "atr": float(atr)}


def _ok(*values: float) -> bool:
    return all(v is not None and math.isfinite(v) for v in values)


def _per(tf: str) -> int:
    return TF_MINUTES[tf] // 15


# ----- A. microstructure ---------------------------------------------------------------------------------

def stop_hunt_pdhl(m: Market, cfg: dict[str, Any]) -> list[Signal]:
    """A1: price sweeps the previous day's high/low by >= depth x ATR(M15) and the same M15 bar closes back inside:
    fade the sweep. Stop beyond the sweep extreme; natural target the previous day's midpoint."""
    ph, pl, _ = m.prev_day
    atr, ah1, day = m.atr_m15, m.atr_h1_at, m.trading_day
    used: set = set()
    out = []
    for i in range(m.n - 1):
        if not _ok(ph[i], pl[i], atr[i], ah1[i]):
            continue
        mid = (ph[i] + pl[i]) / 2
        if m.high[i] > ph[i] + cfg["depth"] * atr[i] and m.close[i] < ph[i] and (day[i], -1) not in used:
            used.add((day[i], -1))
            out.append(_sig(i, -1, m.high[i] + 0.1 * ah1[i], mid, 32, ah1[i]))
        elif m.low[i] < pl[i] - cfg["depth"] * atr[i] and m.close[i] > pl[i] and (day[i], 1) not in used:
            used.add((day[i], 1))
            out.append(_sig(i, 1, m.low[i] - 0.1 * ah1[i], mid, 32, ah1[i]))
    return out


def failed_asian_breakout(m: Market, cfg: dict[str, Any]) -> list[Signal]:
    """A2: during 07:00-12:00 UTC price closes beyond the Asian (00:00-07:00 UTC) range, then closes back inside
    within N M15 bars: the breakout failed, fade it. Stop beyond the post-break extreme; target the far range edge."""
    hi, lo, _ = m.window_range(0, 420)
    mins, day, ah1 = m.utc_minutes, m.utc_day, m.atr_h1_at
    out, state, done = [], {}, set()
    for i in range(m.n - 1):
        if not (420 <= mins[i] < 720) or not _ok(hi[i], lo[i], ah1[i]):
            continue
        d = day[i]
        st = state.get(d)
        if st is None:
            if m.close[i] > hi[i]:
                state[d] = {"side": 1, "at": i, "ext": m.high[i]}
            elif m.close[i] < lo[i]:
                state[d] = {"side": -1, "at": i, "ext": m.low[i]}
            continue
        if d in done:
            continue
        if st["side"] == 1:
            st["ext"] = max(st["ext"], m.high[i])
            if m.close[i] < hi[i] and i - st["at"] <= cfg["n"]:
                out.append(_sig(i, -1, st["ext"] + 0.1 * ah1[i], lo[i], 32, ah1[i]))
                done.add(d)
        else:
            st["ext"] = min(st["ext"], m.low[i])
            if m.close[i] > lo[i] and i - st["at"] <= cfg["n"]:
                out.append(_sig(i, 1, st["ext"] - 0.1 * ah1[i], hi[i], 32, ah1[i]))
                done.add(d)
        if i - st["at"] > cfg["n"]:
            done.add(d)
    return out


def displacement_pullback(m: Market, cfg: dict[str, Any]) -> list[Signal]:
    """A3: a displacement candle (body >= k x ATR, close in the outer quarter of its range) shows one-sided order
    flow; enter on the first pullback that tests the candle's 50% level and closes back beyond it (within 6
    bars). Stop beyond the candle's origin."""
    f = m.frame(cfg["tf"])
    per = _per(cfg["tf"])
    out, pending = [], None
    ah1 = m.atr_h1_at
    for k in range(20, len(f.close)):
        i = int(f.last_m15[k])
        if i >= m.n - 1:
            break
        if pending is not None:
            d, mid, origin, start = pending
            if k - start > 6 or (d == 1 and f.close[k] < origin) or (d == -1 and f.close[k] > origin):
                pending = None
            elif (d == 1 and f.low[k] <= mid < f.close[k]) or (d == -1 and f.high[k] >= mid > f.close[k]):
                atr = f.atr[k]
                if _ok(atr, ah1[i]):
                    out.append(_sig(i, d, origin - d * 0.1 * atr, None, 8 * per, ah1[i]))
                pending = None
                continue
        atr = f.atr[k]
        rng = f.high[k] - f.low[k]
        body = f.close[k] - f.open[k]
        if not _ok(atr) or rng <= 0 or abs(body) < cfg["k"] * atr:
            continue
        if body > 0 and f.close[k] >= f.high[k] - 0.25 * rng:
            pending = (1, (f.high[k] + f.low[k]) / 2, f.low[k], k)
        elif body < 0 and f.close[k] <= f.low[k] + 0.25 * rng:
            pending = (-1, (f.high[k] + f.low[k]) / 2, f.high[k], k)
    return out


# ----- B. statistical ------------------------------------------------------------------------------------

def anchored_mean_reversion(m: Market, cfg: dict[str, Any]) -> list[Signal]:
    """B1: deviation of the close from the trading-day anchored, tick-weighted average price (a VWAP PROXY:
    broker tick counts, not traded volume) of >= k x ATR(H1), with H1 ADX < 25 (no strong trend): fade towards
    the average. Signal on the bar the deviation first crosses k."""
    tp = (m.high + m.low + m.close) / 3
    vol = np.where(m.volume > 0, m.volume, 1.0)
    day = m.trading_day
    av = np.empty(m.n)
    num = den = 0.0
    bars_in_day = np.zeros(m.n, int)
    for i in range(m.n):
        if i == 0 or day[i] != day[i - 1]:
            num = den = 0.0
            bars_in_day[i] = 0
        else:
            bars_in_day[i] = bars_in_day[i - 1] + 1
        num += tp[i] * vol[i]
        den += vol[i]
        av[i] = num / den
    h1 = m.frame("H1")
    adx_idx = np.searchsorted(h1.last_m15, np.arange(m.n), side="right") - 1
    ah1 = m.atr_h1_at
    out = []
    prev_dev = 0.0
    for i in range(m.n - 1):
        if not _ok(ah1[i]) or ah1[i] <= 0 or adx_idx[i] < 0:
            prev_dev = 0.0
            continue
        dev = (m.close[i] - av[i]) / ah1[i]
        adx = h1.adx[adx_idx[i]]
        if bars_in_day[i] >= 8 and _ok(adx) and adx < 25:
            if dev >= cfg["k"] > prev_dev:
                out.append(_sig(i, -1, m.close[i] + ah1[i], av[i], 32, ah1[i]))
            elif dev <= -cfg["k"] < prev_dev:
                out.append(_sig(i, 1, m.close[i] - ah1[i], av[i], 32, ah1[i]))
        prev_dev = dev
    return out


def volatility_expansion(m: Market, cfg: dict[str, Any]) -> list[Signal]:
    """B2: ATR(14) below 0.75 x its 100-bar average at some point in the last 5 bars (compression), then a close
    beyond the prior 20-bar high/low (expansion): follow the break. Stop 1.5 ATR."""
    f = m.frame(cfg["tf"])
    per = _per(cfg["tf"])
    atr = f.atr
    from strategy_bank import indicators as ind
    base = ind.sma(np.nan_to_num(atr, nan=0.0), 100)
    ratio = atr / np.where(base > 0, base, np.nan)
    hi20, lo20 = ind.prior_max(f.high, 20), ind.prior_min(f.low, 20)
    ah1 = m.atr_h1_at
    out = []
    for k in range(120, len(f.close)):
        i = int(f.last_m15[k])
        if i >= m.n - 1 or not _ok(atr[k], hi20[k], lo20[k], ah1[i]):
            continue
        recent = ratio[k - 4:k + 1]
        if not (np.nanmin(recent) < 0.75):
            continue
        if f.close[k] > hi20[k] and f.close[k - 1] <= hi20[k - 1]:
            out.append(_sig(i, 1, f.close[k] - 1.5 * atr[k], None, 24 * per, ah1[i]))
        elif f.close[k] < lo20[k] and f.close[k - 1] >= lo20[k - 1]:
            out.append(_sig(i, -1, f.close[k] + 1.5 * atr[k], None, 24 * per, ah1[i]))
    return out


def tsmom(m: Market, cfg: dict[str, Any]) -> list[Signal]:
    """B3: time-series momentum. State = sign of the L-bar return when the close is on the same side of EMA(L);
    enter when the state turns to +1 / -1. Stop 2 ATR; meant for trailing exits."""
    f = m.frame(cfg["tf"])
    L = cfg["L"]
    ema = f.ema(L)
    ah1 = m.atr_h1_at
    out, prev = [], 0
    for k in range(L + 20, len(f.close)):
        i = int(f.last_m15[k])
        if i >= m.n - 1:
            break
        r = f.close[k] - f.close[k - L]
        state = 1 if (r > 0 and f.close[k] > ema[k]) else -1 if (r < 0 and f.close[k] < ema[k]) else 0
        if state != 0 and state != prev and _ok(f.atr[k], ah1[i]):
            out.append(_sig(i, state, f.close[k] - state * 2 * f.atr[k], None, 960, ah1[i]))
        if state != 0:
            prev = state
    return out


def large_move(m: Market, cfg: dict[str, Any]) -> list[Signal]:
    """B4: after a bar whose return is beyond 2.5 standard deviations (prior 100 bars), trade in the direction the
    TRAIN-period conditional autocorrelation of this instrument and timeframe indicates (experiment 0):
    continuation if positive, reversal if negative. Stop 1 ATR; natural exit after 4 bars."""
    f = m.frame(cfg["tf"])
    per = _per(cfg["tf"])
    sign = cfg["sign"]
    if sign == 0:
        return []
    c = f.close
    r = np.r_[np.nan, np.diff(np.log(c))]
    ah1 = m.atr_h1_at
    out = []
    for k in range(102, len(c)):
        i = int(f.last_m15[k])
        if i >= m.n - 1:
            break
        window = r[k - 100:k]
        sd = np.nanstd(window)
        if not (sd > 0) or not _ok(f.atr[k], ah1[i]):
            continue
        z = r[k] / sd
        if abs(z) > 2.5:
            d = int(np.sign(z)) * sign
            out.append(_sig(i, d, c[k] - d * f.atr[k], None, 4 * per, ah1[i]))
    return out


# ----- C. session ----------------------------------------------------------------------------------------

def _session_clock(m: Market) -> tuple[Any, int, int]:
    """(timezone, cash-open minute, cash-close minute) for the instrument's reference equity session."""
    if m.symbol == "GER40":
        return FRANKFURT, 9 * 60, 17 * 60 + 30
    return NEW_YORK, 9 * 60 + 30, 16 * 60


def opening_range_breakout(m: Market, cfg: dict[str, Any]) -> list[Signal]:
    """C1: opening range of the first `minutes` of the cash session (New York 09:30; Frankfurt 09:00 for GER40);
    first M15 close beyond it within 2 hours: follow. Stop at the opposite side (the range middle if the range is
    wider than 1.5 ATR(H1)); exit at the cash close."""
    tz, open_min, close_min = _session_clock(m)
    mins, days, wd = m.local(tz)
    ah1 = m.atr_h1_at
    out, rng, done = [], {}, set()
    end_or = open_min + cfg["minutes"]
    for i in range(m.n - 1):
        d, t = days[i], mins[i]
        if wd[i] >= 5:
            continue
        if open_min <= t < end_or:
            hi, lo = rng.get(d, (-math.inf, math.inf))
            rng[d] = (max(hi, m.high[i]), min(lo, m.low[i]))
            continue
        if d in done or d not in rng or not (end_or <= t < end_or + 120) or not _ok(ah1[i]):
            continue
        hi, lo = rng[d]
        width = hi - lo
        bars_left = max(1, (close_min - (t + 15)) // 15)
        if m.close[i] > hi:
            stop = lo if width <= 1.5 * ah1[i] else (hi + lo) / 2
            out.append(_sig(i, 1, stop, None, bars_left, ah1[i]))
            done.add(d)
        elif m.close[i] < lo:
            stop = hi if width <= 1.5 * ah1[i] else (hi + lo) / 2
            out.append(_sig(i, -1, stop, None, bars_left, ah1[i]))
            done.add(d)
    return out


def intraday_momentum(m: Market, cfg: dict[str, Any]) -> list[Signal]:
    """C2: the return from the cash open over the first `minutes` predicts the last hour (Gao et al. 2018): at
    one hour before the cash close, trade in its direction; exit at the close. Stop 1 ATR(H1)."""
    tz, open_min, close_min = _session_clock(m)
    mins, days, wd = m.local(tz)
    ah1 = m.atr_h1_at
    first_open: dict[int, float] = {}
    window_close: dict[int, float] = {}
    out = []
    for i in range(m.n - 1):
        d, t = days[i], mins[i]
        if wd[i] >= 5:
            continue
        if t == open_min:
            first_open[d] = m.open[i]
        if t + 15 == open_min + cfg["minutes"] and d in first_open:
            window_close[d] = m.close[i]
        if t + 15 == close_min - 60 and d in window_close and _ok(ah1[i]):
            r = window_close[d] - first_open[d]
            if abs(r) >= 0.1 * ah1[i]:
                dd = 1 if r > 0 else -1
                out.append(_sig(i, dd, m.close[i] - dd * ah1[i], None, 4, ah1[i]))
    return out


def london_compression_breakout(m: Market, cfg: dict[str, Any]) -> list[Signal]:
    """C3: when the Asian range (00:00-07:00 UTC) is narrower than q x the 20-day average range, the first close
    beyond it between 07:00 and 11:00 UTC is followed. Stop at the opposite side; exit 16:00 UTC."""
    hi, lo, _ = m.window_range(0, 420)
    mins, day, adr, ah1 = m.utc_minutes, m.utc_day, m.adr20, m.atr_h1_at
    out, done = [], set()
    for i in range(m.n - 1):
        if not (420 <= mins[i] < 660) or day[i] in done or not _ok(hi[i], lo[i], adr[i], ah1[i]):
            continue
        if hi[i] - lo[i] > cfg["q"] * adr[i]:
            done.add(day[i])
            continue
        bars_left = max(1, (960 - (mins[i] + 15)) // 15)
        if m.close[i] > hi[i]:
            out.append(_sig(i, 1, lo[i], None, bars_left, ah1[i]))
            done.add(day[i])
        elif m.close[i] < lo[i]:
            out.append(_sig(i, -1, hi[i], None, bars_left, ah1[i]))
            done.add(day[i])
    return out


def overlap_continuation(m: Market, cfg: dict[str, Any]) -> list[Signal]:
    """C4: a London-session move (07:00 -> 12:00 UTC) of at least k x the 20-day average range continues into the
    London/New York overlap: enter at 12:00 UTC in its direction, exit 16:00 UTC. Stop 1 ATR(H1)."""
    mins, day, adr, ah1 = m.utc_minutes, m.utc_day, m.adr20, m.atr_h1_at
    london_open: dict[int, float] = {}
    out = []
    for i in range(m.n - 1):
        if mins[i] == 420:
            london_open[day[i]] = m.open[i]
        if mins[i] == 705 and day[i] in london_open and _ok(adr[i], ah1[i]):      # bar 11:45-12:00 closes at 12:00
            move = m.close[i] - london_open[day[i]]
            if abs(move) >= cfg["k"] * adr[i]:
                d = 1 if move > 0 else -1
                out.append(_sig(i, d, m.close[i] - d * ah1[i], None, 16, ah1[i]))
    return out


def london_exhaustion_fade(m: Market, cfg: dict[str, Any]) -> list[Signal]:
    """C5: a London move (07:00 -> 13:30 UTC) of at least k x the 20-day average range is faded at the New York
    open (13:30 UTC). Stop beyond the session extreme; natural target the session midpoint; exit 20:00 UTC."""
    mins, day, adr, ah1 = m.utc_minutes, m.utc_day, m.adr20, m.atr_h1_at
    out = []
    sess: dict[int, list] = {}
    for i in range(m.n - 1):
        d = day[i]
        if 420 <= mins[i] < 810:
            if mins[i] == 420:
                sess[d] = [m.open[i], m.high[i], m.low[i]]
            elif d in sess:
                sess[d][1], sess[d][2] = max(sess[d][1], m.high[i]), min(sess[d][2], m.low[i])
        if mins[i] == 795 and d in sess and _ok(adr[i], ah1[i]):                 # bar 13:15-13:30
            o, h, l = sess[d]
            move = m.close[i] - o
            if abs(move) >= cfg["k"] * adr[i]:
                dd = -1 if move > 0 else 1
                stop = h + 0.2 * ah1[i] if dd == -1 else l - 0.2 * ah1[i]
                out.append(_sig(i, dd, stop, (h + l) / 2, 26, ah1[i]))
    return out


# ----- D. price action -----------------------------------------------------------------------------------

def pdhl_break_retest(m: Market, cfg: dict[str, Any]) -> list[Signal]:
    """D1: a close beyond the previous day's high/low, then within N M15 bars a retest of the level that closes back
    on the break side: continuation. Stop below the retest low (above the high) - 0.1 ATR(H1)."""
    ph, pl, _ = m.prev_day
    atr, ah1, day = m.atr_m15, m.atr_h1_at, m.trading_day
    out, pending, used = [], {}, set()
    for i in range(m.n - 1):
        if not _ok(ph[i], pl[i], atr[i], ah1[i]):
            continue
        for side in (1, -1):
            key = (day[i], side)
            p = pending.get(key)
            level = ph[i] if side == 1 else pl[i]
            if p is None:
                if key not in used and side * (m.close[i] - level) > 0.1 * atr[i]:
                    pending[key] = i
                    used.add(key)
                continue
            if i - p > cfg["n"] or side * (m.close[i] - level) < -0.25 * ah1[i]:
                pending.pop(key)
                continue
            touched = (m.low[i] <= level + 0.1 * ah1[i]) if side == 1 else (m.high[i] >= level - 0.1 * ah1[i])
            if i > p and touched and side * (m.close[i] - level) > 0:
                stop = (m.low[i] - 0.1 * ah1[i]) if side == 1 else (m.high[i] + 0.1 * ah1[i])
                out.append(_sig(i, side, stop, None, 32, ah1[i]))
                pending.pop(key)
    return out


def pwhl_reaction(m: Market, cfg: dict[str, Any]) -> list[Signal]:
    """D2: reactions to the previous week's high/low on H1. mode 'fade': the H1 bar trades through the level and
    closes back inside; 'fade_wick': the same with a rejection wick >= 50% of the bar; 'continue': an H1 close
    beyond the level by > 0.25 ATR. Once per week and side."""
    wh, wl, _ = m.prev_week
    f = m.frame("H1")
    week = (m.trading_day - 1) // 7
    out, used = [], set()
    for k in range(20, len(f.close)):
        i = int(f.last_m15[k])
        if i >= m.n - 1 or not _ok(wh[i], wl[i], f.atr[k]):
            continue
        atr, o, h, l, c = f.atr[k], f.open[k], f.high[k], f.low[k], f.close[k]
        rng = max(h - l, 1e-12)
        for side, level in ((1, wh[i]), (-1, wl[i])):
            key = (week[i], side)
            if key in used:
                continue
            crossed = h > level if side == 1 else l < level
            if not crossed:
                continue
            if cfg["mode"] == "continue":
                if side * (c - level) > 0.25 * atr:
                    used.add(key)
                    out.append(_sig(i, side, c - side * 1.5 * atr, None, 480, atr))
            else:
                back = c < level if side == 1 else c > level
                wick = (h - max(o, c)) / rng if side == 1 else (min(o, c) - l) / rng
                if back and (cfg["mode"] == "fade" or wick >= 0.5):
                    used.add(key)
                    stop = h + 0.2 * atr if side == 1 else l - 0.2 * atr
                    out.append(_sig(i, -side, stop, None, 480, atr))
    return out


GENERATORS: dict[str, Callable[[Market, dict[str, Any]], list[Signal]]] = {
    "stop_hunt_pdhl": stop_hunt_pdhl, "failed_asian_breakout": failed_asian_breakout,
    "displacement_pullback": displacement_pullback, "anchored_mean_reversion": anchored_mean_reversion,
    "volatility_expansion": volatility_expansion, "tsmom": tsmom, "large_move": large_move,
    "opening_range_breakout": opening_range_breakout, "intraday_momentum": intraday_momentum,
    "london_compression_breakout": london_compression_breakout, "overlap_continuation": overlap_continuation,
    "london_exhaustion_fade": london_exhaustion_fade, "pdhl_break_retest": pdhl_break_retest,
    "pwhl_reaction": pwhl_reaction,
}
