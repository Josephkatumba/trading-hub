"""Read-only dataset and source-time audit helpers for future ML preparation.

This module never writes observations, lifecycle events, or outcomes. Feature
construction is an explicit allow-list so derived/future fields cannot leak in.
"""
from __future__ import annotations

import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable

from observations import CONFIRMATIONS_FILE, LIFECYCLE_FILE, LOG_FILE
from outcomes import MARKET_OUTCOMES_FILE, TRADE_OUTCOMES_FILE, configured_horizons
from market_time import parse_aware_utc
from strategies import LEGACY_STRATEGY_ID, REGISTRY, record_strategy_id

DATASET_SCHEMA_VERSION = "ml-observation-v1"
LABEL_DEFINITION = "target-invalidation-first-v1"
FUTURE_TOLERANCE_SECONDS = 5.0

# Only snapshot-time fields are admitted. IDs and timestamps remain join/audit
# metadata, never model features. Post-observation outcomes/events are excluded.
FEATURE_PATHS = (
    "symbol", "timeframe", "direction", "setup_type", "lifecycle_state",
    "reference_price", "proposed_entry", "proposed_stop_loss",
    "proposed_take_profit", "invalidation_price", "score",
    "features.price", "features.bid", "features.ask", "features.spread",
    "features.change_pct", "features.rsi", "features.ema20", "features.ema50",
    "features.atr", "features.higher_timeframe_bias", "features.market_bias",
    "features.momentum", "features.structure", "features.price_action",
    "features.price_action_state", "features.trendline", "features.trendline_state",
    "features.nearest_level", "features.nearest_level_type", "features.nearest_level_atr",
    "features.spread_atr", "features.crt_context", "features.crt_state",
    "features.rr", "features.risk_distance", "features.reward_distance",
    "rule_evidence.trendline_gate", "rule_evidence.confirmation_alignment",
    "score_breakdown.trendline",
    "score_breakdown.structure", "score_breakdown.support_resistance",
    "score_breakdown.price_action", "score_breakdown.session",
    "score_breakdown.momentum", "score_breakdown.higher_timeframe",
    "score_breakdown.crt", "session.session", "session.london_high",
    "session.london_low", "session.london_complete", "session.session_alignment",
)
_CATEGORICAL_FEATURES = {
    "symbol", "timeframe", "direction", "setup_type", "lifecycle_state",
    "features.higher_timeframe_bias", "features.market_bias", "features.momentum",
    "features.structure", "features.price_action", "features.price_action_state",
    "features.trendline", "features.trendline_state", "features.nearest_level_type",
    "features.crt_context", "features.crt_state", "session.session",
    "session.session_alignment",
}
_BOOLEAN_FEATURES = {"features.london_complete", "session.london_complete",
                     "rule_evidence.trendline_gate", "rule_evidence.confirmation_alignment"}


def _parse_time(value: Any) -> datetime | None:
    return parse_aware_utc(value)


def _timestamp_verified(snapshot: dict[str, Any]) -> bool:
    provenance = snapshot.get("time_provenance") or {}
    quality = snapshot.get("data_quality") or {}
    observed = _parse_time(snapshot.get("observed_at") or snapshot.get("timestamp"))
    source = _parse_time(snapshot.get("source_timestamp"))
    flags = set(quality.get("flags") or [])
    return bool(provenance.get("timezone_normalization_status") == "VERIFIED" and
        quality.get("timestamp_quality") == "VERIFIED" and observed and source and
        (source - observed).total_seconds() <= FUTURE_TOLERANCE_SECONDS and
        "FUTURE_SOURCE_TIMESTAMP" not in flags)


def _timestamp_offset_seconds(left: Any, right: Any) -> float | None:
    first, second = _parse_time(left), _parse_time(right)
    return round((first - second).total_seconds(), 3) if first and second else None


