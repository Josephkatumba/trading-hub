"""Strategy Lab: per-strategy measurement of setups, confirmations and outcomes.

Read-only and on demand (never part of a scan). Every figure is computed per
strategy_id and strategies are never combined. Records without strategy_id are
trendline (read-time mapping).

Outcomes are classified only from existing MarketOutcome records, with the ML
dataset's integrity rules (ml_dataset._outcome_quarantine_reasons): an outcome
counts as verified only when its timestamps and candle chronology are proven.
Pending (no outcome yet) and unverified outcomes are reported as such, never
as target or stop hits. A win rate is only reported once enough verified
target/stop outcomes exist.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Iterable

import observations
from ml_dataset import _outcome_quarantine_reasons
from outcomes import DEFAULT_HORIZONS
from strategies import REGISTRY, record_strategy_id

TERMINAL = ("INVALIDATED", "EXPIRED", "RESOLVED")
STATES = ("DETECTED", "DEVELOPING", "CONFIRMING", "CONFIRMED", "ACTIVE", *TERMINAL)
OUTCOME_KINDS = ("pending", "unverified", "verified_target", "verified_stop", "verified_other")
# Minimum verified target+stop outcomes before a win rate is shown at all.
MIN_VERIFIED_FOR_RATE = 30


def classify_outcome(confirmation: dict[str, Any], outcomes: Iterable[dict[str, Any]],
                     snapshot: dict[str, Any] | None, horizons: tuple[str, ...] = DEFAULT_HORIZONS) -> tuple[str, str | None]:
    """(kind, horizon) of one confirmed setup's market path, from verified outcomes only.

    Barrier windows are nested, so the shortest horizon with a verified WIN/LOSS
    decides which barrier was touched first; otherwise the longest verified
    horizon (NO_HIT / AMBIGUOUS) is reported as verified_other.
    """
    own = [row for row in outcomes if row.get("record_type") in (None, "market_outcome")
           and str(row.get("observation_id")) == str(confirmation.get("observation_id"))]
    verified = {row.get("horizon"): row for row in own if not _outcome_quarantine_reasons(row, snapshot)}
    for horizon in horizons:
        label = str((verified.get(horizon) or {}).get("label") or "").upper()
        if label in ("WIN", "LOSS"):
            return ("verified_target" if label == "WIN" else "verified_stop"), horizon
    for horizon in reversed(horizons):
        if horizon in verified:
            return "verified_other", horizon
    return ("unverified" if own else "pending"), None


def _mode(strategy_id: str) -> str:
    try:
        return REGISTRY.mode(strategy_id)
    except KeyError:
        return "UNREGISTERED"


def _bucket() -> dict[str, Any]:
    return {"setups": 0, "confirmed": 0, **{kind: 0 for kind in OUTCOME_KINDS}}


def strategy_lab_report(market_outcomes: list[dict[str, Any]], recent_limit: int = 25,
                        min_verified_for_rate: int = MIN_VERIFIED_FOR_RATE) -> dict[str, Any]:
    first: dict[str, dict[str, Any]] = {}
    latest: dict[str, dict[str, Any]] = {}
    for summary in observations._observation_index().summaries():
        if summary.get("rt") != "setup_snapshot" or not summary.get("setup_id"):
            continue
        sid = str(summary["setup_id"])
        first.setdefault(sid, summary)
        latest[sid] = summary
    last_state: dict[str, str] = {}
    for event in observations._lifecycle_index().summaries():
        if event.get("to"):
            last_state[str(event.get("sid"))] = str(event["to"])
    confirmations = {str(row.get("setup_id")): row for row in observations.confirmation_events()}
    snapshots = observations.snapshots_by_observation_id(str(row.get("observation_id")) for row in confirmations.values())
    outcomes_by_setup: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in market_outcomes:
        outcomes_by_setup[str(row.get("setup_id"))].append(row)

    per_strategy: dict[str, dict[str, Any]] = {}
    for strategy_id in REGISTRY.registered():
        per_strategy[strategy_id] = None  # registered strategies are always listed, in registry order
    rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for sid, summary in latest.items():
        strategy_id = record_strategy_id(summary)
        confirmation = confirmations.get(sid)
        state = last_state.get(sid) or str(summary.get("lifecycle_state") or "DETECTED")
        outcome, horizon = (classify_outcome(confirmation, outcomes_by_setup.get(sid, []),
                                             snapshots.get(str(confirmation.get("observation_id"))))
                            if confirmation else (None, None))
        rows[strategy_id].append({"setup_id": sid, "symbol": summary.get("symbol"), "direction": summary.get("direction"),
            "timeframe": summary.get("timeframe") or "M15", "setup_type": summary.get("setup_type"),
            "lifecycle_state": state, "confirmed": confirmation is not None, "outcome": outcome, "outcome_horizon": horizon,
            "first_observed_at": first[sid].get("observed_at"), "last_observed_at": summary.get("observed_at"),
            "shadow": summary.get("shadow") is True})
        per_strategy.setdefault(strategy_id, None)

    report = []
    for strategy_id in per_strategy:
        items = rows.get(strategy_id, [])
        states = Counter(item["lifecycle_state"] for item in items)
        confirmed = [item for item in items if item["confirmed"]]
        outcomes = Counter(item["outcome"] for item in confirmed)
        groups: dict[str, dict[str, dict[str, Any]]] = {name: defaultdict(_bucket) for name in
                                                        ("by_instrument", "by_direction", "by_timeframe", "by_setup_type")}
        for item in items:
            for name, key in (("by_instrument", item["symbol"]), ("by_direction", item["direction"]),
                              ("by_timeframe", item["timeframe"]), ("by_setup_type", item["setup_type"])):
                bucket = groups[name][str(key or "UNKNOWN")]
                bucket["setups"] += 1
                if item["confirmed"]:
                    bucket["confirmed"] += 1
                    bucket[item["outcome"]] += 1
        decisive = outcomes["verified_target"] + outcomes["verified_stop"]
        enough = decisive >= min_verified_for_rate
        strategy = REGISTRY.get(strategy_id) if strategy_id in REGISTRY.registered() else None
        report.append({
            "strategy_id": strategy_id, "mode": _mode(strategy_id), "version": strategy.version if strategy else None,
            "shadow_records": sum(1 for item in items if item["shadow"]),
            "setups": {"total": len(items), "open": sum(states[s] for s in STATES if s not in TERMINAL),
                       "closed": sum(states[s] for s in TERMINAL), "by_state": {s: states.get(s, 0) for s in STATES}},
            "confirmations": len(confirmed),
            "outcomes": {"horizons": list(DEFAULT_HORIZONS), **{kind: outcomes.get(kind, 0) for kind in OUTCOME_KINDS}},
            "win_rate": round(outcomes["verified_target"] / decisive * 100, 1) if enough else None,
            "win_rate_note": (f"Based on {decisive} verified target/stop outcomes." if enough else
                              f"Not shown: {decisive} verified target/stop outcomes (needs {min_verified_for_rate})."),
            **{name: {key: dict(value) for key, value in sorted(group.items())} for name, group in groups.items()},
            "recent": sorted(items, key=lambda item: str(item["last_observed_at"] or ""), reverse=True)[:recent_limit],
        })
    return {"strategies": report, "min_verified_for_rate": min_verified_for_rate,
            "outcome_rules": "Verified = MarketOutcome passing the ML dataset integrity checks (verified timestamps and candle chronology). "
                             "Pending = no outcome yet; unverified = outcome not yet provable. Neither counts as a target or stop hit.",
            "comparison_note": "Strategies are measured separately and never combined. Small samples do not show which strategy is better."}
