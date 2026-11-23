"""Fixed-horizon trade simulator, controls, benchmarks and statistics for TradeDen V3.

A trade request is (series, decision index i, entry index k = i + 1, exit index x, side). Fills are at bar OPENS
(bars are bid; the ask is bid + spread). Costs per side: spread floor 1.5 bp (doubled for D1 opens, which sit at
the 17:00 New York rollover), slippage 1 bp (3 bp within 2 h after a release), commission 0.3 bp; plus financing
for the time held (longs pay fed funds + 0.8%/yr, shorts receive fed funds - 0.8%/yr; calendar days / 360).
R = net return / (trailing 100-bar volatility of that series x sqrt(holding bars)): a volatility-unit "R".
One position at a time per configuration (requests that overlap an open trade are skipped).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .registry import COSTS


@dataclass
class Req:
    series: str        # "H1" or "D1"
    i: int             # decision bar (its close is the last information used)
    x: int             # exit at the OPEN of bar x (entry at the open of bar i + 1)
    side: int
    event: bool = False


class Series:
    def __init__(self, name: str, df: pd.DataFrame, time_col: str, dff: np.ndarray):
        self.name = name
        self.df = df
        self.t = pd.to_datetime(df[time_col]).to_numpy()
        self.o = df["open"].to_numpy(float)
        self.c = df["close"].to_numpy(float)
        self.spread = df["spread_px"].to_numpy(float)
        self.dff = dff
        lr = np.diff(np.log(self.c), prepend=np.log(self.c[0]))
        self.vol = pd.Series(lr).rolling(100, min_periods=50).std().to_numpy()
        self.n = len(df)


def simulate(s: Series, reqs: list[Req], cost_mult: float = 1.0) -> pd.DataFrame:
    rows, busy = [], -1
    floor_bp = COSTS["spread_floor_bp"] * (2.0 if s.name == "D1" else 1.0)
    for r in sorted(reqs, key=lambda q: (q.i, q.x)):
        k = r.i + 1
        if k <= busy or r.x <= k or r.x >= s.n or not np.isfinite(s.vol[r.i]):
            continue
        p_in, p_out = s.o[k], s.o[r.x]
        spr_in = max(s.spread[k], floor_bp * 1e-4 * p_in) * cost_mult
        spr_out = max(s.spread[r.x], floor_bp * 1e-4 * p_out) * cost_mult
        slip_in = (COSTS["event_slippage_bp"] if r.event else COSTS["slippage_bp"]) * 1e-4 * p_in * cost_mult
        slip_out = COSTS["slippage_bp"] * 1e-4 * p_out * cost_mult
        fill = p_in + spr_in + slip_in if r.side > 0 else p_in - slip_in
        exit_px = p_out - slip_out if r.side > 0 else p_out + spr_out + slip_out
        gross = (exit_px - fill) * r.side
        comm = COSTS["commission_rate"] * cost_mult * (fill + exit_px)
        days = (s.t[r.x] - s.t[k]) / np.timedelta64(1, "D")
        rate = s.dff[k] / 100.0 if np.isfinite(s.dff[k]) else 0.0
        fin = (rate + COSTS["financing_markup"] * cost_mult) if r.side > 0 else -(rate - COSTS["financing_markup"] * cost_mult)
        financing = fin * max(days, 0) / 360.0 * fill
        net = gross - comm - financing
        risk = s.vol[r.i] * math.sqrt(r.x - k) * fill
        rows.append({"i": r.i, "entry_time": s.t[k], "exit_time": s.t[r.x], "side": r.side, "fill": fill,
                     "exit": exit_px, "net_bp": net / fill * 1e4, "r": net / risk, "cost_bp": ((p_out - p_in) * r.side - net) / fill * 1e4, "series": s.name})
        busy = r.x
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ statistics
def t_p(x: np.ndarray) -> tuple[float, float]:
    n = len(x)
    if n < 3 or x.std(ddof=1) == 0:
        return float("nan"), float("nan")
    t = x.mean() / (x.std(ddof=1) / math.sqrt(n))
    z = t * (1 - 1 / (4 * (n - 1))) / math.sqrt(1 + t * t / (2 * (n - 1)))
    return float(t), float(0.5 * math.erfc(z / math.sqrt(2)))


def bootstrap_ci(x: np.ndarray, reps: int = 4000, seed: int = 11) -> tuple[float, float]:
    if len(x) < 5:
        return float("nan"), float("nan")
    m = x[np.random.default_rng(seed).integers(0, len(x), (reps, len(x)))].mean(axis=1)
    return float(np.quantile(m, 0.025)), float(np.quantile(m, 0.975))


def summarize(tr: pd.DataFrame) -> dict:
    if tr is None or tr.empty:
        return {"trades": 0}
    r = tr["r"].to_numpy(float)
    bp = tr["net_bp"].to_numpy(float)
    w, l = r[r > 0], r[r <= 0]
    cum = np.cumsum(r)
    dd = float((np.maximum.accumulate(np.r_[0, cum]) - np.r_[0, cum]).max())
    years = max((pd.Timestamp(tr["entry_time"].max()) - pd.Timestamp(tr["entry_time"].min())).days / 365.25, 1 / 12)
    t, p = t_p(r)
    lo, hi = bootstrap_ci(r)
    return {"trades": int(len(r)), "mean_r": round(float(r.mean()), 4), "mean_net_bp": round(float(bp.mean()), 2),
            "win_rate": round(len(w) / len(r) * 100, 1),
            "profit_factor": round(float(w.sum() / -l.sum()), 3) if l.sum() < 0 else None,
            "max_dd_r": round(dd, 2), "trades_per_year": round(len(r) / years, 1),
            "t": round(t, 2), "p_one_sided": round(p, 4), "ci95_r": [round(lo, 4), round(hi, 4)]}


def by_year(tr: pd.DataFrame) -> dict:
    if tr is None or tr.empty:
        return {}
    y = pd.to_datetime(tr["entry_time"]).dt.year
    return {int(k): {"trades": int(len(g)), "mean_r": round(float(g["r"].mean()), 3)} for k, g in tr.groupby(y)}


def direction_control(s_map: dict, reqs_taken: list[Req], seeds: int = 200) -> dict:
    """Same entries and exits with a random side."""
    if not reqs_taken:
        return {}
    means = []
    for seed in range(seeds):
        rng = np.random.default_rng(5000 + seed)
        parts = []
        for name in {q.series for q in reqs_taken}:
            qs = [Req(q.series, q.i, q.x, int(rng.choice([-1, 1])), q.event) for q in reqs_taken if q.series == name]
            parts.append(simulate(s_map[name], qs))
        allr = pd.concat([p for p in parts if not p.empty])
        means.append(allr["r"].mean())
    return {"seeds": seeds, "mean": round(float(np.mean(means)), 4), "p90": round(float(np.quantile(means, 0.9)), 4)}


def always_long(s_map: dict, reqs_taken: list[Req]) -> pd.DataFrame:
    parts = []
    for name in {q.series for q in reqs_taken}:
        parts.append(simulate(s_map[name], [Req(q.series, q.i, q.x, 1, q.event) for q in reqs_taken if q.series == name]))
    parts = [p for p in parts if not p.empty]
    return pd.concat(parts) if parts else pd.DataFrame()


def random_time_long(s: Series, reqs_taken: list[Req], start, end, draws: int = 400, seed: int = 9) -> dict:
    """Unconditional drift benchmark for long-only rules: long at random bars in the window, same holding length."""
    if not reqs_taken:
        return {}
    rng = np.random.default_rng(seed)
    ok = np.flatnonzero((s.t >= np.datetime64(start)) & (s.t < np.datetime64(end)))
    holds = [q.x - q.i - 1 for q in reqs_taken]
    means = []
    for _ in range(draws):
        qs = []
        for h in rng.choice(holds, len(holds)):
            i = int(rng.choice(ok))
            qs.append(Req(s.name, i, i + 1 + int(h), 1))
        sim = simulate(s, qs)
        if not sim.empty:
            means.append(sim["r"].mean())
    return {"draws": len(means), "mean": round(float(np.mean(means)), 4), "p90": round(float(np.quantile(means, 0.9)), 4)}
