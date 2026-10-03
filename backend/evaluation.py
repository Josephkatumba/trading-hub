"""Phase 11: the historical evaluation layer (foundation).

Deterministic, transparent and read-only. It never creates, changes or rejects a
setup: strategies produce setups, and this layer only reports what has happened,
historically, to confirmed setups that shared a condition with the one in question.

What counts as evidence
  Only a confirmed setup's VERIFIED market outcome (MarketOutcome passing the ML
  dataset integrity checks, via strategy_lab.classify_outcome): target first,
  stop first, or verified other (no barrier / ambiguous candle). Pending outcomes,
  unverified outcomes and quarantined records are counted and shown, never used as
  evidence. Strategies are never mixed: every table is one strategy_id.

Conditions
  Fixed, documented buckets of values stored on the confirmation snapshot (see
  CONDITIONS). A condition whose value is not recorded is "UNRECORDED", never
  guessed. Nothing is fitted, weighted or combined into a score.

Sample size
  A target share is shown for a condition value only once it has at least
  MIN_VERIFIED verified target/stop outcomes (the Strategy Lab's 30). Below that
  the status is INSUFFICIENT_VERIFIED_DATA and no rate is given. Even above it a
  share is a historical description, not a prediction.

Similar setups
  For one setup: for each of its condition values, the verified history of the
  same strategy's setups confirmed BEFORE it (no hindsight), excluding itself.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable, Iterable, Mapping

from ml_dataset import _outcome_quarantine_reasons
from strategies import record_strategy_id
from strategy_lab import MIN_VERIFIED_FOR_RATE, classify_outcome

EVALUATION_VERSION = "historical-evaluation-v1"
MIN_VERIFIED = MIN_VERIFIED_FOR_RATE
INSUFFICIENT = "INSUFFICIENT_VERIFIED_DATA"
UNRECORDED = "UNRECORDED"


def _get(record: Mapping[str, Any], path: str) -> Any:
    value: Any = record
    for part in path.split("."):
        if not isinstance(value, Mapping):
            return None
        value = value.get(part)
    return value


def _band(value: Any, edges: Iterable[float], fmt: str = "{:g}") -> str:
    """'<a', 'a-b', ..., '>=z' for a number; UNRECORDED otherwise."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return UNRECORDED
    edges = list(edges)
    if number < edges[0]:
        return "<" + fmt.format(edges[0])
    for low, high in zip(edges, edges[1:]):
        if low <= number < high:
            return fmt.format(low) + "-" + fmt.format(high)
    return ">=" + fmt.format(edges[-1])


def _text(path: str) -> Callable[[Mapping[str, Any]], str]:
    return lambda snapshot: str(_get(snapshot, path)).upper() if _get(snapshot, path) not in (None, "") else UNRECORDED


def _bias_alignment(snapshot: Mapping[str, Any]) -> str:
    bias, direction = str(_get(snapshot, "features.higher_timeframe_bias") or "").upper(), str(snapshot.get("direction") or "")
    if bias not in {"BULLISH", "BEARISH"} or direction not in {"LONG", "SHORT"}:
        return UNRECORDED if not bias else "NEUTRAL"
    return "WITH_H1_BIAS" if (bias == "BULLISH") == (direction == "LONG") else "AGAINST_H1_BIAS"


# name -> (label, extractor, strategies it applies to (None = all))
CONDITIONS: dict[str, tuple[str, Callable[[Mapping[str, Any]], str], frozenset[str] | None]] = {
    "instrument": ("Instrument", lambda s: str(s.get("symbol") or UNRECORDED), None),
    "direction": ("Direction", lambda s: str(s.get("direction") or UNRECORDED), None),
    "strategy_version": ("Strategy version", lambda s: str(s.get("strategy_version") or UNRECORDED), None),
    "setup_type": ("Setup type", _text("setup_type"), None),
    "session": ("Session at confirmation", _text("session.session"), None),
    "score": ("Score", lambda s: _band(s.get("score"), (60, 70, 80, 90), "{:.0f}"), None),
    "rr": ("Planned R:R", lambda s: _band(_get(s, "features.rr"), (2, 3, 5)), None),
    "h1_bias": ("H1 bias alignment", _bias_alignment, frozenset({"trendline", "trendline_v5"})),
    "retracement": ("Pullback depth", lambda s: _band(_get(s, "strategy_evidence.pullback.retracement"), (0.382, 0.5)),
                    frozenset({"trend_momentum"})),
    "d1_context": ("D1 context", _text("strategy_evidence.trend.d1.status"), frozenset({"trend_momentum"})),
    "efficiency": ("Impulse efficiency", lambda s: _band(_get(s, "strategy_evidence.momentum.efficiency"), (0.45, 0.6)),
                   frozenset({"trend_momentum"})),
    "stop_distance": ("Stop distance (ATR H1)", lambda s: _band(_get(s, "strategy_evidence.plan.risk") and
                      _get(s, "strategy_evidence.plan.risk") / _get(s, "strategy_evidence.atr.H1")
                      if _get(s, "strategy_evidence.atr.H1") else None, (1.0, 1.5, 2.0)), frozenset({"trend_momentum"})),
    "risk_quality": ("Stop quality", _text("strategy_evidence.stop.risk_quality"), frozenset({"trend_momentum"})),
}


