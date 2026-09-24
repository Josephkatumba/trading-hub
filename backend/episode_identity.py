"""Persisted setup-episode matching, separate from strategy and scoring."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any
from market_time import parse_aware_utc

MATCHER_VERSION = "episode-match-v2"
TERMINAL_STATES = {"INVALIDATED", "EXPIRED", "RESOLVED"}


def _dt(value: Any) -> datetime | None:
    return parse_aware_utc(value)


def _configured_float(key: str, default: float, minimum: float) -> float:
    try:
        return max(minimum, float(os.getenv(key, default)))
    except (TypeError, ValueError):
        return default


def trendline_identity(market: dict[str, Any]) -> dict[str, Any] | None:
    value = market.get("trendline_identity")
    if not isinstance(value, dict) or not value.get("anchors"):
        return None
    stable = {"orientation": value.get("orientation"), "anchors": value.get("anchors")}
    fingerprint = hashlib.sha256(json.dumps(stable, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:24]
    return {**stable, "fingerprint": fingerprint}


def identity_evidence(market: dict[str, Any]) -> dict[str, Any]:
    return {"matcher_version": MATCHER_VERSION,
            "trendline_identity": trendline_identity(market),
            "setup_family": market.get("setup_family"),
            "reference_price": market.get("price"),
            "atr": market.get("atr"),
            "timeframe": str(market.get("timeframe") or "M15"),
            "detection_source_timestamp": market.get("source_timestamp")}


def _specific_family(value: Any) -> str | None:
    text = str(value or "").upper()
    return text if text not in {"", "NONE", "GENERAL", "WATCHING"} else None


def _price_limit(current: dict[str, Any], previous: dict[str, Any]) -> float:
    atr = current.get("atr") or previous.get("atr")
    if atr and float(atr) > 0:
        return float(atr) * _configured_float("TRADING_HUB_EPISODE_MAX_ATR_DRIFT", 3.0, 0.1)
    reference = float(current.get("price") or previous.get("reference_price") or 0)
    return abs(reference) * 0.0025


def evaluate_episode(market: dict[str, Any], previous: dict[str, Any], now: datetime) -> tuple[str, str | None, float]:
    """Return CONTINUE, INVALIDATE, EXPIRE, or NO_MATCH plus reason and distance."""
    symbol = str(market.get("symbol", "UNKNOWN"))
    timeframe = str(market.get("timeframe") or "M15")
    if symbol != str(previous.get("symbol", "UNKNOWN")) or timeframe != str(previous.get("timeframe") or "M15"):
        return "NO_MATCH", "SCOPE_CHANGED", float("inf")

    prior_at = _dt(previous.get("observed_at") or previous.get("timestamp"))
    max_gap = _configured_float("TRADING_HUB_EPISODE_MAX_GAP_SECONDS", 86400.0, 60.0)
    if prior_at and (now - prior_at).total_seconds() > max_gap:
        return "EXPIRE", "INACTIVITY_TIMEOUT", float("inf")

    price = market.get("price")
    invalidation = previous.get("invalidation_price")
    if invalidation is None:
        invalidation = (previous.get("rule_evidence") or {}).get("invalidation_hint")
    direction = str(previous.get("direction") or "").upper()
    if price is not None and invalidation is not None:
        crossed = (direction == "LONG" and float(price) <= float(invalidation)) or (direction == "SHORT" and float(price) >= float(invalidation))
        if crossed:
            return "INVALIDATE", "INVALIDATION_PRICE_CROSSED", abs(float(price) - float(previous.get("reference_price") or price))

    if str(market.get("direction") or "").upper() != direction:
        return "NO_MATCH", "DIRECTION_CHANGED", float("inf")

    old_family = _specific_family(previous.get("setup_family") or previous.get("setup_type"))
    new_family = _specific_family(market.get("setup_family"))
    if old_family and new_family and old_family != new_family:
        return "NO_MATCH", "SETUP_FAMILY_CHANGED", float("inf")

    old_tl = (previous.get("episode_identity") or {}).get("trendline_identity")
    if old_tl is None:
        old_tl = previous.get("trendline_identity")
    new_tl = trendline_identity(market)
    if old_tl and new_tl and old_tl.get("fingerprint") != new_tl.get("fingerprint"):
        return "NO_MATCH", "TRENDLINE_GEOMETRY_CHANGED", float("inf")

    old_price = previous.get("reference_price")
    if old_price is None:
        old_price = previous.get("price")
    distance = abs(float(price) - float(old_price)) if price is not None and old_price is not None else 0.0
    if distance > _price_limit(market, previous):
        return "NO_MATCH", "SIGNIFICANT_PRICE_DISPLACEMENT", distance
    return "CONTINUE", None, distance


def rank_candidates(market: dict[str, Any], candidates: list[dict[str, Any]], now: datetime) -> tuple[dict[str, Any] | None, list[tuple[dict[str, Any], str, str | None, float]]]:
    evaluated = []
    for candidate in candidates:
        decision, reason, distance = evaluate_episode(market, candidate, now)
        if decision in {"INVALIDATE", "EXPIRE"}:
            evaluated.append((candidate, decision, reason, distance))
        elif decision == "NO_MATCH" and reason == "TRENDLINE_GEOMETRY_CHANGED":
            # Trendline anchors can move as the scanner adds candles. Preserve the
            # episode through nearby geometry churn; a direction/family change or
            # material price displacement still starts a distinct episode.
            old_price = candidate.get("reference_price") or candidate.get("price")
            new_price = market.get("price")
            tolerance = _price_limit(market, candidate)
            if old_price is not None and new_price is not None and abs(float(new_price) - float(old_price)) <= tolerance:
                evaluated.append((candidate, "MATCH", "TRENDLINE_GEOMETRY_REVISED", abs(float(new_price) - float(old_price)) + 1e3))
            else:
                evaluated.append((candidate, "EXPIRE", "EPISODE_REPLACED:" + str(reason), distance))
        elif decision == "NO_MATCH" and reason in {"DIRECTION_CHANGED", "SETUP_FAMILY_CHANGED"}:
            evaluated.append((candidate, "INVALIDATE", reason, distance))
        elif decision == "NO_MATCH" and reason == "SIGNIFICANT_PRICE_DISPLACEMENT":
            evaluated.append((candidate, "EXPIRE", "EPISODE_REPLACED:" + str(reason), distance))
        elif decision == "CONTINUE":
            tl = (candidate.get("episode_identity") or {}).get("trendline_identity")
            exact = bool(tl and trendline_identity(market) and tl.get("fingerprint") == trendline_identity(market).get("fingerprint"))
            family = bool(_specific_family(candidate.get("setup_family") or candidate.get("setup_type")) == _specific_family(market.get("setup_family")))
            evaluated.append((candidate, "MATCH", "EXACT_TRENDLINE" if exact else "CONTINUITY", distance - (1e12 if exact else 0) - (1e6 if family else 0)))
    matches = sorted((item for item in evaluated if item[1] == "MATCH"), key=lambda item: item[3])
    # Ambiguous candidates are safer as a new episode than an arbitrary merge.
    if len(matches) > 1 and abs(matches[0][3] - matches[1][3]) < 1e-9:
        return None, evaluated
    return (matches[0][0] if matches else None), evaluated
