"""Deterministic, evidence-referenced setup analysis. No model or external calls."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from schemas import AnalystEvidence, SetupAnalysis
from market_time import utc_iso

ANALYST_VERSION = "deterministic-setup-analyst-v1"

_FEATURE_CATEGORIES = {
    "trendline": {"trendline", "trendline_state", "trendline_line"},
    "support_resistance": {"nearest_level", "nearest_level_type", "nearest_level_atr"},
    "structure": {"structure"},
    "higher_timeframe": {"higher_timeframe_bias"},
    "session": {"session", "london_high", "london_low", "session_alignment"},
    "momentum": {"rsi", "ema20", "ema50", "momentum", "market_bias"},
    "volatility": {"atr", "spread", "spread_atr"},
    "price_action": {"price_action", "price_action_state"},
    "crt": {"crt_context", "crt_state"},
}

_OPTIONAL_EVIDENCE = {
    "H4 bias": ("features.h4_bias", "features.higher_timeframe_bias_h4"),
    "MACD": ("features.macd",),
    "ADX": ("features.adx",),
    "Volume": ("features.volume", "features.volume_confirmation"),
    "Session alignment": ("session.session_alignment", "features.session_alignment"),
}


def _value(snapshot: dict[str, Any], source_field: str) -> Any:
    value: Any = snapshot
    for part in source_field.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _evidence(category: str, claim: str, source_field: str, source_value: Any) -> AnalystEvidence:
    return AnalystEvidence(category=category, claim=claim, source_field=source_field,
                           source_value=source_value)


def analyze_snapshot(snapshot: dict[str, Any], generated_at: str | None = None) -> SetupAnalysis:
    """Explain one recorded snapshot; every factual item points to its source field."""
    features = snapshot.get("features") or {}
    session = snapshot.get("session") or {}
    rules = snapshot.get("rule_evidence") or {}
    rule_valid = rules.get("strategy_valid")
    classification = "CONFIRMED" if rule_valid is True else "WATCH"
    direction = snapshot.get("direction")
    setup_type = snapshot.get("setup_type") or snapshot.get("setup_family")
    evidence: list[AnalystEvidence] = []
    confirmations: list[AnalystEvidence] = []
    conflicts: list[AnalystEvidence] = []
    missing: list[AnalystEvidence] = []

    for category, keys in _FEATURE_CATEGORIES.items():
        for key in sorted(keys):
            value = features.get(key)
            if value is not None:
                evidence.append(_evidence(category, f"Recorded {key.replace('_', ' ')} value.",
                                          f"features.{key}", value))
    for key, value in sorted(session.items()):
        if value is not None:
            evidence.append(_evidence("session", f"Recorded session {key.replace('_', ' ')} value.",
                                      f"session.{key}", value))
    for key in ("trendline_gate", "confirmation_alignment", "strategy_valid"):
        value = rules.get(key)
        if value is not None:
            evidence.append(_evidence("confirmation", f"Scanner recorded {key}={str(value).lower()}.",
                                      f"rule_evidence.{key}", value))
    if snapshot.get("score") is not None:
        evidence.append(_evidence("score", "Recorded scanner score.",
                                  "score", snapshot["score"]))
    for key, value in (snapshot.get("score_breakdown") or {}).items():
        evidence.append(_evidence("score", f"Recorded {key.replace('_', ' ')} score component.",
                                  f"score_breakdown.{key}", value))

    if rule_valid is True:
        confirmations.append(_evidence("confirmation",
            "The scanner's recorded strategy validation passed.",
            "rule_evidence.strategy_valid", True))
        if rules.get("trendline_gate") is True:
            confirmations.append(_evidence("trendline",
                "The scanner recorded a qualifying trendline event.",
                "rule_evidence.trendline_gate", True))
        trendline_label = features.get("trendline")
        trendline_state = features.get("trendline_state")
        if trendline_label is not None:
            confirmations.append(_evidence("trendline", str(trendline_label),
                "features.trendline", trendline_label))
        elif trendline_state is not None:
            confirmations.append(_evidence("trendline", f"Trendline state: {trendline_state}.",
                "features.trendline_state", trendline_state))
        pa_value = features.get("price_action_state") or features.get("price_action")
        pa_text = str(pa_value or "").upper()
        if pa_value is not None and ((direction == "LONG" and "BULLISH" in pa_text)
                                     or (direction == "SHORT" and "BEARISH" in pa_text)):
            pa_field = "features.price_action_state" if features.get("price_action_state") is not None else "features.price_action"
            confirmations.append(_evidence("price_action",
                f"Recorded price action aligns with {direction}.", pa_field, pa_value))
        level = features.get("nearest_level")
        level_distance = features.get("nearest_level_atr")
        if level is not None:
            confirmations.append(_evidence("support_resistance",
                "Recorded nearby support/resistance level.", "features.nearest_level", level))
        if level_distance is not None:
            confirmations.append(_evidence("support_resistance",
                "Recorded distance to the nearest level in ATR units.",
                "features.nearest_level_atr", level_distance))
        # Keep the scanner-authored rationale intact; it is the auditable
        # explanation of which inputs the existing scanner cited.
        for key in ("reason", "trigger"):
            if rules.get(key):
                confirmations.append(_evidence("scanner_rationale",
                    f"Scanner recorded {key}: {rules[key]}", f"rule_evidence.{key}", rules[key]))
    else:
        if rule_valid is False:
            missing.append(_evidence("confirmation",
                "The recorded scanner strategy_valid flag is false.",
                "rule_evidence.strategy_valid", False))
        else:
            missing.append(_evidence("confirmation",
                "The snapshot does not contain strategy_valid.",
                "rule_evidence.strategy_valid", None))
        if rules.get("trendline_gate") is False:
            missing.append(_evidence("trendline", "No qualifying trendline event is recorded.",
                                     "rule_evidence.trendline_gate", False))
        if rules.get("confirmation_alignment") is False:
            missing.append(_evidence("confirmation",
                "The scanner did not record confirmation alignment.",
                "rule_evidence.confirmation_alignment", False))
        score = snapshot.get("score")
        if isinstance(score, (int, float)) and score < 65:
            missing.append(_evidence("score", "Recorded score is below the scanner's 65 threshold.",
                                     "score", score))
        rr = features.get("rr")
        if rr is not None and isinstance(rr, (int, float)) and rr < 1.5:
            missing.append(_evidence("risk", "Recorded risk/reward is below 1.5.",
                                     "features.rr", rr))
        elif rr is None and rule_valid is False and rules.get("trendline_gate") is True:
            missing.append(_evidence("risk", "Risk/reward evidence is unavailable.",
                                     "features.rr", None))

    bias = features.get("higher_timeframe_bias")
    if direction == "LONG" and bias == "BEARISH" or direction == "SHORT" and bias == "BULLISH":
        conflicts.append(_evidence("higher_timeframe", "Higher-timeframe bias opposes the recorded direction.",
                                   "features.higher_timeframe_bias", bias))
    pa = str(features.get("price_action_state") or "").upper()
    if (direction == "LONG" and pa.startswith("BEARISH")) or (direction == "SHORT" and pa.startswith("BULLISH")):
        conflicts.append(_evidence("price_action", "Recorded price action opposes the setup direction.",
                                   "features.price_action_state", features.get("price_action_state")))
    momentum = str(features.get("momentum") or "").upper()
    if (direction == "LONG" and momentum == "BEARISH") or (direction == "SHORT" and momentum == "BULLISH"):
        conflicts.append(_evidence("momentum", "Recorded momentum opposes the setup direction.",
                                   "features.momentum", features.get("momentum")))

    # Anything recorded in the same direction is support, never conflict.
    if bias and ((direction == "LONG" and bias == "BULLISH") or
                 (direction == "SHORT" and bias == "BEARISH")):
        confirmations.append(_evidence("higher_timeframe",
            f"Higher-timeframe bias supports {direction}.",
            "features.higher_timeframe_bias", bias))
    if momentum and ((direction == "LONG" and momentum == "BULLISH") or
                     (direction == "SHORT" and momentum == "BEARISH")):
        confirmations.append(_evidence("momentum", f"Recorded momentum supports {direction}.",
            "features.momentum", features.get("momentum")))
    pa_value = features.get("price_action_state") or features.get("price_action")
    pa_text = str(pa_value or "").upper()
    if pa_value is not None and ((direction == "LONG" and "BULLISH" in pa_text)
                                 or (direction == "SHORT" and "BEARISH" in pa_text)):
        pa_field = "features.price_action_state" if features.get("price_action_state") is not None else "features.price_action"
        if not any(item["source_field"] == pa_field for item in confirmations):
            confirmations.append(_evidence("price_action",
                f"{pa_value} supports the {direction} direction.", pa_field, pa_value))
    for key in ("nearest_level_type", "nearest_level", "nearest_level_atr"):
        value = features.get(key)
        source_field = f"features.{key}"
        if value is not None and not any(item["source_field"] == source_field for item in confirmations):
            if key == "nearest_level_type":
                claim = f"Nearest level type is {value}."
            elif key == "nearest_level":
                claim = f"Nearest level price is {value}."
            else:
                claim = f"Distance to nearest level is {value} ATR."
            confirmations.append(_evidence("support_resistance",
                claim, source_field, value))
    if rules.get("reason"):
        confirmations.append(_evidence("scanner_rationale",
            str(rules["reason"]), "rule_evidence.reason", rules["reason"]))
    for label, paths in _OPTIONAL_EVIDENCE.items():
        source = next((path for path in paths if _value(snapshot, path) is not None), None)
        if source is None:
            missing.append(_evidence("availability", f"{label} evidence is unavailable in this snapshot.",
                                     paths[0], None))

    risk_context = {
        "reference_price": snapshot.get("reference_price"),
        "entry": snapshot.get("proposed_entry"),
        "invalidation": snapshot.get("invalidation_price", rules.get("invalidation_hint", snapshot.get("proposed_stop_loss"))),
        "stop_loss": snapshot.get("proposed_stop_loss"),
        "take_profit": snapshot.get("proposed_take_profit"),
        "rr": features.get("rr"),
        "atr": features.get("atr"),
    }
    risk_sources = {
        "reference_price": "reference_price", "entry": "proposed_entry",
        "invalidation": ("invalidation_price" if snapshot.get("invalidation_price") is not None
                         else "rule_evidence.invalidation_hint" if rules.get("invalidation_hint") is not None
                         else "proposed_stop_loss"),
        "stop_loss": "proposed_stop_loss", "take_profit": "proposed_take_profit",
        "rr": "features.rr", "atr": "features.atr",
    }
    for key, value in risk_context.items():
        if value is None:
            continue
        source = risk_sources[key]
        source_value = _value(snapshot, source)
        evidence.append(_evidence("risk", f"Recorded {key.replace('_', ' ')} value.",
                                  source, source_value))
    invalidation_source = ("invalidation_price" if snapshot.get("invalidation_price") is not None
                           else "rule_evidence.invalidation_hint" if rules.get("invalidation_hint") is not None
                           else "proposed_stop_loss" if snapshot.get("proposed_stop_loss") is not None else None)
    if risk_context["invalidation"] is not None and invalidation_source:
        evidence.append(_evidence("risk", "Recorded invalidation level.",
                                  invalidation_source, _value(snapshot, invalidation_source)))
    summary = (f"CONFIRMED {direction or ''}: scanner strategy validation passed. "
               f"{len(confirmations)} snapshot-backed supporting evidence items and "
               f"{len(conflicts)} opposing evidence items are recorded."
               if classification == "CONFIRMED"
               else "WATCH: the recorded scanner strategy_valid flag is not true.")
    if "FUTURE_SOURCE_TIMESTAMP" in (snapshot.get("data_quality") or {}).get("flags", []):
        summary += " Source timestamp is ahead of observation time and is untrusted."
    elif any(flag in (snapshot.get("data_quality") or {}).get("flags", [])
             for flag in ("SOURCE_TIME_BASIS_UNVERIFIED", "SOURCE_TIME_INVALID")):
        summary += " MT5 source-time basis is unverified; timestamp freshness is untrusted."
    return SetupAnalysis(schema_version="1.0", analyst_version=ANALYST_VERSION,
        setup_id=str(snapshot.get("setup_id") or ""), observation_id=str(snapshot.get("observation_id") or ""),
        classification=classification, direction=direction, setup_type=setup_type,
        summary=summary, confirmations=confirmations, conflicts=conflicts,
        missing_confirmations=missing, evidence=evidence, risk_context=risk_context,
        data_quality=dict(snapshot.get("data_quality") or {}),
        generated_at=generated_at or utc_iso(datetime.now(timezone.utc)))
