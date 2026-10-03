"""Deterministic synthetic MT5 bars for the trendline v5 tests.

M15 bars are a seeded random walk with alternating trend legs (so swings and
trendlines form); H1 bars aggregate complete groups of four M15 bars. Times are
MT5 server epochs through the verified test basis, like the other session tests.
The last M15 row (and the last H1 row) is the still-forming bar, as in a live scan.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from test_time_basis import BASIS, server_epoch_of  # noqa: F401  (BASIS re-exported)

START = datetime(2026, 9, 22, 4, 0, tzinfo=timezone.utc)   # 300 bars later: New York session, 23 Sep


def m15_rows(seed: int, count: int = 300, start: datetime = START, price: float = 100.0) -> list[dict]:
    rng = random.Random(seed)
    rows, drift, leg = [], 0.0, 0
    for i in range(count):
        if leg <= 0:
            drift, leg = rng.uniform(-0.06, 0.06), rng.randint(8, 30)
        leg -= 1
        open_ = price
        close = open_ + drift + rng.gauss(0, 0.12)
        high = max(open_, close) + abs(rng.gauss(0, 0.07))
        low = min(open_, close) - abs(rng.gauss(0, 0.07))
        rows.append({"time": server_epoch_of(start + timedelta(minutes=15 * i)), "open": open_, "high": high, "low": low, "close": close})
        price = close
    return rows


def h1_rows(m15: list[dict]) -> list[dict]:
    """Complete hours from the M15 history, plus the M15 forming bar's hour as the forming H1 bar."""
    out = []
    for i in range(0, len(m15) - (len(m15) % 4 or 4), 4):
        group = m15[i:i + 4]
        out.append({"time": group[0]["time"], "open": group[0]["open"], "high": max(r["high"] for r in group),
                    "low": min(r["low"] for r in group), "close": group[-1]["close"]})
    tail = m15[len(out) * 4:]
    out.append({"time": tail[0]["time"], "open": tail[0]["open"], "high": max(r["high"] for r in tail),
                "low": min(r["low"] for r in tail), "close": tail[-1]["close"]})
    return out


def forming_variants(last_closed: dict, atr: float) -> dict[str, dict]:
    """Extreme possibilities for the still-forming bar that opens after `last_closed`."""
    t = last_closed["time"] + 900
    o = last_closed["close"]
    bar = lambda h, l, c: {"time": t, "open": o, "high": max(o, h, c), "low": min(o, l, c), "close": c}
    return {
        "flat": bar(o, o, o),
        "surge_up": bar(o + 4 * atr, o, o + 3.8 * atr),
        "crash_down": bar(o, o - 4 * atr, o - 3.8 * atr),
        "wick_up_reject": bar(o + 3 * atr, o - 0.2 * atr, o - 0.1 * atr),
        "wick_down_reject": bar(o + 0.2 * atr, o - 3 * atr, o + 0.1 * atr),
        "small_up": bar(o + 0.5 * atr, o - 0.1 * atr, o + 0.4 * atr),
        "small_down": bar(o + 0.1 * atr, o - 0.5 * atr, o - 0.4 * atr),
    }
