"""Indicator math shared (by specification) with the C# cBot.

Every formula here has a line-for-line twin in cbot/TradeDenScalper.cs
(class `Ind`). Both seed recursive averages with the first value so the two
implementations agree once ~200 bars of warm-up have passed.
"""
from __future__ import annotations

import numpy as np


def ema(values: np.ndarray, period: int) -> np.ndarray:
    alpha = 2.0 / (period + 1.0)
    out = np.empty(len(values), dtype=float)
    if len(values) == 0:
        return out
    acc = float(values[0])
    for i, v in enumerate(values):
        acc = acc + alpha * (float(v) - acc) if i else acc
        out[i] = acc
    return out


def wilder(values: np.ndarray, period: int) -> np.ndarray:
    alpha = 1.0 / period
    out = np.empty(len(values), dtype=float)
    if len(values) == 0:
        return out
    acc = float(values[0])
    for i, v in enumerate(values):
        acc = acc + alpha * (float(v) - acc) if i else acc
        out[i] = acc
    return out


def rsi(close: np.ndarray, period: int = 14) -> np.ndarray:
    diff = np.diff(close, prepend=close[0])
    gain = wilder(np.clip(diff, 0, None), period)
    loss = wilder(np.clip(-diff, 0, None), period)
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = np.where(loss > 0, gain / loss, np.inf)
    out = 100.0 - 100.0 / (1.0 + rs)
    out[(gain == 0) & (loss == 0)] = 50.0
    return out


def true_range(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
    prev = np.concatenate([[close[0]], close[:-1]])
    return np.maximum(high - low, np.maximum(np.abs(high - prev), np.abs(low - prev)))


def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    return wilder(true_range(high, low, close), period)
