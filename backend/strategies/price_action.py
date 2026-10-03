"""Deterministic candle confirmation at a level (shared by S/R v2, Trendline v5.1 and SMC).

A level touch is not a setup. A setup is confirmed only when the last CLOSED candle
shows that the level actually rejected price, by ANY ONE of three fixed patterns
(LONG described; SHORT is the exact mirror: highs for lows, bearish for bullish):

  wick_rejection : the confirming candle C itself reached the level and its
                   level-side wick (lower wick: min(open, close) - low) is at least
                   WICK_RATIO (50%) of C's range. Most of the candle was rejected.
  engulfing      : C is bullish, the previous candle P is bearish, C's body engulfs
                   P's body (C.open <= P.close and C.close >= P.open), and C or P
                   reached the level.
  close_away     : one of the TOUCH_WINDOW (2) candles before C reached the level and C
                   is bullish and closes above that touch candle's HIGH: price tested
                   the level, then closed beyond the whole test candle.

Every pattern also needs C to close on the trade side of the level (`closed_outside`).
Only one pattern is required; all three are reported. "Reached the level" is a
predicate supplied by the strategy (zone edge for S/R, the broken line for the
trendline retest, the order block for SMC), so the patterns are identical everywhere.

Parameters are round, conventional values chosen before looking at any outcome.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

WICK_RATIO = 0.5
TOUCH_WINDOW = 2
PATTERNS = ("wick_rejection", "engulfing", "close_away")


def _f(bar: Mapping[str, Any], key: str) -> float:
    return float(bar[key])


def confirm_rejection(closed: Sequence[Mapping[str, Any]], long: bool, touched: Callable[[int], bool],
                      closed_outside: Callable[[int], bool], earliest: int = 0) -> dict[str, Any]:
    """The candle confirmation for the last closed bar `closed[-1]`.

    touched(i)        -> whether closed[i] reached the level.
    closed_outside(i) -> whether closed[i] closed on the trade side of the level.
    earliest          -> no bar before this index may serve as the touch / engulfed bar
                         (e.g. the trendline break bar itself is not a retest).
    """
    patterns = {name: False for name in PATTERNS}
    c = len(closed) - 1
    if c < 1:
        return {"confirmed": False, "pattern": None, "patterns": patterns, "touch_index": None}
    bar, prev = closed[c], closed[c - 1]
    open_, high, low, close = (_f(bar, key) for key in ("open", "high", "low", "close"))
    span = high - low
    outside = closed_outside(c)
    with_trade = close > open_ if long else close < open_
    if span > 0 and outside and touched(c):
        wick = (min(open_, close) - low) if long else (high - max(open_, close))
        patterns["wick_rejection"] = wick >= WICK_RATIO * span
    p_open, p_close = _f(prev, "open"), _f(prev, "close")
    if outside and with_trade and c - 1 >= earliest:
        against = p_close < p_open if long else p_close > p_open
        engulfs = (open_ <= p_close and close >= p_open) if long else (open_ >= p_close and close <= p_open)
        patterns["engulfing"] = against and engulfs and (touched(c) or touched(c - 1))
    touch_index = None
    for i in range(c - 1, max(earliest, c - TOUCH_WINDOW) - 1, -1):
        if touched(i):
            touch_index = i
            break
    if outside and with_trade and touch_index is not None:
        extreme = _f(closed[touch_index], "high" if long else "low")
        patterns["close_away"] = close > extreme if long else close < extreme
    pattern = next((name for name in PATTERNS if patterns[name]), None)
    return {"confirmed": pattern is not None, "pattern": pattern, "patterns": patterns,
            "touch_index": touch_index if touch_index is not None else (c if touched(c) else None),
            "candle_time": bar.get("time")}
