"""Explicit MT5 source clock interpretation and provenance helpers."""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import Any


def parse_aware_utc(value: Any) -> datetime | None:
    """Parse an ISO timestamp or datetime only when it identifies an instant.

    Naive values are rejected rather than being interpreted in the host's local
    timezone. Successful values are returned in the canonical UTC zone.
    """
    if isinstance(value, datetime):
        stamp = value
    elif isinstance(value, str) and value.strip():
        try:
            stamp = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except (TypeError, ValueError, OverflowError):
            return None
    else:
        return None
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        return None
    try:
        return stamp.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


def utc_iso(value: datetime) -> str:
    """Serialize an aware datetime as canonical UTC ISO-8601."""
    stamp = parse_aware_utc(value)
    if stamp is None:
        raise ValueError("Timestamp must be timezone-aware")
    return stamp.isoformat()


def combined_normalization_status(*source_records: dict[str, Any]) -> str:
    """Verify a source clock only when both quote and candle stamps normalize."""
    statuses = [str(item.get("normalization_status") or "MISSING") for item in source_records]
    if not statuses:
        return "MISSING"
    if "INVALID" in statuses or "MISSING" in statuses:
        return "INVALID" if "INVALID" in statuses else "MISSING"
    if all(status == "VERIFIED" for status in statuses):
        return "VERIFIED"
    return "UNVERIFIED"


def normalize_mt5_epoch(raw_epoch: float | int | None, source_time_basis: str | None) -> dict[str, Any]:
    """Interpret the epoch's displayed wall clock only when its basis is explicit.

    MT5 terminal builds may expose server-local wall time in the epoch fields.
    An unset basis is deliberately UNVERIFIED. No implicit UTC or fixed offset.
    """
    raw_value = raw_epoch.item() if callable(getattr(raw_epoch, "item", None)) else raw_epoch
    result: dict[str, Any] = {"raw_mt5_epoch": raw_value,
        "source_time_basis": source_time_basis or "UNVERIFIED",
        "interpreted_source_time": None, "normalized_utc": None,
        "normalization_status": "UNVERIFIED", "normalization_method": None,
        "normalization_reason": None}
    if raw_epoch is None:
        result["normalization_status"] = "MISSING"
        result["normalization_reason"] = "MT5_SOURCE_TIMESTAMP_MISSING"
        return result
    try:
        numeric = float(raw_value)
        if numeric != numeric or abs(numeric) == float("inf"):
            raise ValueError("invalid epoch")
        wall = datetime.fromtimestamp(numeric, timezone.utc).replace(tzinfo=None)
        result["interpreted_source_time"] = wall.isoformat()
        basis = str(source_time_basis or "").strip()
        if not basis:
            result["normalization_reason"] = "SOURCE_TIME_BASIS_UNVERIFIED"
            return result
        if basis.upper() == "UTC":
            normalized = datetime.fromtimestamp(numeric, timezone.utc)
            result.update(normalized_utc=normalized.isoformat(), normalization_status="VERIFIED",
                          normalization_method="explicit-utc-epoch",
                          normalization_reason="SOURCE_BASIS_EXPLICIT_UTC")
            return result
        zone = ZoneInfo(basis)
        candidates = []
        for fold in (0, 1):
            local = wall.replace(tzinfo=zone, fold=fold)
            roundtrip = local.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None)
            if roundtrip == wall and all(local.utcoffset() != old.utcoffset() for old in candidates):
                candidates.append(local)
        if len(candidates) != 1:
            result["normalization_status"] = "INVALID" if not candidates else "UNVERIFIED"
            result["normalization_method"] = "nonexistent-or-ambiguous-local-time"
            result["normalization_reason"] = ("NONEXISTENT_LOCAL_SOURCE_TIME" if not candidates
                                               else "AMBIGUOUS_LOCAL_SOURCE_TIME")
            return result
        normalized = candidates[0].astimezone(timezone.utc)
        result.update(normalized_utc=normalized.isoformat(), normalization_status="VERIFIED",
                      normalization_method="explicit-iana-zone", source_time_basis=basis,
                      normalization_reason="SOURCE_BASIS_EXPLICIT_IANA_ZONE")
    except ZoneInfoNotFoundError:
        result["normalization_status"] = "UNVERIFIED"
        result["normalization_method"] = "timezone-database-unavailable-or-basis-unknown"
        result["normalization_reason"] = "SOURCE_TIME_BASIS_UNKNOWN_OR_TZDATA_UNAVAILABLE"
    except (TypeError, ValueError, OverflowError, OSError):
        result["normalization_status"] = "INVALID"
        result["normalization_method"] = "invalid-epoch-or-time-basis"
        result["normalization_reason"] = "INVALID_MT5_EPOCH_OR_SOURCE_TIME_BASIS"
    return result


def mt5_epoch_to_utc_iso(epoch_seconds: float | int) -> str:
    """Legacy helper retained for the diagnostic route's raw UTC interpretation."""
    return datetime.fromtimestamp(float(epoch_seconds), tz=timezone.utc).isoformat()
