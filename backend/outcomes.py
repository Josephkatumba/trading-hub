"""Append-only market and execution outcome records; these are never conflated."""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from schemas import validate_trade_outcome
from market_time import parse_aware_utc, utc_iso

DATA_DIR = Path(__file__).resolve().parent / "data"
MARKET_OUTCOMES_FILE = DATA_DIR / "market_outcomes.jsonl"
TRADE_OUTCOMES_FILE = DATA_DIR / "trade_outcomes.jsonl"
DEFAULT_HORIZONS = ("15m", "1h", "4h", "24h")
SOURCE_FUTURE_TOLERANCE_SECONDS = 5.0


def configured_horizons() -> tuple[str, ...]:
    raw = os.getenv("TRADING_HUB_OUTCOME_HORIZONS", ",".join(DEFAULT_HORIZONS))
    allowed = {"15m", "1h", "4h", "24h"}
    values = tuple(part.strip().lower() for part in raw.split(",") if part.strip())
    return tuple(value for value in values if value in allowed) or DEFAULT_HORIZONS


def _append(path: Path, record: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, separators=(",", ":"), default=str) + "\n")


def list_records(path: Path, setup_id: str | None = None) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                row = json.loads(line)
                if setup_id is None or row.get("setup_id") == setup_id:
                    records.append(row)
            except json.JSONDecodeError:
                continue
    return records


def record_trade_outcome(payload: dict[str, Any]) -> dict[str, Any]:
    """Record only an explicitly submitted actual or simulated execution."""
    validate_trade_outcome(payload)
    now = utc_iso(datetime.now(timezone.utc))
    record = {"record_type": "trade_outcome", "schema_version": "1.0",
        "trade_id": payload.get("trade_id") or "trd_" + uuid.uuid4().hex,
        "setup_id": payload["setup_id"], "execution_type": payload["execution_type"],
        "entry_time": payload["entry_time"], "entry_price": float(payload["entry_price"]),
        "exit_time": payload.get("exit_time"), "exit_price": payload.get("exit_price"),
        "direction": payload["direction"], "size": payload.get("size"),
        "size_unit": payload.get("size_unit"), "realized_pnl": payload.get("realized_pnl"),
        "currency": payload.get("currency"), "exit_reason": payload.get("exit_reason"),
        "execution_metadata": payload.get("execution_metadata") or {}, "recorded_at": now}
    _append(TRADE_OUTCOMES_FILE, record)
    return record


def validate_outcome_time(snapshot: dict[str, Any],
                          candidate_bars: list[dict[str, Any]]) -> dict[str, Any]:
    """Validate candidate candle times against a verified decision-time domain."""
    provenance = snapshot.get("time_provenance") or {}
    basis_quality = str(provenance.get("timezone_normalization_status") or "UNVERIFIED")
    observation_value = snapshot.get("observed_at") or snapshot.get("observation_time")
    observation = None
    observation = parse_aware_utc(observation_value)
    source = parse_aware_utc(snapshot.get("source_timestamp"))
    source_valid = bool(observation and source and
        (source - observation).total_seconds() <= SOURCE_FUTURE_TOLERANCE_SECONDS)
    timestamp_quality = ("VERIFIED" if basis_quality == "VERIFIED" and source_valid
                         else "UNVERIFIED")
    stamps: list[datetime] = []
    malformed = False
    for bar in candidate_bars:
        try:
            value = bar.get("time")
            stamp = (datetime.fromtimestamp(float(value), tz=timezone.utc)
                     if isinstance(value, (int, float)) else parse_aware_utc(value))
            if stamp is None:
                malformed = True
                continue
            stamps.append(stamp.astimezone(timezone.utc))
        except (TypeError, ValueError, OverflowError, OSError):
            malformed = True
    first = utc_iso(stamps[0]) if stamps else None
    last = utc_iso(stamps[-1]) if stamps else None
    strictly_after = (all(stamp > observation for stamp in stamps)
                      if observation is not None and stamps else None)
    chronological = all(left < right for left, right in zip(stamps, stamps[1:]))
    if basis_quality != "VERIFIED" or observation is None or source is None:
        status = "OUTCOME_TIME_UNVERIFIED"
    elif (source - observation).total_seconds() > SOURCE_FUTURE_TOLERANCE_SECONDS:
        status = "OUTCOME_TIME_INVALID"
    elif malformed or not stamps or not strictly_after or not chronological:
        status = "OUTCOME_TIME_INVALID"
    else:
        status = "OUTCOME_TIME_VALID"
    return {
        "setup_observation_time": utc_iso(observation) if observation else observation_value,
        "first_candidate_candle_timestamp": first,
        "last_candidate_candle_timestamp": last,
        "candidate_candle_count": len(stamps),
        "every_candidate_strictly_after_observation": strictly_after,
        "candidate_candles_chronological": chronological if stamps else False,
        "timestamp_quality": timestamp_quality,
        "outcome_time_validity": status,
    }


