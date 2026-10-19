"""Causal indicator arrays for the Strategy Bank.

Every function maps an array of CLOSED bars to an array where element i depends only on bars 0..i
(swing points are reported at the bar where they become known, k bars after the pivot). The same
functions serve the live scanner (a recent window) and historical tests (the full history), so a
strategy decides identically in both.
"""
from __future__ import annotations

from typing import Any, Sequence

import numpy as np


def arrays(bars: Sequence[dict[str, Any]]) -> dict[str, np.ndarray]:
    return {k: np.array([float(b[k]) for b in bars]) for k in ("open", "high", "low", "close")} | {
        "utc": np.array([float(b["utc"]) for b in bars]),
        "volume": np.array([float(b.get("tick_volume", 0) or 0) for b in bars])}


def ema(x: np.ndarray, period: int) -> np.ndarray:
    out = np.empty_like(x)
    if not len(x):
        return out
    k = 2 / (period + 1)
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = out[i - 1] + k * (x[i] - out[i - 1])
    return out


def sma(x: np.ndarray, period: int) -> np.ndarray:
    out = np.full_like(x, np.nan)
    if len(x) >= period:
        c = np.cumsum(np.insert(x, 0, 0.0))
        out[period - 1:] = (c[period:] - c[:-period]) / period
    return out


def true_range(h: np.ndarray, l: np.ndarray, c: np.ndarray) -> np.ndarray:
    prev = np.concatenate([[c[0]], c[:-1]])
    return np.maximum(h - l, np.maximum(np.abs(h - prev), np.abs(l - prev)))


def atr(h: np.ndarray, l: np.ndarray, c: np.ndarray, period: int = 14) -> np.ndarray:
    """Wilder ATR; NaN until `period` bars exist."""
    tr = true_range(h, l, c)
    out = np.full_like(tr, np.nan)
    if len(tr) > period:
        out[period] = tr[1:period + 1].mean()
        for i in range(period + 1, len(tr)):
            out[i] = (out[i - 1] * (period - 1) + tr[i]) / period
    return out


def rsi(c: np.ndarray, period: int = 14) -> np.ndarray:
    out = np.full_like(c, np.nan)
    if len(c) <= period:
        return out
    d = np.diff(c)
    gain, loss = np.maximum(d, 0), np.maximum(-d, 0)
    g, l = gain[:period].mean(), loss[:period].mean()
    out[period] = 100.0 if l == 0 else 100 - 100 / (1 + g / l)
    for i in range(period + 1, len(c)):
        g = (g * (period - 1) + gain[i - 1]) / period
        l = (l * (period - 1) + loss[i - 1]) / period
        out[i] = 100.0 if l == 0 else 100 - 100 / (1 + g / l)
    return out


def macd(c: np.ndarray, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[np.ndarray, np.ndarray]:
    line = ema(c, fast) - ema(c, slow)
    return line, ema(line, signal)


def rolling_std(x: np.ndarray, period: int) -> np.ndarray:
    out = np.full_like(x, np.nan)
    for i in range(period - 1, len(x)):
        out[i] = x[i - period + 1:i + 1].std()
    return out


def prior_max(x: np.ndarray, period: int) -> np.ndarray:
    """Max of the `period` bars BEFORE i (excludes bar i)."""
    out = np.full_like(x, np.nan)
    for i in range(period, len(x)):
        out[i] = x[i - period:i].max()
    return out


def prior_min(x: np.ndarray, period: int) -> np.ndarray:
    out = np.full_like(x, np.nan)
    for i in range(period, len(x)):
        out[i] = x[i - period:i].min()
    return out


def ichimoku(h: np.ndarray, l: np.ndarray, tenkan: int = 9, kijun: int = 26, senkou: int = 52,
             shift: int = 26) -> dict[str, np.ndarray]:
    """Tenkan, Kijun and the cloud AS IT STANDS at bar i (spans computed at i - shift, i.e. causal)."""
    def mid(period):
        out = np.full_like(h, np.nan)
        for i in range(period - 1, len(h)):
            out[i] = (h[i - period + 1:i + 1].max() + l[i - period + 1:i + 1].min()) / 2
        return out
    t, k, b = mid(tenkan), mid(kijun), mid(senkou)
    a = (t + k) / 2
    span_a, span_b = np.full_like(h, np.nan), np.full_like(h, np.nan)
    span_a[shift:], span_b[shift:] = a[:-shift], b[:-shift]
    return {"tenkan": t, "kijun": k, "span_a": span_a, "span_b": span_b}


def swings(h: np.ndarray, l: np.ndarray, k: int = 3) -> tuple[np.ndarray, np.ndarray]:
    """known_high[i] / known_low[i]: the most recent swing high / low CONFIRMED by bar i (a pivot at
    j is confirmed at j + k, when k bars on each side are lower / higher). Also returns the pivot
    index via `swing_points`."""
    hi, lo = np.full_like(h, np.nan), np.full_like(l, np.nan)
    last_h = last_l = np.nan
    for i in range(len(h)):
        j = i - k
        if j >= k:
            if h[j] > h[j - k:j].max() and h[j] >= h[j + 1:i + 1].max():
                last_h = h[j]
            if l[j] < l[j - k:j].min() and l[j] <= l[j + 1:i + 1].min():
                last_l = l[j]
        hi[i], lo[i] = last_h, last_l
    return hi, lo


def swing_points(h: np.ndarray, l: np.ndarray, k: int = 3) -> tuple[list[tuple[int, int, float]], list[tuple[int, int, float]]]:
    """[(pivot index, confirmation index, price)] for swing highs and lows, in confirmation order."""
    highs, lows = [], []
    for i in range(2 * k, len(h)):
        j = i - k
        if h[j] > h[j - k:j].max() and h[j] >= h[j + 1:i + 1].max():
            highs.append((j, i, float(h[j])))
        if l[j] < l[j - k:j].min() and l[j] <= l[j + 1:i + 1].min():
            lows.append((j, i, float(l[j])))
    return highs, lows
