"""Derived setup performance from append-only confirmations and market outcomes."""
from __future__ import annotations

import os
import hashlib
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import Any

from outcomes import DEFAULT_HORIZONS
from outcome_identity import unique_outcomes
from market_time import parse_aware_utc
from strategies.base import record_strategy_id

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
    if outcome and outcome.get("outcome_status") == "DUPLICATE_OUTCOME_CONFLICT":
        return "PENDING"
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
        if row.get("shadow") is True:
            continue                         # shadow-mode setups are not on the live watchlist
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
    # Live figures (headline, groups, the setups list that drives alerts) count
    # live confirmations only; shadow-mode strategies appear in by_strategy only.
    everything, selected = selected, [event for event in selected if event.get("shadow") is not True]
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
    # One group per strategy; confirmations recorded before strategy_id existed map to trendline.
    by_strategy = _metrics([{**event, "strategy_id": record_strategy_id(event)} for event in everything],
                           outcome_index, PRIMARY_HORIZON, "strategy_id")["groups"]
    shadow_strategies = sorted({record_strategy_id(event) for event in everything if event.get("shadow") is True})
    setups = []
    for event in selected:
        results = {horizon: _classify(outcome_index.get((str(event.get("setup_id")),
                    str(event.get("observation_id")), horizon))) for horizon in horizons}
        setups.append({**event, "strategy_id": record_strategy_id(event), "market_outcomes": results,
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
        "by_strategy": by_strategy, "shadow_strategies": shadow_strategies, "setups": setups}


# ----- verified resolution (reconciled with the Strategy Lab) --------------------------
# The per-horizon tables above count every stored outcome label. The `verified` block
# applies the Strategy Lab's rule instead (strategy_lab.classify_outcome): only outcomes
# passing the ML dataset integrity checks count, and the shortest horizon with a verified
# WIN/LOSS decides which barrier was reached first. Every confirmed setup lands in exactly
# one bucket, so the buckets always add up to `confirmed` (`reconciled`).
VERIFIED_KINDS = ("verified_target", "verified_stop", "verified_other", "unverified", "pending")
MIN_DECISIVE_FOR_RATE = 30           # the Strategy Lab's MIN_VERIFIED_FOR_RATE


def _plan_r(snapshot: dict[str, Any] | None) -> float | None:
    """Reward/risk the setup offered when it was recorded: the executable R:R (spread
    included, qualification.py) when stored, else from the observed price to the target
    and invalidation. None when the plan is incomplete or inconsistent."""
    if not snapshot:
        return None
    qualification = (snapshot.get("rule_evidence") or {}).get("qualification") or {}
    if qualification.get("executable_rr") is not None:
        try:
            return float(qualification["executable_rr"])
        except (TypeError, ValueError):
            return None
    try:
        ref = float(snapshot.get("reference_price"))
        target = float(snapshot.get("proposed_take_profit"))
        stop = snapshot.get("invalidation_price")
        stop = float(stop if stop is not None else snapshot.get("proposed_stop_loss"))
    except (TypeError, ValueError):
        return None
    sign = 1 if snapshot.get("direction") == "LONG" else -1 if snapshot.get("direction") == "SHORT" else 0
    reward, risk = sign * (target - ref), sign * (ref - stop)
    return reward / risk if sign and reward > 0 and risk > 0 else None


def _r_multiple(kind: str, plan_r: float | None) -> float | None:
    """Result in R of a decisive verified outcome: +plan R at the target, -1 at the stop."""
    if kind == "verified_target":
        return plan_r
    if kind == "verified_stop":
        return -1.0
    return None


def verified_resolution(event: dict[str, Any], outcomes: list[dict[str, Any]],
                        snapshot: dict[str, Any] | None, horizons: tuple[str, ...] = DEFAULT_HORIZONS) -> dict[str, Any]:
    """One confirmed setup's verified result (kind, deciding horizon, R)."""
    from strategy_lab import classify_outcome     # local: strategy_lab imports the observation store
    kind, horizon = classify_outcome(event, outcomes, snapshot, horizons)
    plan_r = _plan_r(snapshot)
    return {"kind": kind, "horizon": horizon, "plan_r": plan_r, "r_multiple": _r_multiple(kind, plan_r)}


def verified_summary(resolutions: list[dict[str, Any]], min_decisive: int = MIN_DECISIVE_FOR_RATE) -> dict[str, Any]:
    counts = {kind: sum(1 for item in resolutions if item["kind"] == kind) for kind in VERIFIED_KINDS}
    decisive = counts["verified_target"] + counts["verified_stop"]
    rs = [item["r_multiple"] for item in resolutions if item["r_multiple"] is not None]
    gains, losses = sum(r for r in rs if r > 0), -sum(r for r in rs if r < 0)
    sufficient = decisive >= min_decisive
    return {"confirmed": len(resolutions), **counts,
            "reconciled": sum(counts.values()) == len(resolutions),
            "decisive": decisive, "min_decisive_for_rate": min_decisive, "sample_sufficient": sufficient,
            # Rates and averages are shown only with enough decisive outcomes (as in the Strategy Lab).
            "target_first_rate": round(counts["verified_target"] / decisive * 100, 1) if sufficient else None,
            "r": {"count": len(rs), "missing_plan": decisive - len(rs),
                  "total_r": round(sum(rs), 2) if rs else None,
                  "average_r": round(sum(rs) / len(rs), 3) if rs and sufficient else None,
                  "profit_factor": round(gains / losses, 2) if losses and sufficient else None},
            "basis": "Strategy Lab rule: verified outcomes only; the shortest horizon with a verified target/stop "
                     "decides. R: +planned R (executable when recorded) at the target, -1 at the stop; "
                     "no-barrier, unverified and pending setups carry no R. No costs beyond the recorded spread."}


def _verified_groups(setups: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for setup in setups:
        grouped[setup["strategy_id"]].append(setup["verified_outcome"])
    return (verified_summary([setup["verified_outcome"] for setup in setups]),
            {strategy_id: verified_summary(items) for strategy_id, items in sorted(grouped.items())})


def report_end_day(report_date: str | None = None, timezone_name: str | None = None) -> date:
    """The last day performance_report covers (today in the reporting timezone by default)."""
    tz_name = timezone_name or reporting_timezone()
    return date.fromisoformat(report_date) if report_date else datetime.now(_tzinfo(tz_name)).date()


def performance_report(confirmations: list[dict[str, Any]], outcomes: list[dict[str, Any]],
                       snapshots: list[dict[str, Any]], report_date: str | None = None,
                       days: int = 1, horizons: tuple[str, ...] = DEFAULT_HORIZONS,
                       timezone_name: str | None = None,
                       decision_snapshots: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """`decision_snapshots` ({observation_id: confirmation snapshot}) adds the verified,
    reconciled figures: `verified`, `verified_by_strategy` and setups[].verified_outcome."""
    tz_name = timezone_name or reporting_timezone()
    end_day = report_end_day(report_date, tz_name)
    outcomes = unique_outcomes(outcomes)
    days = max(1, min(int(days), 30))
    daily = [_daily(confirmations, outcomes, snapshots, end_day - timedelta(days=offset),
                    tz_name, horizons) for offset in reversed(range(days))]
    if decision_snapshots is not None:
        outcomes_by_setup: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in outcomes:
            outcomes_by_setup[str(row.get("setup_id"))].append(row)
        for day in daily:
            for setup in day["setups"]:
                setup["verified_outcome"] = verified_resolution(
                    setup, outcomes_by_setup.get(str(setup.get("setup_id")), []),
                    decision_snapshots.get(str(setup.get("observation_id"))), horizons)
            day["verified"], day["verified_by_strategy"] = _verified_groups(day["setups"])
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
            "by_symbol": {}, "by_setup_type": {}, "by_timeframe": {}, "by_strategy": {},
            "shadow_strategies": sorted({sid for day in daily for sid in day["shadow_strategies"]}),
            "setups": [setup for day in daily for setup in day["setups"]]})
        if decision_snapshots is not None:
            summary["verified"], summary["verified_by_strategy"] = _verified_groups(summary["setups"])
        for key in ("by_symbol", "by_setup_type", "by_timeframe", "by_strategy"):
            merged: dict[str, dict[str, int]] = defaultdict(_empty_counts)
            for item in daily:
                for group, counts in item[key].items():
                    for label in LABELS_LOWER:
                        merged[group][label] += counts.get(label, 0)
            summary[key] = dict(merged)
    return {"timezone": tz_name, "primary_horizon": PRIMARY_HORIZON,
            "available_horizons": list(horizons), "daily": daily, "summary": summary}


LABELS_LOWER = tuple(label.lower() for label in LABELS)
