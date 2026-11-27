"""Causal per-instrument market arrays for edge research.

Everything is indexed on the M15 bar grid (the execution grid of research/simulate.py). A value at M15 bar i
uses only bars that CLOSED at or before bar i's close; a signal decided at the close of bar i is entered at
the open of bar i + 1 (BUY at the ask = open + recorded spread, SELL at the bid).

Higher timeframes (M30, H1, H4) are aggregated from M15 on fixed UTC buckets; a bucket exists only when it is
complete (no synthesised prices). Trading days roll at 17:00 New York (the FX/CFD convention), so previous-day
and previous-week levels match what broker charts show.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import cached_property
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np

from strategy_bank import indicators as ind

UTC = timezone.utc
NEW_YORK, LONDON, FRANKFURT = ZoneInfo("America/New_York"), ZoneInfo("Europe/London"), ZoneInfo("Europe/Berlin")
TF_MINUTES = {"M15": 15, "M30": 30, "H1": 60, "H4": 240}


@dataclass
class Frame:
    tf: str
    utc: np.ndarray          # bucket open
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    last_m15: np.ndarray     # index of the M15 bar that closes this bucket
    cache: dict = field(default_factory=dict)

    @property
    def atr(self) -> np.ndarray:
        if "atr" not in self.cache:
            self.cache["atr"] = ind.atr(self.high, self.low, self.close, 14)
        return self.cache["atr"]

    def ema(self, n: int) -> np.ndarray:
        key = ("ema", n)
        if key not in self.cache:
            self.cache[key] = ind.ema(self.close, n)
        return self.cache[key]

    @property
    def adx(self) -> np.ndarray:
        if "adx" not in self.cache:
            self.cache["adx"] = ind.adx(self.high, self.low, self.close, 14)[0]
        return self.cache["adx"]


class Market:
    def __init__(self, symbol: str, history: Any) -> None:
        self.symbol = symbol
        self.history = history
        bars = history.full["M15"]
        self.n = len(bars)
        self.utc = np.array([b["utc"] for b in bars], dtype=float)
        self.open = np.array([b["open"] for b in bars], dtype=float)
        self.high = np.array([b["high"] for b in bars], dtype=float)
        self.low = np.array([b["low"] for b in bars], dtype=float)
        self.close = np.array([b["close"] for b in bars], dtype=float)
        self.spread = np.array([b["spread"] for b in bars], dtype=float)
        self.volume = np.array([b.get("tick_volume", 0) for b in bars], dtype=float)
        self._frames: dict[str, Frame] = {}

    # ----- frames ------------------------------------------------------------------------------------
    def frame(self, tf: str) -> Frame:
        if tf in self._frames:
            return self._frames[tf]
        if tf == "M15":
            f = Frame("M15", self.utc, self.open, self.high, self.low, self.close, self.volume, np.arange(self.n))
        else:
            size = TF_MINUTES[tf] * 60
            per = TF_MINUTES[tf] // 15
            bucket = np.floor(self.utc / size).astype(np.int64)
            starts = np.flatnonzero(np.r_[True, bucket[1:] != bucket[:-1]])
            ends = np.r_[starts[1:], self.n]
            keep = (ends - starts) == per
            # a complete bucket: every M15 bar present and contiguous
            s, e = starts[keep], ends[keep]
            contiguous = (self.utc[e - 1] - self.utc[s]) == (per - 1) * 900
            s, e = s[contiguous], e[contiguous]
            f = Frame(tf, bucket[s].astype(float) * size, self.open[s],
                      np.array([self.high[a:b].max() for a, b in zip(s, e)]),
                      np.array([self.low[a:b].min() for a, b in zip(s, e)]), self.close[e - 1],
                      np.array([self.volume[a:b].sum() for a, b in zip(s, e)]), e - 1)
        self._frames[tf] = f
        return f

    def tf_index_at(self, tf: str, i: int) -> int:
        """Index of the last `tf` bucket closed at (or before) the close of M15 bar i, or -1."""
        f = self.frame(tf)
        return int(np.searchsorted(f.last_m15, i, side="right")) - 1

    @cached_property
    def atr_m15(self) -> np.ndarray:
        return self.frame("M15").atr

    @cached_property
    def atr_h1_at(self) -> np.ndarray:
        """ATR(14) of the last closed H1 bucket at each M15 close."""
        f = self.frame("H1")
        idx = np.searchsorted(f.last_m15, np.arange(self.n), side="right") - 1
        out = np.full(self.n, np.nan)
        ok = idx >= 0
        out[ok] = f.atr[idx[ok]]
        return out

    # ----- clocks --------------------------------------------------------------------------------------
    @cached_property
    def close_utc(self) -> np.ndarray:
        return self.utc + 900

    def local(self, tz: ZoneInfo) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """(minutes since local midnight of the bar OPEN, local date ordinal, weekday) per M15 bar."""
        key = ("local", str(tz))
        if key not in self._frames:
            mins, days, wd = np.empty(self.n, int), np.empty(self.n, int), np.empty(self.n, int)
            for k, t in enumerate(self.utc):
                d = datetime.fromtimestamp(t, UTC).astimezone(tz)
                mins[k], days[k], wd[k] = d.hour * 60 + d.minute, d.toordinal(), d.weekday()
            self._frames[key] = (mins, days, wd)        # type: ignore[assignment]
        return self._frames[key]                        # type: ignore[return-value]

    @cached_property
    def utc_minutes(self) -> np.ndarray:
        return ((self.utc % 86400) // 60).astype(int)

    @cached_property
    def utc_day(self) -> np.ndarray:
        return (self.utc // 86400).astype(int)

    @cached_property
    def trading_day(self) -> np.ndarray:
        """Trading-day id per M15 bar: days roll at 17:00 New York."""
        mins, days, _ = self.local(NEW_YORK)
        return days + (mins >= 17 * 60).astype(int)

    # ----- levels ------------------------------------------------------------------------------------
    def _period_levels(self, key: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Previous period high / low / close per M15 bar for a period id array (causal: only completed periods)."""
        starts = np.flatnonzero(np.r_[True, key[1:] != key[:-1]])
        ends = np.r_[starts[1:], self.n]
        ph, pl, pc = np.full(self.n, np.nan), np.full(self.n, np.nan), np.full(self.n, np.nan)
        for k in range(1, len(starts)):
            a, b = starts[k - 1], ends[k - 1]
            ph[starts[k]:ends[k]] = self.high[a:b].max()
            pl[starts[k]:ends[k]] = self.low[a:b].min()
            pc[starts[k]:ends[k]] = self.close[b - 1]
        return ph, pl, pc

    @cached_property
    def prev_day(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        return self._period_levels(self.trading_day)

    @cached_property
    def prev_week(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        # trading weeks roll with the Sunday 17:00 NY open: ordinal of the trading day shifted to Monday-based weeks
        td = self.trading_day
        return self._period_levels((td - 1) // 7)        # ordinal 1 = Monday 0001-01-01

    @cached_property
    def adr20(self) -> np.ndarray:
        """Average range of the previous 20 completed trading days, per M15 bar."""
        key = self.trading_day
        starts = np.flatnonzero(np.r_[True, key[1:] != key[:-1]])
        ends = np.r_[starts[1:], self.n]
        ranges = np.array([self.high[a:b].max() - self.low[a:b].min() for a, b in zip(starts, ends)])
        out = np.full(self.n, np.nan)
        for k in range(20, len(starts)):
            out[starts[k]:ends[k]] = ranges[k - 20:k].mean()
        return out

    def window_range(self, start_min: int, end_min: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """For each M15 bar, the high / low of today's UTC window [start_min, end_min) if that window has
        fully closed by the bar's close, else NaN; plus a flag of whether the bar is after the window."""
        key = ("window", start_min, end_min)
        if key in self._frames:
            return self._frames[key]                    # type: ignore[return-value]
        hi, lo = np.full(self.n, np.nan), np.full(self.n, np.nan)
        day, mins = self.utc_day, self.utc_minutes
        cur_day, h, l, count = None, -math.inf, math.inf, 0
        for k in range(self.n):
            if day[k] != cur_day:
                cur_day, h, l, count = day[k], -math.inf, math.inf, 0
            if start_min <= mins[k] < end_min:
                h, l, count = max(h, self.high[k]), min(l, self.low[k]), count + 1
            elif mins[k] >= end_min and count >= (end_min - start_min) // 15 * 0.8:
                hi[k], lo[k] = h, l
        self._frames[key] = (hi, lo, None)              # type: ignore[assignment]
        return hi, lo, None                             # type: ignore[return-value]
