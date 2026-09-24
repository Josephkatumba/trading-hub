"""Frozen copy of the production session functions of trendline-first-v3.

Verbatim from backend/main.py at commit 884a3cf (before trendline-first-v4), so the
legacy session behaviour stays provable after production moved to the corrected
broker-time basis. Only the clock is injectable: `datetime` is looked up at module
level, so tests patch `legacy_session_context.datetime`. Do not edit.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

LONDON = ZoneInfo("Europe/London")
NEW_YORK = ZoneInfo("America/New_York")


def _bar_dt(row: dict[str, Any]) -> datetime:
    return datetime.fromtimestamp(float(row["time"]), tz=timezone.utc)


def session_context(rows: list[dict[str, Any]], price: float) -> dict[str, Any]:
    now_utc = datetime.now(timezone.utc)
    london_now = now_utc.astimezone(LONDON)
    ny_now = now_utc.astimezone(NEW_YORK)

    # Treat London and New York as independent local sessions. The important
    # strategy window is the period after London's close while New York is active.
    london_active = time(8, 0) <= london_now.time() < time(16, 30)
    ny_active = time(8, 0) <= ny_now.time() < time(17, 0)

    if ny_active and not london_active:
        session = "New York"
    elif london_active and ny_active:
        session = "London / New York Overlap"
    elif london_active:
        session = "London"
    elif time(0, 0) <= london_now.time() < time(8, 0):
        session = "Asia"
    else:
        session = "Off-hours"

    # Find the most recent London session represented in the M15 history.
    # Before London's open, this deliberately falls back to the previous
    # completed session instead of looking for bars on the new London date.
    london_bars = []
    london_date = None
    for days_back in range(8):
        candidate_date = london_now.date() - timedelta(days=days_back)
        candidate = []
        for row in rows:
            dt = _bar_dt(row).astimezone(LONDON)
            if dt.date() == candidate_date and time(8, 0) <= dt.time() < time(16, 30):
                candidate.append(row)
        if candidate:
            london_bars = candidate
            london_date = candidate_date
            break

    london_high = max((float(r["high"]) for r in london_bars), default=0.0)
    london_low = min((float(r["low"]) for r in london_bars), default=0.0)
    london_complete = bool(london_date) and (
        london_date < london_now.date() or london_now.time() >= time(16, 30)
    )

    alignment = None
    if london_complete and session == "New York" and london_high and london_low:
        # Use 0.35 ATR-ish proximity later in the scanner, while keeping this
        # context simple and explainable.
        distance_high = abs(price - london_high)
        distance_low = abs(price - london_low)
        span = max(london_high - london_low, 0.0000001)
        if distance_high <= span * 0.08:
            alignment = "New York is retesting the London high, watch for bearish confirmation"
        elif distance_low <= span * 0.08:
            alignment = "New York is retesting the London low, watch for bullish confirmation"

    return {
        "session": session,
        "london_high": london_high,
        "london_low": london_low,
        "london_complete": london_complete,
        "session_alignment": alignment,
        "london_date": london_date.isoformat() if london_date else None,
        "new_york_time": ny_now.isoformat(),
    }
