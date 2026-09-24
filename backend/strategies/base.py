"""The strategy contract.

A strategy turns one symbol's market data into one result (its payload). Each
strategy owns its detection, confirmation, invalidation, entry, stop loss, take
profit and evidence rules; the contract only fixes WHERE those decisions appear
in the payload (CORE_FIELDS) and how every result is identified (strategy_id +
version), so later phases can scope episodes, lifecycle and suppression by
strategy without knowing any strategy's rules.

Nothing here changes what a strategy computes: StrategyResult.payload is the
strategy's own output, unmodified. The only metadata a result adds is listed in
METADATA_FIELDS. Strategy-specific evidence that fits none of the core fields
goes in the payload's EVIDENCE_CONTAINER dict, which is persisted as is.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar, Mapping, Sequence

# Payload keys every strategy reports its decisions under. A strategy may add
# any strategy-specific fields next to them (the trendline strategy adds many).
CORE_FIELDS = {
    "state": "state",                    # detection: NO SETUP / WATCHING / DEVELOPING / CONFIRMING
    "direction": "direction",            # LONG / SHORT / None
    "confirmed": "strategy_valid",       # confirmation: every strategy rule satisfied
    "entry": "entry",
    "stop_loss": "stop_loss",
    "take_profit": "take_profit",
    "invalidation": "invalidation_hint",  # price that invalidates the setup
    "score": "score",
    "evidence": "score_breakdown",       # the evidence the decision rests on
}

# Optional payload dict of strategy-specific evidence, persisted unmodified on
# each snapshot (the trendline strategy keeps its evidence in its own fields).
EVIDENCE_CONTAINER = "strategy_evidence"

# The only keys StrategyResult.record() adds to a payload.
METADATA_FIELDS = ("strategy_id",)

# Every record written before strategy_id existed came from the trendline engine.
LEGACY_STRATEGY_ID = "trendline"


def record_strategy_id(record: Mapping[str, Any]) -> str:
    """The strategy a market, snapshot, episode or confirmation record belongs to.

    Historical records carry no strategy_id and are mapped here, at read time,
    never rewritten: setup_type BREAK and REVERSAL are trendline setups, and
    WATCHING / GENERAL are the trendline strategy's directional-context
    episodes. All map to "trendline"; setup_type keeps telling them apart.
    """
    value = record.get("strategy_id")
    return str(value) if value else LEGACY_STRATEGY_ID


@dataclass(frozen=True)
class MarketInput:
    """What a strategy receives for one symbol in one scan.

    `rows` / `higher_rows` are the OHLC bars the trendline strategy has always
    used (M15 / H1). `bars` is the market context by timeframe (e.g. M15, H1,
    H4, D1), each bar with tick_volume when the broker provides it;
    `unavailable_timeframes` names requested timeframes the broker could not
    supply, with the reason. Empty `bars` means no context was collected.
    """
    symbol: str
    rows: Sequence[Mapping[str, Any]]                   # primary timeframe bars, oldest first
    spread: float = 0.0
    session_context: Mapping[str, Any] | None = None
    higher_rows: Sequence[Mapping[str, Any]] | None = None
    bars: Mapping[str, Sequence[Mapping[str, Any]]] = field(default_factory=dict)
    unavailable_timeframes: Mapping[str, str] = field(default_factory=dict)


class Strategy(ABC):
    strategy_id: ClassVar[str]                # stable identity; results and (later) episodes are scoped by it
    version: ClassVar[str]                    # bump whenever the strategy's rules change
    timeframe: ClassVar[str]
    higher_timeframes: ClassVar[tuple[str, ...]] = ()
    lifecycle: ClassVar[str]                  # episode/lifecycle policy its setups follow
    # Market data the strategy needs: {timeframe: bars}. The collector supplies
    # these in MarketInput.bars; a strategy is not run when one is unavailable.
    data_requirements: ClassVar[Mapping[str, int]] = {}

    @abstractmethod
    def evaluate(self, market: MarketInput) -> dict[str, Any]:
        """Return this strategy's payload for one symbol. Must not mutate `market`."""


# Registry modes. LIVE strategies produce live setups (Garden, alerts, live
# performance). SHADOW strategies run and are persisted for review and research
# only: their records are marked shadow and never reach the Garden or alerts.
LIVE, SHADOW, DISABLED = "LIVE", "SHADOW", "DISABLED"


@dataclass(frozen=True)
class StrategyResult:
    strategy_id: str
    strategy_version: str
    payload: dict[str, Any] | None           # None when the strategy raised
    error: Exception | None = None
    mode: str = LIVE

    @property
    def ok(self) -> bool:
        return self.error is None

    def core(self, name: str) -> Any:
        """A contract decision (see CORE_FIELDS) read from the payload."""
        return (self.payload or {}).get(CORE_FIELDS[name])

    @property
    def confirmed(self) -> bool:
        return self.core("confirmed") is True

    def metadata(self) -> dict[str, Any]:
        return {"strategy_id": self.strategy_id}

    def record(self) -> dict[str, Any]:
        """The payload plus the approved strategy metadata, and nothing else."""
        if self.payload is None:
            raise ValueError(f"strategy {self.strategy_id} failed: {self.error!r}")
        return {**self.payload, **self.metadata()}
