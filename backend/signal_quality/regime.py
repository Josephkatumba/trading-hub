"""Causal market-regime classification from closed H1 bars (with H4 context).

Every input at H1 bar i uses bars 0..i only, so the regime known at a signal is the regime of the last
CLOSED H1 bar before the entry. Thresholds are fixed, round numbers chosen before any evaluation; the
research pipeline measures how strategies behave in each regime, it does not tune these cut-offs.

Regimes (first matching rule wins):
  HIGH_VOLATILITY  ATR(14) more than 1.5x its 200-bar median
  BREAKOUT         Bollinger width (20, 2) was in its lowest 20% of the last 200 bars within the last
                   10 bars, and the close is now outside the prior 20-bar high/low (compression release)
  REVERSAL         the H1 trend (EMA20 vs EMA50) flipped within the last 10 bars against the H4 trend
                   (EMA50 vs EMA200), i.e. a counter-trend turn is in progress
  TRENDING         ADX(14) >= 25 and the EMA50 moved >= 0.5 ATR over 10 bars
  LOW_VOLATILITY   ATR(14) below 0.75x its 200-bar median
  RANGING          everything else (ADX < 25 or a flat EMA50)
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

from strategy_bank import indicators as ind

REGIMES = ("TRENDING", "RANGING", "HIGH_VOLATILITY", "LOW_VOLATILITY", "BREAKOUT", "REVERSAL")
TREND_ADX = 25.0
RANGE_ADX = 20.0
HIGH_VOL = 1.5
LOW_VOL = 0.75
SQUEEZE_PCT = 0.20


def _median_prior(x: np.ndarray, period: int) -> np.ndarray:
    out = np.full_like(x, np.nan)
    for i in range(period, len(x)):
        w = x[i - period:i]
        w = w[w == w]
        if len(w):
            out[i] = float(np.median(w))
    return out


def arrays(ctx: Any, tf: str = "H1") -> dict[str, np.ndarray]:
    """Regime inputs for every bar of `tf`, cached on the strategy-bank Ctx."""
    key = (tf, "regime_arrays", ())
    if key in ctx._cache:
        return ctx._cache[key]
    a = ctx.a[tf]
    c = a["close"]
    atr = ctx.get(tf, "atr")
    adx, plus, minus = ctx.get(tf, "adx")
    e20, e50 = ctx.get(tf, "ema", 20), ctx.get(tf, "ema", 50)
    std = ctx.get(tf, "std", 20)
    width = 4 * std / np.where(e20 > 0, e20, np.nan)
    width_pct = ind.rolling_percentile(width, 200)
    out = {
        "atr": atr, "atr_ratio": atr / _median_prior(atr, 200), "adx": adx, "plus_di": plus, "minus_di": minus,
        "ema20": e20, "ema50": e50, "slope50": np.concatenate([np.full(10, np.nan), e50[10:] - e50[:-10]]) / atr,
        "width_pct": width_pct, "prior_high": ind.prior_max(a["high"], 20), "prior_low": ind.prior_min(a["low"], 20),
    }
    ctx._cache[key] = out
    return out


def _h4_trend(ctx: Any, at_utc: float) -> int:
    if "H4" not in ctx.a:
        return 0
    j = ctx.last_closed("H4", at_utc)
    if j < 200:
        return 0
    e50, e200 = ctx.get("H4", "ema", 50)[j], ctx.get("H4", "ema", 200)[j]
    return 1 if e50 > e200 else -1 if e50 < e200 else 0


def classify(ctx: Any, at_utc: float, tf: str = "H1") -> dict[str, Any]:
    """Regime of the last `tf` bar CLOSED by `at_utc`."""
    i = ctx.last_closed(tf, at_utc)
    if i < 210:
        return {"regime": "UNKNOWN", "trend": 0, "reason": "insufficient history"}
    r = arrays(ctx, tf)
    c = ctx.a[tf]["close"]
    val = lambda name, k=i: float(r[name][k])
    atr_ratio, adx, slope = val("atr_ratio"), val("adx"), val("slope50")
    trend = 1 if slope > 0 else -1 if slope < 0 else 0
    h4 = _h4_trend(ctx, at_utc)
    info = {"trend": trend, "h4_trend": h4, "adx": round(adx, 1) if math.isfinite(adx) else None,
            "atr_ratio": round(atr_ratio, 2) if math.isfinite(atr_ratio) else None,
            "bb_width_pct": round(val("width_pct"), 2) if math.isfinite(val("width_pct")) else None,
            "ema50_slope_atr": round(slope, 2) if math.isfinite(slope) else None}
    if math.isfinite(atr_ratio) and atr_ratio > HIGH_VOL:
        return {"regime": "HIGH_VOLATILITY", **info, "reason": f"ATR {atr_ratio:.2f}x its 200-bar median"}
    recent = r["width_pct"][max(0, i - 10):i + 1]
    squeezed = bool(np.nanmin(recent) < SQUEEZE_PCT) if np.isfinite(recent).any() else False
    if squeezed and (c[i] > val("prior_high") or c[i] < val("prior_low")):
        side = 1 if c[i] > val("prior_high") else -1
        return {"regime": "BREAKOUT", **info, "trend": side, "reason": "volatility compression released through the 20-bar range"}
    h1_now = np.sign(r["ema20"][i] - r["ema50"][i])
    h1_before = np.sign(r["ema20"][i - 10] - r["ema50"][i - 10])
    if h4 and h1_now != h1_before and h1_now == -h4:
        return {"regime": "REVERSAL", **info, "trend": int(h1_now), "reason": "H1 trend flipped against the H4 trend within 10 bars"}
    if math.isfinite(adx) and adx >= TREND_ADX and math.isfinite(slope) and abs(slope) >= 0.5:
        return {"regime": "TRENDING", **info, "reason": f"ADX {adx:.0f} with a sloping EMA50"}
    if math.isfinite(atr_ratio) and atr_ratio < LOW_VOL:
        return {"regime": "LOW_VOLATILITY", **info, "reason": f"ATR {atr_ratio:.2f}x its 200-bar median"}
    return {"regime": "RANGING", **info, "trend": 0, "reason": f"ADX {adx:.0f}" if math.isfinite(adx) else "no trend"}
