"""Strategy contract, registry and the registered strategies.

Only the trendline strategy is registered, and it is enabled. New strategies
are added by implementing base.Strategy and registering them in
build_default_registry(); they do not touch the trendline strategy.
"""
from __future__ import annotations

from .base import CORE_FIELDS, METADATA_FIELDS, MarketInput, Strategy, StrategyResult
from .registry import StrategyRegistry
from .trendline import TrendlineStrategy

TRENDLINE = TrendlineStrategy.strategy_id


def build_default_registry() -> StrategyRegistry:
    registry = StrategyRegistry()
    registry.register(TrendlineStrategy(), enabled=True)
    return registry


REGISTRY = build_default_registry()

__all__ = ["CORE_FIELDS", "METADATA_FIELDS", "MarketInput", "REGISTRY", "Strategy", "StrategyRegistry",
           "StrategyResult", "TRENDLINE", "TrendlineStrategy", "build_default_registry"]
