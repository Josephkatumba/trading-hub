"""The eight pre-registered entry models (rules fixed; only registry grid values vary).

Each generator returns Signals decided at bar CLOSES using causal features from data.load().
Hashed together with registry.py before any result was computed.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .engine import Signal

LDN_OPEN, LDN_CLOSE = 8 * 60, 16 * 60 + 30
NY_OPEN, NY_CLOSE = 9 * 60 + 30, 16 * 60
ACTIVE_FROM_LDN, ACTIVE_TO_NY = 7 * 60, 16 * 60     # entries between 07:00 London and 16:00 New York


def next_where(cond: np.ndarray) -> np.ndarray:
    """For each i, the smallest j > i with cond[j] (or n)."""
    n = len(cond)
    out = np.full(n, n)
    nxt = n
    for k in range(n - 1, -1, -1):
        out[k] = nxt
        if cond[k]:
            nxt = k
    return out


class Ctx:
    def __init__(self, df: pd.DataFrame):
        self.df = df
        self.o, self.h, self.l, self.c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
        self.atr = df["atr_prev"].to_numpy(float)
        self.adr = df["adr20"].to_numpy(float)
        self.ny = df["ny_min"].to_numpy()
        self.ldn = df["ldn_min"].to_numpy()
        self.tday = df["tday"].to_numpy()
        self.n = len(df)
        self.active = (self.ldn >= ACTIVE_FROM_LDN) & (self.ny < ACTIVE_TO_NY) & (self.ny >= 3 * 60)
        self.next_ny_close = next_where(self.ny == NY_CLOSE)
        self.next_ldn_close = next_where(self.ldn == LDN_CLOSE)
        self.next_asia_end = next_where(self.ldn == 7 * 60)
        self.new_day = np.r_[True, self.tday[1:] != self.tday[:-1]]

    def ok(self, i: int) -> bool:
        return self.atr[i] > 0 and self.adr[i] > 0


# ---------------------------------------------------------------- H1
def h1_msb_displacement(x: Ctx, disp_atr: float, target_r: float, htf_filter: bool) -> list[Signal]:
    sh, sl = x.df["last_swing_hi"].to_numpy(), x.df["last_swing_lo"].to_numpy()
    slope = x.df["h4_slope"].to_numpy()
    out = []
    for i in range(1, x.n):
        if not (x.active[i] and x.ok(i)):
            continue
        rng = x.h[i] - x.l[i]
        if rng < disp_atr * x.atr[i] or abs(x.c[i] - x.o[i]) < 0.6 * rng:
            continue
        pos = (x.c[i] - x.l[i]) / rng
        if x.c[i] > x.o[i] and pos >= 0.75 and x.c[i] > sh[i - 1] >= x.c[i - 1] and (not htf_filter or slope[i] > 0):
            out.append(Signal(i, 1, x.l[i] - 0.1 * x.atr[i], target_r=target_r, exit_idx=i + 33))
        elif x.c[i] < x.o[i] and pos <= 0.25 and x.c[i] < sl[i - 1] <= x.c[i - 1] and (not htf_filter or slope[i] < 0):
            out.append(Signal(i, -1, x.h[i] + 0.1 * x.atr[i], target_r=target_r, exit_idx=i + 33))
    return out


# ---------------------------------------------------------------- H2
def h2_sweep_reversal(x: Ctx, level: str, confirm_bars: int, target_r: float) -> list[Signal]:
    hi = x.df["prev_hi" if level == "prev_day" else "asia_hi"].to_numpy()
    lo = x.df["prev_lo" if level == "prev_day" else "asia_lo"].to_numpy()
    out = []
    used: set = set()
    pend = {1: None, -1: None}     # side of the trade -> (sweep bar, extreme)
    for i in range(1, x.n):
        if x.new_day[i]:
            pend = {1: None, -1: None}
        if not x.ok(i) or np.isnan(hi[i]):
            continue
        for side in (1, -1):
            lvl = lo[i] if side > 0 else hi[i]
            key = (x.tday[i], side)
            p = pend[side]
            if p is None:
                swept = (x.l[i] < lvl) if side > 0 else (x.h[i] > lvl)
                if swept and key not in used and x.active[i]:
                    pend[side] = p = (i, x.l[i] if side > 0 else x.h[i])
                    used.add(key)
                else:
                    continue
            s, ext = p
            ext = min(ext, x.l[i]) if side > 0 else max(ext, x.h[i])
            pend[side] = (s, ext)
            if i - s > confirm_bars:
                pend[side] = None
                continue
            back = (x.c[i] > lvl and x.c[i] > x.h[s]) if side > 0 else (x.c[i] < lvl and x.c[i] < x.l[s])
            if back and x.active[i]:
                stop = ext - side * 0.1 * x.atr[i]
                out.append(Signal(i, side, stop, target_r=target_r, exit_idx=min(x.next_ny_close[i], i + 33)))
                pend[side] = None
    return out


# ---------------------------------------------------------------- H3
def h3_opening_range(x: Ctx, session: str, range_min: int, exit: str) -> list[Signal]:
    clock = x.ldn if session == "london" else x.ny
    open_min = LDN_OPEN if session == "london" else NY_OPEN
    close_next = x.next_ldn_close if session == "london" else x.next_ny_close
    nbars = range_min // 15
    out = []
    i = 0
    while i < x.n:
        if clock[i] != open_min:
            i += 1
            continue
        end = i + nbars
        if end >= x.n or any(x.tday[k] != x.tday[i] for k in range(i, end)):
            i += 1
            continue
        rh, rl = x.h[i:end].max(), x.l[i:end].min()
        for k in range(end, min(end + 12, x.n)):
            if x.tday[k] != x.tday[i] or not x.ok(k):
                break
            side = 1 if x.c[k] > rh else (-1 if x.c[k] < rl else 0)
            if side:
                stop = rl if side > 0 else rh
                ex = close_next[k]
                out.append(Signal(k, side, stop, target_r=2.0 if exit == "2r" else None, exit_idx=ex))
                break
        i = end
    return out


# ---------------------------------------------------------------- H4
def h4_trend_day(x: Ctx, decision_ny: str, move_adr: float, exit: str) -> list[Signal]:
    hh, mm = map(int, decision_ny.split(":"))
    bar_open = hh * 60 + mm - 15                      # bar that CLOSES at the decision time
    dopen = x.df["day_open"].to_numpy()
    dhi, dlo = x.df["day_hi_sofar"].to_numpy(), x.df["day_lo_sofar"].to_numpy()
    out = []
    for i in np.flatnonzero(x.ny == bar_open):
        if not x.ok(i) or x.df["ny_wd"].iat[i] > 4:
            continue
        move = x.c[i] - dopen[i]
        rng = dhi[i] - dlo[i]
        if rng <= 0 or abs(move) < move_adr * x.adr[i]:
            continue
        pos = (x.c[i] - dlo[i]) / rng
        side = 1 if (move > 0 and pos >= 0.75) else (-1 if (move < 0 and pos <= 0.25) else 0)
        if side:
            out.append(Signal(int(i), side, x.c[i] - side * 0.5 * x.adr[i],
                              target_r=2.0 if exit == "2r" else None, exit_idx=int(x.next_ny_close[i])))
    return out


# ---------------------------------------------------------------- H5
def h5_compression_expansion(x: Ctx, box_width_adr: float, stop: str, target_r: float) -> list[Signal]:
    L = 16
    out = []
    for i in range(L + 1, x.n):
        if not (x.active[i] and x.ok(i)):
            continue
        bh, bl = x.h[i - L:i].max(), x.l[i - L:i].min()
        if bh - bl > box_width_adr * x.adr[i]:
            continue
        side = 1 if (x.c[i] > bh and x.c[i - 1] <= bh) else (-1 if (x.c[i] < bl and x.c[i - 1] >= bl) else 0)
        if not side:
            continue
        st = (bl if side > 0 else bh) if stop == "opposite" else (bh + bl) / 2
        out.append(Signal(i, side, st, target_r=target_r, exit_idx=i + 33))
    return out


# ---------------------------------------------------------------- H6
def h6_session_gold(x: Ctx, variant: str, stretch: float, exit: str) -> list[Signal]:
    out = []
    if variant == "ny_reverses_london":
        idx_open = {}
        for i in np.flatnonzero(x.ldn == LDN_OPEN):
            idx_open[x.tday[i]] = i
        for i in np.flatnonzero(x.ny == NY_OPEN - 15):        # bar closing 09:30 NY
            s = idx_open.get(x.tday[i])
            if s is None or s >= i or not x.ok(i):
                continue
            move = x.c[i] - x.o[s]
            if abs(move) < stretch * x.adr[i]:
                continue
            side = -1 if move > 0 else 1
            ext = x.h[s:i + 1].max() if side < 0 else x.l[s:i + 1].min()
            out.append(Signal(int(i), side, ext - side * 0.1 * x.atr[i],
                              target_r=2.0 if exit == "2r" else None, exit_idx=int(x.next_ny_close[i])))
    else:  # asia_fade: London 00:00-06:00, fade stretches from the session mean
        start, s_sum, s_n, done = None, 0.0, 0, set()
        for i in range(x.n):
            if x.ldn[i] == 0:
                start, s_sum, s_n = i, 0.0, 0
            if start is None or x.ldn[i] >= 6 * 60:
                continue
            s_sum += x.c[i]
            s_n += 1
            if s_n < 4 or not x.ok(i) or x.tday[i] in done:
                continue
            mean = s_sum / s_n
            dev = x.c[i] - mean
            if abs(dev) < stretch * 0.5 * x.adr[i]:
                continue
            side = -1 if dev > 0 else 1
            sg = Signal(i, side, x.c[i] - side * abs(dev), target=mean if exit == "time" else None,
                        target_r=2.0 if exit == "2r" else None, exit_idx=int(x.next_asia_end[i]))
            out.append(sg)
            done.add(x.tday[i])
    return out


# ---------------------------------------------------------------- H7
def h7_news_momentum(x: Ctx, shock_atr: float, confirm_bars: int, exit: str) -> list[Signal]:
    wd = x.df["ny_wd"].to_numpy()
    spread, med = x.df["spread_px"].to_numpy(), x.df["spread_med"].to_numpy()
    release = ((x.ny == 8 * 60 + 30) | (x.ny == 10 * 60) | ((x.ny == 14 * 60) & (wd == 2))) & (wd < 5)
    out = []
    for s in np.flatnonzero(release):
        if not x.ok(s) or s + confirm_bars >= x.n:
            continue
        rng = x.h[s] - x.l[s]
        if rng < shock_atr * x.atr[s] or x.c[s] == x.o[s]:
            continue
        side = 1 if x.c[s] > x.o[s] else -1
        mid = (x.h[s] + x.l[s]) / 2
        k = s + confirm_bars
        conf = all((x.c[j] - mid) * side > 0 for j in range(s + 1, k + 1)) and (x.c[k] - x.o[k]) * side > 0
        if not conf or x.tday[k] != x.tday[s]:
            continue
        if not (spread[k] <= 2 * med[k]):
            continue
        stop = mid - side * 0.25 * x.atr[s]
        out.append(Signal(int(k), side, stop, target_r=2.0 if exit == "2r" else None, exit_idx=int(k + 17)))
    return out


# ---------------------------------------------------------------- H8
def h8_failed_breakout(x: Ctx, level: str, window: int, target: str) -> list[Signal]:
    hi = x.df["prev_hi" if level == "prev_day" else "prev_whi"].to_numpy()
    lo = x.df["prev_lo" if level == "prev_day" else "prev_wlo"].to_numpy()
    out = []
    used: set = set()
    pend = {1: None, -1: None}   # trade side -> (breakout bar, extreme)
    for i in range(1, x.n):
        if not x.ok(i) or np.isnan(hi[i]):
            continue
        for side in (1, -1):        # side = direction of the FADE trade
            lvl = lo[i] if side > 0 else hi[i]
            p = pend[side]
            if p is not None and (i - p[0] > window or x.tday[i] != x.tday[p[0]]):
                pend[side] = p = None
            if p is None:
                broke = (lvl - x.c[i]) * side > 0.1 * x.atr[i]
                key = (x.tday[i], side)
                if broke and key not in used and x.active[i]:
                    pend[side] = (i, x.l[i] if side > 0 else x.h[i])
                    used.add(key)
                continue
            b, ext = p
            ext = min(ext, x.l[i]) if side > 0 else max(ext, x.h[i])
            pend[side] = (b, ext)
            if (x.c[i] - lvl) * side > 0.25 * x.atr[i] and x.active[i]:
                tgt = (hi[i] + lo[i]) / 2 if target == "level_mid" else None
                out.append(Signal(i, side, ext - side * 0.1 * x.atr[i], target=tgt,
                                  target_r=2.0 if target == "2r" else None, exit_idx=min(x.next_ny_close[i], i + 33)))
                pend[side] = None
    return out


GENERATORS = {
    "H1_msb_displacement": h1_msb_displacement,
    "H2_sweep_reversal": h2_sweep_reversal,
    "H3_opening_range": h3_opening_range,
    "H4_trend_day": h4_trend_day,
    "H5_compression_expansion": h5_compression_expansion,
    "H6_session_gold": h6_session_gold,
    "H7_news_momentum": h7_news_momentum,
    "H8_failed_breakout": h8_failed_breakout,
}
