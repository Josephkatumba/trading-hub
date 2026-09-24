"""Derived setup performance from append-only confirmations and market outcomes."""
from __future__ import annotations

import os
import hashlib
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import Any

from outcomes import DEFAULT_HORIZONS
from market_time import parse_aware_utc

REPORTING_TIMEZONE = "Africa/Nairobi"
PRIMARY_HORIZON = "4h"
LABELS = ("WIN", "LOSS", "PENDING", "NO_HIT", "AMBIGUOUS")


def _tzinfo(name: str) -> tzinfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        # Africa/Nairobi has no daylight-saving transitions. This keeps the
        # explicit reporting zone usable on Windows without adding tzdata.
        if name == "Africa/Nairobi":
            return timezone(timedelta(hours=3), name)
        if name == "UTC":
            return timezone.utc
        raise


def reporting_timezone() -> str:
    value = os.getenv("TRADING_HUB_REPORTING_TIMEZONE", REPORTING_TIMEZONE)
    try:
        _tzinfo(value)
        return value
    except (ZoneInfoNotFoundError, ValueError):
        return REPORTING_TIMEZONE


def _parse(value: Any) -> datetime | None:
    return parse_aware_utc(value)


def _empty_counts() -> dict[str, int]:
    return {label.lower(): 0 for label in LABELS}


def _classify(outcome: dict[str, Any] | None) -> str:
    if not outcome or not outcome.get("label"):
        return "PENDING"
    label = str(outcome["label"]).upper()
    return label if label in LABELS else "PENDING"


def _metrics(events: list[dict[str, Any]], outcome_index: dict[tuple[str, str, str], dict[str, Any]],
             horizon: str, grouping: str | None = None) -> dict[str, Any]:
    counts = _empty_counts()
    groups: dict[str, dict[str, int]] = defaultdict(_empty_counts)
    for event in events:
        outcome = outcome_index.get((str(event.get("setup_id")), str(event.get("observation_id")), horizon))
        label = _classify(outcome)
        counts[label.lower()] += 1
        if grouping:
            key = str(event.get(grouping) or "UNKNOWN")
            groups[key][label.lower()] += 1
    denominator = counts["win"] + counts["loss"]
    return {**counts, "win_rate": round(counts["win"] / denominator * 100, 1) if denominator else None,
            "win_rate_denominator": denominator,
            **({"groups": dict(groups)} if grouping else {})}


def _watch_count(snapshots: list[dict[str, Any]], confirmations: list[dict[str, Any]],
                 report_day: date, tz: tzinfo) -> int:
    cutoff = datetime.combine(report_day + timedelta(days=1), time.min, tzinfo=tz).astimezone(timezone.utc)
    latest: dict[str, dict[str, Any]] = {}
    for row in snapshots:
        stamp = _parse(row.get("observed_at") or row.get("timestamp"))
        if stamp is None or stamp > cutoff:
            continue
        if row.get("setup_id"):
            sid = str(row["setup_id"])
        elif row.get("symbol"):
            key = str(row.get("symbol", "UNKNOWN")) + "|" + str(row.get("direction") or "NONE")
            sid = "stp_legacy_" + hashlib.sha256(key.encode()).hexdigest()[:24]
        else:
            sid = str(row.get("observation_id") or "")
        if not sid:
            continue
        if sid not in latest or (_parse(latest[sid].get("observed_at") or latest[sid].get("timestamp")) or stamp) < stamp:
            latest[sid] = row
    confirmed_ids = {str(event.get("setup_id")) for event in confirmations
                     if (_parse(event.get("confirmed_at")) or cutoff) <= cutoff}
    return sum(1 for sid, row in latest.items()
               if sid not in confirmed_ids and str(row.get("lifecycle_state") or "").upper() not in
               {"INVALIDATED", "EXPIRED", "RESOLVED"})


