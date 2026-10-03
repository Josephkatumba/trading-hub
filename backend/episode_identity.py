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
# Lifecycle policies (Strategy.lifecycle). MATCHER_VERSION is the original policy.
# CONFIRMED_EVENTS_LIFECYCLE adds: a confirmed setup is a historical event. Once an
# episode is CONFIRMED/ACTIVE, a later observation of its strategy in the other
# direction (or another setup family) is a separate, competing hypothesis: it never
# closes the confirmed episode, which resolves on its own confirmed levels (see
# CONFIRMED_LEVELS): INVALIDATED at the confirmed stop, RESOLVED at the confirmed target.
CONFIRMED_EVENTS_LIFECYCLE = MATCHER_VERSION + "+confirmed-events-v1"
CONFIRMED_STATES = {"CONFIRMED", "ACTIVE"}
# Keys a caller puts on a confirmed candidate: the stop/target recorded on the
# confirmation snapshot. They replace the latest observation's (live, drifting) plan.
CONFIRMED_LEVELS = ("confirmed_invalidation_price", "confirmed_target_price")
# LEVEL_EPISODES_LIFECYCLE (Support & Resistance) = CONFIRMED_EVENTS_LIFECYCLE plus a
# level identity. The S/R scanner reports only its best candidate per symbol: the
# nearest support (LONG), the nearest resistance (SHORT), or NO SETUP. A different
# report is another hypothesis, not evidence against the open one:
# - another direction or NO SETUP never closes an episode (COMPETING); an unconfirmed
#   one still EXPIREs when price has moved away (SIGNIFICANT_PRICE_DISPLACEMENT);
# - same direction, another level: the unconfirmed episode is replaced (EXPIRED);
# - same direction, same level, another family label (SR_BOUNCE <-> SR_BREAK_RETEST as
#   the break window rolls): the same test of the same level, so it continues.
# An episode ends on the market itself (INVALIDATED at its stop, RESOLVED at a confirmed
# target) or by expiry. A market-ended episode records its level and closing bar
# (LEVEL_CLOSURE) and suppresses only the same level/direction until a NEW test of it:
# a touch on a bar that opened after the closing bar. Closures without that record
# (every historical S/R closure, expiries) suppress nothing.
LEVEL_EPISODES_LIFECYCLE = CONFIRMED_EVENTS_LIFECYCLE + "+level-episodes-v1"
LEVEL_CLOSURE = "level_closure"          # lifecycle event metadata key
_M15_SECONDS = 900


def is_confirmed(episode: dict[str, Any]) -> bool:
    return str(episode.get("lifecycle_state") or "").upper() in CONFIRMED_STATES


def level_identity(record: dict[str, Any]) -> dict[str, float] | None:
    """The S/R zone a market observation or episode row refers to (strategy_evidence.level)."""
    level = (record.get("strategy_evidence") or {}).get("level") if isinstance(record.get("strategy_evidence"), dict) else None
    if not isinstance(level, dict):
        return None
    try:
        low, high = float(level["zone_low"]), float(level["zone_high"])
    except (KeyError, TypeError, ValueError):
        return None
    return {"zone_low": low, "zone_high": high} if low <= high else None


def same_level(old: dict[str, Any] | None, new: dict[str, Any] | None) -> bool:
    """Overlapping zones are the same level: a level's weighted price drifts as swings are added."""
    return bool(old and new and float(old["zone_low"]) <= float(new["zone_high"])
                and float(new["zone_low"]) <= float(old["zone_high"]))


def closing_bar_time(market: dict[str, Any]) -> float | None:
    """Open time (raw MT5 epoch, the bars' own clock) of the bar forming when an episode closed."""
    value = ((market.get("time_provenance") or {}).get("bar_open_time") or {}).get("raw_mt5_epoch")
    if value is None:
        candle = ((market.get("strategy_evidence") or {}).get("rejection") or {}).get("candle_time")
        value = float(candle) + _M15_SECONDS if candle is not None else None
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def tested_bar_time(market: dict[str, Any]) -> float | None:
    """Open time of the bar that touched the level in a clean test, or None when there is no test."""
    evidence = market.get("strategy_evidence") or {}
    touch, rejection = evidence.get("touch") or {}, evidence.get("rejection") or {}
    if not (touch.get("touched") and touch.get("clean_test")) or touch.get("bars_ago") is None or rejection.get("candle_time") is None:
        return None
    return float(rejection["candle_time"]) - int(touch["bars_ago"]) * _M15_SECONDS