def derive_market_outcome(snapshot: dict[str, Any], horizon: str, bars: list[dict[str, Any]],
                          timeframe: str, quality: dict[str, Any] | None = None,
                          target_price: float | None = None,
                          invalidation_price: float | None = None,
                          now: datetime | None = None) -> dict[str, Any] | None:
    """Label a market path using only completed candles after the decision snapshot."""
    from datetime import timedelta
    units = {"15m": timedelta(minutes=15), "1h": timedelta(hours=1),
             "4h": timedelta(hours=4), "24h": timedelta(hours=24)}
    if horizon not in units or not bars:
        return None
    provenance = snapshot.get("time_provenance") or {}
    observed = parse_aware_utc(snapshot.get("observed_at") or snapshot.get("timestamp"))
    current = parse_aware_utc(now or datetime.now(timezone.utc))
    if (observed is None or current is None or
            provenance.get("timezone_normalization_status") != "VERIFIED"):
        return None
    end = observed + units[horizon]
    frame_minutes = _timeframe_minutes(timeframe)
    if frame_minutes is None:
        return None
    frame_seconds = frame_minutes * 60
    end_epoch = end.timestamp()
    aligned_end = datetime.fromtimestamp(((int(end_epoch) + frame_seconds - 1) // frame_seconds) * frame_seconds,
                                         tz=timezone.utc)
    # OHLC candles cannot resolve a time inside the still-forming source bar.
    # Wait for the next candle boundary, then use only fully closed bars.
    if current < aligned_end:
        return None
    selected = []
    for bar in bars:
        stamp = (datetime.fromtimestamp(float(bar["time"]), tz=timezone.utc)
                 if isinstance(bar.get("time"), (int, float)) else parse_aware_utc(bar.get("time")))
        if stamp is None:
            return None
        if observed < stamp < aligned_end:
            selected.append((stamp, bar))
    if not selected:
        return None
    selected.sort(key=lambda item: item[0])
    if selected[-1][0] < aligned_end - timedelta(minutes=frame_minutes):
        return None
    time_validation = validate_outcome_time(snapshot, [bar for _, bar in selected])
    if time_validation["outcome_time_validity"] != "OUTCOME_TIME_VALID":
        return None
    ref = snapshot.get("reference_price")
    direction = snapshot.get("direction")
    future = float(selected[-1][1]["close"])
    highs = [float(row["high"]) for _, row in selected]
    lows = [float(row["low"]) for _, row in selected]
    if not ref:
        mfe = mae = distance = ret = None
    else:
        sign = 1 if direction == "LONG" else -1 if direction == "SHORT" else 0
        distance = future - float(ref)
        ret = distance / float(ref) if ref else None
        if sign == 1:
            mfe, mae = max(0.0, max(highs) - float(ref)), min(0.0, min(lows) - float(ref))
        elif sign == -1:
            mfe, mae = max(0.0, float(ref) - min(lows)), min(0.0, float(ref) - max(highs))
        else:
            mfe = mae = None
    label = None
    label_reason = "Target or invalidation level unavailable; market path is unlabeled."
    favorable_at = adverse_at = None
    if direction in {"LONG", "SHORT"} and target_price is not None and invalidation_price is not None:
        for stamp, bar in selected:
            high, low = float(bar["high"]), float(bar["low"])
            target_hit = high >= float(target_price) if direction == "LONG" else low <= float(target_price)
            invalid_hit = low <= float(invalidation_price) if direction == "LONG" else high >= float(invalidation_price)
            if target_hit and invalid_hit:
                label, label_reason = "AMBIGUOUS", "Target and invalidation were both touched in the same candle; ordering is unknown."
                break
            if target_hit:
                label, label_reason, favorable_at = "WIN", "Target reached before invalidation.", stamp
                break
            if invalid_hit:
                label, label_reason, adverse_at = "LOSS", "Invalidation reached before target.", stamp
                break
        if label is None:
            label, label_reason = "NO_HIT", "Neither target nor invalidation was reached within the horizon."

    observed_at = utc_iso(current)
    dq = quality or {"status": "DEGRADED", "flags": ["OUTCOME_CANDLE_COVERAGE_UNVERIFIED"], "source": "MT5",
        "source_timestamp": None, "observed_at": observed_at, "source_age_seconds": None,
        "timeframe": timeframe, "expected_bars": None, "received_bars": len(selected), "missing_intervals": None,
        "notes": ["Outcome uses supplied post-observation candles only."]}
    dq.setdefault("timestamp_quality", "VERIFIED")
    dq.setdefault("time_basis", provenance.get("source_time_basis"))
    dq.setdefault("chronology", "NORMALIZED_CANDLES_STRICTLY_AFTER_OBSERVATION")
    return {"record_type": "market_outcome", "schema_version": "1.0",
        "outcome_id": "mktout_" + uuid.uuid4().hex, "setup_id": snapshot["setup_id"],
        "observation_id": snapshot["observation_id"], "resolved_at": observed_at,
        "horizon": horizon, "timeframe": timeframe, "direction": direction,
        "reference_price": ref, "future_price": future, "return": ret, "distance": distance,
        "maximum_favorable_excursion": mfe, "maximum_adverse_excursion": mae,
        "time_to_favorable_movement": str(favorable_at - observed) if favorable_at else None,
        "time_to_adverse_movement": str(adverse_at - observed) if adverse_at else None,
        "label": label, "label_reason": label_reason,
        "label_definition": "target-invalidation-first-v1", "data_quality": dq,
        "timestamp_quality": time_validation["timestamp_quality"], "source_time_basis": provenance.get("source_time_basis"),
        "outcome_time_validity": time_validation["outcome_time_validity"],
        "outcome_time_validation": time_validation, "outcome_status": "OUTCOME_EVALUATED"}


def _timeframe_minutes(timeframe: str) -> int | None:
    text = str(timeframe or "").upper()
    if len(text) < 2:
        return None
    try:
        amount = int(text[1:])
    except ValueError:
        return None
    if text[0] == "M":
        return amount
    if text[0] == "H":
        return amount * 60
    return None


def resolve_due_market_outcomes(confirmations: list[dict[str, Any]],
                                snapshots_by_id: dict[str, dict[str, Any]],
                                bars_by_symbol: dict[str, list[dict[str, Any]]],
                                existing: list[dict[str, Any]],
                                horizons: tuple[str, ...],
                                now: datetime | None = None,
                                watch_snapshots: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Appendable market paths for confirmed and barrier-valid WATCH observations."""
    current = parse_aware_utc(now or datetime.now(timezone.utc))
    if current is None:
        return []
    present = {(row.get("setup_id"), row.get("observation_id"), row.get("horizon"),
                row.get("label_definition")) for row in existing}
    created = []
    candidates: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for confirmation in confirmations:
        snapshot = snapshots_by_id.get(str(confirmation.get("observation_id")))
        if snapshot:
            candidates.append((snapshot, confirmation))
    for snapshot in watch_snapshots or []:
        if (snapshot.get("record_type") == "setup_snapshot" and
                (snapshot.get("rule_evidence") or {}).get("strategy_valid") is not True):
            candidates.append((snapshot, snapshot))
    visited: set[str] = set()
    for snapshot, source_record in candidates:
        obs_id = str(snapshot.get("observation_id") or "")
        if not obs_id or obs_id in visited:
            continue
        visited.add(obs_id)
        if not snapshot:
            continue
        snapshot_provenance = snapshot.get("time_provenance") or {}
        if snapshot_provenance.get("timezone_normalization_status") != "VERIFIED":
            continue
        observed = parse_aware_utc(snapshot.get("observed_at") or snapshot.get("timestamp"))
        if observed is None:
            continue
        symbol = str(source_record.get("symbol") or snapshot.get("symbol") or "")
        bars = bars_by_symbol.get(symbol)
        if not bars:
            continue
        rules = snapshot.get("rule_evidence") or {}
        target = snapshot.get("proposed_take_profit")
        invalidation = snapshot.get("invalidation_price")
        if invalidation is None:
            invalidation = rules.get("invalidation_hint", snapshot.get("proposed_stop_loss"))
        # WATCH rows without actual decision-time barriers remain unlabeled; do
        # not infer levels or manufacture binary outcomes from later data.
        if source_record is snapshot:
            try:
                reference = float(snapshot.get("reference_price"))
                target_value, invalid_value = float(target), float(invalidation)
                valid = (reference > 0 and target_value > 0 and invalid_value > 0 and
                    (target_value > reference > invalid_value if snapshot.get("direction") == "LONG" else
                     target_value < reference < invalid_value if snapshot.get("direction") == "SHORT" else False))
            except (TypeError, ValueError):
                valid = False
            if not valid:
                continue
        for horizon in horizons:
            key = (snapshot.get("setup_id"), snapshot.get("observation_id"),
                   horizon, "target-invalidation-first-v1")
            if key in present:
                continue
            timeframe = str(snapshot.get("timeframe") or "M15")
            frame_minutes = _timeframe_minutes(timeframe) or 0
            horizon_minutes = {"15m": 15, "1h": 60, "4h": 240, "24h": 1440}.get(horizon, 0)
            expected = max(1, (horizon_minutes + frame_minutes - 1) // frame_minutes) if frame_minutes else None
            actual = [bar for bar in bars if float(bar["time"]) > observed.timestamp()
                      and float(bar["time"]) < (current.timestamp() // (frame_minutes * 60) * (frame_minutes * 60) if frame_minutes else 0)]
            flags = ["INCOMPLETE_CANDLE_COVERAGE"] if expected and len(actual) < max(1, expected - 1) else []
            last_source = utc_iso(datetime.fromtimestamp(float(bars[-1]["time"]), tz=timezone.utc))
            last_source_dt = parse_aware_utc(last_source)
            if last_source_dt is None:
                continue
            quality = {"status": "DEGRADED" if flags else "OK", "flags": flags, "source": "MT5",
                "source_timestamp": last_source, "observed_at": utc_iso(current),
                "source_age_seconds": max(0.0, (current - last_source_dt).total_seconds()),
                "timeframe": timeframe, "expected_bars": expected, "received_bars": len(actual),
                "missing_intervals": max(0, (expected or 0) - len(actual)) if expected else None,
                "timestamp_quality": "VERIFIED",
                "notes": ["Horizon evaluation uses verified normalized UTC candles strictly after the observation; result is aligned to the candle boundary."]}
            outcome = derive_market_outcome(snapshot, horizon, bars, timeframe, quality=quality,
                target_price=target, invalidation_price=invalidation, now=current)
            if outcome is None:
                continue
            created.append(outcome)
            present.add(key)
    return created


def append_market_outcome(record: dict[str, Any]) -> None:
    if record.get("record_type") != "market_outcome":
        raise ValueError("Only market_outcome records may be written here")
    _append(MARKET_OUTCOMES_FILE, record)
