"""Strategy contract, registry and the registered strategies.

The trendline strategy is the only LIVE strategy. Support & Resistance runs in
SHADOW mode: evaluated and persisted for review and research, never presented
as a live setup. New strategies are added by implementing base.Strategy and
registering them in build_default_registry(); they do not touch the trendline
strategy.
"""
from __future__ import annotations

from .base import (CORE_FIELDS, DISABLED, EVIDENCE_CONTAINER, LEGACY_STRATEGY_ID, LIVE, METADATA_FIELDS, SHADOW,
                   MarketInput, Strategy, StrategyResult, record_strategy_id)
from .registry import StrategyRegistry
from .support_resistance import SupportResistanceStrategy
from .trendline import TrendlineStrategy

TRENDLINE = TrendlineStrategy.strategy_id


def build_default_registry() -> StrategyRegistry:
    registry = StrategyRegistry()
    registry.register(TrendlineStrategy(), enabled=True, mode=LIVE)
    registry.register(SupportResistanceStrategy(), enabled=True, mode=SHADOW)
    return registry


REGISTRY = build_default_registry()

__all__ = ["CORE_FIELDS", "DISABLED", "EVIDENCE_CONTAINER", "LEGACY_STRATEGY_ID", "LIVE", "METADATA_FIELDS", "MarketInput",
           "REGISTRY", "SHADOW", "Strategy", "StrategyRegistry", "StrategyResult", "SupportResistanceStrategy", "TRENDLINE",
           "TrendlineStrategy", "build_default_registry", "record_strategy_id"]
