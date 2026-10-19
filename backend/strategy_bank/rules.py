"""Strategy Bank strategies: objective specifications and decide() functions (no fixed number).

A decide(ctx, i) function looks only at bars <= i of the context's CLOSED bars (bar i is the candle
that has just closed) and returns at most one Decision. Entry happens after the close: live at the
current quote, historically at the next bar's open. Stops are absolute prices or ATR distances from
the entry; targets an absolute price or an R multiple. Every threshold below is a number, not a
judgement. All strategies are EXPERIMENTAL: implementing a rule correctly says nothing about whether
it is profitable (see the historical results in data/strategy_bank/historical.json).

ATR = Wilder ATR(14) of the strategy's timeframe; EMAn = exponential moving average of closes.
"""
from __future__ import annotations

import bisect
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import cached_property
from typing import Any, Callable
from zoneinfo import ZoneInfo

import numpy as np

from strategy_bank import indicators as ind

TF_SECONDS = {"M15": 900, "H1": 3600, "H4": 14400, "D1": 86400}
FX = ("EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD", "EURJPY", "GBPJPY")
METALS = ("XAUUSD", "XAGUSD")
INDICES = ("NAS100", "US500", "GER40")
CRYPTO = ("BTCUSD", "ETHUSD")
ALL = FX + METALS + INDICES + CRYPTO
NEW_YORK, FRANKFURT = ZoneInfo("America/New_York"), ZoneInfo("Europe/Berlin")


@dataclass
class Decision:
    direction: str                       # LONG / SHORT
    stop: float | None = None            # absolute stop price, or
    stop_atr: float | None = None        # stop distance from the entry in ATR
    target: float | None = None          # absolute target price, or
    target_r: float | None = 2.0         # target as a multiple of the entry-stop risk
    evidence: dict[str, Any] = field(default_factory=dict)
    explanation: str = ""
    max_bars: int | None = None          # time exit in M15 bars (session strategies)


class Ctx:
    """Closed bars by timeframe for one symbol, with cached causal indicators."""

    def __init__(self, symbol: str, frames: dict[str, list[dict[str, Any]]]) -> None:
        self.symbol = symbol
        self.a = {tf: ind.arrays(bars) for tf, bars in frames.items() if bars}
        self._cache: dict[tuple, Any] = {}

    def get(self, tf: str, name: str, *args: Any) -> Any:
        key = (tf, name, args)
        if key not in self._cache:
            a = self.a[tf]
            h, l, c = a["high"], a["low"], a["close"]
            fn = {"atr": lambda: ind.atr(h, l, c, *(args or (14,))), "ema": lambda: ind.ema(c, *args),
                  "rsi": lambda: ind.rsi(c, *(args or (14,))), "macd": lambda: ind.macd(c),
                  "prior_max": lambda: ind.prior_max(h, *args), "prior_min": lambda: ind.prior_min(l, *args),
                  "ichimoku": lambda: ind.ichimoku(h, l), "swing_points": lambda: ind.swing_points(h, l, *(args or (3,))),
                  "swings": lambda: ind.swings(h, l, *(args or (3,)))}[name]
            self._cache[key] = fn()
        return self._cache[key]

    def close_utc(self, tf: str, i: int) -> float:
        return float(self.a[tf]["utc"][i]) + TF_SECONDS[tf]

    def last_closed(self, tf: str, at_utc: float) -> int:
        """Index of the last `tf` bar closed by `at_utc`, or -1."""
        closes = self._cache.setdefault((tf, "close_times"), self.a[tf]["utc"] + TF_SECONDS[tf])
        return int(np.searchsorted(closes, at_utc, side="right")) - 1


def _ok(*values: float) -> bool:
    return all(v is not None and math.isfinite(v) for v in values)


# ----- strategy decide functions --------------------------------------------------------------------

def breakout(ctx: Ctx, i: int, tf: str = "H1") -> Decision | None:
    a = ctx.a[tf]; c = a["close"]; atr = ctx.get(tf, "atr")[i]
    hi, lo = ctx.get(tf, "prior_max", 20)[i], ctx.get(tf, "prior_min", 20)[i]
    hi1, lo1 = ctx.get(tf, "prior_max", 20)[i - 1], ctx.get(tf, "prior_min", 20)[i - 1]
    if not _ok(atr, hi, lo, hi1, lo1) or hi - lo > 3 * atr:
        return None
    mid = (hi + lo) / 2
    for long in (True, False):
        beyond = c[i] > hi + 0.1 * atr if long else c[i] < lo - 0.1 * atr
        first = c[i - 1] <= hi1 if long else c[i - 1] >= lo1
        if beyond and first:
            return Decision("LONG" if long else "SHORT", stop=mid,
                            evidence={"range_high": hi, "range_low": lo, "range_atr": (hi - lo) / atr},
                            explanation=f"{tf} close broke the 20-bar range ({(hi - lo) / atr:.1f} ATR wide) by more than 0.1 ATR.")
    return None


def ema_crossover(ctx: Ctx, i: int, tf: str = "H1") -> Decision | None:
    c = ctx.a[tf]["close"]; e20, e50, e200 = ctx.get(tf, "ema", 20), ctx.get(tf, "ema", 50), ctx.get(tf, "ema", 200)
    if i < 200:
        return None
    if e20[i] > e50[i] and e20[i - 1] <= e50[i - 1] and c[i] > e200[i]:
        return Decision("LONG", stop_atr=1.5, explanation=f"EMA20 crossed above EMA50 on the {tf} close with price above EMA200.")
    if e20[i] < e50[i] and e20[i - 1] >= e50[i - 1] and c[i] < e200[i]:
        return Decision("SHORT", stop_atr=1.5, explanation=f"EMA20 crossed below EMA50 on the {tf} close with price below EMA200.")
    return None


