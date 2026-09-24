"""Session context for the trendline scanner, with an explicit bar-time reader.

`compute_session_context` is the session logic of `main.session_context`, with
the two inputs that function takes implicitly made explicit:

- `now_utc`: the real current instant (main uses datetime.now(timezone.utc));
- `bar_time`: how an M15 bar's timestamp becomes an instant.

LEGACY  (`legacy_bar_time`): the raw MT5 epoch read as if it were UTC - exactly
        main._bar_dt, the production behaviour. MT5 epochs encode the broker's
        server wall clock (New York + 7 h), so the "London session" window this
        selects is 2-3 hours early.
CORRECTED (`corrected_bar_time`): the epoch converted through the verified
        broker basis (market_time.normalize_mt5_epoch, Phase 8). Bars whose
        server time does not exist or is ambiguous under the basis (DST gaps /
        repeated hours) are skipped rather than guessed.

Production (main.session_context) is unchanged and remains the LEGACY path; this
module exists for the Phase 9 A/B experiment. tests/test_session_time.py proves
the legacy path here is identical to main.session_context.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Any, Callable, Sequence
from zoneinfo import ZoneInfo

from market_time import normalize_mt5_epoch

LONDON = ZoneInfo("Europe/London")
NEW_YORK = ZoneInfo("America/New_York")
BarTime = Callable[[dict[str, Any]], "datetime | None"]


def legacy_bar_time(row: dict[str, Any]) -> datetime:
    """Production (main._bar_dt): the raw epoch read as a UTC instant."""
    return datetime.fromtimestamp(float(row["time"]), tz=timezone.utc)


def corrected_bar_time(basis: str) -> BarTime:
    """Epoch -> real UTC instant through the verified broker basis; None when not verifiable."""
    def bar_time(row: dict[str, Any]) -> datetime | None:
        stamp = normalize_mt5_epoch(row["time"], basis)
        if stamp.get("normalization_status") != "VERIFIED":
            return None
        return datetime.fromisoformat(stamp["normalized_utc"])
    return bar_time


def compute_session_context(rows: Sequence[dict[str, Any]], price: float, now_utc: datetime,
                            bar_time: BarTime = legacy_bar_time) -> dict[str, Any]:
    london_now = now_utc.astimezone(LONDON)
    ny_now = now_utc.astimezone(NEW_YORK)
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

    # Most recent London session present in the M15 history (see main.session_context).
    london_times = []
    for row in rows:
        instant = bar_time(row)
        london_times.append(instant.astimezone(LONDON) if instant is not None else None)
    london_bars, london_date = [], None
    for days_back in range(8):
        candidate_date = london_now.date() - timedelta(days=days_back)
        candidate = [row for row, dt in zip(rows, london_times)
                     if dt is not None and dt.date() == candidate_date and time(8, 0) <= dt.time() < time(16, 30)]
        if candidate:
            london_bars, london_date = candidate, candidate_date
            break

    london_high = max((float(r["high"]) for r in london_bars), default=0.0)
    london_low = min((float(r["low"]) for r in london_bars), default=0.0)
    london_complete = bool(london_date) and (london_date < london_now.date() or london_now.time() >= time(16, 30))
    alignment = None
    if london_complete and session == "New York" and london_high and london_low:
        distance_high = abs(price - london_high)
        distance_low = abs(price - london_low)
        span = max(london_high - london_low, 0.0000001)
        if distance_high <= span * 0.08:
            alignment = "New York is retesting the London high, watch for bearish confirmation"
        elif distance_low <= span * 0.08:
            alignment = "New York is retesting the London low, watch for bullish confirmation"
    return {"session": session, "london_high": london_high, "london_low": london_low,
            "london_complete": london_complete, "session_alignment": alignment,
            "london_date": london_date.isoformat() if london_date else None,
            "new_york_time": ny_now.isoformat()}


def session_context_legacy(rows, price, now_utc):
    return compute_session_context(rows, price, now_utc, legacy_bar_time)


def session_context_corrected(rows, price, now_utc, basis: str):
    return compute_session_context(rows, price, now_utc, corrected_bar_time(basis))