def _daily(events: list[dict[str, Any]], outcomes: list[dict[str, Any]],
           snapshots: list[dict[str, Any]], report_day: date, tz_name: str,
           horizons: tuple[str, ...]) -> dict[str, Any]:
    tz = _tzinfo(tz_name)
    selected = []
    for event in events:
        stamp = _parse(event.get("confirmed_at"))
        if stamp and stamp.astimezone(tz).date() == report_day:
            selected.append(event)
    # A malformed/duplicated file still counts one confirmation per setup/day.
    dedup: dict[str, dict[str, Any]] = {}
    for event in sorted(selected, key=lambda row: str(row.get("confirmed_at") or "")):
        dedup.setdefault(str(event.get("setup_id")), event)
    selected = list(dedup.values())
    outcome_index = {}
    for outcome in outcomes:
        if outcome.get("record_type") not in {None, "market_outcome"}:
            continue
        key = (str(outcome.get("setup_id")), str(outcome.get("observation_id")), str(outcome.get("horizon")))
        outcome_index[key] = outcome
    per_horizon = {horizon: _metrics(selected, outcome_index, horizon) for horizon in horizons}
    primary = per_horizon.get(PRIMARY_HORIZON, _empty_counts())
    by_symbol = _metrics(selected, outcome_index, PRIMARY_HORIZON, "symbol")["groups"]
    by_setup_type = _metrics(selected, outcome_index, PRIMARY_HORIZON, "setup_type")["groups"]
    by_timeframe = _metrics(selected, outcome_index, PRIMARY_HORIZON, "timeframe")["groups"]
    setups = []
    for event in selected:
        results = {horizon: _classify(outcome_index.get((str(event.get("setup_id")),
                    str(event.get("observation_id")), horizon))) for horizon in horizons}
        setups.append({**event, "market_outcomes": results,
                       "primary_outcome": results.get(PRIMARY_HORIZON, "PENDING")})
    return {"date": report_day.isoformat(), "reporting_timezone": tz_name,
        "primary_horizon": PRIMARY_HORIZON, "confirmed": len(selected),
        "wins": primary.get("win", 0), "losses": primary.get("loss", 0),
        "pending": primary.get("pending", 0), "no_hit": primary.get("no_hit", 0),
        "ambiguous": primary.get("ambiguous", 0), "win_rate": primary.get("win_rate"),
        "win_rate_denominator": primary.get("win_rate_denominator", 0),
        "watchlist": _watch_count(snapshots, events, report_day, tz),
        "by_horizon": per_horizon, "by_symbol": by_symbol,
        "by_setup_type": by_setup_type, "by_timeframe": by_timeframe,
        "setups": setups}


def performance_report(confirmations: list[dict[str, Any]], outcomes: list[dict[str, Any]],
                       snapshots: list[dict[str, Any]], report_date: str | None = None,
                       days: int = 1, horizons: tuple[str, ...] = DEFAULT_HORIZONS,
                       timezone_name: str | None = None) -> dict[str, Any]:
    tz_name = timezone_name or reporting_timezone()
    tz = _tzinfo(tz_name)
    end_day = date.fromisoformat(report_date) if report_date else datetime.now(tz).date()
    days = max(1, min(int(days), 30))
    daily = [_daily(confirmations, outcomes, snapshots, end_day - timedelta(days=offset),
                    tz_name, horizons) for offset in reversed(range(days))]
    if days == 1:
        summary = daily[0]
    else:
        sum_fields = ("confirmed", "wins", "losses", "pending", "no_hit", "ambiguous")
        summary = {key: sum(item[key] for item in daily) for key in sum_fields}
        denominator = summary["wins"] + summary["losses"]
        summary.update({"date": f"{daily[0]['date']}..{daily[-1]['date']}",
            "reporting_timezone": tz_name, "primary_horizon": PRIMARY_HORIZON,
            "win_rate_denominator": denominator,
            "win_rate": round(summary["wins"] / denominator * 100, 1) if denominator else None,
            "watchlist": daily[-1]["watchlist"],
            "by_horizon": {h: {k: sum(d["by_horizon"][h][k] for d in daily)
                               for k in LABELS_LOWER} for h in horizons},
            "by_symbol": {}, "by_setup_type": {}, "by_timeframe": {},
            "setups": [setup for day in daily for setup in day["setups"]]})
        for key in ("by_symbol", "by_setup_type", "by_timeframe"):
            merged: dict[str, dict[str, int]] = defaultdict(_empty_counts)
            for item in daily:
                for group, counts in item[key].items():
                    for label in LABELS_LOWER:
                        merged[group][label] += counts.get(label, 0)
            summary[key] = dict(merged)
    return {"timezone": tz_name, "primary_horizon": PRIMARY_HORIZON,
            "available_horizons": list(horizons), "daily": daily, "summary": summary}


LABELS_LOWER = tuple(label.lower() for label in LABELS)