def ema_pullback(ctx: Ctx, i: int, tf: str = "H1") -> Decision | None:
    a = ctx.a[tf]; o, h, l, c = a["open"], a["high"], a["low"], a["close"]
    e20, e50, e200 = ctx.get(tf, "ema", 20), ctx.get(tf, "ema", 50), ctx.get(tf, "ema", 200)
    atr = ctx.get(tf, "atr")[i]
    if i < 210 or not _ok(atr):
        return None
    if e50[i] > e200[i] and e50[i] > e50[i - 10] and l[i] <= e20[i] <= h[i] and c[i] > e20[i] and c[i] > o[i]:
        return Decision("LONG", stop=min(l[i], c[i] - 0.5 * atr) - 0.5 * atr,
                        explanation=f"Uptrend (EMA50 above EMA200 and rising); the {tf} candle tagged EMA20 and closed bullish above it.")
    if e50[i] < e200[i] and e50[i] < e50[i - 10] and l[i] <= e20[i] <= h[i] and c[i] < e20[i] and c[i] < o[i]:
        return Decision("SHORT", stop=max(h[i], c[i] + 0.5 * atr) + 0.5 * atr,
                        explanation=f"Downtrend (EMA50 below EMA200 and falling); the {tf} candle tagged EMA20 and closed bearish below it.")
    return None


def rsi_divergence(ctx: Ctx, i: int, tf: str = "H1") -> Decision | None:
    a = ctx.a[tf]; h, l, c = a["high"], a["low"], a["close"]
    rsi = ctx.get(tf, "rsi"); atr = ctx.get(tf, "atr")[i]
    highs, lows = ctx.get(tf, "swing_points")
    if not _ok(atr):
        return None
    for long, points in ((True, lows), (False, highs)):
        conf = ctx._cache.setdefault((tf, "conf_idx", long), [p[1] for p in points])
        k = bisect.bisect_right(conf, i) - 1          # swing points confirmed by bar i
        if k < 1:
            continue
        (j1, _, p1), (j2, c2, p2) = points[k - 1], points[k]
        if not (5 <= j2 - j1 <= 40 and i - c2 <= 10 and _ok(rsi[j1], rsi[j2])):
            continue
        trigger = h[j2] if long else l[j2]
        if long and p2 < p1 and rsi[j2] > rsi[j1] and rsi[j1] < 35 and c[i] > trigger and c[i - 1] <= trigger:
            return Decision("LONG", stop=p2 - 0.3 * atr, evidence={"rsi_1": rsi[j1], "rsi_2": rsi[j2]},
                            explanation=f"Price made a lower swing low while RSI(14) made a higher low ({rsi[j1]:.0f} -> {rsi[j2]:.0f}); the {tf} close broke the pivot candle's high.")
        if not long and p2 > p1 and rsi[j2] < rsi[j1] and rsi[j1] > 65 and c[i] < trigger and c[i - 1] >= trigger:
            return Decision("SHORT", stop=p2 + 0.3 * atr, evidence={"rsi_1": rsi[j1], "rsi_2": rsi[j2]},
                            explanation=f"Price made a higher swing high while RSI(14) made a lower high ({rsi[j1]:.0f} -> {rsi[j2]:.0f}); the {tf} close broke the pivot candle's low.")
    return None


def macd_momentum(ctx: Ctx, i: int, tf: str = "H1") -> Decision | None:
    c = ctx.a[tf]["close"]; line, sig = ctx.get(tf, "macd"); e50 = ctx.get(tf, "ema", 50)
    if i < 60:
        return None
    if line[i] > sig[i] and line[i - 1] <= sig[i - 1] and line[i] > 0 and c[i] > c[i - 1] and c[i] > e50[i]:
        return Decision("LONG", stop_atr=1.5, explanation=f"MACD crossed above its signal line above zero, with a higher {tf} close above EMA50.")
    if line[i] < sig[i] and line[i - 1] >= sig[i - 1] and line[i] < 0 and c[i] < c[i - 1] and c[i] < e50[i]:
        return Decision("SHORT", stop_atr=1.5, explanation=f"MACD crossed below its signal line below zero, with a lower {tf} close below EMA50.")
    return None


def bollinger_reversion(ctx: Ctx, i: int, tf: str = "H1", z: float = 2.5) -> Decision | None:
    """Identical to the researched candidate (research/v6.bollinger_reversion, research/adapter.py)."""
    a = ctx.a[tf]; h, l, c = a["high"], a["low"], a["close"]
    atr, e50 = ctx.get(tf, "atr")[i], ctx.get(tf, "ema", 50)
    if i < 60 or not _ok(atr) or abs(e50[i] - e50[i - 10]) > 0.3 * atr:
        return None
    window = c[i - 20:i]
    mean, sd = float(window.mean()), float(window.std())
    if not sd:
        return None
    for long in (True, False):
        outside = c[i - 1] < mean - z * sd if long else c[i - 1] > mean + z * sd
        back = c[i] > mean - z * sd if long else c[i] < mean + z * sd
        if outside and back:
            extreme = min(l[i - 1], l[i]) if long else max(h[i - 1], h[i])
            return Decision("LONG" if long else "SHORT", stop=extreme - atr if long else extreme + atr, target=mean, target_r=None,
                            evidence={"mean": mean, "sd": sd},
                            explanation=f"A {tf} close outside the {z}-sigma Bollinger band was followed by a close back inside, in a flat market; target the 20-bar mean.")
    return None


