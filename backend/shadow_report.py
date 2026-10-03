"""Read-only experiment report for a SHADOW strategy (trendline-first-v5-shadow).

Everything here is counted from the existing append-only records of that one
strategy_id: episodes (observations + lifecycle events), confirmation events and
market outcomes. Nothing is written, nothing is estimated.

Outcome of a CONFIRMED episode = how its lifecycle closed:
  TARGET_HIT  lifecycle RESOLVED, reason TARGET_PRICE_CROSSED (its confirmed target)
  STOP_HIT    lifecycle INVALIDATED, reason INVALIDATION_PRICE_CROSSED (its confirmed stop)
  EXPIRED     lifecycle EXPIRED (no observation within the episode time limit)
  INVALIDATED any other closing after confirmation (should not occur under the
              confirmed-events lifecycle; counted separately so it is visible)
  STILL_OPEN  no closing event yet
Being confirmed is never an outcome. Nominal R multiples (target = +planned R:R,
stop = -1R) are reported separately with their assumptions; no profitability or
expectancy is derived.
"""
from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Iterable

STAGES = ("DETECTED", "DEVELOPING", "CONFIRMING", "CONFIRMED", "ACTIVE")
RANK = {"DETECTED": 0, "DEVELOPING": 1, "CONFIRMING": 2, "CONFIRMED": 3, "ACTIVE": 4}
OUTCOMES = ("TARGET_HIT", "STOP_HIT", "EXPIRED", "INVALIDATED", "STILL_OPEN")
NOMINAL_R_ASSUMPTIONS = ("Entry at the confirmed entry (last closed M15 close), exit exactly at the confirmed stop "
                         "(-1R) or target (+planned R:R); no spread, slippage, fees or partial fills. Not a P&L.")


