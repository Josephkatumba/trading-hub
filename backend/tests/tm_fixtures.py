"""Synthetic multi-timeframe markets for the Trend / Momentum tests.

Every scenario is built from explicit, readable price paths (no randomness), one
per timeframe, on one clock: the forming H1 and H4 bars open at T0, the forming
M15 bar at T0 + 15 min (inside the forming H1 bar), the forming D1 bar at
midnight. A bearish scenario is the exact price mirror of the bullish one
(`mirror`), so LONG/SHORT symmetry is tested on identical geometry.
"""
from __future__ import annotations

from datetime import datetime, timezone

from strategies import MarketInput

T0 = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc).timestamp()
STEP = {"M15": 900, "H1": 3600, "H4": 14400, "D1": 86400}
FORMING_OPEN = {"M15": T0 + 900, "H1": T0, "H4": T0, "D1": T0 - 12 * 3600}
WICK = {"M15": 0.08, "H1": 0.25, "H4": 0.4, "D1": 0.8}
MIRROR_AXIS = 400.0


def tri(i: int, period: int) -> float:
    """Triangle wave in [-1, 1]."""
    phase = (i % period) / period
    return 4 * phase - 1 if phase < 0.5 else 3 - 4 * phase


def bars(timeframe: str, closes: list[float], wick: float | None = None) -> list[dict]:
    """OHLC bars from closes; the last bar is the forming one. The open is midway between the
    previous and the current close, so neighbouring bars never share an exact high/low
    (which would hide a strict fractal pivot in these perfectly regular paths)."""
    wick = WICK[timeframe] if wick is None else wick
    out = []
    for i, close in enumerate(closes):
        open_ = (closes[i - 1] + close) / 2 if i else close
        out.append({"time": FORMING_OPEN[timeframe] - STEP[timeframe] * (len(closes) - 1 - i), "open": open_,
                    "high": max(open_, close) + wick, "low": min(open_, close) - wick, "close": close, "tick_volume": 100})
    return out


def mirror(rows: list[dict]) -> list[dict]:
    return [{**row, "open": MIRROR_AXIS - row["open"], "close": MIRROR_AXIS - row["close"],
             "high": MIRROR_AXIS - row["low"], "low": MIRROR_AXIS - row["high"]} for row in rows]


def d1_path(trend: float = 0.3) -> list[float]:
    return [100 + trend * i + 0.6 * tri(i, 6) for i in range(120)]


def h4_path(trend: float = 0.25) -> list[float]:
    return [100 + trend * i + 2.0 * tri(i, 12) for i in range(120)]


def h1_path(*, impulse_step: float = 0.6, impulse_bars: int = 12, retracement: float = 0.45, pullback_bars: int = 6,
            choppy: bool = False, base_trend: float = 0.05, wiggle: float = 0.3, alternation: float = 0.2) -> list[float]:
    """Gentle H1 uptrend, an impulse leg, then a pullback retracing `retracement` of the
    impulse (measured the strategy's way: impulse high vs the low of the 30 bars before it)."""
    closes = [100 + base_trend * i + wiggle * tri(i, 8) for i in range(120)]
    for j in range(impulse_bars):
        step = (3.0 if j % 2 == 0 else -2.6) if choppy else impulse_step + (alternation if j % 2 == 0 else -alternation)
        closes.append(closes[-1] + step)
    wick = WICK["H1"]
    provisional = bars("H1", closes + [closes[-1]])[:-1]
    ih = max(range(len(provisional) - 30, len(provisional)), key=lambda i: (provisional[i]["high"], i))
    high = provisional[ih]["high"]
    low = min(row["low"] for row in provisional[max(0, ih - 30):ih])
    pullback_low = high - retracement * (high - low)
    start = closes[-1]
    end = pullback_low + wick
    for k in range(1, pullback_bars + 1):
        closes.append(start + (end - start) * k / pullback_bars)
    closes.append(closes[-1] + 0.05)                         # forming H1 bar
    return closes


def m15_path(pullback_close: float, *, trigger: bool = True, lift: float = 1.0) -> list[float]:
    """M15 drifting down into the pullback, then (optionally) a continuation bar."""
    closes = [pullback_close + 2.0 - 1.7 * i / 99 + 0.05 * tri(i, 4) for i in range(100)]
    closes.append(closes[-1] + (lift if trigger else -0.02))   # last closed bar: the trigger (or not)
    closes.append(closes[-1] + 0.01)                           # forming bar = current price
    return closes


def scenario(*, d1_trend: float = 0.3, h4_trend: float = 0.25, trigger: bool = True, lift: float = 1.0,
             bearish: bool = False, symbol: str = "TEST", **h1: object) -> MarketInput:
    h1_closes = h1_path(**h1)
    h1_bars = bars("H1", h1_closes)
    pullback_close = h1_bars[-2]["close"]
    frames = {"M15": bars("M15", m15_path(pullback_close, trigger=trigger, lift=lift)), "H1": h1_bars,
              "H4": bars("H4", h4_path(h4_trend)), "D1": bars("D1", d1_path(d1_trend))}
    if bearish:
        frames = {tf: mirror(rows) for tf, rows in frames.items()}
    return MarketInput(symbol, frames["M15"], higher_rows=frames["H1"], bars=frames)
