"""Performance statistics shared by the simulator, walk-forward and live journal."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd


def summarize(trades: pd.DataFrame, start_equity: float = 10_000.0, days: float | None = None) -> dict:
    if trades is None or trades.empty:
        return {"trades": 0, "net_pnl": 0.0, "win_rate": None, "profit_factor": None,
                "expectancy_r": None, "max_drawdown_pct": 0.0}
    t = trades.sort_values("exit_time")
    pnl = t["pnl"].to_numpy(float)
    wins, losses = pnl[pnl > 0], pnl[pnl <= 0]
    eq = start_equity + np.cumsum(pnl)
    peak = np.maximum.accumulate(np.concatenate([[start_equity], eq]))[1:]
    dd = ((peak - eq) / peak).max() * 100
    r = t["r_multiple"].to_numpy(float) if "r_multiple" in t else None
    if days is None:
        span = (pd.Timestamp(t["exit_time"].max()) - pd.Timestamp(t["entry_time"].min())).total_seconds() / 86400
        days = max(span * 5 / 7, 1.0)
    out = {
        "trades": int(len(t)),
        "net_pnl": round(float(pnl.sum()), 2),
        "return_pct": round(float(pnl.sum()) / start_equity * 100, 2),
        "win_rate": round(len(wins) / len(pnl) * 100, 1),
        "profit_factor": round(float(wins.sum() / -losses.sum()), 3) if losses.sum() < 0 else None,
        "avg_win": round(float(wins.mean()), 2) if len(wins) else None,
        "avg_loss": round(float(losses.mean()), 2) if len(losses) else None,
        "max_drawdown_pct": round(float(dd), 2),
        "trades_per_day": round(len(t) / days, 2),
        "commission": round(float(t["commission"].sum()), 2) if "commission" in t else None,
    }
    if r is not None and len(r):
        sd = r.std(ddof=1) if len(r) > 1 else float("nan")
        out["expectancy_r"] = round(float(r.mean()), 3)
        out["t_stat"] = round(float(r.mean() / (sd / math.sqrt(len(r)))), 2) if sd and sd > 0 else None
    return out


def breakdown(trades: pd.DataFrame, by: str, start_equity: float = 10_000.0) -> dict:
    if trades is None or trades.empty or by not in trades:
        return {}
    return {str(k): summarize(g, start_equity) for k, g in trades.groupby(by)}
