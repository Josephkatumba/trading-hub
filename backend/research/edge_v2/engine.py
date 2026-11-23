"""Execution simulator and statistics for Edge Discovery V2.

Fill model on M15 bid bars (ask = bid + spread_px of that bar):
* decision at the close of bar i, market entry at the open of bar i+1
  (BUY at ask + slippage, SELL at bid - slippage); no entry across a gap > 30 min
  or into a blocked bar (rollover, scheduled-release bars, Friday close);
* stop checked on the closing side (bid for longs, ask for shorts); a gap
  through the stop fills at the bar open; slippage on stop fills;
* target is a limit (no slippage); stop and target in the same bar -> STOP;
* time exit at the open of the named bar (closing side, with slippage);
* commission = rate x notional on entry and exit.
R = net P&L per unit / (fill - stop) per unit. One position at a time.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .data import blocked_entry
from .registry import COSTS

MAX_HOLD = 96          # bars (24 h) safety cap
MIN_RISK_ATR = 0.5     # stops tighter than 0.5 x ATR(14) are rejected (cost blow-up)


@dataclass
class Signal:
    i: int                 # decision bar
    side: int              # +1 long, -1 short
    stop: float            # absolute price
    target: float | None = None
    target_r: float | None = None
    exit_idx: int | None = None   # time exit at the open of this bar


class Book:
    def __init__(self, df: pd.DataFrame):
        self.df = df
        self.o, self.h, self.l, self.c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
        self.s = df["spread_px"].to_numpy(float)
        self.atr = df["atr"].to_numpy(float)
        self.gap = df["next_gap_min"].to_numpy(float)
        self.blocked = blocked_entry(df)
        self.utc = df["utc"].to_numpy()
        self.n = len(df)


def simulate(book: Book, signals: list[Signal], cost_mult: float = 1.0, respect_block: bool = True) -> pd.DataFrame:
    slip = COSTS["slippage"] * cost_mult
    rate = COSTS["commission_rate"] * cost_mult
    extra_spread = (cost_mult - 1.0)
    rows = []
    busy_until = -1
    for sg in sorted(signals, key=lambda x: x.i):
        i = sg.i
        k = i + 1
        if i <= busy_until or k >= book.n or not (book.gap[i] <= 30):
            continue
        if respect_block and book.blocked[k]:
            continue
        if sg.exit_idx is not None and sg.exit_idx <= k:
            continue
        side = sg.side
        spread_k = book.s[k] * (1 + extra_spread)
        fill = book.o[k] + spread_k + slip if side > 0 else book.o[k] - slip
        risk = (fill - sg.stop) * side
        if not (risk >= MIN_RISK_ATR * book.atr[i]):
            continue
        target = sg.target if sg.target is not None else (fill + side * sg.target_r * risk if sg.target_r else None)
        if target is not None and (target - fill) * side <= 0:
            continue
        last = min(book.n - 1, k + MAX_HOLD, sg.exit_idx if sg.exit_idx is not None else k + MAX_HOLD)
        exit_px, reason, j_exit = None, "time", last
        for j in range(k, last):
            sj = book.s[j] * (1 + extra_spread)
            if side > 0:
                adv, fav, opn = book.l[j], book.h[j], book.o[j]
            else:
                adv, fav, opn = book.h[j] + sj, book.l[j] + sj, book.o[j] + sj
            if (adv - sg.stop) * side <= 0:
                gap_px = opn if j > k else sg.stop
                exit_px = (min(sg.stop, gap_px) if side > 0 else max(sg.stop, gap_px)) - side * slip
                reason, j_exit = "stop", j
                break
            if target is not None and (fav - target) * side >= 0:
                exit_px, reason, j_exit = target, "target", j
                break
            if j + 1 < book.n and book.gap[j] > 6 * 60:   # weekend/holiday: flat at the reopen
                last = j + 1
                break
        if exit_px is None:
            j_exit = last
            sj = book.s[j_exit] * (1 + extra_spread)
            exit_px = (book.o[j_exit] if side > 0 else book.o[j_exit] + sj) - side * slip
            reason = "time"
        comm = rate * (fill + exit_px)
        r = ((exit_px - fill) * side - comm) / risk
        rows.append({"i": i, "entry_utc": book.utc[k], "exit_utc": book.utc[j_exit], "side": side, "fill": fill,
                     "stop": sg.stop, "exit": exit_px, "risk": risk, "r": r, "reason": reason,
                     "session": book.df["session"].iat[k], "bars": j_exit - k + 1})
        busy_until = j_exit
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ statistics
def t_p(r: np.ndarray) -> tuple[float, float]:
    """t-statistic and one-sided p (mean > 0), normal approximation for n >= 30, t-approx otherwise."""
    n = len(r)
    if n < 3:
        return float("nan"), float("nan")
    sd = r.std(ddof=1)
    if sd == 0:
        return float("nan"), float("nan")
    t = r.mean() / (sd / math.sqrt(n))
    # Student-t survival via regularised incomplete beta would need scipy; use a Cornish-Fisher-free
    # normal approximation with a small-sample correction (Hill 1970-lite).
    z = t * (1 - 1 / (4 * (n - 1))) / math.sqrt(1 + t * t / (2 * (n - 1)))
    p = 0.5 * math.erfc(z / math.sqrt(2))
    return float(t), float(p)


def bootstrap_ci(r: np.ndarray, reps: int = 4000, seed: int = 7) -> tuple[float, float]:
    if len(r) < 5:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    means = r[rng.integers(0, len(r), (reps, len(r)))].mean(axis=1)
    return float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))


def summarize(tr: pd.DataFrame) -> dict:
    if tr is None or tr.empty:
        return {"trades": 0}
    r = tr["r"].to_numpy(float)
    wins, losses = r[r > 0], r[r <= 0]
    cum = np.cumsum(r)
    dd = float((np.maximum.accumulate(np.r_[0, cum]) - np.r_[0, cum]).max())
    months = max((pd.Timestamp(tr["entry_utc"].max()) - pd.Timestamp(tr["entry_utc"].min())).days / 30.44, 1.0)
    t, p = t_p(r)
    lo, hi = bootstrap_ci(r)
    return {
        "trades": int(len(r)), "expectancy_r": round(float(r.mean()), 4), "median_r": round(float(np.median(r)), 3),
        "win_rate": round(len(wins) / len(r) * 100, 1),
        "profit_factor": round(float(wins.sum() / -losses.sum()), 3) if losses.sum() < 0 else None,
        "total_r": round(float(r.sum()), 2), "max_dd_r": round(dd, 2), "max_dd_pct_at_0p5": round(dd * 0.5, 2),
        "trades_per_month": round(len(r) / months, 2), "t": round(t, 2), "p_one_sided": round(p, 4),
        "ci95": [round(lo, 4), round(hi, 4)],
    }


def by(tr: pd.DataFrame, col: str) -> dict:
    if tr is None or tr.empty:
        return {}
    return {str(k): {kk: v for kk, v in summarize(g).items() if kk in ("trades", "expectancy_r", "profit_factor", "win_rate", "p_one_sided")}
            for k, g in tr.groupby(col)}


def direction_control(book: Book, signals: list[Signal], trades: pd.DataFrame, seeds: int = 200) -> dict:
    """Same decision bars, stop distances, targets (in R) and time exits; random direction."""
    if trades.empty:
        return {}
    taken = set(trades["i"])
    base = [s for s in signals if s.i in taken]
    means = []
    for seed in range(seeds):
        rng = np.random.default_rng(1000 + seed)
        ctrl = []
        for s in base:
            c = book.c[s.i]
            dist = abs(c - s.stop)
            side = int(rng.choice([-1, 1]))
            tr_r = s.target_r if s.target_r else (abs(s.target - c) / dist if s.target is not None and dist > 0 else None)
            ctrl.append(Signal(s.i, side, c - side * dist, None, tr_r, s.exit_idx))
        sim = simulate(book, ctrl)
        if not sim.empty:
            means.append(sim["r"].mean())
    means = np.array(means)
    actual = trades["r"].mean()
    return {"seeds": int(len(means)), "control_mean": round(float(means.mean()), 4),
            "control_p90": round(float(np.quantile(means, 0.9)), 4), "control_p95": round(float(np.quantile(means, 0.95)), 4),
            "strategy_percentile": round(float((means < actual).mean()), 3)}