def _outcome_quarantine_reasons(outcome: dict[str, Any],
                                snapshot: dict[str, Any] | None = None) -> list[str]:
    reasons = []
    if outcome.get("timestamp_quality") != "VERIFIED":
        reasons.append("OUTCOME_TIMESTAMP_QUALITY_MISSING_OR_UNVERIFIED")
    if (outcome.get("data_quality") or {}).get("timestamp_quality") != "VERIFIED":
        reasons.append("OUTCOME_DATA_QUALITY_TIMESTAMP_MISSING_OR_UNVERIFIED")
    if outcome.get("outcome_time_validity") != "OUTCOME_TIME_VALID":
        reasons.append("OUTCOME_CHRONOLOGY_MISSING_OR_INVALID")
    if ((outcome.get("outcome_time_validation") or {}).get("outcome_time_validity") !=
            "OUTCOME_TIME_VALID"):
        reasons.append("OUTCOME_TIME_VALIDATION_MISSING_OR_INVALID")
    if snapshot is None:
        reasons.append("LINKED_OBSERVATION_MISSING_OR_AMBIGUOUS")
    elif not _timestamp_verified(snapshot):
        reasons.append("LINKED_OBSERVATION_TIME_UNVERIFIED")
    else:
        decision = _parse_time(snapshot.get("observed_at") or snapshot.get("timestamp"))
        resolved = _parse_time(outcome.get("resolved_at"))
        validation = outcome.get("outcome_time_validation") or {}
        first = _parse_time(validation.get("first_candidate_candle_timestamp"))
        last = _parse_time(validation.get("last_candidate_candle_timestamp"))
        if (decision is None or resolved is None or first is None or last is None or
                resolved < decision or first <= decision or last < first or last > resolved):
            reasons.append("OUTCOME_RESOLUTION_CHRONOLOGY_INVALID_OR_INCOMPLETE")
        if (validation.get("every_candidate_strictly_after_observation") is not True or
                validation.get("candidate_candles_chronological") is not True):
            reasons.append("OUTCOME_CANDLE_ORDER_NOT_PROVEN")
    return reasons


def _get_path(record: dict[str, Any], path: str) -> Any:
    value: Any = record
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _is_prospective_snapshot(snapshot: dict[str, Any]) -> bool:
    if snapshot.get("record_type") != "setup_snapshot":
        return False
    provenance = snapshot.get("time_provenance") or {}
    bar = provenance.get("bar_open_time") or {}
    tick = provenance.get("tick_time") or {}
    return bool(snapshot.get("timeframe") and snapshot.get("observed_at") and
        provenance.get("backend_received_at") and provenance.get("observation_time") and
        bar.get("raw_mt5_epoch") is not None and tick.get("raw_mt5_epoch") is not None)


