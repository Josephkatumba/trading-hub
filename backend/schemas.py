"""Versioned JSONL contracts for setup observations and derived records."""
from __future__ import annotations

from typing import Any, Literal, NotRequired, TypedDict


class DataQuality(TypedDict):
    status: Literal["OK", "DEGRADED", "UNAVAILABLE"]
    flags: list[str]
    source: str | None
    source_timestamp: str | None
    observed_at: str
    source_age_seconds: float | None
    timeframe: str
    expected_bars: int | None
    received_bars: int | None
    missing_intervals: int | None
    notes: list[str]
    candle_age_seconds: NotRequired[float | None]
    tick_age_seconds: NotRequired[float | None]
    observation_latency_seconds: NotRequired[float | None]
    timestamp_quality: NotRequired[str]


class SetupSnapshot(TypedDict):
    record_type: Literal["setup_snapshot"]
    schema_version: str
    setup_id: str
    observation_id: str
    observed_at: str
    source_timestamp: str | None
    symbol: str
    broker_symbol: str | None
    timeframe: str
    higher_timeframes: list[str]
    direction: str | None
    strategy_id: str
    strategy_version: str
    setup_type: str | None
    # Durable episode state; raw scanner state remains in rule_evidence/features.
    lifecycle_state: Literal["DETECTED", "DEVELOPING", "CONFIRMING", "CONFIRMED", "ACTIVE"]
    reference_price: float | None
    proposed_entry: float | None
    proposed_stop_loss: float | None
    proposed_take_profit: float | None
    features: dict[str, Any]
    rule_evidence: dict[str, Any]
    strategy_evidence: dict[str, Any]
    score: float | None
    score_breakdown: dict[str, Any]
    session: dict[str, Any]
    data_freshness: dict[str, Any]
    data_quality: DataQuality
    episode_identity: NotRequired[dict[str, Any]]
    scanner_state: NotRequired[Literal["WATCHING", "DEVELOPING", "CONFIRMING", "NO SETUP"]]
    invalidation_price: NotRequired[float | None]
    atr: NotRequired[float | None]
    time_provenance: NotRequired[dict[str, Any]]
    shadow: NotRequired[bool]            # present (True) only for shadow-mode strategies


class SetupLifecycleEvent(TypedDict):
    record_type: Literal["setup_lifecycle_event"]
    schema_version: str
    event_id: str
    setup_id: str
    occurred_at: str
    from_state: Literal["DETECTED", "DEVELOPING", "CONFIRMING", "CONFIRMED", "ACTIVE",
                        "INVALIDATED", "EXPIRED", "RESOLVED"] | None
    to_state: Literal["DETECTED", "DEVELOPING", "CONFIRMING", "CONFIRMED", "ACTIVE",
                      "INVALIDATED", "EXPIRED", "RESOLVED"]
    reason_code: str
    reason: str | None
    triggering_observation_id: str | None
    metadata: dict[str, Any]


class SetupConfirmationEvent(TypedDict):
    record_type: Literal["setup_confirmation"]
    schema_version: str
    confirmation_event_id: str
    setup_id: str
    confirmed_at: str
    observation_id: str
    strategy_id: str
    strategy_version: str
    symbol: str
    direction: str | None
    setup_type: str | None
    timeframe: str
    score: float | None
    rule_evidence: dict[str, Any]
    score_breakdown: dict[str, Any]
    shadow: NotRequired[bool]            # present (True) only for shadow-mode strategies


class AnalystEvidence(TypedDict):
    category: str
    claim: str
    source_field: str
    source_value: Any


class SetupAnalysis(TypedDict):
    schema_version: str
    analyst_version: str
    setup_id: str
    observation_id: str
    classification: Literal["WATCH", "CONFIRMED"]
    direction: str | None
    setup_type: str | None
    summary: str
    confirmations: list[AnalystEvidence]
    conflicts: list[AnalystEvidence]
    missing_confirmations: list[AnalystEvidence]
    evidence: list[AnalystEvidence]
    risk_context: dict[str, Any]
    data_quality: dict[str, Any]
    generated_at: str


class DailySetupPerformance(TypedDict):
    date: str
    reporting_timezone: str
    primary_horizon: str
    confirmed: int
    wins: int
    losses: int
    pending: int
    no_hit: int
    ambiguous: int
    win_rate: float | None
    win_rate_denominator: int
    watchlist: int
    by_horizon: dict[str, dict[str, int]]
    by_symbol: dict[str, dict[str, int]]
    by_setup_type: dict[str, dict[str, int]]
    by_timeframe: dict[str, dict[str, int]]


class OutcomeTimeValidation(TypedDict):
    setup_observation_time: str | None
    first_candidate_candle_timestamp: str | None
    last_candidate_candle_timestamp: str | None
    candidate_candle_count: int
    every_candidate_strictly_after_observation: bool | None
    candidate_candles_chronological: bool
    timestamp_quality: str
    outcome_time_validity: Literal["OUTCOME_TIME_VALID", "OUTCOME_TIME_INVALID",
                                    "OUTCOME_TIME_UNVERIFIED"]


MarketOutcome = TypedDict("MarketOutcome", {
    "record_type": Literal["market_outcome"], "schema_version": str,
    "outcome_id": str, "setup_id": str, "observation_id": str,
    "resolved_at": str, "horizon": str, "timeframe": str,
    "direction": str | None, "reference_price": float | None,
    "future_price": float | None, "return": float | None,
    "distance": float | None, "maximum_favorable_excursion": float | None,
    "maximum_adverse_excursion": float | None,
    "time_to_favorable_movement": str | None,
    "time_to_adverse_movement": str | None, "label": str | None,
    "label_reason": str | None, "label_definition": str,
    "data_quality": DataQuality,
    "timestamp_quality": str, "source_time_basis": str | None,
    "outcome_time_validity": Literal["OUTCOME_TIME_VALID", "OUTCOME_TIME_INVALID",
                                     "OUTCOME_TIME_UNVERIFIED"],
    "outcome_time_validation": OutcomeTimeValidation,
    "outcome_status": str,
})


class TradeOutcome(TypedDict):
    record_type: Literal["trade_outcome"]
    schema_version: str
    trade_id: str
    setup_id: str
    execution_type: Literal["ACTUAL", "SIMULATED"]
    entry_time: str
    entry_price: float
    exit_time: str | None
    exit_price: float | None
    direction: Literal["LONG", "SHORT"]
    size: float | None
    size_unit: str | None
    realized_pnl: float | None
    currency: str | None
    exit_reason: str | None
    execution_metadata: dict[str, Any]
    recorded_at: str


def validate_trade_outcome(value: dict[str, Any]) -> None:
    required = ("setup_id", "execution_type", "entry_time", "entry_price", "direction")
    missing = [key for key in required if key not in value]
    if missing:
        raise ValueError("Missing required trade outcome fields: " + ", ".join(missing))
    if value["execution_type"] not in {"ACTUAL", "SIMULATED"}:
        raise ValueError("execution_type must be ACTUAL or SIMULATED")
    if value["direction"] not in {"LONG", "SHORT"}:
        raise ValueError("direction must be LONG or SHORT")