def _time(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")) if value else None
    except ValueError:
        return None


def _minutes(start: datetime | None, end: datetime | None) -> float | None:
    return round((end - start).total_seconds() / 60, 1) if start and end else None


def _stats(values: Iterable[float | None]) -> dict[str, Any]:
    values = [float(v) for v in values if v is not None]
    if not values:
        return {"n": 0, "median": None, "average": None, "best": None, "worst": None}
    return {"n": len(values), "median": round(statistics.median(values), 2), "average": round(statistics.fmean(values), 2),
            "best": round(max(values), 2), "worst": round(min(values), 2)}


def _rate(part: int, whole: int) -> dict[str, Any]:
    return {"value": round(part / whole * 100, 1) if whole else None, "numerator": part, "denominator": whole}


def episode_outcome(events: list[dict[str, Any]], confirmed_at: datetime | None) -> dict[str, Any]:
    """Outcome of one confirmed episode from its lifecycle events after confirmation."""
    after = [e for e in events if confirmed_at and (_time(e.get("occurred_at")) or confirmed_at) >= confirmed_at]
    active = next((e for e in after if e.get("to_state") == "ACTIVE"), None)
    close = next((e for e in after if e.get("to_state") in {"INVALIDATED", "EXPIRED", "RESOLVED"}), None)
    if close is None:
        kind = "STILL_OPEN"
    elif close.get("reason_code") == "TARGET_PRICE_CROSSED":
        kind = "TARGET_HIT"
    elif close.get("reason_code") == "INVALIDATION_PRICE_CROSSED":
        kind = "STOP_HIT"
    elif close.get("to_state") == "EXPIRED":
        kind = "EXPIRED"
    else:
        kind = "INVALIDATED"
    return {"outcome": kind, "active_at": active.get("occurred_at") if active else None,
            "closed_at": close.get("occurred_at") if close else None,
            "close_reason": close.get("reason_code") if close else None}


def shadow_report(strategy_id: str, episodes: list[dict[str, Any]], events: list[dict[str, Any]],
                  confirmations: list[dict[str, Any]], outcomes: list[dict[str, Any]],
                  confirmation_sessions: dict[str, str | None] | None = None,
                  observation_count: int | None = None, status: str | None = None) -> dict[str, Any]:
    """Pure: the experiment metrics for `strategy_id` from records already read."""
    episodes = [e for e in episodes if e.get("strategy_id") == strategy_id]
    ids = {str(e.get("setup_id")) for e in episodes}
    by_setup: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in sorted(events, key=lambda e: str(e.get("occurred_at") or "")):
        if str(event.get("setup_id")) in ids:
            by_setup[str(event.get("setup_id"))].append(event)
    confirms = {str(c.get("setup_id")): c for c in confirmations
                if c.get("strategy_id") == strategy_id and str(c.get("setup_id")) in ids}
    sessions = confirmation_sessions or {}

    reached = Counter()
    pre_confirmation_direction_changes = 0
    closed_before_confirmation = Counter()
    for episode in episodes:
        sid = str(episode.get("setup_id"))
        timeline = by_setup.get(sid, [])
        states = [str(e.get("to_state")) for e in timeline] + [str(episode.get("lifecycle_state") or "DETECTED")]
        top = max((RANK[s] for s in states if s in RANK), default=0)
        if sid in confirms:
            top = max(top, RANK["CONFIRMED"])
        for stage, rank in RANK.items():
            if top >= rank:
                reached[stage] += 1
        if sid not in confirms:
            close = next((e for e in timeline if e.get("to_state") in {"INVALIDATED", "EXPIRED", "RESOLVED"}), None)
            if close:
                closed_before_confirmation[str(close.get("to_state"))] += 1
                if close.get("reason_code") == "DIRECTION_CHANGED":
                    pre_confirmation_direction_changes += 1

    rows = []
    for sid, confirmation in confirms.items():
        episode = next(e for e in episodes if str(e.get("setup_id")) == sid)
        plan = episode.get("confirmed_plan") or {}
        confirmed_at = _time(confirmation.get("confirmed_at"))
        fate = episode_outcome(by_setup.get(sid, []), confirmed_at)
        rr = plan.get("rr")
        rows.append({
            "setup_id": sid, "symbol": confirmation.get("symbol") or episode.get("symbol"),
            "direction": confirmation.get("direction") or episode.get("direction"),
            "setup_type": confirmation.get("setup_type") or episode.get("setup_type"),
            "session": sessions.get(str(confirmation.get("observation_id"))),
            "entry": plan.get("entry"), "stop": plan.get("stop_loss"), "target": plan.get("take_profit"), "rr": rr,
            "confirmed_at": confirmation.get("confirmed_at"), **fate,
            "minutes_to_active": _minutes(confirmed_at, _time(fate["active_at"])),
            "minutes_to_close": _minutes(confirmed_at, _time(fate["closed_at"])),
            "nominal_r": (float(rr) if rr is not None else None) if fate["outcome"] == "TARGET_HIT" else -1.0 if fate["outcome"] == "STOP_HIT" else None,
        })
    counts = Counter(row["outcome"] for row in rows)
    decided = counts["TARGET_HIT"] + counts["STOP_HIT"]
    post_confirmation_direction_changes = sum(1 for row in rows if row["close_reason"] == "DIRECTION_CHANGED")

    def breakdown(key: str) -> dict[str, dict[str, int]]:
        table: dict[str, Counter] = defaultdict(Counter)
        for row in rows:
            group = str(row.get(key) or "UNKNOWN")
            table[group]["confirmed"] += 1
            table[group][row["outcome"].lower()] += 1
        return {group: dict(values) for group, values in sorted(table.items())}

    valid_outcomes = [o for o in outcomes if str(o.get("setup_id")) in confirms
                      and o.get("observation_id") == confirms[str(o.get("setup_id"))].get("observation_id")]
    verified = [o for o in valid_outcomes if o.get("timestamp_quality") == "VERIFIED" and o.get("outcome_time_validity") == "OUTCOME_TIME_VALID"]
    horizon_labels: dict[str, Counter] = defaultdict(Counter)
    for outcome in verified:
        horizon_labels[str(outcome.get("horizon"))][str(outcome.get("label"))] += 1
    nominal = [row["nominal_r"] for row in rows if row["nominal_r"] is not None]
    return {
        "strategy_id": strategy_id,
        "status": status,
        "observations": observation_count,
        "episodes": len(episodes),
        "stages_reached": {stage: reached[stage] for stage in STAGES},
        "confirmed": len(rows),
        "active": sum(1 for row in rows if row["active_at"]),
        "outcomes": {name.lower(): counts[name] for name in OUTCOMES},
        "closed_before_confirmation": dict(closed_before_confirmation),
        "rates": {"confirmation_rate": _rate(len(rows), len(episodes)),
                  "target_hit_rate": _rate(counts["TARGET_HIT"], decided),
                  "stop_hit_rate": _rate(counts["STOP_HIT"], decided)},
        "rr_at_confirmation": _stats(row["rr"] for row in rows),
        "minutes_confirm_to_active": _stats(row["minutes_to_active"] for row in rows),
        "minutes_confirm_to_close": _stats(row["minutes_to_close"] for row in rows),
        "direction_change_closures_after_confirmation": post_confirmation_direction_changes,
        "direction_change_invalidations_before_confirmation": pre_confirmation_direction_changes,
        "by_symbol": breakdown("symbol"), "by_direction": breakdown("direction"),
        "by_session": breakdown("session"), "by_setup_type": breakdown("setup_type"),
        "nominal_r": {"values": nominal, "sum": round(sum(nominal), 2) if nominal else None, "n": len(nominal),
                      "assumptions": NOMINAL_R_ASSUMPTIONS},
        "verified_market_outcomes_by_horizon": {h: dict(c) for h, c in sorted(horizon_labels.items())},
        "confirmed_setups": sorted(rows, key=lambda row: str(row["confirmed_at"])),
    }


def load_shadow_report(strategy_id: str, status: str | None = None, outcomes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Reads the current store (observations module paths) and returns shadow_report()."""
    import observations
    episodes = observations.setup_episodes("all", 100000, include_shadow=True)
    confirmations = observations._read_jsonl(observations.CONFIRMATIONS_FILE)
    events = observations._read_jsonl(observations.LIFECYCLE_FILE)
    mine = [c for c in confirmations if c.get("strategy_id") == strategy_id]
    snapshots = observations.snapshots_by_observation_id(str(c.get("observation_id")) for c in mine)
    sessions = {oid: ((snap.get("session") or {}).get("session") if isinstance(snap.get("session"), dict) else snap.get("session"))
                for oid, snap in snapshots.items()}
    index = observations._observation_index()
    with index.lock:
        groups = index.groups("k_snap")
        count = sum(len(positions) for positions in groups.values() if index.summary(positions[0]).get("strategy_id") == strategy_id)
    return shadow_report(strategy_id, episodes, events, confirmations, outcomes or [], sessions, count, status)