def snapshot_features(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Return only allow-listed values already present at observation time."""
    features = {}
    for path in FEATURE_PATHS:
        value = _get_path(snapshot, path)
        # Legacy rows stored most equivalent fields at top level.
        if value is None and path.startswith("features."):
            value = snapshot.get(path.split(".", 1)[1])
        elif value is None and path.startswith("score_breakdown."):
            value = (snapshot.get("score_breakdown") or {}).get(path.split(".", 1)[1])
        elif value is None and path.startswith("session."):
            key = path.split(".", 1)[1]
            value = snapshot.get(key)
            if value is None and key == "session" and isinstance(snapshot.get("session"), str):
                value = snapshot.get("session")
        elif value is None and path == "setup_type":
            value = snapshot.get("setup_family")
        elif value is None and path == "lifecycle_state":
            value = snapshot.get("state")
        elif value is None and path == "reference_price":
            value = snapshot.get("price")
        if value is not None:
            features[path] = value
    return features


def audit_candle_ordering(bars: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Check supplied MT5 candle sequence without sorting or mutating it."""
    stamps: list[float] = []
    invalid = 0
    for bar in bars:
        try:
            value = bar.get("time")
            stamp = float(value) if isinstance(value, (int, float)) else _parse_time(value).timestamp()
            if not math.isfinite(stamp):
                raise ValueError("non-finite timestamp")
            stamps.append(stamp)
        except (AttributeError, TypeError, ValueError, OverflowError):
            invalid += 1
    inversions = sum(1 for left, right in zip(stamps, stamps[1:]) if right < left)
    duplicates = sum(1 for left, right in zip(stamps, stamps[1:]) if right == left)
    return {"count": len(stamps), "invalid_timestamps": invalid,
            "out_of_order_pairs": inversions, "duplicate_adjacent_timestamps": duplicates,
            "chronological": invalid == 0 and inversions == 0,
            "first_timestamp": stamps[0] if stamps else None,
            "last_timestamp": stamps[-1] if stamps else None}


def _timestamp_audit(observations: list[dict[str, Any]]) -> dict[str, Any]:
    offsets: list[float] = []
    by_symbol: dict[str, list[float]] = defaultdict(list)
    by_timeframe: dict[str, list[float]] = defaultdict(list)
    by_symbol_timeframe: dict[str, list[float]] = defaultdict(list)
    counts = Counter()
    for row in observations:
        observed = _parse_time(row.get("observed_at") or row.get("timestamp"))
        source = _parse_time(row.get("source_timestamp"))
        if source is None:
            counts["missing_or_invalid_source_timestamp"] += 1
            continue
        if observed is None:
            counts["missing_or_invalid_observation_timestamp"] += 1
            continue
        offset = (source - observed).total_seconds()
        offsets.append(offset)
        by_symbol[str(row.get("symbol") or "UNKNOWN")].append(offset)
        timeframe = str(row.get("timeframe") or "UNKNOWN")
        by_timeframe[timeframe].append(offset)
        by_symbol_timeframe[f"{row.get('symbol') or 'UNKNOWN'}|{timeframe}"].append(offset)
        if offset > FUTURE_TOLERANCE_SECONDS:
            counts["future_source_timestamp"] += 1
        elif offset >= 0:
            counts["non_future_source_timestamp"] += 1
        else:
            counts["source_timestamp_before_observation"] += 1
        quality = row.get("data_quality") or {}
        if quality.get("status") == "DEGRADED" or quality.get("flags"):
            counts["stored_degraded"] += 1

    def summary(values: list[float]) -> dict[str, Any]:
        if not values:
            return {"count": 0, "mean_seconds": None, "median_seconds": None,
                    "min_seconds": None, "max_seconds": None, "range_seconds": None,
                    "population_stddev_seconds": None}
        return {"count": len(values), "mean_seconds": round(statistics.fmean(values), 3),
                "median_seconds": round(statistics.median(values), 3),
                "min_seconds": round(min(values), 3), "max_seconds": round(max(values), 3),
                "range_seconds": round(max(values) - min(values), 3),
                "population_stddev_seconds": round(statistics.pstdev(values), 3)}

    symbol_medians = [summary(values)["median_seconds"] for values in by_symbol.values() if values]
    symbol_spread = max(symbol_medians) - min(symbol_medians) if symbol_medians else None
    positive_ratio = (sum(1 for value in offsets if value > FUTURE_TOLERANCE_SECONDS) / len(offsets)) if offsets else None
    mostly_future = positive_ratio is not None and positive_ratio >= 0.95
    symbol_stable = symbol_spread is not None and symbol_spread <= 60
    if mostly_future and symbol_stable and len(by_timeframe) == 1:
        pattern = "COMMON_FUTURE_OFFSET_ACROSS_SYMBOLS; WITHIN_GROUP_VARIATION_REMAINS; TIMEFRAME_DEPENDENCE_UNTESTABLE"
    elif mostly_future and symbol_stable:
        pattern = "COMMON_FUTURE_OFFSET_ACROSS_SYMBOLS; COMPARE_TIMEFRAME_MEDIANS"
    elif mostly_future:
        pattern = "FUTURE_OFFSET_PRESENT_BUT_SYMBOL_VARIATION_REQUIRES_REVIEW"
    else:
        pattern = "VARIABLE_OR_NOT_PREDOMINANTLY_FUTURE"
    return {"definition": "source_timestamp minus observed_at, both parsed as timezone-aware instants",
            "future_tolerance_seconds": FUTURE_TOLERANCE_SECONDS,
            "offset_seconds": summary(offsets), "counts": dict(counts),
            "pattern": pattern, "future_sample_ratio": positive_ratio,
            "symbol_median_spread_seconds": round(symbol_spread, 3) if symbol_spread is not None else None,
            "timeframe_medians": {k: summary(v)["median_seconds"] for k, v in sorted(by_timeframe.items())},
            "timeframe_dependence_assessable": len(by_timeframe) > 1,
            "by_symbol": {k: summary(v) for k, v in sorted(by_symbol.items())},
            "by_timeframe": {k: summary(v) for k, v in sorted(by_timeframe.items())},
            "by_symbol_timeframe": {k: summary(v) for k, v in sorted(by_symbol_timeframe.items())},
            "interpretation": "A positive offset means the source time is later than the backend observation time. No timestamps are corrected."}


def _snapshot_quality(snapshot: dict[str, Any]) -> tuple[str, list[str]]:
    quality = snapshot.get("data_quality") or {}
    flags = list(quality.get("flags") or [])
    provenance = snapshot.get("time_provenance") or {}
    if provenance.get("timezone_normalization_status") != "VERIFIED":
        flags.append("SOURCE_TIME_BASIS_UNVERIFIED")
    observed = _parse_time(snapshot.get("observed_at") or snapshot.get("timestamp"))
    source = _parse_time(snapshot.get("source_timestamp"))
    if source is None:
        flags.append("SOURCE_TIMESTAMP_MISSING_OR_INVALID")
    if observed is None:
        flags.append("OBSERVATION_TIMESTAMP_MISSING_OR_INVALID")
    if source is not None and observed is not None and (source - observed).total_seconds() > FUTURE_TOLERANCE_SECONDS:
        flags.append("FUTURE_SOURCE_TIMESTAMP")
    return ("DEGRADED" if quality.get("status") == "DEGRADED" or flags else "OK",
            sorted(set(flags)))


def audit_outcome_chronology(outcomes: list[dict[str, Any]],
                             snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    """Verify stored outcome resolution times follow their decision snapshots."""
    id_counts = Counter(str(row.get("observation_id")) for row in snapshots if row.get("observation_id"))
    ambiguous_ids = {oid for oid, count in id_counts.items() if count > 1}
    by_id = {str(row.get("observation_id")): row for row in snapshots
             if row.get("observation_id") and str(row.get("observation_id")) not in ambiguous_ids}
    checks = Counter()
    invalid: list[str] = []
    for outcome in outcomes:
        snapshot = by_id.get(str(outcome.get("observation_id")))
        if not snapshot:
            if str(outcome.get("observation_id")) in ambiguous_ids:
                checks["ambiguous_observation_id"] += 1
            else:
                checks["snapshot_not_found"] += 1
            continue
        decision = _parse_time(snapshot.get("observed_at") or snapshot.get("timestamp"))
        resolved = _parse_time(outcome.get("resolved_at"))
        if decision is None or resolved is None:
            checks["invalid_or_missing_time"] += 1
        elif resolved < decision:
            checks["resolved_before_observation"] += 1
            invalid.append(str(outcome.get("outcome_id") or outcome.get("observation_id")))
        else:
            checks["resolution_not_before_observation"] += 1
    return {"outcomes_checked": len(outcomes), "counts": dict(checks),
            "invalid_outcome_ids": invalid,
            "historical_candles_available": False,
            "note": "Stored outcomes retain resolution timestamps, not candle arrays; label-time order can be checked, but historical OHLC ordering cannot be reconstructed."}


def prepare_dataset(observations: list[dict[str, Any]], outcomes: list[dict[str, Any]],
                    lifecycle_events: list[dict[str, Any]], confirmations: list[dict[str, Any]],
                    horizons: tuple[str, ...] | None = None,
                    include_projection: bool = True) -> dict[str, Any]:
    """Produce a non-persisted audit projection and aggregate readiness stats."""
    horizons = horizons or configured_horizons()
    snapshots = [r for r in observations if r.get("record_type") == "setup_snapshot" or not r.get("record_type")]
    observation_id_counts = Counter(str(row.get("observation_id")) for row in snapshots if row.get("observation_id"))
    ambiguous_observation_ids = {oid for oid, count in observation_id_counts.items() if count > 1}
    snapshots_by_observation = {str(row.get("observation_id")): row for row in snapshots
        if row.get("observation_id") and observation_id_counts[str(row.get("observation_id"))] == 1}
    duplicate_observation_rows = sum(count - 1 for count in observation_id_counts.values() if count > 1)
    ambiguous_observation_rows = sum(count for count in observation_id_counts.values() if count > 1)
    terminal_by_setup: dict[str, str] = {}
    for event in lifecycle_events:
        state = str(event.get("to_state") or "").upper()
        if state in {"INVALIDATED", "EXPIRED", "RESOLVED"}:
            terminal_by_setup[str(event.get("setup_id") or "")] = state
    confirmed_ids = {str(event.get("observation_id")) for event in confirmations if event.get("observation_id")}
    outcome_key_counts = Counter((str(row.get("observation_id")), str(row.get("horizon")))
                                 for row in outcomes if row.get("record_type") == "market_outcome")
    ambiguous_outcome_keys = {key for key, count in outcome_key_counts.items() if count > 1}
    by_observation_horizon = {(str(row.get("observation_id")), str(row.get("horizon"))): row
        for row in outcomes if row.get("record_type") == "market_outcome"
        and outcome_key_counts[(str(row.get("observation_id")), str(row.get("horizon")))] == 1}
    label_counts = Counter()
    quarantined_outcomes = 0
    quarantine_reason_counts = Counter()
    quarantine_examples = []
    for item in outcomes:
        if item.get("record_type") != "market_outcome":
            continue
        linked = snapshots_by_observation.get(str(item.get("observation_id")))
        reasons = _outcome_quarantine_reasons(item, linked)
        if reasons:
            quarantined_outcomes += 1
            quarantine_reason_counts.update(reasons)
            if len(quarantine_examples) < 5:
                quarantine_examples.append({"outcome_id": item.get("outcome_id"),
                    "observation_id": item.get("observation_id"), "setup_id": item.get("setup_id"),
                    "horizon": item.get("horizon"), "label": item.get("label"),
                    "resolved_at": item.get("resolved_at"),
                    "linked_observed_at": (linked or {}).get("observed_at") or (linked or {}).get("timestamp"),
                    "linked_source_timestamp": (linked or {}).get("source_timestamp"),
                    "outcome_source_timestamp": (item.get("data_quality") or {}).get("source_timestamp"),
                    "outcome_source_minus_resolution_seconds": _timestamp_offset_seconds(
                        (item.get("data_quality") or {}).get("source_timestamp"), item.get("resolved_at")),
                    "linked_raw_bar": (((linked or {}).get("time_provenance") or {}).get("bar_open_time") or {}),
                    "quarantine_reasons": reasons})
            continue
        label_counts[str(item.get("label") or "UNLABELED").upper()] += 1
    cohort_counts = Counter()
    exclusion_counts = Counter()
    quality_counts = Counter()
    feature_present = Counter()
    projection: list[dict[str, Any]] = []
    projection_row_count = 0
    usable_count = 0
    usable_observation_ids: set[str] = set()
    target_rows = 0
    for row_number, snapshot in enumerate(snapshots, start=1):
        oid = str(snapshot.get("observation_id") or "")
        setup_id = str(snapshot.get("setup_id") or "")
        rules = snapshot.get("rule_evidence") or {}
        is_confirmed = rules.get("strategy_valid") is True if snapshot.get("record_type") == "setup_snapshot" else snapshot.get("strategy_valid") is True
        terminal = terminal_by_setup.get(setup_id)
        if terminal == "INVALIDATED": cohort_counts["invalidated_observations"] += 1
        elif terminal == "EXPIRED": cohort_counts["expired_observations"] += 1
        if is_confirmed:
            cohort_counts["confirmed_observations"] += 1
        else:
            cohort_counts["watch_observations"] += 1
        ambiguous_id = oid in ambiguous_observation_ids
        has_confirmation = oid in confirmed_ids and not ambiguous_id
        cohort_counts["observations_with_confirmation_event"] += int(has_confirmation)

        features = snapshot_features(snapshot)
        for name in features:
            feature_present[name] += 1
        quality, flags = _snapshot_quality(snapshot)
        quality_counts[quality.lower()] += 1
        missing_minimum = [path for path in ("symbol", "timeframe", "direction", "reference_price")
                           if path not in features]
        if missing_minimum:
            exclusion_counts["missing_required_decision_fields"] += 1
        if ambiguous_id:
            exclusion_counts["ambiguous_observation_id"] += 1
        if quality != "OK":
            exclusion_counts["degraded_or_untrusted_source_time"] += 1

        for horizon in horizons:
            outcome_key = (oid, horizon)
            outcome = None if ambiguous_id or outcome_key in ambiguous_outcome_keys else by_observation_horizon.get(outcome_key)
            quarantine = bool(outcome and _outcome_quarantine_reasons(
                outcome, snapshots_by_observation.get(oid)))
            if outcome and not quarantine:
                target_rows += 1
                label = str(outcome.get("label") or "UNLABELED").upper()
            elif quarantine:
                label = str(outcome.get("label") or "QUARANTINED").upper()
            elif has_confirmation:
                label = "PENDING"
            else:
                label = "NOT_APPLICABLE"
            eligible_features = not missing_minimum and quality == "OK"
            if not snapshot.get("record_type"):
                readiness = "NOT_READY_LEGACY"
            elif quarantine:
                readiness = "QUARANTINED_HISTORICAL_OUTCOME"
            elif quality != "OK":
                readiness = "NOT_READY_TIMESTAMP"
            elif missing_minimum:
                readiness = "NOT_READY_MISSING_FEATURES"
            elif label not in {"WIN", "LOSS"}:
                readiness = "NOT_READY_OUTCOME"
            else:
                readiness = "ML_READY"
            usable_target = readiness == "ML_READY" and not ambiguous_id
            cohort_counts[f"readiness_{readiness.lower()}"] += 1
            if label in {"PENDING", "UNLABELED"}:
                exclusion_counts["missing_or_incomplete_outcome"] += 1
            elif label == "NOT_APPLICABLE":
                reason = ("confirmed_observation_without_confirmation_event" if is_confirmed
                          else "watch_observation_has_no_market_outcome")
                exclusion_counts[reason] += 1
            elif label in {"NO_HIT", "AMBIGUOUS"}:
                exclusion_counts[f"outcome_{label.lower()}_not_binary_target"] += 1
            if label in {"WIN", "LOSS"} and not eligible_features:
                exclusion_counts["resolved_outcome_but_ineligible_features_or_time"] += 1
            if outcome_key in ambiguous_outcome_keys:
                exclusion_counts["ambiguous_outcome_link"] += 1
            usable_count += int(usable_target)
            if usable_target:
                usable_observation_ids.add(oid)
            cohort_tags = ["CONFIRMED" if is_confirmed else "WATCH"]
            if terminal in {"INVALIDATED", "EXPIRED"}:
                cohort_tags.append(terminal)
            if missing_minimum:
                cohort_tags.append("INSUFFICIENT_DECISION_FIELDS")
            if quality != "OK":
                cohort_tags.append("DEGRADED_OR_UNTRUSTED_TIME")
            if ambiguous_id:
                cohort_tags.append("AMBIGUOUS_OBSERVATION_ID")
            if outcome_key in ambiguous_outcome_keys:
                cohort_tags.append("AMBIGUOUS_OUTCOME_LINK")
            if label in {"PENDING", "UNLABELED", "NOT_APPLICABLE"}:
                cohort_tags.append("INSUFFICIENT_TARGET")
            projection_row_count += 1
            if include_projection:
                projection.append({
                "dataset_schema_version": DATASET_SCHEMA_VERSION,
                "dataset_row_id": f"raw-observation-{row_number}-horizon-{horizon}",
                "observation_id": oid, "setup_id": setup_id,
                "observed_at": snapshot.get("observed_at") or snapshot.get("timestamp"),
                "decision_class": "CONFIRMED" if is_confirmed else "WATCH",
                "cohort_tags": cohort_tags,
                "terminal_lifecycle_state": terminal,
                "time_quality": quality, "time_quality_flags": flags,
                "features": features,
                "target": {"horizon": horizon, "label": label,
                           "label_definition": (outcome or {}).get("label_definition", LABEL_DEFINITION),
                           "outcome_id": (outcome or {}).get("outcome_id"),
                           "readiness": readiness},
                "ml_usable": usable_target,
                })

    eligible_confirmation_ids = confirmed_ids - ambiguous_observation_ids
    expected_confirmed_targets = len(eligible_confirmation_ids) * len(horizons)
    resolved_confirmed_targets = sum(1 for (oid, horizon), _ in by_observation_horizon.items()
                                     if oid in eligible_confirmation_ids and horizon in horizons)
    pending_targets = max(0, expected_confirmed_targets - resolved_confirmed_targets)
    insufficient = len(snapshots) - sum(1 for row in snapshots
        if row.get("symbol") and row.get("timeframe") and row.get("direction") and
        (row.get("reference_price") if row.get("record_type") else row.get("price")) is not None)
    prospective = [row for row in snapshots if _is_prospective_snapshot(row)]
    time_valid = [row for row in prospective if _timestamp_verified(row)]
    stats = {
        "total_observations": len(snapshots),
        "unique_observation_ids": len(observation_id_counts),
        "duplicate_observation_id_groups": len(ambiguous_observation_ids),
        "duplicate_observation_id_rows": duplicate_observation_rows,
        "ambiguous_observation_id_rows": ambiguous_observation_rows,
        "ambiguous_outcome_observation_horizon_keys": len(ambiguous_outcome_keys),
        "usable_observations": len(usable_observation_ids),
        "PROSPECTIVE_OBSERVATIONS": len(prospective),
        "TIME_VALID_OBSERVATIONS": len(time_valid),
        "TIME_UNVERIFIED_OBSERVATIONS": len(prospective) - len(time_valid),
        "ML_READY_OBSERVATIONS": len(usable_observation_ids),
        "QUARANTINED_HISTORICAL_OUTCOMES": quarantined_outcomes,
        "usable_observation_horizon_rows": usable_count,
        "usable_definition": "distinct observations with at least one horizon row that has required decision fields, trustworthy source time, and a WIN/LOSS market outcome",
        "confirmed_observations": cohort_counts["confirmed_observations"],
        "watch_observations": cohort_counts["watch_observations"],
        "invalidated_observations": cohort_counts["invalidated_observations"],
        "expired_observations": cohort_counts["expired_observations"],
        "observations_with_confirmation_event": cohort_counts["observations_with_confirmation_event"],
        "wins": label_counts["WIN"], "losses": label_counts["LOSS"],
        "pending_incomplete": label_counts["PENDING"] + pending_targets,
        "ambiguous": label_counts["AMBIGUOUS"], "no_hit": label_counts["NO_HIT"],
        "unlabeled_outcomes": label_counts["UNLABELED"],
        "degraded_timestamp_observations": quality_counts["degraded"],
        "insufficient_required_data_observations": insufficient,
        "outcome_rows": len([r for r in outcomes if r.get("record_type") == "market_outcome"]),
        "quarantined_historical_outcomes": quarantined_outcomes,
        "readiness_by_horizon_row": {key.removeprefix("readiness_").upper(): value
            for key, value in cohort_counts.items() if key.startswith("readiness_")},
        "label_rows": target_rows,
        "configured_horizons": list(horizons),
        "exclusions": dict(exclusion_counts),
    }
    availability = dict(sorted(feature_present.items()))
    feature_schema = [{"name": path,
        "type": "boolean" if path in _BOOLEAN_FEATURES else "categorical" if path in _CATEGORICAL_FEATURES else "number",
        "nullable": True, "available_observations": availability.get(path, 0)}
        for path in FEATURE_PATHS]
    return {"audit_only": True, "dataset_schema_version": DATASET_SCHEMA_VERSION,
            "label_definition": LABEL_DEFINITION, "feature_paths": list(FEATURE_PATHS),
            "feature_schema": feature_schema,
            "statistics": stats, "timestamp_audit": {**_timestamp_audit(snapshots),
                "examples": [{"observation_id": row.get("observation_id"),
                    "symbol": row.get("symbol"),
                    "raw_mt5_bar_epoch": (((row.get("time_provenance") or {}).get("bar_open_time") or {}).get("raw_mt5_epoch")),
                    "interpreted_mt5_bar_time": (((row.get("time_provenance") or {}).get("bar_open_time") or {}).get("interpreted_source_time")),
                    "normalized_mt5_bar_utc": (((row.get("time_provenance") or {}).get("bar_open_time") or {}).get("normalized_utc")),
                    "raw_mt5_tick_epoch": (((row.get("time_provenance") or {}).get("tick_time") or {}).get("raw_mt5_epoch")),
                    "interpreted_mt5_tick_time": (((row.get("time_provenance") or {}).get("tick_time") or {}).get("interpreted_source_time")),
                    "normalized_mt5_tick_utc": (((row.get("time_provenance") or {}).get("tick_time") or {}).get("normalized_utc")),
                    "source_time_basis": (((row.get("time_provenance") or {}).get("bar_open_time") or {}).get("source_time_basis")),
                    "normalization_status": (((row.get("time_provenance") or {}).get("bar_open_time") or {}).get("normalization_status")),
                    "persisted_source_timestamp": row.get("source_timestamp"),
                    "persisted_observed_at": row.get("observed_at") or row.get("timestamp"),
                    "source_minus_observation_seconds": _timestamp_offset_seconds(
                        row.get("source_timestamp"), row.get("observed_at") or row.get("timestamp")),
                    "backend_received_at": ((row.get("time_provenance") or {}).get("backend_received_at")),
                    "data_quality": (row.get("data_quality") or {}).get("timestamp_quality")}
                    for row in prospective[:5]]},
            "outcome_quarantine": {"reason_counts": dict(quarantine_reason_counts),
                "examples": quarantine_examples},
            "feature_availability_counts": availability,
            "outcome_chronology": audit_outcome_chronology(outcomes, snapshots),
            "candle_ordering": {"historical_candle_sequences_available": False,
                "outcome_calculation_sorts_selected_bars": True,
                "outcome_time_validation": "New outcomes must carry OUTCOME_TIME_VALID and candidate bars must be strictly after the snapshot observation time in the verified normalized domain.",
                "note": "Raw candle arrays are not persisted, so historical per-symbol candle order cannot be independently reconstructed; outcomes without prospective chronology proof stay quarantined."},
            "leakage_controls": ["Explicit decision-time feature allow-list only.",
                "Setup and observation IDs are join metadata, not features.",
                "Outcome labels, outcome timestamps, lifecycle events after observation, confirmation-event timestamps, and analyst outputs are excluded from features.",
                "Outcome labels are emitted separately by observation and horizon."],
            "dataset_projection_rows": projection_row_count,
            **({"dataset_rows": projection} if include_projection else {})}


UNATTRIBUTED = "UNATTRIBUTED"
_RECORD_SETS = ("observations", "market_outcomes", "lifecycle_events", "confirmation_events")


def split_by_strategy(observations: list[dict[str, Any]], outcomes: list[dict[str, Any]],
                      lifecycle_events: list[dict[str, Any]], confirmations: list[dict[str, Any]]
                      ) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Records of each strategy, never mixed.

    Snapshots are attributed by strategy_id (records without one are trendline,
    including pre-episode rows); confirmations by their own strategy_id, else
    their setup; lifecycle events and outcomes join through setup_id /
    observation_id. Anything that cannot be joined is reported as UNATTRIBUTED
    rather than guessed (legacy stp_legacy_* setups are trendline).
    """
    groups: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: {name: [] for name in _RECORD_SETS})
    by_setup: dict[str, str] = {}
    by_observation: dict[str, str] = {}
    for row in observations:
        strategy_id = record_strategy_id(row)
        groups[strategy_id]["observations"].append(row)
        if row.get("setup_id"):
            by_setup[str(row["setup_id"])] = strategy_id
        if row.get("observation_id"):
            by_observation[str(row["observation_id"])] = strategy_id

    def of_setup(setup_id: Any) -> str:
        key = str(setup_id or "")
        return by_setup.get(key) or (LEGACY_STRATEGY_ID if key.startswith("stp_legacy_") else UNATTRIBUTED)
    for row in confirmations:
        groups[record_strategy_id(row) if row.get("strategy_id") else of_setup(row.get("setup_id"))]["confirmation_events"].append(row)
    for row in lifecycle_events:
        groups[of_setup(row.get("setup_id"))]["lifecycle_events"].append(row)
    for row in outcomes:
        groups[by_observation.get(str(row.get("observation_id"))) or of_setup(row.get("setup_id"))]["market_outcomes"].append(row)
    return dict(groups)


def audit_by_strategy(observations: list[dict[str, Any]], outcomes: list[dict[str, Any]],
                      lifecycle_events: list[dict[str, Any]], confirmations: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-strategy data-quality statistics (the same audit, run on each strategy's records alone)."""
    result = {}
    for strategy_id, records in sorted(split_by_strategy(observations, outcomes, lifecycle_events, confirmations).items()):
        audit = prepare_dataset(records["observations"], records["market_outcomes"], records["lifecycle_events"],
                                records["confirmation_events"], include_projection=False)
        try:
            mode = REGISTRY.mode(strategy_id)
        except KeyError:
            mode = "UNREGISTERED"
        result[strategy_id] = {"mode": mode, "records": {name: len(rows) for name, rows in records.items()},
                               "shadow_snapshots": sum(1 for row in records["observations"] if row.get("shadow") is True),
                               "statistics": audit["statistics"],
                               "outcome_quarantine": audit["outcome_quarantine"]["reason_counts"]}
    return result


def audit_live_dataset() -> dict[str, Any]:
    """Read existing JSONL files and return audit results without writes."""
    paths = {"observations": LOG_FILE, "market_outcomes": MARKET_OUTCOMES_FILE,
             "lifecycle_events": LIFECYCLE_FILE, "confirmation_events": CONFIRMATIONS_FILE,
             "trade_outcomes": TRADE_OUTCOMES_FILE}
    loaded: dict[str, list[dict[str, Any]]] = {}
    malformed: dict[str, int] = {}
    for name, path in paths.items():
        rows, rejected = [], 0
        if path.exists():
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    try:
                        value = json.loads(line)
                        if isinstance(value, dict):
                            rows.append(value)
                        else:
                            rejected += 1
                    except json.JSONDecodeError:
                        rejected += 1
        loaded[name], malformed[name] = rows, rejected
    observations = loaded["observations"]
    outcomes = loaded["market_outcomes"]
    lifecycle = loaded["lifecycle_events"]
    confirmations = loaded["confirmation_events"]
    trade_outcomes = loaded["trade_outcomes"]
    result = prepare_dataset(observations, outcomes, lifecycle, confirmations, include_projection=False)
    # The top-level figures cover every strategy together; strategy-specific data
    # quality is only ever read from by_strategy.
    result["strategy_scope"] = "ALL_STRATEGIES_COMBINED"
    result["by_strategy"] = audit_by_strategy(observations, outcomes, lifecycle, confirmations)
    result["statistics"]["trade_outcomes_excluded"] = len(trade_outcomes)
    result["statistics"]["malformed_jsonl_lines"] = sum(malformed.values())
    result["statistics"]["malformed_jsonl_by_file"] = malformed
    # The HTTP audit is aggregate-only. Call prepare_dataset directly when an
    # in-memory projection is needed; never emit/persist it as a training file.
    result["storage"] = {"observations_path": str(LOG_FILE.name),
                         "market_outcomes_path": str(MARKET_OUTCOMES_FILE.name),
                         "legacy_observations_adapted_in_memory": sum(1 for row in observations if not row.get("record_type")),
                         "jsonl_records_read": {"observations": len(observations), "market_outcomes": len(outcomes),
                             "lifecycle_events": len(lifecycle), "confirmation_events": len(confirmations),
                             "trade_outcomes": len(trade_outcomes)}}
    return result
