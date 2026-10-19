"""Trade-list statistics in R, with uncertainty.

Ambiguous trades (both levels inside one candle, no finer data) count as stops in the
headline (pessimistic) expectancy; the optimistic bound counts them as targets. A rate or
expectancy from fewer than MIN_TRADES trades is reported but flagged insufficient.
"""
from __future__ import annotations

import math
import random
from typing import Any, Iterable

MIN_TRADES = 30
BOOTSTRAP = 4000


def _bootstrap(values: list[float], seed: int = 7) -> tuple[float | None, float | None, float | None]:
    if len(values) < 2:
        return None, None, None
    rng = random.Random(seed)
    n = len(values)
    means = sorted(sum(rng.choice(values) for _ in range(n)) / n for _ in range(BOOTSTRAP))
    return (round(means[int(0.025 * BOOTSTRAP)], 4), round(means[int(0.975 * BOOTSTRAP) - 1], 4),
            round(sum(m > 0 for m in means) / BOOTSTRAP, 3))


def max_drawdown(rs: Iterable[float]) -> float:
    peak = equity = drawdown = 0.0
    for r in rs:
        equity += r
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return round(drawdown, 3)


def summarize(trades: list[dict[str, Any]], months: float | None = None) -> dict[str, Any]:
    """`trades`: simulated trades in chronological order (each with outcome and r)."""
    closed = [t for t in trades if t.get("r") is not None]
    rs = [t["r"] for t in closed]
    # A win is a trade closed with positive R: a target, or a trailed/timed exit in profit.
    wins = sum(t["outcome"] != "AMBIGUOUS" and t["r"] > 0 for t in closed)
    losses = sum(t["outcome"] != "AMBIGUOUS" and t["r"] <= 0 for t in closed)
    ambiguous = sum(t["outcome"] == "AMBIGUOUS" for t in closed)
    timeouts = sum(t["outcome"] == "TIMEOUT" for t in closed)
    gross_win = sum(r for r in rs if r > 0)
    gross_loss = -sum(r for r in rs if r < 0)
    optimistic = [t.get("r_if_target", t["r"]) for t in closed]
    low, high, p_positive = _bootstrap(rs)
    n = len(rs)
    mean = sum(rs) / n if n else None
    sd = math.sqrt(sum((r - mean) ** 2 for r in rs) / (n - 1)) if n > 1 else None
    return {
        "trades": n, "wins": wins, "losses": losses, "ambiguous": ambiguous, "timeouts": timeouts,
        "win_rate": round(wins / (wins + losses), 4) if wins + losses else None,
        "expectancy_r": round(mean, 4) if mean is not None else None,
        "expectancy_r_optimistic": round(sum(optimistic) / n, 4) if n else None,
        "expectancy_ci95": [low, high], "p_expectancy_positive": p_positive,
        "t_stat": round(mean / (sd / math.sqrt(n)), 2) if sd else None,
        "profit_factor": round(gross_win / gross_loss, 3) if gross_loss else None,
        "total_r": round(sum(rs), 2), "max_drawdown_r": max_drawdown(rs),
        "avg_hold_hours": round(sum(t.get("hold_hours", 0) for t in closed) / n, 1) if n else None,
        "trades_per_month": round(n / months, 1) if months else None,
        "sufficient": n >= MIN_TRADES,
    }
