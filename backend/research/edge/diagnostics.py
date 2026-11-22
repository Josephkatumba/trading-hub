"""Experiment 0: the native return structure of each instrument and timeframe (no trading, no costs).

Per instrument x timeframe (M15, M30, H1, H4), separately for the TRAIN and VALIDATION periods:
  ac1             lag-1 autocorrelation of log returns, with t = ac1 * sqrt(n)
  variance ratio  VR(q) for q = 2, 4, 8, 16 with the Lo-MacKinlay heteroskedasticity-robust z statistic
                  (VR > 1: momentum / trending; VR < 1: mean reversion)
  large moves     after a bar whose return is beyond 2 standard deviations (prior 100 bars), the mean of the
                  next 4 bars' return in the move's direction (in units of sigma), with its t statistic:
                  positive = continuation, negative = reversal
  time of day     (M15 only) mean return and volatility by UTC hour
Returns spanning a market gap (longer than 1.5 bar lengths) are excluded. Only the TRAIN large-move sign feeds
the tournament (family large_move); validation shows whether the structure persisted.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

from research.edge.market import TF_MINUTES, Market


def _returns(m: Market, tf: str, start: float, end: float) -> tuple[np.ndarray, np.ndarray]:
    f = m.frame(tf)
    r = np.diff(np.log(f.close))
    gap = np.diff(f.utc) <= 1.5 * TF_MINUTES[tf] * 60
    t = f.utc[1:]
    keep = gap & (t >= start) & (t < end) & np.isfinite(r)
    return r[keep], t[keep]


def variance_ratio(r: np.ndarray, q: int) -> tuple[float | None, float | None]:
    """Lo-MacKinlay (1988) variance ratio with the heteroskedasticity-consistent z statistic."""
    n = len(r)
    if n < 10 * q:
        return None, None
    mu = r.mean()
    d = r - mu
    var1 = (d ** 2).sum() / (n - 1)
    rq = np.convolve(r, np.ones(q), mode="valid")
    m_ = q * (n - q + 1) * (1 - q / n)
    varq = ((rq - q * mu) ** 2).sum() / m_
    vr = varq / var1
    d2 = d ** 2
    denom = d2.sum() ** 2
    theta = 0.0
    for j in range(1, q):
        delta = (d2[j:] * d2[:-j]).sum() / denom * n
        theta += (2 * (q - j) / q) ** 2 * delta
    z = (vr - 1) / math.sqrt(theta / n) if theta > 0 else None
    return round(float(vr), 4), (round(float(z), 2) if z is not None else None)


def large_move_continuation(r: np.ndarray, threshold: float = 2.0, horizon: int = 4) -> dict[str, Any]:
    vals = []
    for k in range(100, len(r) - horizon):
        sd = r[k - 100:k].std()
        if sd <= 0:
            continue
        z = r[k] / sd
        if abs(z) > threshold:
            vals.append(np.sign(z) * r[k + 1:k + 1 + horizon].sum() / sd)
    if len(vals) < 20:
        return {"events": len(vals), "mean_sigma": None, "t": None, "sign": 0}
    v = np.array(vals)
    t = v.mean() / (v.std(ddof=1) / math.sqrt(len(v)))
    return {"events": len(v), "mean_sigma": round(float(v.mean()), 4), "t": round(float(t), 2),
            "sign": int(np.sign(v.mean()))}


def time_of_day(m: Market, start: float, end: float) -> dict[str, Any]:
    r, t = _returns(m, "M15", start, end)
    hours = ((t % 86400) // 3600).astype(int)
    out = {}
    for h in range(24):
        x = r[hours == h]
        if len(x) < 50:
            continue
        out[str(h)] = {"mean_bps": round(float(x.mean() * 1e4), 3), "vol_bps": round(float(x.std() * 1e4), 2),
                       "t": round(float(x.mean() / (x.std(ddof=1) / math.sqrt(len(x)))), 2)}
    return out


def structure(m: Market, start: float, end: float) -> dict[str, Any]:
    out = {}
    for tf in ("M15", "M30", "H1", "H4"):
        r, _ = _returns(m, tf, start, end)
        if len(r) < 200:
            continue
        ac1 = float(np.corrcoef(r[:-1], r[1:])[0, 1])
        out[tf] = {"n": len(r), "ac1": round(ac1, 4), "ac1_t": round(ac1 * math.sqrt(len(r)), 2),
                   "variance_ratio": {str(q): dict(zip(("vr", "z"), variance_ratio(r, q))) for q in (2, 4, 8, 16)},
                   "large_move": large_move_continuation(r)}
    return out


def run(m: Market, splits: dict[str, tuple]) -> dict[str, Any]:
    return {name: {"structure": structure(m, a.timestamp(), b.timestamp()),
                   "time_of_day": time_of_day(m, a.timestamp(), b.timestamp())}
            for name, (a, b) in splits.items() if name in ("train", "validation")}
