"""Read-only re-verification of historical records under a verified MT5 time basis.

Stored records are never modified. For each stored snapshot this builds an
in-memory *verified view*: the raw MT5 bar/tick epochs it recorded are
normalized with the verified basis exactly as main.market_snapshot does for new
scans, and its data quality is recomputed with the same observations._quality
rules. Records without raw epochs (legacy rows) cannot be re-verified and stay
quarantined. Outcomes are then derived by the unchanged outcome engine
(outcomes.resolve_due_market_outcomes) from historical MT5 bars normalized the
same way, and classified with the unchanged integrity rules
(strategy_lab.classify_outcome -> ml_dataset._outcome_quarantine_reasons).
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Iterable

import observations
from market_time import combined_normalization_status, normalize_mt5_epoch, parse_aware_utc
from outcomes import DEFAULT_HORIZONS, resolve_due_market_outcomes
from strategies import record_strategy_id
from strategy_lab import OUTCOME_KINDS, classify_outcome


def verified_view(snapshot: dict[str, Any], basis: str) -> tuple[dict[str, Any] | None, str | None]:
    """(view, None) when the snapshot's own raw MT5 epochs normalize under `basis`, else (None, reason)."""
    provenance = snapshot.get("time_provenance") or {}
    if provenance.get("timezone_normalization_status") == "VERIFIED":
        return snapshot, None                           # recorded with a verified basis already
    bar_raw = (provenance.get("bar_open_time") or {}).get("raw_mt5_epoch")
    tick_raw = (provenance.get("tick_time") or {}).get("raw_mt5_epoch")
    if bar_raw is None or tick_raw is None:
        return None, "NO_RAW_MT5_EPOCH"
    bar, tick = normalize_mt5_epoch(bar_raw, basis), normalize_mt5_epoch(tick_raw, basis)
    status = combined_normalization_status(bar, tick)
    if status != "VERIFIED":
        reasons = {bar.get("normalization_reason"), tick.get("normalization_reason")} - {None, "SOURCE_BASIS_EXPLICIT_SHIFTED_IANA_ZONE",
                                                                                          "SOURCE_BASIS_EXPLICIT_IANA_ZONE", "SOURCE_BASIS_EXPLICIT_UTC"}
        return None, "SOURCE_TIME_" + status + (":" + ",".join(sorted(reasons)) if reasons else "")
    received = provenance.get("backend_received_at")
    received_dt, tick_dt = parse_aware_utc(received), parse_aware_utc(tick["normalized_utc"])
    tick_age = (received_dt - tick_dt).total_seconds() if received_dt and tick_dt else None
    new_provenance = {**provenance, "bar_open_time": bar, "tick_time": tick, "source_time_basis": basis,
                      "timezone_normalization_status": "VERIFIED"}
    old_quality = snapshot.get("data_quality") or {}
    market_like = {"source_timestamp": bar["normalized_utc"], "time_provenance": new_provenance,
                   "tick_age_seconds": tick_age, "candle_age_seconds": float(tick_raw) - float(bar_raw),
                   "backend_received_at": received, "source": old_quality.get("source") or "MT5",
                   "timeframe": snapshot.get("timeframe"), "received_bars": old_quality.get("received_bars")}
    quality = dict(observations._quality(market_like, snapshot.get("observed_at")))
    view = {**snapshot, "source_timestamp": bar["normalized_utc"], "time_provenance": new_provenance,
            "data_quality": quality,
            "data_freshness": {key: quality.get(key) for key in ("candle_age_seconds", "tick_age_seconds",
                                                                  "observation_latency_seconds", "timestamp_quality")},
            "time_reverification": {"basis": basis, "stored_record_unchanged": True}}
    return view, None


def normalized_bars(rates: Iterable[Any], basis: str) -> tuple[list[dict[str, Any]], int]:
    """Historical MT5 rates -> UTC bars for the outcome engine; bars whose server time is
    nonexistent/ambiguous under the basis are dropped and counted (never guessed)."""
    bars, dropped = [], 0
    for rate in rates:
        stamp = normalize_mt5_epoch(rate["time"], basis)
        if stamp.get("normalization_status") != "VERIFIED":
            dropped += 1
            continue
        bars.append({"time": datetime.fromisoformat(stamp["normalized_utc"]).timestamp(), "open": float(rate["open"]),
                     "high": float(rate["high"]), "low": float(rate["low"]), "close": float(rate["close"])})
    return bars, dropped


def reverify_outcomes(snapshots: list[dict[str, Any]], confirmations: list[dict[str, Any]],
                      stored_outcomes: list[dict[str, Any]], bars_by_symbol: dict[str, list[dict[str, Any]]],
                      basis: str, now: datetime, horizons: tuple[str, ...] = DEFAULT_HORIZONS) -> dict[str, Any]:
    """Before/after outcome audit per strategy. Pure: reads its arguments, writes nothing."""
    by_observation = {str(row.get("observation_id")): row for row in snapshots if row.get("observation_id")}
    views: dict[str, dict[str, Any]] = {}
    view_failures: Counter = Counter()
    for confirmation in confirmations:
        snapshot = by_observation.get(str(confirmation.get("observation_id")))
        if snapshot is None:
            view_failures["LINKED_SNAPSHOT_MISSING"] += 1
            continue
        view, reason = verified_view(snapshot, basis)
        if view is None:
            view_failures[reason] += 1
        else:
            views[str(confirmation["observation_id"])] = view
    verifiable = [c for c in confirmations if str(c.get("observation_id")) in views]
    derived = resolve_due_market_outcomes(verifiable, views, bars_by_symbol, [], horizons, now=now)
    derived_by_setup: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in derived:
        derived_by_setup[str(row.get("setup_id"))].append(row)
    stored_by_setup: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in stored_outcomes:
        stored_by_setup[str(row.get("setup_id"))].append(row)

    report: dict[str, Any] = {}
    for confirmation in confirmations:
        strategy_id = record_strategy_id(confirmation)
        block = report.setdefault(strategy_id, {"confirmations": 0, "before": Counter(), "after": Counter(),
                                                "time_unverifiable": Counter(), "stored_outcome_records": 0,
                                                "stored_outcomes_still_quarantined": 0})
        block["confirmations"] += 1
        sid, oid = str(confirmation.get("setup_id")), str(confirmation.get("observation_id"))
        stored = stored_by_setup.get(sid, [])
        original = by_observation.get(oid)
        block["before"][classify_outcome(confirmation, stored, original)[0]] += 1
        block["stored_outcome_records"] += len(stored)
        view = views.get(oid)
        # Stored outcome records are judged with the verified snapshot view too; they are not rewritten.
        block["stored_outcomes_still_quarantined"] += sum(1 for row in stored if classify_outcome(confirmation, [row], view or original)[0] == "unverified")
        if view is None:
            block["after"]["time_unverifiable"] += 1
            block["time_unverifiable"][verified_view(original, basis)[1] if original else "LINKED_SNAPSHOT_MISSING"] += 1
            continue
        block["after"][classify_outcome(confirmation, derived_by_setup.get(sid, []), view, horizons)[0]] += 1
    for block in report.values():
        for key in ("before", "after", "time_unverifiable"):
            block[key] = dict(block[key])
    return {"basis": basis, "horizons": list(horizons), "strategies": report, "view_failures": dict(view_failures),
            "derived_outcome_records": len(derived), "outcome_kinds": list(OUTCOME_KINDS),
            "note": "Derived outcomes are computed in memory from historical MT5 bars; no record was written or rewritten."}
