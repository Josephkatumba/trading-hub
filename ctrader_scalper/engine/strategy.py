"""Signal logic: M15 bias, M5 setups, M1 spike filter, quality score.

This module is the reference specification for the C# cBot. The cBot's
`Evaluate()` follows these steps in the same order with the same constants.

Decisions are made only on CLOSED bars: at the close of M5 bar i (time
open_i + 5 min) using the last M15 bar that has also closed by then.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

from .indicators import atr, ema, rsi
from .market import INSTRUMENTS, resample

SETUP_BREAKOUT_RETEST = "BRT"
SETUP_PULLBACK = "PB"


@dataclass(frozen=True)
class SignalConstants:
    """Fixed (not optimised) constants. Changing these is a new strategy version."""
    ema_fast: int = 9
    ema_mid: int = 21
    ema_slow: int = 50
    rsi_period: int = 14
    atr_period: int = 14
    m15_slope_bars: int = 3
    breakout_lookback: int = 24      # M5 bars (2 hours)
    breakout_margin_atr: float = 0.10
    retest_window: int = 6           # M5 bars a breakout stays valid for a retest
    retest_tolerance_atr: float = 0.25
    breakout_fail_atr: float = 0.30
    pullback_zone_atr: float = 0.15
    max_spread_atr: float = 0.15     # hard filter: spread / M5 ATR
    m1_spike_mult: float = 3.0       # hard filter: last M1 range vs M1 ATR
    atr_rank_window: int = 288       # one day of M5 bars


CONST = SignalConstants()


def session_blocked(ts: pd.Timestamp, crypto: bool) -> bool:
    minute = ts.hour * 60 + ts.minute
    dow = ts.dayofweek  # Monday=0
    if crypto:
        return dow == 4 and 20 * 60 + 30 <= minute < 22 * 60 + 30
    if 20 * 60 + 45 <= minute < 22 * 60 + 15:      # daily rollover / thin liquidity
        return True
    if dow == 4 and minute >= 20 * 60:              # Friday close
        return True
    if dow == 6 and minute < 23 * 60 + 30:          # Sunday open
        return True
    return dow == 5


def session_points(ts: pd.Timestamp) -> int:
    h = ts.hour
    if 12 <= h < 16:
        return 10
    if 7 <= h < 12 or 16 <= h < 20:
        return 7
    return 3


def session_name(ts: pd.Timestamp) -> str:
    h = ts.hour
    if 7 <= h < 12:
        return "london"
    if 12 <= h < 16:
        return "overlap"
    if 16 <= h < 21:
        return "newyork"
    return "asia"


def atr_rank(values: np.ndarray, window: int) -> np.ndarray:
    out = np.full(len(values), np.nan)
    if len(values) < window:
        return out
    win = sliding_window_view(values, window)
    out[window - 1:] = (win <= win[:, -1:]).sum(axis=1) / window
    return out


def build_frames(m1: pd.DataFrame) -> dict:
    c = CONST
    m5 = resample(m1, 5)
    m15 = resample(m1, 15)
    o, h, l, cl = (m5[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    m5["ema9"] = ema(cl, c.ema_fast)
    m5["ema21"] = ema(cl, c.ema_mid)
    m5["ema50"] = ema(cl, c.ema_slow)
    m5["rsi"] = rsi(cl, c.rsi_period)
    m5["atr"] = atr(h, l, cl, c.atr_period)
    m5["atr_rank"] = atr_rank(m5["atr"].to_numpy(), c.atr_rank_window)

    c15 = m15["close"].to_numpy(float)
    m15["ema50"] = ema(c15, c.ema_slow)
    m15["slope"] = m15["ema50"].diff(c.m15_slope_bars)
    # last M15 bar closed at or before each M5 close
    m15_close = (m15["time"] + pd.Timedelta(minutes=15)).to_numpy()
    m5_close = (m5["time"] + pd.Timedelta(minutes=5)).to_numpy()
    j = np.searchsorted(m15_close, m5_close, side="right") - 1
    valid = j >= c.ema_slow
    jj = np.clip(j, 0, len(m15) - 1)
    above = c15[jj] > m15["ema50"].to_numpy()[jj]
    slope = np.nan_to_num(m15["slope"].to_numpy()[jj])
    bias = np.where(above & (slope > 0), 1, np.where(~above & (slope < 0), -1, 0))
    m5["m15_bias"] = np.where(valid, bias, 0)

    a1 = atr(*(m1[k].to_numpy(float) for k in ("high", "low", "close")), c.atr_period)
    m1_rng = (m1["high"] - m1["low"]).to_numpy(float)
    last_m1 = np.searchsorted(m1["time"].to_numpy(), (m5["time"] + pd.Timedelta(minutes=4)).to_numpy(), side="right") - 1
    last_m1 = np.clip(last_m1, 0, len(m1) - 1)
    prev = np.clip(last_m1 - 1, 0, None)
    m5["m1_spike"] = m1_rng[last_m1] > c.m1_spike_mult * a1[prev]
    return {"m5": m5, "m15": m15}


def score_candidate(side: int, setup: str, row, ts: pd.Timestamp) -> tuple[int, dict]:
    comp = {}
    stacked = (row.ema21 - row.ema50) * side > 0
    comp["stack"] = 20 if stacked else 0
    r = row.rsi if side > 0 else 100 - row.rsi
    comp["rsi"] = 15 if 52 <= r <= 68 else (8 if 48 <= r <= 75 else 0)
    ar = row.atr_rank
    comp["atr_regime"] = 15 if 0.3 <= ar <= 0.9 else (7 if 0.15 <= ar <= 0.97 else 0)
    sa = row.spread_px / row.atr if row.atr > 0 else 1
    comp["spread"] = 15 if sa <= 0.05 else (8 if sa <= 0.10 else 0)
    rng = row.high - row.low
    body = abs(row.close - row.open)
    pos = (row.close - row.low) / rng if rng > 0 else 0.5
    pos = pos if side > 0 else 1 - pos
    good_body = rng > 0 and body / rng >= 0.5
    comp["candle"] = 15 if (good_body and pos >= 0.7) else (7 if pos >= 0.6 else 0)
    comp["session"] = session_points(ts)
    comp["setup"] = 10 if setup == SETUP_BREAKOUT_RETEST else 5
    return int(sum(comp.values())), comp


def generate_candidates(symbol: str, m1: pd.DataFrame) -> pd.DataFrame:
    """All raw setups that pass the hard (non-optimised) filters."""
    c = CONST
    inst = INSTRUMENTS[symbol]
    frames = build_frames(m1)
    m5 = frames["m5"]
    rows = list(m5.itertuples(index=False))
    pending = {1: None, -1: None}   # side -> (level, breakout_index)
    out = []
    warm = max(c.atr_rank_window, 3 * c.ema_slow)
    for i in range(warm, len(rows)):
        row = rows[i]
        ts = row.time + pd.Timedelta(minutes=5)       # decision time (bar close)
        a = row.atr
        if not a > 0:
            continue
        # --- breakout bookkeeping (runs regardless of filters so state stays honest)
        hh = max(r.high for r in rows[i - c.breakout_lookback:i])
        ll = min(r.low for r in rows[i - c.breakout_lookback:i])
        found = []
        for side in (1, -1):
            p = pending[side]
            if p is not None:
                level, b = p
                if i - b > c.retest_window or (level - row.close) * side > c.breakout_fail_atr * a:
                    pending[side] = None
                else:
                    touched = (row.low <= level + c.retest_tolerance_atr * a) if side > 0 else (row.high >= level - c.retest_tolerance_atr * a)
                    closed_beyond = (row.close - level) * side > 0 and (row.close - row.open) * side > 0
                    if touched and closed_beyond and i > b:
                        anchor = min(row.low, level) if side > 0 else max(row.high, level)
                        found.append((side, SETUP_BREAKOUT_RETEST, anchor))
                        pending[side] = None
            level_now = hh if side > 0 else ll
            if (row.close - level_now) * side > c.breakout_margin_atr * a:
                pending[side] = (level_now, i)
        # --- trend pullback
        for side in (1, -1):
            if (row.ema9 - row.ema21) * side <= 0:
                continue
            zone = (row.low <= row.ema21 + c.pullback_zone_atr * a) if side > 0 else (row.high >= row.ema21 - c.pullback_zone_atr * a)
            reclaim = (row.close - row.ema9) * side > 0 and (row.close - row.open) * side > 0
            r_now = row.rsi if side > 0 else 100 - row.rsi
            r_prev = rows[i - 1].rsi if side > 0 else 100 - rows[i - 1].rsi
            r_min = min((x.rsi if side > 0 else 100 - x.rsi) for x in rows[i - 4:i])
            if zone and reclaim and r_now > r_prev and 45 <= r_now <= 70 and r_min <= 52:
                win = rows[i - 3:i + 1]
                anchor = min(x.low for x in win) if side > 0 else max(x.high for x in win)
                found.append((side, SETUP_PULLBACK, anchor))
        if not found:
            continue
        # --- hard filters
        if session_blocked(ts, inst.crypto) or row.m1_spike or row.spread_px > c.max_spread_atr * a:
            continue
        for side, setup, anchor in found:
            if row.m15_bias != side or (row.ema9 - row.ema21) * side <= 0:
                continue
            score, comp = score_candidate(side, setup, row, ts)
            out.append({
                "symbol": symbol, "time": ts, "side": side, "setup": setup,
                "ref": row.close, "anchor": anchor, "atr": a, "spread": row.spread_px,
                "rsi": row.rsi, "score": score, "session": session_name(ts), **{f"s_{k}": v for k, v in comp.items()},
            })
    return pd.DataFrame(out)


def constants_dict() -> dict:
    return asdict(CONST)