def level_closure(episode: dict[str, Any], market: dict[str, Any]) -> dict[str, Any] | None:
    """What a market-ended level episode records so that only its own level is suppressed."""
    level = level_identity(episode)
    return {"level": level, "bar_time": closing_bar_time(market)} if level else None


def level_suppresses(closure: Any, market: dict[str, Any]) -> bool:
    """Same level (direction already matched) and no new test since the closing bar."""
    if not isinstance(closure, dict) or not same_level(closure.get("level"), level_identity(market)):
        return False
    tested, closed_bar = tested_bar_time(market), closure.get("bar_time")
    return not (tested is not None and (closed_bar is None or tested > float(closed_bar)))


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
    invalidation = previous.get("confirmed_invalidation_price")
    if invalidation is None:
        invalidation = previous.get("invalidation_price")
    if invalidation is None:
        invalidation = (previous.get("rule_evidence") or {}).get("invalidation_hint")
    direction = str(previous.get("direction") or "").upper()
    if price is not None and invalidation is not None:
        crossed = (direction == "LONG" and float(price) <= float(invalidation)) or (direction == "SHORT" and float(price) >= float(invalidation))
        if crossed:
            return "INVALIDATE", "INVALIDATION_PRICE_CROSSED", abs(float(price) - float(previous.get("reference_price") or price))
    target = previous.get("confirmed_target_price")
    if price is not None and target is not None:
        reached = (direction == "LONG" and float(price) >= float(target)) or (direction == "SHORT" and float(price) <= float(target))
        if reached:
            return "RESOLVE", "TARGET_PRICE_CROSSED", abs(float(price) - float(previous.get("reference_price") or price))

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


def _level_decision(market: dict[str, Any], candidate: dict[str, Any], reason: str | None,
                    confirmed: bool) -> tuple[dict[str, Any], str, str | None, float]:
    """LEVEL_EPISODES_LIFECYCLE for a NO_MATCH/CONTINUE evaluation (see above)."""
    old_price = candidate.get("reference_price", candidate.get("price"))
    price = market.get("price")
    moved = abs(float(price) - float(old_price)) if price is not None and old_price is not None else 0.0
    # Why this observation is not the candidate's setup; None when it is.
    if reason == "DIRECTION_CHANGED":
        other = "DIRECTION_CHANGED"
    elif not same_level(level_identity(candidate), level_identity(market)) and level_identity(candidate) and level_identity(market):
        other = "LEVEL_CHANGED"
    else:
        other = None
    if moved > _price_limit(market, candidate) and other != "LEVEL_CHANGED":
        other = other or "SIGNIFICANT_PRICE_DISPLACEMENT"
        if not confirmed:        # an unconfirmed hypothesis price has left behind
            return candidate, "EXPIRE", "EPISODE_REPLACED:SIGNIFICANT_PRICE_DISPLACEMENT", moved
    if other:
        # A confirmed setup resolves only on its confirmed levels; another direction or
        # NO SETUP is a competing hypothesis; another level replaces an unconfirmed one.
        if confirmed or other == "DIRECTION_CHANGED":
            return candidate, "COMPETING", other, moved
        return candidate, "EXPIRE", "EPISODE_REPLACED:" + other, moved
    family = _specific_family(candidate.get("setup_family") or candidate.get("setup_type")) == _specific_family(market.get("setup_family"))
    return candidate, "MATCH", "SAME_LEVEL" if family else "SAME_LEVEL_FAMILY_REVISED", moved - (1e6 if family else 0)


def rank_candidates(market: dict[str, Any], candidates: list[dict[str, Any]], now: datetime,
                    confirmed_events: bool = False,
                    level_episodes: bool = False) -> tuple[dict[str, Any] | None, list[tuple[dict[str, Any], str, str | None, float]]]:
    """`confirmed_events`: the CONFIRMED_EVENTS_LIFECYCLE policy; `level_episodes`: LEVEL_EPISODES_LIFECYCLE (see above)."""
    evaluated = []
    for candidate in candidates:
        decision, reason, distance = evaluate_episode(market, candidate, now)
        if level_episodes and decision in {"NO_MATCH", "CONTINUE"} and reason != "SCOPE_CHANGED":
            evaluated.append(_level_decision(market, candidate, reason, confirmed_events and is_confirmed(candidate)))
            continue
        if decision in {"INVALIDATE", "EXPIRE", "RESOLVE"}:
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
            # A confirmed episode stays open: the new observation is a competing episode.
            evaluated.append((candidate, "COMPETING" if confirmed_events and is_confirmed(candidate) else "INVALIDATE",
                              reason, distance))
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
