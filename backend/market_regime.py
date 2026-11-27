"""Market-regime classification (eight regimes) and strategy-family regime suitability.

Causal: the regime known at time t is the regime of the last H1 bar CLOSED by t, computed from bars
0..i only (the inputs are signal_quality.regime.arrays, which are causal). Thresholds are the fixed,
round values of signal_quality.regime (chosen before any evaluation); this module only splits that
classifier's TRENDING into a direction and separates a volatility squeeze that has not yet released
(COMPRESSION) from LOW_VOLATILITY. Nothing here is tuned to outcomes.

Regimes (first matching rule wins):
  HIGH_VOLATILITY   ATR(14) more than 1.5x its 200-bar median
  BREAKOUT          Bollinger width (20, 2) in its lowest 20% (of 200 bars) within the last 10 bars and
                    the close now outside the prior 20-bar range (compression released)
  REVERSAL          the H1 EMA20/EMA50 order flipped within 10 bars against the H4 EMA50/EMA200 trend
  STRONG_UPTREND    ADX(14) >= 25 and the EMA50 rose >= 0.5 ATR over 10 bars
  STRONG_DOWNTREND  ADX(14) >= 25 and the EMA50 fell >= 0.5 ATR over 10 bars
  COMPRESSION       Bollinger width in its lowest 20% now (squeeze, not released)
  LOW_VOLATILITY    ATR(14) below 0.75x its 200-bar median
  RANGING           everything else (no directional strength, normal volatility)

SUITABILITY maps each strategy methodology to the regimes its hypothesis is DESIGNED for. It is a
statement of design intent written from the strategy definitions, not a fit to results; the
participation report measures whether each strategy actually performs better inside them.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

REGIMES = ("STRONG_UPTREND", "STRONG_DOWNTREND", "RANGING", "HIGH_VOLATILITY", "LOW_VOLATILITY", "BREAKOUT",
           "COMPRESSION", "REVERSAL")
LABELS = {"STRONG_UPTREND": "Strong uptrend", "STRONG_DOWNTREND": "Strong downtrend", "RANGING": "Sideways / ranging",
          "HIGH_VOLATILITY": "High volatility", "LOW_VOLATILITY": "Low volatility", "BREAKOUT": "Breakout",
          "COMPRESSION": "Compression", "REVERSAL": "Reversal", "UNKNOWN": "Unknown"}
TREND_ADX, HIGH_VOL, LOW_VOL, SQUEEZE_PCT, SLOPE_ATR = 25.0, 1.5, 0.75, 0.20, 0.5
MIN_INDEX = 210

TRENDS = ("STRONG_UPTREND", "STRONG_DOWNTREND")
SUITABILITY: dict[str, tuple[str, ...]] = {
    "Trendlines": TRENDS + ("BREAKOUT",),
    "Support & Resistance": ("RANGING", "LOW_VOLATILITY", "REVERSAL"),
    "Breakouts": ("COMPRESSION", "BREAKOUT"),
    "Momentum": TRENDS + ("BREAKOUT",),
    "Mean Reversion": ("RANGING", "LOW_VOLATILITY"),
    "Smart Money Concepts": TRENDS + ("REVERSAL",),
    "Liquidity Sweeps": ("REVERSAL", "RANGING"),
    "Order Blocks": TRENDS,
    "Fair Value Gaps": TRENDS,
    "Trend Following": TRENDS,
    "Volatility Expansion": ("COMPRESSION", "BREAKOUT", "HIGH_VOLATILITY"),
    "Range Trading": ("RANGING", "LOW_VOLATILITY", "COMPRESSION"),
    "Market Structure": TRENDS + ("REVERSAL",),
    "Session-Based": ("BREAKOUT", "COMPRESSION", "HIGH_VOLATILITY"),
    "Price Action": ("RANGING", "REVERSAL"),
}


# Methodology taxonomy: primary family + the concepts each strategy uses. Written from the strategy
# definitions (docstrings / specs), not from results.
STRATEGY_FAMILY: dict[str, tuple[str, tuple[str, ...]]] = {
    "trendline_v5": ("Trendlines", ("Breakouts", "Price Action")),
    "trendline_break_retest": ("Trendlines", ("Breakouts",)),
    "trendline_bounce": ("Trendlines", ("Price Action",)),
    "support_resistance": ("Support & Resistance", ("Range Trading", "Price Action")),
    "trend_momentum": ("Trend Following", ("Momentum",)),
    "smc": ("Smart Money Concepts", ("Order Blocks", "Fair Value Gaps", "Market Structure", "Liquidity Sweeps")),
    "breakout": ("Breakouts", ()), "ema_crossover": ("Trend Following", ()), "ema_pullback": ("Trend Following", ()),
    "rsi_divergence": ("Mean Reversion", ("Momentum",)), "macd_momentum": ("Momentum", ()),
    "bollinger_reversion": ("Mean Reversion", ("Range Trading",)), "donchian": ("Breakouts", ("Trend Following",)),
    "london_breakout": ("Session-Based", ("Breakouts",)), "opening_range_breakout": ("Session-Based", ("Breakouts",)),
    "vwap_reversion": ("Mean Reversion", ()), "liquidity_sweep": ("Liquidity Sweeps", ()),
    "fair_value_gap": ("Fair Value Gaps", ()), "order_block_retest": ("Order Blocks", ()),
    "market_structure_break": ("Market Structure", ()), "inside_bar_breakout": ("Price Action", ("Breakouts",)),
    "atr_breakout": ("Volatility Expansion", ("Breakouts",)), "ichimoku": ("Trend Following", ()),
    "ict_sweep_reversal": ("Liquidity Sweeps", ("Smart Money Concepts",)),
    "ict_mss": ("Market Structure", ("Smart Money Concepts",)),
    "ict_fvg_continuation": ("Fair Value Gaps", ("Smart Money Concepts",)),
    "ict_ob_reversal": ("Order Blocks", ("Smart Money Concepts",)), "ict_ote": ("Smart Money Concepts", ("Trend Following",)),
    "ict_silver_bullet": ("Session-Based", ("Smart Money Concepts", "Fair Value Gaps")),
    "ict_judas": ("Session-Based", ("Liquidity Sweeps",)), "ict_sweep_fvg": ("Liquidity Sweeps", ("Fair Value Gaps",)),
    "breakout_v2": ("Breakouts", ()), "trend_pullback_v2": ("Trend Following", ()), "momentum_v2": ("Momentum", ()),
    "divergence_v2": ("Mean Reversion", ()), "orb_v2": ("Session-Based", ("Breakouts",)),
    "crypto_trend_v2": ("Trend Following", ()),
}


def family_of(key: str) -> str:
    return STRATEGY_FAMILY.get(key, ("Other", ()))[0]


def tag(ctx: Any, key: str, at_utc: float) -> dict[str, Any]:
    """Regime context recorded with a live signal: the regime at confirmation and whether the strategy's
    methodology is designed for it. Informational only: it never blocks or alters a signal."""
    regime = classify(ctx, at_utc)
    family = family_of(key)
    return {"regime": regime, "label": LABELS.get(regime, regime), "family": family,
            "designed_for": list(SUITABILITY.get(family, ())), "in_design_regime": suitable(family, regime)}


def label_array(ctx: Any, tf: str = "H1") -> np.ndarray:
    """Regime label for every bar of `tf` (object array; UNKNOWN before MIN_INDEX). Cached on ctx."""
    key = (tf, "market_regime_labels", ())
    if key in ctx._cache:
        return ctx._cache[key]
    from signal_quality import regime as base
    r = base.arrays(ctx, tf)
    c = ctx.a[tf]["close"]
    n = len(c)
    out = np.full(n, "UNKNOWN", dtype=object)
    h4 = None
    if "H4" in ctx.a and len(ctx.a["H4"]["close"]) > 200:
        h4 = np.sign(ctx.get("H4", "ema", 50) - ctx.get("H4", "ema", 200))
    for i in range(MIN_INDEX, n):
        out[i] = _label(r, c, i, _h4_at(ctx, h4, tf, i))
    ctx._cache[key] = out
    return out


def _h4_at(ctx: Any, h4: np.ndarray | None, tf: str, i: int) -> int:
    if h4 is None:
        return 0
    j = ctx.last_closed("H4", ctx.close_utc(tf, i))
    if j < 200:
        return 0
    v = h4[j]
    return int(v) if v == v else 0


def _label(r: dict[str, np.ndarray], c: np.ndarray, i: int, h4: int) -> str:
    def val(name: str, k: int = i) -> float:
        return float(r[name][k])
    atr_ratio, adx, slope, width = val("atr_ratio"), val("adx"), val("slope50"), val("width_pct")
    if math.isfinite(atr_ratio) and atr_ratio > HIGH_VOL:
        return "HIGH_VOLATILITY"
    recent = r["width_pct"][max(0, i - 10):i + 1]
    squeezed = bool(np.nanmin(recent) < SQUEEZE_PCT) if np.isfinite(recent).any() else False
    if squeezed and (c[i] > val("prior_high") or c[i] < val("prior_low")):
        return "BREAKOUT"
    h1_now = np.sign(r["ema20"][i] - r["ema50"][i])
    h1_before = np.sign(r["ema20"][i - 10] - r["ema50"][i - 10])
    if h4 and h1_now != h1_before and h1_now == -h4:
        return "REVERSAL"
    if math.isfinite(adx) and adx >= TREND_ADX and math.isfinite(slope) and abs(slope) >= SLOPE_ATR:
        return "STRONG_UPTREND" if slope > 0 else "STRONG_DOWNTREND"
    if math.isfinite(width) and width < SQUEEZE_PCT:
        return "COMPRESSION"
    if math.isfinite(atr_ratio) and atr_ratio < LOW_VOL:
        return "LOW_VOLATILITY"
    return "RANGING"


def classify(ctx: Any, at_utc: float, tf: str = "H1") -> str:
    """Regime of the last `tf` bar closed by `at_utc` (UNKNOWN without enough history)."""
    i = ctx.last_closed(tf, at_utc)
    if i < MIN_INDEX:
        return "UNKNOWN"
    return str(label_array(ctx, tf)[i])


def suitable(family: str, regime: str) -> bool:
    return regime in SUITABILITY.get(family, ())