def conditions_of(snapshot: Mapping[str, Any]) -> dict[str, str]:
    strategy_id = record_strategy_id(snapshot)
    return {name: extract(snapshot) for name, (_, extract, scope) in CONDITIONS.items()
            if scope is None or strategy_id in scope}


def _empty() -> dict[str, int]:
    return {"confirmed": 0, "verified_target": 0, "verified_stop": 0, "verified_other": 0,
            "unverified": 0, "pending": 0, "quarantined": 0}


def _finish(bucket: dict[str, int]) -> dict[str, Any]:
    decisive = bucket["verified_target"] + bucket["verified_stop"]
    enough = decisive >= MIN_VERIFIED
    return {**bucket, "verified_decisive": decisive,
            "status": "SUFFICIENT" if enough else INSUFFICIENT,
            "target_share": round(bucket["verified_target"] / decisive, 3) if enough else None}


def setup_records(confirmations: Iterable[Mapping[str, Any]], snapshots: Mapping[str, Mapping[str, Any]],
                  outcomes: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """One record per confirmed setup: strategy, time, conditions and verified outcome kind."""
    by_setup: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in outcomes:
        by_setup[str(row.get("setup_id"))].append(row)
    records = []
    for confirmation in confirmations:
        snapshot = snapshots.get(str(confirmation.get("observation_id")))
        own = [row for row in by_setup.get(str(confirmation.get("setup_id")), [])
               if str(row.get("observation_id")) == str(confirmation.get("observation_id"))]
        kind, horizon = classify_outcome(dict(confirmation), own, dict(snapshot) if snapshot else None)
        # Quarantined: historical records whose decision snapshot is missing or whose time
        # basis was never verified. They can never become evidence. Other unverified
        # outcomes failed a chronology/candle check.
        if kind == "unverified" and any(set(_outcome_quarantine_reasons(dict(row), dict(snapshot) if snapshot else None)) &
                                        {"LINKED_OBSERVATION_MISSING_OR_AMBIGUOUS", "LINKED_OBSERVATION_TIME_UNVERIFIED"}
                                        for row in own):
            kind = "quarantined"
        records.append({"setup_id": confirmation.get("setup_id"), "strategy_id": record_strategy_id(confirmation),
                        "confirmed_at": str(confirmation.get("confirmed_at") or ""),
                        "outcome": kind, "horizon": horizon,
                        "shadow": confirmation.get("shadow") is True,
                        "conditions": conditions_of(snapshot) if snapshot else {}})
    return records


def _tally(records: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    bucket = _empty()
    for record in records:
        bucket["confirmed"] += 1
        bucket[record["outcome"]] += 1
    return bucket


def condition_report(records: list[Mapping[str, Any]], strategy_ids: Iterable[str]) -> dict[str, Any]:
    """Per strategy: totals and, for every condition value, its verified outcome counts."""
    strategies = []
    for strategy_id in strategy_ids:
        own = [record for record in records if record["strategy_id"] == strategy_id]
        tables = {}
        for name, (label, _, scope) in CONDITIONS.items():
            if scope is not None and strategy_id not in scope:
                continue
            values: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
            for record in own:
                values[record["conditions"].get(name, UNRECORDED)].append(record)
            tables[name] = {"label": label, "values": {value: _finish(_tally(rows)) for value, rows in sorted(values.items())}}
        strategies.append({"strategy_id": strategy_id, "totals": _finish(_tally(own)), "conditions": tables})
    return {"evaluation_version": EVALUATION_VERSION, "min_verified": MIN_VERIFIED, "strategies": strategies,
            "rules": "Verified = MarketOutcome passing the ML dataset integrity checks. Pending, unverified and "
                     "quarantined outcomes are counted but never used as evidence. A target share is shown only with "
                     f"at least {MIN_VERIFIED} verified target/stop outcomes; it describes history and predicts nothing.",
            "comparison_note": "Each table is one strategy. Strategies are never combined."}


def similar_setups(snapshot: Mapping[str, Any], records: list[Mapping[str, Any]],
                   before: str | None = None) -> dict[str, Any]:
    """What happened to the same strategy's earlier confirmed setups sharing each condition."""
    strategy_id = record_strategy_id(snapshot)
    own_id = snapshot.get("setup_id")
    history = [record for record in records if record["strategy_id"] == strategy_id and record["setup_id"] != own_id
               and (before is None or record["confirmed_at"] < before)]
    conditions = conditions_of(snapshot)
    rows = []
    for name, value in conditions.items():
        matching = [record for record in history if record["conditions"].get(name) == value] if value != UNRECORDED else []
        rows.append({"condition": name, "label": CONDITIONS[name][0], "value": value,
                     **_finish(_tally(matching))})
    return {"evaluation_version": EVALUATION_VERSION, "strategy_id": strategy_id, "setup_id": own_id,
            "history_before": before, "min_verified": MIN_VERIFIED, "strategy_totals": _finish(_tally(history)),
            "conditions": rows,
            "note": "Each row is one condition on its own, never combined into a score. Only earlier confirmed setups "
                    "of the same strategy count, and only verified outcomes are evidence."}