def donchian(ctx: Ctx, i: int, tf: str = "H1") -> Decision | None:
    c = ctx.a[tf]["close"]
    hi, lo = ctx.get(tf, "prior_max", 20), ctx.get(tf, "prior_min", 20)
    if not _ok(hi[i], lo[i], hi[i - 1], lo[i - 1]):
        return None
    if c[i] > hi[i] and c[i - 1] <= hi[i - 1]:
        return Decision("LONG", stop_atr=2.0, explanation=f"{tf} close above the 20-bar Donchian high.")
    if c[i] < lo[i] and c[i - 1] >= lo[i - 1]:
        return Decision("SHORT", stop_atr=2.0, explanation=f"{tf} close below the 20-bar Donchian low.")
    return None


def _day_start(utc: float) -> float:
    return utc - utc % 86400


def london_breakout(ctx: Ctx, i: int, tf: str = "M15") -> Decision | None:
    a = ctx.a[tf]; utc = a["utc"]; c = a["close"]
    open_t = utc[i]
    day = _day_start(open_t)
    if not (day + 7 * 3600 <= open_t < day + 11 * 3600):
        return None
    lo_idx = int(np.searchsorted(utc, day, side="left")); hi_idx = int(np.searchsorted(utc, day + 7 * 3600, side="left"))
    if hi_idx - lo_idx < 20:                                   # Asian session must be (mostly) present
        return None
    rng_h, rng_l = float(a["high"][lo_idx:hi_idx].max()), float(a["low"][lo_idx:hi_idx].min())
    j = ctx.last_closed("H1", ctx.close_utc(tf, i))
    atr = ctx.get("H1", "atr")[j] if j >= 0 else None
    if not _ok(atr):
        return None
    for long in (True, False):
        level = rng_h + 0.1 * atr if long else rng_l - 0.1 * atr
        beyond = (lambda x: x > level) if long else (lambda x: x < level)
        if beyond(c[i]) and not any(beyond(x) for x in c[hi_idx:i]):
            width = rng_h - rng_l
            stop = (rng_l if long else rng_h) if width <= 1.5 * atr else (rng_h + rng_l) / 2
            exit_bars = int((day + 16 * 3600 - (open_t + 900)) // 900)
            return Decision("LONG" if long else "SHORT", stop=stop, max_bars=max(1, exit_bars),
                            evidence={"asian_high": rng_h, "asian_low": rng_l},
                            explanation=f"First M15 close beyond the Asian-session range (00:00-07:00 UTC) after the London open; exit by 16:00 UTC.")
    return None


def opening_range_breakout(ctx: Ctx, i: int, tf: str = "M15") -> Decision | None:
    zone = {"NAS100": NEW_YORK, "US500": NEW_YORK, "GER40": FRANKFURT}.get(ctx.symbol)
    if zone is None:
        return None
    a = ctx.a[tf]; utc = a["utc"]; c = a["close"]
    local = datetime.fromtimestamp(utc[i], timezone.utc).astimezone(zone)
    (oh, om), (ch, cm) = ((9, 30), (16, 0)) if zone is NEW_YORK else ((9, 0), (17, 30))
    session_open = local.replace(hour=oh, minute=om, second=0, microsecond=0)
    minutes = (local - session_open).total_seconds() / 60
    if not (30 <= minutes < 150):
        return None
    start = session_open.timestamp()
    s, e = int(np.searchsorted(utc, start, side="left")), int(np.searchsorted(utc, start + 1800, side="left"))
    if e - s != 2:
        return None
    rng_h, rng_l = float(a["high"][s:e].max()), float(a["low"][s:e].min())
    for long in (True, False):
        beyond = (lambda x: x > rng_h) if long else (lambda x: x < rng_l)
        if beyond(c[i]) and not any(beyond(x) for x in c[e:i]):
            close_t = local.replace(hour=ch, minute=cm, second=0, microsecond=0).timestamp()
            return Decision("LONG" if long else "SHORT", stop=rng_l if long else rng_h,
                            max_bars=max(1, int((close_t - (utc[i] + 900)) // 900)),
                            evidence={"or_high": rng_h, "or_low": rng_l},
                            explanation="M15 close beyond the first 30 minutes' range of the cash session; exit at the session close.")
    return None


def vwap_reversion(ctx: Ctx, i: int, tf: str = "M15") -> Decision | None:
    """UNSUPPORTED: see SPECS[13]. Never produces a decision."""
    return None


def liquidity_sweep(ctx: Ctx, i: int, tf: str = "H1") -> Decision | None:
    a = ctx.a[tf]; o, h, l, c = a["open"], a["high"], a["low"], a["close"]
    atr = ctx.get(tf, "atr")[i]
    d = ctx.last_closed("D1", ctx.close_utc(tf, i) - 1)
    if d < 0 or not _ok(atr):
        return None
    pdh, pdl = float(ctx.a["D1"]["high"][d]), float(ctx.a["D1"]["low"][d])
    rng = h[i] - l[i]
    if rng < 0.8 * atr:
        return None
    if h[i] > pdh and c[i] < pdh and (h[i] - max(o[i], c[i])) >= 0.5 * rng:
        return Decision("SHORT", stop=h[i] + 0.2 * atr, evidence={"previous_day_high": pdh},
                        explanation=f"The {tf} candle swept the previous day's high and closed back below it with a rejection wick over half its range.")
    if l[i] < pdl and c[i] > pdl and (min(o[i], c[i]) - l[i]) >= 0.5 * rng:
        return Decision("LONG", stop=l[i] - 0.2 * atr, evidence={"previous_day_low": pdl},
                        explanation=f"The {tf} candle swept the previous day's low and closed back above it with a rejection wick over half its range.")
    return None


def fair_value_gap(ctx: Ctx, i: int, tf: str = "H1") -> Decision | None:
    a = ctx.a[tf]; o, h, l, c = a["open"], a["high"], a["low"], a["close"]
    atr = ctx.get(tf, "atr")[i]
    if not _ok(atr) or i < 35:
        return None
    for j in range(i - 3, i - 31, -1):                         # gap candles (j-2, j-1, j), j at least 3 bars old
        if l[j] > h[j - 2] and l[j] - h[j - 2] >= 0.3 * atr:       # bullish FVG
            bottom, top = h[j - 2], l[j]
            if c[j + 1:i].min() >= bottom and l[j + 1:i].min() > top and l[i] <= top and c[i] > top and c[i] > o[i]:
                return Decision("LONG", stop=bottom - 0.3 * atr, evidence={"gap_bottom": bottom, "gap_top": top},
                                explanation=f"Price returned into an unfilled bullish fair value gap ({(top - bottom) / atr:.1f} ATR) and the {tf} candle closed bullish above it.")
        if h[j] < l[j - 2] and l[j - 2] - h[j] >= 0.3 * atr:       # bearish FVG
            top, bottom = l[j - 2], h[j]
            if c[j + 1:i].max() <= top and h[j + 1:i].max() < bottom and h[i] >= bottom and c[i] < bottom and c[i] < o[i]:
                return Decision("SHORT", stop=top + 0.3 * atr, evidence={"gap_bottom": bottom, "gap_top": top},
                                explanation=f"Price returned into an unfilled bearish fair value gap ({(top - bottom) / atr:.1f} ATR) and the {tf} candle closed bearish below it.")
    return None


def order_block_retest(ctx: Ctx, i: int, tf: str = "H1") -> Decision | None:
    a = ctx.a[tf]; o, h, l, c = a["open"], a["high"], a["low"], a["close"]
    atr_arr = ctx.get(tf, "atr"); atr = atr_arr[i]
    known_hi, known_lo = ctx.get(tf, "swings")
    if not _ok(atr) or i < 50:
        return None
    for k in range(i - 3, i - 41, -1):
        ak = atr_arr[k]
        if not _ok(ak):
            continue
        for long in (True, False):
            if (c[k] >= o[k]) if long else (c[k] <= o[k]):        # OB candle: last opposite-colour candle
                continue
            for m in range(k + 1, min(k + 4, i - 1)):
                body = (c[m] - o[m]) if long else (o[m] - c[m])
                level = known_hi[k] if long else known_lo[k]
                if body >= ak and _ok(level) and ((c[m] > level) if long else (c[m] < level)):
                    zl, zh = l[k], h[k]
                    after = slice(m + 1, i)
                    touched_before = (l[after].min() <= zh) if long else (h[after].max() >= zl)
                    broken = (c[after].min() < zl) if long else (c[after].max() > zh)
                    if touched_before or broken:
                        break
                    touch = (l[i] <= zh and l[i] >= zl - 0.1 * atr) if long else (h[i] >= zl and h[i] <= zh + 0.1 * atr)
                    confirm = (c[i] > (zl + zh) / 2 and c[i] > o[i]) if long else (c[i] < (zl + zh) / 2 and c[i] < o[i])
                    if touch and confirm:
                        return Decision("LONG" if long else "SHORT", stop=zl - 0.2 * atr if long else zh + 0.2 * atr,
                                        evidence={"ob_low": zl, "ob_high": zh},
                                        explanation=f"First retest of the {tf} order block that launched a structure-breaking displacement; the candle closed {'bullish' if long else 'bearish'} beyond the block's midpoint.")
                    break
    return None


def market_structure_break(ctx: Ctx, i: int, tf: str = "H1") -> Decision | None:
    a = ctx.a[tf]; c = a["close"]; atr = ctx.get(tf, "atr")[i]
    highs, lows = ctx.get(tf, "swing_points")
    if not _ok(atr):
        return None
    hc = ctx._cache.setdefault((tf, "conf_idx", False), [p[1] for p in highs])
    lc = ctx._cache.setdefault((tf, "conf_idx", True), [p[1] for p in lows])
    kh, kl = bisect.bisect_right(hc, i - 1) - 1, bisect.bisect_right(lc, i - 1) - 1
    if kh < 1 or kl < 1:
        return None
    h1, h2 = highs[kh - 1][2], highs[kh][2]
    l1, l2 = lows[kl - 1][2], lows[kl][2]
    if h2 < h1 and l2 < l1 and c[i] > h2 + 0.1 * atr and c[i - 1] <= h2 + 0.1 * atr:
        stop = l2 - 0.2 * atr
        if c[i] - stop <= 3 * atr:
            return Decision("LONG", stop=stop, evidence={"broken_swing_high": h2},
                            explanation=f"In a bearish structure (lower highs and lows) the {tf} close broke the last swing high by 0.1 ATR (change of character).")
    if h2 > h1 and l2 > l1 and c[i] < l2 - 0.1 * atr and c[i - 1] >= l2 - 0.1 * atr:
        stop = h2 + 0.2 * atr
        if stop - c[i] <= 3 * atr:
            return Decision("SHORT", stop=stop, evidence={"broken_swing_low": l2},
                            explanation=f"In a bullish structure (higher highs and lows) the {tf} close broke the last swing low by 0.1 ATR (change of character).")
    return None


def inside_bar_breakout(ctx: Ctx, i: int, tf: str = "H1") -> Decision | None:
    a = ctx.a[tf]; h, l, c = a["high"], a["low"], a["close"]; atr = ctx.get(tf, "atr")[i]
    if i < 20 or not _ok(atr):
        return None
    mh, ml = h[i - 2], l[i - 2]
    if not (h[i - 1] <= mh and l[i - 1] >= ml and mh - ml >= 0.5 * atr):
        return None
    if c[i] > mh:
        return Decision("LONG", stop=ml, explanation=f"{tf} close above the mother candle after an inside bar.")
    if c[i] < ml:
        return Decision("SHORT", stop=mh, explanation=f"{tf} close below the mother candle after an inside bar.")
    return None


def atr_breakout(ctx: Ctx, i: int, tf: str = "H1") -> Decision | None:
    c = ctx.a[tf]["close"]; e20 = ctx.get(tf, "ema", 20); atr = ctx.get(tf, "atr")
    if not _ok(atr[i], atr[i - 1]):
        return None
    up, up1 = e20[i] + 2 * atr[i], e20[i - 1] + 2 * atr[i - 1]
    dn, dn1 = e20[i] - 2 * atr[i], e20[i - 1] - 2 * atr[i - 1]
    if c[i] > up and c[i - 1] <= up1:
        return Decision("LONG", stop_atr=1.5, explanation=f"{tf} close above the Keltner band (EMA20 + 2 ATR): a volatility-adjusted breakout.")
    if c[i] < dn and c[i - 1] >= dn1:
        return Decision("SHORT", stop_atr=1.5, explanation=f"{tf} close below the Keltner band (EMA20 - 2 ATR): a volatility-adjusted breakout.")
    return None


def ichimoku_trend(ctx: Ctx, i: int, tf: str = "H1") -> Decision | None:
    c = ctx.a[tf]["close"]; ich = ctx.get(tf, "ichimoku"); atr = ctx.get(tf, "atr")[i]
    if i < 80 or not _ok(atr):
        return None

    def state(k):
        top, bot = max(ich["span_a"][k], ich["span_b"][k]), min(ich["span_a"][k], ich["span_b"][k])
        if not _ok(top, bot, ich["tenkan"][k], ich["kijun"][k]):
            return None
        if c[k] > top and ich["tenkan"][k] > ich["kijun"][k] and c[k] > c[k - 26]:
            return "LONG"
        if c[k] < bot and ich["tenkan"][k] < ich["kijun"][k] and c[k] < c[k - 26]:
            return "SHORT"
        return None

    now, before = state(i), state(i - 1)
    if now and now != before:
        kijun = ich["kijun"][i]
        long = now == "LONG"
        stop = kijun - 0.5 * atr if long else kijun + 0.5 * atr
        dist = (c[i] - stop) if long else (stop - c[i])
        if dist < 0.5 * atr:
            stop = c[i] - 0.5 * atr if long else c[i] + 0.5 * atr
        if abs(c[i] - stop) > 3 * atr:
            return None
        return Decision(now, stop=stop, evidence={"kijun": kijun},
                        explanation=f"Ichimoku alignment on {tf}: price {'above' if long else 'below'} the cloud, Tenkan {'above' if long else 'below'} Kijun, and the lagging span confirming.")
    return None


# ----- specifications -------------------------------------------------------------------------------------

LINKED = "LINKED"          # produced by an existing production strategy; attributed, not re-implemented
EXPERIMENTAL = "EXPERIMENTAL"  # the T-034 bank strategies: scanned and (CEO-approved) alerting
RESEARCH = "RESEARCH"      # new strategies: scanned and recorded in shadow, NEVER alerted until promoted
UNSUPPORTED = "UNSUPPORTED"
SCANNED_STATUSES = (EXPERIMENTAL, RESEARCH)
REQUIRED_FIELDS = ("key", "name", "status", "timeframe", "instruments", "entry", "indicators", "confirmation",
                   "stop", "take_profit", "min_rr", "invalidation", "data")
COMMON_STOP_RULE = "Stop must sit on the loss side, 0.2-5 ATR from the entry."
COMMON_INVALIDATION = ("Not issued if the data is stale, the spread exceeds 25% of the risk, the entry quote is more "
                       "than 0.5 ATR from the confirming close, or the executable reward/risk is below the minimum.")

SPECS: list[dict[str, Any]] = [
    {"n": 1, "key": "trendline_break_retest", "name": "Trendline Break & Retest", "status": LINKED,
     "linked_to": {"strategy_id": "trendline_v5", "setup_type": "BREAK"}, "timeframe": "M15", "instruments": ALL,
     "entry": "Production trendline-first-v5.1 BREAK: a genuine close through the trendline, then within 12 closed M15 bars a retest to within 0.15 ATR of the broken line and a deterministic rejection candle closing on the break side.",
     "indicators": "Trendline from swing anchors, ATR(14), price-action candle classes (strategies/trendline.py, scanner.py)",
     "confirmation": "Production confirmation plus executable-price qualification (qualification.py).",
     "stop": "Production structural stop (M15 invalidation).", "take_profit": "H1 structural target (trade_planning.apply_plan).",
     "min_rr": 1.5, "invalidation": "Close more than 0.08 ATR back through the line before the retest confirms; production lifecycle invalidation.",
     "data": ["M15", "H1"]},
    {"n": 2, "key": "trendline_bounce", "name": "Trendline Bounce", "status": LINKED,
     "linked_to": {"strategy_id": "trendline_v5", "setup_type": "REVERSAL"}, "timeframe": "M15", "instruments": ALL,
     "entry": "Production trendline-first-v5.1 REVERSAL: rejection from a validated (multi-touch) trendline with a bullish/bearish rejection candle.",
     "indicators": "Trendline, ATR(14), candle classes, S/R proximity", "confirmation": "Production confirmation plus executable-price qualification.",
     "stop": "Beyond the trendline/rejection extreme (production).", "take_profit": "H1 structural target.", "min_rr": 1.5,
     "invalidation": "Close through the trendline (production lifecycle).", "data": ["M15", "H1"]},
    {"n": 3, "key": "support_resistance", "name": "Support & Resistance", "status": LINKED,
     "linked_to": {"strategy_id": "support_resistance"}, "timeframe": "M15", "instruments": ALL,
     "entry": "Production sr-levels-v2: rejection (or break-and-retest) at a multi-timeframe level with >= 3 reactions, confirmed by a closed M15 rejection candle and momentum.",
     "indicators": "Pivot-clustered levels on M15/H1/H4/D1, ATR(14), candle classes", "confirmation": "Production confirmation plus executable-price qualification.",
     "stop": "Beyond the rejection zone (production).", "take_profit": "Next S/R zone edge.", "min_rr": 1.5,
     "invalidation": "Close through the zone (production lifecycle).", "data": ["M15", "H1", "H4", "D1"]},
    {"n": 4, "key": "breakout", "name": "Breakout Trading", "status": EXPERIMENTAL, "decide": breakout, "timeframe": "H1", "instruments": ALL,
     "entry": "H1 close beyond the prior 20-bar high (low) by more than 0.1 ATR, the first such close, when that 20-bar range is no wider than 3 ATR (a defined consolidation).",
     "indicators": "20-bar high/low, ATR(14)", "confirmation": "Completed H1 close beyond the range edge + 0.1 ATR.",
     "stop": "Middle of the 20-bar range.", "take_profit": "2R.", "min_rr": 1.5, "invalidation": COMMON_INVALIDATION, "data": ["H1"]},
    {"n": 5, "key": "ema_crossover", "name": "EMA Crossover", "status": EXPERIMENTAL, "decide": ema_crossover, "timeframe": "H1", "instruments": ALL,
     "entry": "EMA20 crosses EMA50 on the H1 close; trend confirmation: close on the same side of EMA200.",
     "indicators": "EMA20, EMA50, EMA200, ATR(14)", "confirmation": "Cross on a completed H1 candle (EMA20 vs EMA50 sign change) and close vs EMA200.",
     "stop": "1.5 ATR from the entry.", "take_profit": "2R.", "min_rr": 1.5, "invalidation": COMMON_INVALIDATION, "data": ["H1"]},
    {"n": 6, "key": "ema_pullback", "name": "EMA Pullback", "status": EXPERIMENTAL, "decide": ema_pullback, "timeframe": "H1", "instruments": ALL,
     "entry": "Established trend: EMA50 above EMA200 and EMA50 higher than 10 bars ago (mirror for shorts). The H1 candle's range contains EMA20 and it closes bullish above EMA20.",
     "indicators": "EMA20, EMA50, EMA200, ATR(14)", "confirmation": "Completed H1 candle tagging EMA20 with a close in the trend direction.",
     "stop": "Below the candle low (or 0.5 ATR below the close, whichever is lower) minus 0.5 ATR.", "take_profit": "2R.", "min_rr": 1.5,
     "invalidation": COMMON_INVALIDATION, "data": ["H1"]},
    {"n": 7, "key": "rsi_divergence", "name": "RSI Divergence", "status": EXPERIMENTAL, "decide": rsi_divergence, "timeframe": "H1", "instruments": ALL,
     "entry": "Two consecutive confirmed swing lows (3-bar pivots) 5-40 bars apart: the second lower in price, higher in RSI(14), first RSI below 35. Structure confirmation: the first H1 close above the second pivot candle's high within 10 bars of the pivot's confirmation (mirror for bearish, RSI above 65).",
     "indicators": "RSI(14), 3-bar swing pivots, ATR(14)", "confirmation": "Close above the pivot candle high (structure break) after the divergence.",
     "stop": "0.3 ATR beyond the second swing extreme.", "take_profit": "2R.", "min_rr": 1.5, "invalidation": COMMON_INVALIDATION, "data": ["H1"]},
    {"n": 8, "key": "macd_momentum", "name": "MACD Momentum", "status": EXPERIMENTAL, "decide": macd_momentum, "timeframe": "H1", "instruments": ALL,
     "entry": "MACD(12,26,9) line crosses its signal line while the MACD line is above zero, with a higher H1 close than the previous close and the close above EMA50 (mirror for shorts).",
     "indicators": "MACD(12,26,9), EMA50, ATR(14)", "confirmation": "Completed H1 candle with all conditions.", "stop": "1.5 ATR.", "take_profit": "2R.",
     "min_rr": 1.5, "invalidation": COMMON_INVALIDATION, "data": ["H1"]},
    {"n": 9, "key": "bollinger_reversion", "name": "Bollinger Band Mean Reversion", "status": EXPERIMENTAL, "decide": bollinger_reversion,
     "timeframe": "H1", "instruments": ALL,
     "entry": "Quiet regime (|EMA50 now - 10 bars ago| <= 0.3 ATR); previous H1 close outside the 20-bar 2.5-sigma band, current close back inside.",
     "indicators": "20-bar mean/standard deviation of closes, EMA50, ATR(14)", "confirmation": "The re-entry close (reversal confirmation).",
     "stop": "1 ATR beyond the extreme of the two candles.", "take_profit": "The 20-bar mean.",
     "min_rr": 0.5, "invalidation": COMMON_INVALIDATION + " Mean-reversion targets are typically ~1R: its minimum is 0.5R by design (high win-rate profile).",
     "data": ["H1"]},
    {"n": 10, "key": "donchian", "name": "Donchian Channel Breakout", "status": EXPERIMENTAL, "decide": donchian, "timeframe": "H1", "instruments": ALL,
     "entry": "First H1 close above the prior 20-bar high (below the 20-bar low).", "indicators": "Donchian(20), ATR(14)",
     "confirmation": "Completed H1 close beyond the channel.", "stop": "2 ATR.", "take_profit": "2R.", "min_rr": 1.5,
     "invalidation": COMMON_INVALIDATION, "data": ["H1"]},
    {"n": 11, "key": "london_breakout", "name": "London Session Breakout", "status": EXPERIMENTAL, "decide": london_breakout,
     "timeframe": "M15", "instruments": FX + METALS + ("GER40",),
     "entry": "Asian range = M15 high/low 00:00-07:00 UTC. Between 07:00 and 11:00 UTC, the first M15 close beyond the range by more than 0.1 H1-ATR.",
     "indicators": "Session range, ATR(14) on H1", "confirmation": "Completed M15 close beyond the range edge.",
     "stop": "Opposite side of the range (range <= 1.5 ATR) or the range middle.", "take_profit": "2R; time exit 16:00 UTC.", "min_rr": 1.5,
     "invalidation": COMMON_INVALIDATION, "data": ["M15", "H1"]},
    {"n": 12, "key": "opening_range_breakout", "name": "Opening Range Breakout", "status": EXPERIMENTAL, "decide": opening_range_breakout,
     "timeframe": "M15", "instruments": INDICES,
     "entry": "Opening range = the first 30 minutes of the cash session (New York 09:30 for NAS100/US500, Frankfurt 09:00 for GER40, DST-aware). Break and hold: the first M15 close beyond it within two hours.",
     "indicators": "Opening range", "confirmation": "Completed M15 close beyond the opening range.",
     "stop": "Opposite side of the opening range.", "take_profit": "2R; time exit at the session close.", "min_rr": 1.5,
     "invalidation": COMMON_INVALIDATION, "data": ["M15"]},
    {"n": 13, "key": "vwap_reversion", "name": "VWAP Reversion", "status": UNSUPPORTED, "decide": vwap_reversion, "timeframe": "M15", "instruments": (),
     "entry": "Not implemented as a signal.", "indicators": "VWAP requires traded volume.",
     "confirmation": "n/a", "stop": "n/a", "take_profit": "n/a", "min_rr": None, "invalidation": "n/a", "data": ["traded_volume"],
     "unsupported_reason": ("MT5 supplies only tick_volume (a count of price updates from one broker's feed) for these CFDs, not traded volume. "
                            "A tick-volume VWAP is a different, broker-specific quantity that cannot be verified against the exchange VWAP "
                            "traders refer to, and for spot FX no consolidated volume exists at all. Rather than fabricate confirmations, "
                            "VWAP Reversion is UNSUPPORTED until a real volume source (e.g. exchange futures data) is connected.")},
    {"n": 14, "key": "liquidity_sweep", "name": "Liquidity Sweep", "status": EXPERIMENTAL, "decide": liquidity_sweep, "timeframe": "H1", "instruments": ALL,
     "entry": "An H1 candle trades beyond the previous day's high (low), closes back inside, with the rejection wick at least 50% of the candle's range and the range at least 0.8 ATR.",
     "indicators": "Previous D1 high/low, ATR(14)", "confirmation": "Completed H1 close back inside the prior day's range.",
     "stop": "0.2 ATR beyond the sweep extreme.", "take_profit": "2R.", "min_rr": 1.5, "invalidation": COMMON_INVALIDATION, "data": ["H1", "D1"]},
    {"n": 15, "key": "fair_value_gap", "name": "Fair Value Gap", "status": EXPERIMENTAL, "decide": fair_value_gap, "timeframe": "H1", "instruments": ALL,
     "entry": "Three-candle imbalance (bullish: candle 3 low above candle 1 high by at least 0.3 ATR), 3-30 bars old, never closed through. Price returns into it (low at or below the gap top) and the H1 candle closes bullish above the gap top (mirror for bearish).",
     "indicators": "FVG detection, ATR(14)", "confirmation": "Completed bullish (bearish) close back above (below) the gap after entering it.",
     "stop": "0.3 ATR beyond the far edge of the gap.", "take_profit": "2R.", "min_rr": 1.5, "invalidation": COMMON_INVALIDATION, "data": ["H1"]},
    {"n": 16, "key": "order_block_retest", "name": "Order Block Retest", "status": EXPERIMENTAL, "decide": order_block_retest, "timeframe": "H1", "instruments": ALL,
     "entry": "Order block = the last opposite-colour H1 candle before a displacement candle (body >= 1 ATR, within 3 bars) that closes beyond the last confirmed swing point. First retest: a later candle trades into the block (not more than 0.1 ATR through it) and closes beyond the block's midpoint in the displacement direction.",
     "indicators": "3-bar swing pivots, ATR(14)", "confirmation": "Completed candle closing beyond the block midpoint on the first retest; no prior touch or close through the block.",
     "stop": "0.2 ATR beyond the far side of the block.", "take_profit": "2R.", "min_rr": 1.5, "invalidation": COMMON_INVALIDATION, "data": ["H1"]},
    {"n": 17, "key": "market_structure_break", "name": "Market Structure Break", "status": EXPERIMENTAL, "decide": market_structure_break,
     "timeframe": "H1", "instruments": ALL,
     "entry": "Bearish structure (last two confirmed swing highs and lows descending), then the first H1 close more than 0.1 ATR above the last swing high (change of character). Mirror for shorts.",
     "indicators": "3-bar swing pivots, ATR(14)", "confirmation": "Completed close beyond the significant swing point.",
     "stop": "0.2 ATR beyond the last opposite swing; skipped if the stop is more than 3 ATR away.", "take_profit": "2R.", "min_rr": 1.5,
     "invalidation": COMMON_INVALIDATION, "data": ["H1"]},
    {"n": 18, "key": "inside_bar_breakout", "name": "Inside Bar Breakout", "status": EXPERIMENTAL, "decide": inside_bar_breakout, "timeframe": "H1", "instruments": ALL,
     "entry": "Candle i-1 inside the mother candle i-2 (mother range >= 0.5 ATR); candle i closes beyond the mother's high (low).",
     "indicators": "Mother/inside candle ranges, ATR(14)", "confirmation": "Completed close beyond the mother candle.",
     "stop": "Opposite side of the mother candle.", "take_profit": "2R.", "min_rr": 1.5, "invalidation": COMMON_INVALIDATION, "data": ["H1"]},
    {"n": 19, "key": "atr_breakout", "name": "ATR Volatility Breakout", "status": EXPERIMENTAL, "decide": atr_breakout, "timeframe": "H1", "instruments": ALL,
     "entry": "First H1 close above EMA20 + 2 x ATR(14) (below EMA20 - 2 ATR): a Keltner-channel breakout.",
     "indicators": "EMA20, ATR(14)", "confirmation": "Completed close beyond the volatility-adjusted threshold.", "stop": "1.5 ATR.",
     "take_profit": "2R.", "min_rr": 1.5, "invalidation": COMMON_INVALIDATION, "data": ["H1"]},
    {"n": 20, "key": "ichimoku", "name": "Ichimoku Trend Following", "status": EXPERIMENTAL, "decide": ichimoku_trend, "timeframe": "H1", "instruments": ALL,
     "entry": "First H1 close where all three hold: close above the cloud (as plotted at that bar, spans computed 26 bars earlier), Tenkan(9) above Kijun(26), and the close above the close 26 bars ago (lagging span). Mirror for shorts.",
     "indicators": "Ichimoku (9, 26, 52, shift 26), ATR(14)", "confirmation": "Completed close establishing the alignment.",
     "stop": "0.5 ATR beyond Kijun (at least 0.5 ATR from the close; skipped if more than 3 ATR).", "take_profit": "2R.", "min_rr": 1.5,
     "invalidation": COMMON_INVALIDATION, "data": ["H1"]},
]
BY_KEY = {s["key"]: s for s in SPECS}


def register(spec: dict[str, Any]) -> dict[str, Any]:
    """Add a strategy to the bank at runtime. There is no limit on the number of strategies: specs are
    validated, keys must be unique, and numbers are assigned in registration order (`n` is a display
    number, never an index). New strategies must enter as RESEARCH (or UNSUPPORTED); only an
    evidence-based promotion in strategy_bank.qualification makes a RESEARCH strategy alert."""
    missing = [f for f in REQUIRED_FIELDS if f not in spec]
    if missing:
        raise ValueError(f"strategy spec {spec.get('key')!r} lacks {missing}")
    if spec["key"] in BY_KEY:
        raise ValueError(f"strategy key {spec['key']!r} is already registered")
    if spec["status"] not in (RESEARCH, UNSUPPORTED):
        raise ValueError("new strategies are registered as RESEARCH (or UNSUPPORTED), never directly as alerting")
    if spec["status"] == RESEARCH and not callable(spec.get("decide")):
        raise ValueError(f"RESEARCH strategy {spec['key']!r} needs a decide() function")
    spec = {**spec, "n": max((s["n"] for s in SPECS), default=0) + 1}
    SPECS.append(spec)
    BY_KEY[spec["key"]] = spec
    return spec


def scanned() -> list[dict[str, Any]]:
    """Strategies the bank scanner runs itself: EXPERIMENTAL (alert-approved) and RESEARCH (shadow)."""
    return [s for s in SPECS if s["status"] in SCANNED_STATUSES and callable(s.get("decide"))]


def alerting(spec: dict[str, Any]) -> bool:
    """May this strategy's signals reach Telegram? EXPERIMENTAL strategies keep their T-034 approval;
    RESEARCH strategies only after an evidence-based promotion recorded in the qualification registry."""
    if spec["status"] == EXPERIMENTAL:
        return True
    if spec["status"] == RESEARCH:
        from strategy_bank import qualification
        return qualification.current_status(spec["key"]) == qualification.QUALIFIED
    return False


def load_expansion() -> list[str]:
    """Register the expansion strategies the qualification registry admits (idempotent)."""
    from strategy_bank import expansion
    return expansion.register_admitted()
